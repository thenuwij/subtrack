"""Find receipt-shaped emails and pull the numbers out of them.

Deliberately narrow: it asks Gmail for likely receipts rather than reading the
mailbox, and it keeps only derived fields (merchant, amount, date). Raw bodies
are never returned or stored.
"""
import base64
import html
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import settings

logger = logging.getLogger(__name__)

# Gmail classifies purchase receipts itself, which beats hand-written keywords.
# The keyword arm catches billers Google files elsewhere (utilities often land
# in Updates rather than Purchases).
SEARCH_QUERY = (
    "(category:purchases OR subject:(receipt OR invoice OR payment OR "
    "subscription OR renewal OR \"tax invoice\")) newer_than:{months}m"
)

CURRENCY_SYMBOLS = {
    "$": "AUD",   # ambiguous; refined below by explicit codes
    "£": "GBP",
    "€": "EUR",
    "¥": "JPY",
}

# "A$12.99", "$12.99", "USD 12.99", "12.99 AUD"
AMOUNT_PATTERNS = [
    re.compile(r"\b([A-Z]{1,2}\$)\s?(\d[\d,]*\.?\d{0,2})"),
    re.compile(r"\b(AUD|USD|GBP|SGD|EUR|JPY)\s?(\d[\d,]*\.?\d{0,2})\b"),
    re.compile(r"(\d[\d,]*\.\d{2})\s?\b(AUD|USD|GBP|SGD|EUR|JPY)\b"),
    re.compile(r"([$£€¥])\s?(\d[\d,]*\.?\d{0,2})"),
]

# Lines like "Total: $12.99" are far more trustworthy than a bare number.
# "subtotal" is excluded — it sits above the real total and is not what was charged.
TOTAL_HINT = re.compile(
    r"((?<!sub)total|amount charged|amount paid|you paid|charged)",
    re.IGNORECASE,
)


@dataclass
class ReceiptCandidate:
    message_id: str
    sender_domain: str
    merchant: str
    subject: str
    date: str
    amount: float | None
    currency: str | None
    confidence: str          # "high" when the amount sat on a total-ish line
    excerpt: str = ""        # short cleaned snippet; names the product being billed


def build_credentials(refresh_token: str) -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
    creds.refresh(Request())
    return creds


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _decode_part(payload: dict) -> str:
    data = payload.get("body", {}).get("data")
    if not data:
        return ""

    text = base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="ignore")
    if payload.get("mimeType") == "text/html":
        # Drop style/script bodies before stripping tags. Removing only the tags
        # leaves their contents behind, and a marketing-grade HTML email carries
        # kilobytes of CSS — enough to bury the product name entirely.
        text = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<!--.*?-->", " ", text)
        text = re.sub(r"(?i)<(br|/p|/div|/tr|/td|/h\d)[^>]*>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    return text


def _collect_parts(payload: dict, by_type: dict[str, list[str]]) -> None:
    if payload.get("mimeType", "").startswith("multipart"):
        for part in payload.get("parts", []):
            _collect_parts(part, by_type)
        return
    text = _decode_part(payload)
    if text.strip():
        by_type.setdefault(payload.get("mimeType", ""), []).append(text)


def _extract_body_text(payload: dict) -> str:
    """Readable body text. Prefers text/plain, falls back to cleaned HTML."""
    by_type: dict[str, list[str]] = {}
    _collect_parts(payload, by_type)

    for mime in ("text/plain", "text/html"):
        if by_type.get(mime):
            return "\n".join(by_type[mime])
    return "\n".join(t for parts in by_type.values() for t in parts)


# Boilerplate that crowds out the useful part of a receipt.
_NOISE = re.compile(
    r"(?i)(unsubscribe|privacy policy|terms (of|and)|all rights reserved|"
    r"view (this|in) browser|do not reply|copyright|©|follow us|"
    r"manage (your )?(preferences|subscription settings))"
)

# Belt and braces: any CSS that survives tag-stripping is noise, not content.
_CSS_LIKE = re.compile(r"[{};]|@media|!important|font-family|text-decoration|px\s*[;}]")


def _excerpt(text: str, limit: int = 600) -> str:
    """A short, cleaned slice of the body.

    A subject line often says nothing useful — "Your tax invoice from Apple."
    covers Apple Music, iCloud and everything else. The product name lives in
    the body, so a trimmed excerpt is what lets a detection be named properly.
    Only this snippet is sent for analysis; full bodies are never stored.
    """
    lines = []
    for raw in re.split(r"[\n\r]+", text):
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 3 or _NOISE.search(line) or _CSS_LIKE.search(line):
            continue
        lines.append(line)
        if sum(len(x) for x in lines) > limit:
            break
    return " | ".join(lines)[:limit]


def _parse_amount(text: str) -> tuple[float | None, str | None, str]:
    """Return (amount, currency, confidence).

    Scans total-ish lines first — a receipt mentions many numbers and the
    largest or first is often shipping, tax, or a previous balance.
    """
    lines = [ln for ln in re.split(r"[\n\r]+", text) if ln.strip()]
    # Reversed: when a receipt has several total-ish lines, the final one is
    # the grand total. Earlier ones are per-item or pre-tax.
    total_lines = [ln for ln in lines if TOTAL_HINT.search(ln)][::-1]

    for candidate_lines, confidence in ((total_lines, "high"), (lines, "low")):
        for line in candidate_lines:
            for pattern in AMOUNT_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue

                groups = match.groups()
                raw_currency, raw_amount = (
                    (groups[1], groups[0]) if groups[0][0].isdigit() else (groups[0], groups[1])
                )

                try:
                    amount = float(raw_amount.replace(",", ""))
                except ValueError:
                    continue
                if amount <= 0:
                    continue

                currency = CURRENCY_SYMBOLS.get(raw_currency)
                if currency is None:
                    currency = raw_currency.replace("$", "").strip() or "AUD"
                    if currency == "A":
                        currency = "AUD"
                    elif currency == "S":
                        currency = "SGD"
                    elif currency == "US":
                        currency = "USD"

                return amount, currency, confidence

    return None, None, "none"


def _merchant_from_sender(sender: str) -> tuple[str, str]:
    """('Spotify', 'spotify.com') from 'Spotify <no-reply@spotify.com>'."""
    domain_match = re.search(r"@([\w.-]+)", sender)
    domain = domain_match.group(1).lower() if domain_match else ""

    display = re.sub(r"<[^>]*>", "", sender).strip().strip('"')
    if not display or "@" in display:
        # Fall back to the registrable-ish part of the domain.
        parts = [p for p in domain.split(".") if p not in {"com", "au", "co", "net", "org", "www"}]
        display = parts[-1].title() if parts else domain

    return display, domain


def _to_candidate(message: dict) -> ReceiptCandidate:
    headers = message["payload"].get("headers", [])
    merchant, domain = _merchant_from_sender(_header(headers, "From"))
    subject = _header(headers, "Subject")
    body = _extract_body_text(message["payload"])
    amount, currency, confidence = _parse_amount(f"{subject}\n{body}")
    received = datetime.fromtimestamp(int(message["internalDate"]) / 1000)

    return ReceiptCandidate(
        message_id=message["id"],
        sender_domain=domain,
        merchant=merchant,
        subject=subject[:120],
        date=received.strftime("%Y-%m-%d"),
        amount=amount,
        currency=currency,
        confidence=confidence,
        excerpt=_excerpt(body),
    )


# Gmail allows 100 requests per batch, but rejects that many concurrent reads
# for one user with 429s. 25 keeps the speedup without tripping the limit.
BATCH_SIZE = 25
MAX_RETRIES = 4


def _fetch_batch(service, message_ids: list[str]) -> tuple[list[ReceiptCandidate], list[str]]:
    """Fetch a batch in one HTTP round-trip. Returns (fetched, ids_to_retry).

    Fetching one message per request is what made this slow: a few hundred
    milliseconds of latency each, multiplied by every message found.
    """
    fetched: list[ReceiptCandidate] = []
    retry: list[str] = []

    def handle(request_id, response, exception):
        if exception is None:
            fetched.append(_to_candidate(response))
            return
        # 429/5xx are transient — the message is fine, Gmail is just busy.
        status = getattr(getattr(exception, "resp", None), "status", None)
        if status == 429 or (status or 0) >= 500:
            retry.append(request_id)
        else:
            logger.warning("Skipping message %s: %s", request_id, exception)

    batch = service.new_batch_http_request(callback=handle)
    for message_id in message_ids:
        batch.add(
            service.users().messages().get(userId="me", id=message_id, format="full"),
            request_id=message_id,
        )
    batch.execute()

    return fetched, retry


def _fetch_all(service, message_ids: list[str], on_progress=None) -> list[ReceiptCandidate]:
    candidates: list[ReceiptCandidate] = []
    pending = list(message_ids)
    attempt = 0

    while pending and attempt <= MAX_RETRIES:
        if attempt:
            # Back off before retrying whatever got rate-limited.
            time.sleep(2 ** attempt)

        still_pending: list[str] = []
        for start in range(0, len(pending), BATCH_SIZE):
            fetched, retry = _fetch_batch(service, pending[start:start + BATCH_SIZE])
            candidates.extend(fetched)
            still_pending.extend(retry)
            if on_progress:
                on_progress(len(candidates), len(message_ids))

        pending = still_pending
        attempt += 1

    if pending:
        logger.warning("Gave up on %d messages after %d retries", len(pending), MAX_RETRIES)

    return candidates


def scan(
    refresh_token: str,
    months: int = 6,
    max_messages: int = 200,
    on_progress=None,
) -> list[ReceiptCandidate]:
    service = build("gmail", "v1", credentials=build_credentials(refresh_token))
    query = SEARCH_QUERY.format(months=months)

    # List first — ids only, and cheap — so we know the total before fetching.
    message_ids: list[str] = []
    page_token = None
    while len(message_ids) < max_messages:
        response = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(500, max_messages - len(message_ids)),
            pageToken=page_token,
        ).execute()

        message_ids.extend(m["id"] for m in response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    message_ids = message_ids[:max_messages]
    if on_progress:
        on_progress(0, len(message_ids))

    return _fetch_all(service, message_ids, on_progress)


def to_dicts(candidates: list[ReceiptCandidate]) -> list[dict]:
    return [asdict(c) for c in candidates]
