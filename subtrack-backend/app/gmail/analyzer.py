"""Merchant-level subscription analysis.

The earlier design classified each email in isolation and reconstructed the
recurrence pattern in Python. That failed in two unfixable ways: free-text
merchant names varied between calls (splitting one subscription into several
groups), and recurrence simply isn't visible in a single email (the same
receipt flip-flopped between runs).

This inverts it. Emails are grouped by sender domain first — deterministic, no
model involved — and the model sees each merchant's full timeline in one call,
exactly the evidence a person would use: dates, amounts, subjects, including
failed payments and cancellation notices. Duplicate lifecycle emails (invoice +
"payment successful" for the same bill) are obvious in context, and aggregators
like Stripe can be split into their real merchants because all their subjects
are visible side by side.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Literal

import anthropic
from pydantic import BaseModel, Field

from app.config import settings
from app.gmail.scanner import ReceiptCandidate

logger = logging.getLogger(__name__)

# The SDK's default timeout is 10 minutes per call. A call that slow would
# outlive the scan's staleness window and make a live scan look dead, so cap
# it: fail the batch and move on rather than hang the whole scan.
client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key,
    timeout=240.0,
    max_retries=1,
)

MODEL = "claude-opus-5"

# How many sender-domain groups to analyze per API call.
GROUPS_PER_CALL = 8

# Analysis calls are network-bound and independent (domains are disjoint), so
# they parallelize cleanly. This is what the scan's wall time is made of: at 8
# groups per call a first scan is easily 5-10 calls of 30-90s each, which
# sequentially is most of "why is this taking so long".
MAX_CONCURRENT_CALLS = 3


class AnalysisFailed(Exception):
    """Every analysis batch failed. Distinct from finding nothing: reporting
    an empty result here would tell the user their inbox has no subscriptions
    when in truth none of it was analyzed."""


class DetectedSubscription(BaseModel):
    sender_domain: str = Field(description="The sender domain this came from, exactly as given")
    merchant: str = Field(
        description="What the user is paying for, specific enough to tell apart "
                    "from anything else billed by the same sender. Name the "
                    "product, not just the company: 'Apple Music', 'iCloud 2TB', "
                    "'Origin Energy', 'Rent - 90/2-6 Willis St'. Read the excerpt "
                    "— the subject is often generic ('Your tax invoice from "
                    "Apple.') while the excerpt names the actual product."
    )
    product_key: str = Field(
        description="A stable lowercase identifier for this exact bill, used to "
                    "recognise it again on a later scan: lowercase, words joined "
                    "by hyphens, no amounts or dates. E.g. 'apple-music', "
                    "'apple-icloud-2tb', 'origin-energy', 'rent-willis-st'. It "
                    "must stay identical for the same bill across scans even if "
                    "the wording of the emails changes."
    )
    cycle: Literal["weekly", "monthly", "yearly"] = Field(
        description="Billing cycle inferred from the spacing of actual charges. "
                    "Ignore duplicate emails about the same bill (an invoice plus a "
                    "payment confirmation days apart is ONE charge, not two)."
    )
    amount: float = Field(
        ge=0,
        description="The current per-cycle amount from the latest charge, or the "
                    "price that will be charged after a free trial. Use 0 only "
                    "when this is clearly a free trial but the future price is absent."
    )
    currency: str = Field(description="ISO currency code, e.g. AUD")
    previous_amount: float | None = Field(
        default=None,
        description="If the per-cycle price changed during the window, the old amount. "
                    "Otherwise null. Different amounts for the same bill's invoice vs "
                    "confirmation emails are NOT a price change."
    )
    cancelled: bool = Field(
        description="True if the emails show this subscription was cancelled or will "
                    "not renew."
    )
    category: Literal[
        "streaming", "software", "cloud", "utilities", "fitness",
        "food", "transport", "other",
    ] = Field(
        description="Best-fit category. Rent, phone, internet, and energy are "
                    "'utilities'; developer/AI/productivity tools are 'software'; "
                    "hosting is 'cloud'. Use 'other' when unsure."
    )
    confidence: Literal["high", "medium"] = Field(
        description="high = several charges at a consistent interval and amount. "
                    "medium = plausible but thin evidence (e.g. only 1-2 charges)."
    )
    charge_count: int = Field(description="Number of distinct successful charges observed (not emails)")
    trial_ends_at: datetime | None = Field(
        default=None,
        description="The explicit free-trial end date in ISO 8601 form, or null "
                    "when this is not a current free trial. Do not guess a date."
    )


class AnalysisResult(BaseModel):
    subscriptions: list[DetectedSubscription] = Field(
        description="Every recurring paid service found. Empty list if a batch "
                    "contains none."
    )


SYSTEM = """You analyze email timelines from a person's inbox to find their paid \
recurring subscriptions, auto-renewing free trials, and bills — streaming, software, utilities, insurance, \
rent, gym, phone plans.

You are shown emails grouped by sender. For each sender you see every matched \
email: date, parsed amount (may be missing or wrong), and subject line.

Rules:
- A subscription shows repeated charges at a roughly regular interval. Judge the \
interval from DISTINCT charges: billers often send several emails about the same \
bill (invoice, then "payment successful") days apart — that is one charge.
- Frequent purchases are not subscriptions. Food delivery, retail orders, ride \
shares, and buy-now-pay-later instalments for shopping are one-off spending even \
when regular-ish.
- Do not count failed payments or refunds as charges, but they are still evidence \
the subscription exists.
- Cancellation notices ("will not renew", "has been canceled", "service will end") \
mean the subscription exists but is ending: include it with cancelled=true.
- ONE SENDER CAN BILL FOR SEVERAL DIFFERENT THINGS. Group by what is being \
billed, not by who sent it. A property manager sends both weekly rent and \
separate quarterly water invoices from one address; a payment processor \
(stripe.com, paypal.com, afterpay.com) sends receipts for many unrelated \
merchants. Read the subjects and amounts and report each distinct bill \
separately — an amount that doesn't fit the dominant pattern is usually its own \
bill, not a price change or noise. Charges are only the same subscription if \
they are for the same thing; similar amounts from differently-named entities are \
separate.
- Utility bills (water, electricity, gas) are recurring even though the amount \
changes every cycle — the varying amount is consumption, not a different \
purchase. Report them with the most recent amount. This is different from \
repeated discrete purchases (retail, food delivery), which are not subscriptions.
- A sender with a single charge and no other signal is usually not worth reporting. \
Report it only if the email text clearly indicates a subscription or an ongoing \
account bill (e.g. "your subscription renewal", a utility invoice), with \
confidence=medium.
- A free trial that will automatically become paid is a recurring commitment even \
before its first charge. Include it when the email explicitly identifies the trial \
and its end date. Set trial_ends_at to that explicit date, charge_count=0 when \
nothing has been charged yet, and amount to the stated post-trial recurring price. \
If the price is not present, use amount=0 so the review screen can ask the user. \
Do not call a permanently free plan or a trial without auto-renewal a subscription.
- Prefer missing a borderline case over inventing one. The user reviews and \
approves everything you report.
- Each email includes an excerpt of its body. Use it to name the product: a \
sender like Apple bills several different subscriptions under one generic \
subject line, and the excerpt is what tells them apart. Report each as its own \
subscription with its own product_key."""


def _group_by_domain(candidates: list[ReceiptCandidate]) -> dict[str, list[ReceiptCandidate]]:
    groups: dict[str, list[ReceiptCandidate]] = {}
    for c in candidates:
        groups.setdefault(c.sender_domain, []).append(c)
    for group in groups.values():
        group.sort(key=lambda c: c.date)
    return groups


def _render_group(domain: str, emails: list[ReceiptCandidate]) -> str:
    lines = [f"### {domain} — {len(emails)} email(s)"]
    for c in emails:
        amount = f"{c.currency} {c.amount:.2f}" if c.amount is not None else "no amount parsed"
        lines.append(f"  {c.date}  [{amount}]  {c.subject}")
        # The subject alone can't distinguish Apple Music from iCloud; the
        # excerpt is what names the product being billed.
        if c.excerpt:
            lines.append(f"      … {c.excerpt[:320]}")
    return "\n".join(lines)


def _analyze_chunk(
    chunk: list[str],
    groups: dict[str, list[ReceiptCandidate]],
) -> list[DetectedSubscription]:
    """One API call over a set of sender domains. Raises on failure so the
    caller can tell a failed batch from a batch that found nothing."""
    prompt = (
        "Find the paid recurring subscriptions in these email timelines:\n\n"
        + "\n\n".join(_render_group(d, groups[d]) for d in chunk)
    )

    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        output_format=AnalysisResult,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError(f"no output (stop_reason={response.stop_reason})")

    results: list[DetectedSubscription] = []
    for sub in response.parsed_output.subscriptions:
        # The model only knows the domains it was shown; anything else is a slip.
        if sub.sender_domain not in chunk:
            logger.warning("Dropping result for unknown domain %r", sub.sender_domain)
            continue
        if (
            sub.trial_ends_at
            and sub.trial_ends_at.date() < datetime.now(timezone.utc).date()
        ):
            sub.trial_ends_at = None
        # Paid bills need an amount. A clear trial can stay at zero until the
        # review screen asks the user for its post-trial price.
        if (sub.amount is None or sub.amount <= 0) and sub.trial_ends_at is None:
            logger.info("Dropping %r — no usable amount", sub.merchant)
            continue
        results.append(sub)
    return results


def analyze(
    candidates: list[ReceiptCandidate],
    on_batch: Callable[[list[DetectedSubscription]], None] | None = None,
) -> list[DetectedSubscription]:
    """Analyze all candidates, including those without a parsed amount —
    cancellation notices and failed payments carry no amount but real signal.

    `on_batch` fires as each batch completes (possibly with an empty list) —
    it's how the scan streams partial results out and proves it's still alive.
    Domains are disjoint across batches, so per-batch results never overlap.

    Raises AnalysisFailed when every batch errored.
    """
    groups = _group_by_domain(candidates)
    domains = sorted(groups, key=lambda d: -len(groups[d]))
    chunks = [domains[i:i + GROUPS_PER_CALL] for i in range(0, len(domains), GROUPS_PER_CALL)]
    if not chunks:
        return []

    results: list[DetectedSubscription] = []
    failed = 0

    with ThreadPoolExecutor(max_workers=min(MAX_CONCURRENT_CALLS, len(chunks))) as pool:
        futures = {pool.submit(_analyze_chunk, chunk, groups): chunk for chunk in chunks}
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                found = _dedupe(future.result())
            except Exception as exc:
                failed += 1
                logger.error("Analysis batch %r… failed: %s: %s",
                             chunk[0], type(exc).__name__, exc)
                continue
            results.extend(found)
            if on_batch is not None:
                on_batch(found)

    if failed == len(chunks):
        raise AnalysisFailed(f"all {failed} analysis batches failed")
    if failed:
        logger.warning("%d of %d analysis batches failed — results may be incomplete",
                       failed, len(chunks))

    return _dedupe(results)


def _dedupe(subs: list[DetectedSubscription]) -> list[DetectedSubscription]:
    """Collapse results that describe the same bill.

    One analysis pass can emit the same subscription twice — the same product
    key at two different amounts, for instance, when the model treats a price
    change as two separate bills. Left alone that becomes two rows in the review
    queue and, if both are approved, two subscriptions.
    """
    best: dict[tuple, DetectedSubscription] = {}

    for sub in subs:
        key = (sub.sender_domain, (sub.product_key or "").strip().lower())
        if not key[1]:
            key = (sub.sender_domain, sub.merchant.strip().lower(), sub.cycle)

        current = best.get(key)
        if current is None:
            best[key] = sub
            continue

        # Keep the better-evidenced one; carry the other's amount across as the
        # previous price so a real change isn't lost in the merge.
        winner, loser = (sub, current) if sub.charge_count > current.charge_count else (current, sub)
        if winner.previous_amount is None and abs(loser.amount - winner.amount) > 0.01:
            winner.previous_amount = loser.amount
        if winner.trial_ends_at is None and loser.trial_ends_at is not None:
            winner.trial_ends_at = loser.trial_ends_at
        winner.charge_count = max(winner.charge_count, loser.charge_count)
        best[key] = winner

    merged = list(best.values())
    merged.sort(key=lambda s: (-s.charge_count, s.merchant.lower()))
    return merged


class SimilarMatch(BaseModel):
    detection_index: int = Field(description="Index of the detection in the list shown")
    subscription_index: int | None = Field(
        description="Index of the tracked subscription that is the SAME service, "
                    "or null if none of them are."
    )
    reason: str = Field(
        description="One short sentence a user would understand, e.g. "
                    "\"Claude is Anthropic's product — same service.\" Empty if no match."
    )


class SimilarityResult(BaseModel):
    matches: list[SimilarMatch]


SIMILARITY_SYSTEM = """You match newly detected bills against the subscriptions a \
person already tracks, so the app doesn't create a duplicate entry for a service \
they already have.

Two entries are the SAME service when a person would say they're paying for one \
thing, not two — even if the names look nothing alike:
- A product and its company: "Claude" and "Anthropic", "ChatGPT" and "OpenAI".
- The same service named loosely vs precisely: "Apple" at $6.99 and "Apple Music".
- The same provider billed through different channels: direct vs via a payment \
processor or app store.

They are DIFFERENT when the same provider sells separate things the person pays \
for independently — Apple Music and iCloud storage are two subscriptions, not one, \
even though both are Apple.

Amounts are a hint, not proof: a price can change, and a shared bill is recorded \
at the user's share rather than the full amount. Cycle mismatches (monthly vs \
yearly) usually mean different plans.

If you are not confident it's the same service, return null. A wrong match \
silently overwrites something the user is tracking; a missed one just means an \
extra row they can merge themselves."""


def find_similar(
    detections: list,
    subscriptions: list,
) -> dict[int, tuple[int, str]]:
    """Map detection index -> (subscription index, reason) for same-service pairs.

    Text matching cannot connect "Claude Pro" to a subscription called
    "Anthropic" — knowing they are one service is world knowledge, which is why
    this asks the model rather than comparing strings.
    """
    if not detections or not subscriptions:
        return {}

    def cycle_of(x):
        return x.cycle.value if hasattr(x.cycle, "value") else x.cycle

    tracked = "\n".join(
        f"  [{i}] {s.name} — {s.currency} {s.amount:.2f}/{cycle_of(s)}"
        for i, s in enumerate(subscriptions)
    )
    found = "\n".join(
        f"  [{i}] {d.merchant} — {d.currency} {d.amount:.2f}/{cycle_of(d)} (from {d.sender_domain})"
        for i, d in enumerate(detections)
    )

    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=8000,
            output_config={"effort": "low"},
            output_format=SimilarityResult,
            system=SIMILARITY_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Already tracked:\n{tracked}\n\n"
                    f"Newly detected:\n{found}\n\n"
                    "For each detection, say which tracked subscription is the same "
                    "service, or null."
                ),
            }],
        )
    except Exception as exc:
        logger.error("Similarity check failed: %s: %s", type(exc).__name__, exc)
        return {}

    if response.stop_reason == "refusal" or response.parsed_output is None:
        return {}

    out: dict[int, tuple[int, str]] = {}
    for m in response.parsed_output.matches:
        if m.subscription_index is None:
            continue
        if 0 <= m.detection_index < len(detections) and 0 <= m.subscription_index < len(subscriptions):
            out[m.detection_index] = (m.subscription_index, m.reason)
    return out


class DuplicatePair(BaseModel):
    keep_index: int = Field(description="Index of the entry to keep — the better-named one")
    merge_index: int = Field(description="Index of the duplicate to fold into it")
    reason: str = Field(description="One short sentence explaining why they're the same service")


class DuplicateResult(BaseModel):
    duplicates: list[DuplicatePair]


def find_duplicates(subscriptions: list) -> list[tuple[int, int, str]]:
    """Find pairs in the user's own list that are the same service.

    A first scan can easily produce "Claude" and "Anthropic (Claude)" as two
    rows, which double-counts the cost. Returns (keep, merge, reason) triples.
    """
    if len(subscriptions) < 2:
        return []

    def cycle_of(x):
        return x.cycle.value if hasattr(x.cycle, "value") else x.cycle

    listing = "\n".join(
        f"  [{i}] {s.name} — {s.currency} {s.amount:.2f}/{cycle_of(s)}"
        for i, s in enumerate(subscriptions)
    )

    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=8000,
            output_config={"effort": "low"},
            output_format=DuplicateResult,
            system=SIMILARITY_SYSTEM + "\n\nHere you are checking one list against "
                   "itself. Report a pair only when both rows are the same service and "
                   "keeping both would double-count the cost. Prefer keeping the more "
                   "specific name. Never pair a row with itself.",
            messages=[{"role": "user", "content":
                       f"Tracked subscriptions:\n{listing}\n\n"
                       "Which pairs are the same service?"}],
        )
    except Exception as exc:
        logger.error("Duplicate check failed: %s: %s", type(exc).__name__, exc)
        return []

    if response.stop_reason == "refusal" or response.parsed_output is None:
        return []

    n = len(subscriptions)
    seen: set[int] = set()
    out: list[tuple[int, int, str]] = []
    for pair in response.parsed_output.duplicates:
        k, m = pair.keep_index, pair.merge_index
        if k == m or not (0 <= k < n and 0 <= m < n):
            continue
        if k in seen or m in seen:      # keep each row in at most one pair
            continue
        seen.update({k, m})
        out.append((k, m, pair.reason))
    return out
