import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_CARD = re.compile(
    r"(?:ending(?:\s+(?:in|with))?|ends\s+(?:in|with)|last\s+(?:4|four)(?:\s+digits)?|"
    r"card\s+(?:number|no\.?)|[x*•·]{2,}[\s-]*)\s*[:#]?\s*\d{4}\b(?![/.-]\d)",
    re.IGNORECASE,
)
_LABELLED = re.compile(
    r"\b(name|customer|account\s+holder|bill\s+to|billed\s+to|ship\s+to|deliver\s+to|"
    r"member|cardholder|address|phone|mobile|email|account\s+(?:no\.?|number)|"
    r"member\s+(?:no\.?|number)|customer\s+(?:no\.?|number|id)|nmi|bsb)\s*[:#]\s*[^|]*",
    re.IGNORECASE,
)
_GREETING = re.compile(
    r"^\s*(hi|hello|hey|dear|good\s+(?:morning|afternoon|evening))\b[^,!.:]{0,40}[,!.:]",
    re.IGNORECASE,
)
_STREET = re.compile(
    r"\b(?:unit\s+|u)?\d{1,5}[a-z]?(?:\s*/\s*\d{1,5}[a-z]?)?(?:\s*-\s*\d{1,5}[a-z]?)?\s+"
    r"(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:street|st|road|rd|avenue|ave|drive|dr|lane|ln|court|ct|place|pl|parade|pde|"
    r"crescent|cres|highway|hwy|boulevard|blvd|way|terrace|tce|close|cl|circuit|cct|"
    r"grove|gr|square|sq)\b\.?",
    re.IGNORECASE,
)
_STATE_POSTCODE = re.compile(r"\b(?:NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\s+\d{4}\b")
_PHONE = re.compile(r"(?<![\w$])\+?\(?\d[\d\s().-]{7,}\d(?![\w])")
_LONG_NUMBER = re.compile(r"\b[A-Z]{0,4}-?\d{6,}\b", re.IGNORECASE)


def _digit_count(text: str) -> int:
    return sum(character.isdigit() for character in text)


def _replace_phone(match: re.Match[str]) -> str:
    return "[phone]" if _digit_count(match.group(0)) >= 9 else match.group(0)


def _replace_labelled(match: re.Match[str]) -> str:
    return f"{match.group(1)}: [removed] "


def redact(text: str) -> str:
    if not text:
        return text
    text = _EMAIL.sub("[email]", text)
    text = _URL.sub("[link]", text)
    text = _GREETING.sub(lambda match: f"{match.group(1)} [name],", text)
    text = _LABELLED.sub(_replace_labelled, text)
    text = _CARD.sub("[card]", text)
    text = _STREET.sub("[address]", text)
    text = _STATE_POSTCODE.sub("[address]", text)
    text = _PHONE.sub(_replace_phone, text)
    text = _LONG_NUMBER.sub("[ref]", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def owner_terms(email_address: str | None) -> list[str]:
    if not email_address or "@" not in email_address:
        return []
    local_part = email_address.split("@", 1)[0]
    parts = {part.lower() for part in re.split(r"[^A-Za-z]+", local_part) if len(part) >= 3}
    return sorted(parts, key=len, reverse=True)


def redact_terms(text: str, terms: list[str], sender_domain: str = "") -> str:
    if not text:
        return text
    domain = sender_domain.lower()
    for term in terms:
        if term in domain:
            continue
        text = re.sub(rf"\b{re.escape(term)}\b", "[name]", text, flags=re.IGNORECASE)
    return text


def redact_owner(candidates: list, email_address: str | None) -> list:
    terms = owner_terms(email_address)
    if not terms:
        return candidates
    for candidate in candidates:
        candidate.subject = redact_terms(candidate.subject, terms, candidate.sender_domain)
        candidate.excerpt = redact_terms(candidate.excerpt, terms, candidate.sender_domain)
    return candidates
