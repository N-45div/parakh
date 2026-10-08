"""What a GSTIN says about itself, offline: format, check digit, state, embedded PAN and entity type."""
import re

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PATTERN = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$")
STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}
# The 4th character of a PAN says what kind of taxpayer holds it
ENTITY = {"P": "individual", "C": "company", "H": "Hindu undivided family", "F": "firm or LLP",
          "A": "association of persons", "T": "trust", "B": "body of individuals", "L": "local authority",
          "J": "artificial juridical person", "G": "government"}
COMPANY_WORDS = re.compile(r"\b(pvt|private|ltd|limited|llp|corporation|inc)\b", re.I)


def check_digit(first14: str) -> str:
    """The GSTN check character: alternate weights 1 and 2 over base-36 values, folded mod 36."""
    total = 0
    for i, ch in enumerate(first14):
        product = CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return CHARS[(36 - total % 36) % 36]


def inspect(gstin: str, name: str = "") -> dict:
    """Facts and flags readable from the number alone. Says nothing about whether it is registered or active."""
    raw = re.sub(r"\s", "", gstin or "").upper()
    if not raw:
        return {"given": False}
    match = PATTERN.match(raw)
    if not match:
        return {"given": True, "gstin": raw, "valid": False,
                "flags": [{"severity": "high", "text": "This is not a valid GSTIN format (15 characters: state code, PAN, entity number, Z, check character)."}]}
    state, pan, _, given_check = match.groups()
    expected = check_digit(raw[:14])
    facts = {"given": True, "gstin": raw, "state_code": state, "state": STATES.get(state), "pan": pan,
             "entity_type": ENTITY.get(pan[3]), "registration_number": int(CHARS.index(raw[12])), "flags": []}
    if given_check != expected:
        facts["valid"] = False
        facts["flags"].append({"severity": "high", "text": f"The check character is {given_check}, but this GSTIN's first 14 characters require {expected}. A typo, or a made-up number."})
        return facts
    facts["valid"] = True
    if state not in STATES:
        facts["flags"].append({"severity": "high", "text": f"State code {state} is not a GST state code."})
    if facts["entity_type"] is None:
        facts["flags"].append({"severity": "medium", "text": f"The PAN's 4th character ({pan[3]}) is not a recognised taxpayer type."})
    elif name and COMPANY_WORDS.search(name) and pan[3] == "P":
        facts["flags"].append({"severity": "medium", "text": "The name looks like a company, but the PAN inside this GSTIN belongs to an individual."})
    elif name and pan[3] in "CF" and not COMPANY_WORDS.search(name) and not re.search(r"\b(and|&|co)\b", name, re.I):
        facts["flags"].append({"severity": "low", "text": f"The PAN inside this GSTIN belongs to a {facts['entity_type']}; check the invoice shows the full legal name."})
    return facts
