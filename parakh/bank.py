"""The bank account a supplier asks to be paid into, read through its IFSC.

The IFSC names the bank branch that holds the account. The directory is the RBI's list as published by Razorpay
(ifsc.razorpay.com, no key needed). An account at a branch in another state from the supplier's GST registration, or
at a different branch from the one the quote itself names, is how diverted-payment fraud usually looks: the money goes
to an account someone else controls.
"""
import re

import httpx

IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
# Words that name a bank or a kind of branch, not where it is
BANK_WORDS = re.compile(r"\b(state|bank|of|india|branch|br|ltd|limited|the|co|op|operative|cooperative|co-operative|sahakari|urban|gramin|main|road|rd)\b")


def normalise_ifsc(text: str | None) -> str:
    return re.sub(r"\s", "", text or "").upper()


def account_digits(text: str | None) -> str:
    """An Indian bank account number (9 to 18 digits) without spaces or dashes; empty if it isn't one."""
    digits = re.sub(r"[\s-]", "", text or "")
    return digits if re.fullmatch(r"\d{9,18}", digits) else ""


def branch(code: str, store=None) -> dict | None:
    """The branch an IFSC belongs to; {} when no branch has that code; None when the directory could not be reached."""
    cached = store.cached(f"ifsc-{code}") if store is not None else None
    if cached is not None:
        return cached["branch"]
    try:
        response = httpx.get(f"https://ifsc.razorpay.com/{code}", timeout=10)
    except httpx.HTTPError:
        return None
    if response.status_code == 404:
        found = {}
    elif response.is_success:
        data = response.json()
        found = {"bank": data.get("BANK") or "", "branch": data.get("BRANCH") or "", "city": data.get("CITY") or "",
                 "district": data.get("DISTRICT") or "", "state": data.get("STATE") or "", "address": data.get("ADDRESS") or ""}
    else:
        return None
    if store is not None:
        store.remember(f"ifsc-{code}", {"branch": found})
    return found


def same_state(a: str, b: str) -> bool:
    a, b = (re.sub(r"[^a-z]", "", s.lower().replace("&", "and")) for s in (a, b))
    return bool(a and b) and (a in b or b in a)


def names_branch(claimed: str, found: dict) -> bool | None:
    """Whether the bank and branch the quote names fit the IFSC's branch; None when the quote names no place."""
    bank_words = set(re.findall(r"[a-z]+", found.get("bank", "").lower()))
    words = {w for w in re.findall(r"[a-z]+", BANK_WORDS.sub(" ", claimed.lower())) if len(w) > 2} - bank_words
    if not words:
        return None
    place = " ".join(found.get(k, "") for k in ("branch", "city", "district", "address")).lower()
    return any(w in place for w in words)
