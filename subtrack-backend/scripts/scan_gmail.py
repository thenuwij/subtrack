"""Print what Subtrack can actually pull out of your inbox. Writes nothing.

This is the checkpoint: if your receipts parse cleanly here, the rest of the
feature is mechanical. If they don't, better to know now.

    python scripts/scan_gmail.py [--months 6] [--max 200]
"""
import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal            # noqa: E402
from app.gmail.crypto import decrypt_token       # noqa: E402
from app.gmail.scanner import scan               # noqa: E402
from app.models import GmailAccount              # noqa: E402


def main():
    logging.basicConfig(level=logging.WARNING, format="  ! %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--max", type=int, default=200)
    parser.add_argument("--classify", action="store_true",
                        help="Run the LLM classification + cadence pass (costs API calls)")
    args = parser.parse_args()

    db = SessionLocal()
    account = db.query(GmailAccount).first()
    if not account:
        print("No Gmail account connected yet. Connect one from the Account page first.")
        return

    print(f"Scanning {account.email_address} — last {args.months} months\n")

    def progress(done, total):
        if done == 0:
            print(f"  found {total} candidate emails, fetching…", flush=True)
        else:
            print(f"  fetched {done}/{total}", flush=True)

    candidates = scan(
        decrypt_token(account.refresh_token_encrypted), args.months, args.max, progress
    )
    print()

    if not candidates:
        print("No receipt-shaped emails matched the search.")
        return

    parsed = [c for c in candidates if c.amount is not None]
    high = [c for c in parsed if c.confidence == "high"]

    print(f"{len(candidates)} candidate emails")
    print(f"{len(parsed)} had an amount ({len(parsed) / len(candidates):.0%})")
    print(f"{len(high)} of those came off a total line (high confidence)\n")

    # Grouping by sender is what turns receipts into subscriptions: the same
    # merchant appearing on a regular cadence is the signal we care about.
    by_domain = defaultdict(list)
    for c in parsed:
        by_domain[c.sender_domain].append(c)

    recurring = {d: cs for d, cs in by_domain.items() if len(cs) >= 2}
    one_offs = {d: cs for d, cs in by_domain.items() if len(cs) == 1}

    print(f"── Recurring: {len(recurring)} senders seen 2+ times ──\n")
    for domain, items in sorted(recurring.items(), key=lambda kv: -len(kv[1])):
        items.sort(key=lambda c: c.date)
        amounts = {f"{c.currency} {c.amount:.2f}" for c in items}
        changed = "  ← amount varies" if len(amounts) > 1 else ""
        print(f"  {items[0].merchant:<24} {domain:<28} {len(items)}x{changed}")
        for c in items[-4:]:
            print(f"      {c.date}  {c.currency} {c.amount:>8.2f}  [{c.confidence}]  {c.subject[:52]}")
        print()

    print(f"── One-offs: {len(one_offs)} senders seen once ──")
    for domain, items in sorted(one_offs.items())[:15]:
        c = items[0]
        print(f"  {c.merchant:<24} {c.date}  {c.currency} {c.amount:>8.2f}  {c.subject[:44]}")

    if args.classify:
        from app.gmail.analyzer import analyze           # noqa: E402

        print(f"\n{'=' * 68}")
        print(f"Analyzing {len(candidates)} emails by merchant…")
        subs = analyze(candidates)

        print(f"\n── Subscription candidates: {len(subs)} ──\n")
        for s in subs:
            flags = []
            if s.previous_amount is not None:
                flags.append(f"price changed from {s.currency} {s.previous_amount:.2f}")
            if s.cancelled:
                flags.append("CANCELLED")
            flag_text = f"  [{', '.join(flags)}]" if flags else ""
            print(f"  {s.merchant:<28} {s.currency} {s.amount:>8.2f} / {s.cycle:<8} "
                  f"{s.charge_count} charge(s)  [{s.confidence}]{flag_text}")
            print(f"      via {s.sender_domain}")

        detected_domains = {s.sender_domain for s in subs}
        skipped = sorted({c.sender_domain for c in candidates} - detected_domains)
        if skipped:
            print(f"\n  No subscription found for: {', '.join(skipped[:15])}")

    unparsed = [c for c in candidates if c.amount is None]
    if unparsed:
        print(f"\n── No amount found: {len(unparsed)} ──")
        for c in unparsed[:15]:
            print(f"  {c.merchant:<24} {c.date}  {c.subject[:60]}")
        print("\n  These are the ones that would need an LLM extraction pass.")

    db.close()


if __name__ == "__main__":
    main()
