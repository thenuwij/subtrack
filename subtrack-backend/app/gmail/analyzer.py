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
        description="Clean display name of the business being paid, e.g. 'Origin "
                    "Broadband', 'Netflix'. For payment processors (Stripe, PayPal, "
                    "Afterpay) this is the underlying merchant from the subject lines, "
                    "and one domain may yield several subscriptions."
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
- Payment processors (stripe.com, paypal.com, afterpay.com) send receipts for many \
unrelated merchants. Read the subject lines and split them: each underlying \
merchant with recurring charges is its own subscription; one-off purchases through \
the processor are ignored. Charges are only recurring if they come from the SAME \
underlying merchant — similar amounts from differently-named entities are separate \
one-offs, not a subscription.
- A sender with a single charge and no other signal is usually not worth reporting. \
Report it only if the email text clearly indicates a subscription (e.g. "your \
subscription renewal"), with confidence=medium.
- Prefer missing a borderline case over inventing one. The user reviews and \
approves everything you report."""


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
            if sub.sender_domain in chunk:
                results.append(sub)
            else:
                logger.warning("Dropping result for unknown domain %r", sub.sender_domain)

    results.sort(key=lambda s: (-s.charge_count, s.merchant.lower()))
    return results
