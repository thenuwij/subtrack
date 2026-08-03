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
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.config import settings
from app.gmail.scanner import ReceiptCandidate

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

MODEL = "claude-opus-5"

# How many sender-domain groups to analyze per API call.
GROUPS_PER_CALL = 8


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
    amount: float = Field(description="The current per-cycle amount, from the most recent successful charge")
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


class AnalysisResult(BaseModel):
    subscriptions: list[DetectedSubscription] = Field(
        description="Every recurring paid service found. Empty list if a batch "
                    "contains none."
    )


SYSTEM = """You analyze email timelines from a person's inbox to find their paid \
recurring subscriptions and bills — streaming, software, utilities, insurance, \
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


def analyze(candidates: list[ReceiptCandidate]) -> list[DetectedSubscription]:
    """Analyze all candidates, including those without a parsed amount —
    cancellation notices and failed payments carry no amount but real signal."""
    groups = _group_by_domain(candidates)
    domains = sorted(groups, key=lambda d: -len(groups[d]))

    results: list[DetectedSubscription] = []

    for start in range(0, len(domains), GROUPS_PER_CALL):
        chunk = domains[start:start + GROUPS_PER_CALL]
        prompt = (
            "Find the paid recurring subscriptions in these email timelines:\n\n"
            + "\n\n".join(_render_group(d, groups[d]) for d in chunk)
        )

        try:
            response = client.messages.parse(
                model=MODEL,
                max_tokens=16000,
                output_config={"effort": "medium"},
                output_format=AnalysisResult,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            logger.error("Analysis batch at %d failed: %s: %s", start, type(exc).__name__, exc)
            continue

        if response.stop_reason == "refusal" or response.parsed_output is None:
            logger.error("Analysis batch at %d returned no output (stop_reason=%s)",
                         start, response.stop_reason)
            continue

        for sub in response.parsed_output.subscriptions:
            # The model only knows the domains it was shown; anything else is a slip.
            if sub.sender_domain not in chunk:
                logger.warning("Dropping result for unknown domain %r", sub.sender_domain)
                continue
            # A bill with no amount can't be tracked as a cost.
            if sub.amount is None or sub.amount <= 0:
                logger.info("Dropping %r — no usable amount", sub.merchant)
                continue
            results.append(sub)

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
        winner.charge_count = max(winner.charge_count, loser.charge_count)
        best[key] = winner

    merged = list(best.values())
    merged.sort(key=lambda s: (-s.charge_count, s.merchant.lower()))
    return merged
