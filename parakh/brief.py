"""Fixed rules turn the GSTIN check, the Maps listing and the labelled results into a brief. No model decides the verdict."""
import time
import uuid
from datetime import date

RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}
SOURCE_NAMES = {"registry": "GST registry listing", "reviews": "Google Maps review", "news": "News",
                "court": "Court record", "complaints": "Complaint or forum post", "company": "Company registry listing",
                "phone": "Report about the phone number"}
GROUPS = {
    "court_case": ("{n} court record{s} name this supplier in routine matters: cases it brought, consumer disputes or appeals.", "Court records"),
    "customer_complaint": ("{n} ordinary customer complaint{s} mention this supplier.", "Reviews and complaint sites"),
    "fraud_or_enforcement": ("{n} minor mention{s} in enforcement-related coverage, with nothing naming this supplier as accused.", "News"),
}
VERDICTS = {
    "hold": "Hold the payment until you have checked these",
    "verify": "Pay only after the checks below",
    "clear": "No red flags in the public records searched",
}


def _flag(severity, text, source, link=None, quote="", date=None, publisher=None):
    return {"severity": severity, "text": text, "source": source, "link": link, "quote": quote, "date": date, "publisher": publisher}


def _age_days(when: str, today: date) -> int | None:
    """Days since a YYYY-MM-DD (or YYYY-MM) date; None for a bare year or nothing."""
    parts = [int(x) for x in when.split("-")] if when else []
    if len(parts) < 2:
        return None
    return (today - date(parts[0], parts[1], parts[2] if len(parts) > 2 else 1)).days


def build(vendor: dict, gst: dict, gathered: dict, judged: list[dict], model: str, searches: list[dict], today: date | None = None) -> dict:
    listing, flags, identity = gathered.get("listing"), [], {}
    today = today or date.today()

    for f in gst.get("flags", []):
        flags.append(_flag(f["severity"], f["text"], "GSTIN check (offline)"))

    registry = [j for j in judged if j["kind"] == "registry_record" and j["about_vendor"] != "no"]
    statuses = {j["status"] for j in registry if j["status"]}
    names = sorted({j["legal_name"] for j in registry if j["legal_name"]})
    identity["registry"] = {"status": next((s for s in ("cancelled", "suspended", "inactive", "active") if s in statuses), None),
                            "legal_names": names, "sources": [{"title": j["title"], "link": j["link"], "quote": j["quote"]} for j in registry[:4]]}
    status = identity["registry"]["status"]
    if status in ("cancelled", "suspended"):
        flags.append(_flag("high", f"Public GST directories list this GSTIN as {status}. Invoices from a {status} registration can cost you the input tax credit.",
                           "GST registry listing", registry[0]["link"], next((j["quote"] for j in registry if j["quote"]), "")))
    elif status == "inactive":
        flags.append(_flag("medium", "A public GST directory lists this GSTIN as inactive. Confirm its current status on the GST portal.",
                           "GST registry listing", registry[0]["link"]))
    if gst.get("given") and gst.get("valid") and not registry:
        flags.append(_flag("low", "No public GST directory listing mentions this GSTIN. New registrations take time to appear; confirm it on the GST portal.", "GST registry search"))
    if len(names) > 1:
        flags.append(_flag("low", f"Directories show different legal names for this GSTIN: {', '.join(names[:3])}. The invoice name should match one exactly.", "GST registry listing"))
    registered = min((j.get("registered_on", "") for j in registry if j.get("registered_on", "")), default="")
    identity["registry"]["registered_on"] = registered or None
    age = _age_days(registered, today)
    if age is not None and 0 <= age < 183:
        flags.append(_flag("medium", f"This GSTIN was registered on {registered}, under six months ago. New registrations are common in fake-invoice rackets; ask for trade references.",
                           "GST registry listing", next((j["link"] for j in registry if j.get("registered_on", "") == registered), None)))

    company = [j for j in judged if j["kind"] == "company_record" and j["about_vendor"] == "yes"]
    if company:
        statuses = [j["status"] for j in company if j["status"]]
        status = next((s for s in ("strike_off", "under_liquidation", "dormant", "amalgamated", "active") if s in statuses), None)
        incorporated = min((j.get("registered_on", "") for j in company if j.get("registered_on", "")), default="")
        identity["company"] = {"status": status, "incorporated": incorporated or None, "cin": next((j.get("cin", "") for j in company if j.get("cin", "")), None),
                               "names": sorted({j["legal_name"] for j in company if j["legal_name"]})[:3],
                               "sources": [{"title": j["title"], "link": j["link"], "quote": j["quote"]} for j in company[:3]]}
        source = next((j for j in company if j["status"] == status), company[0])
        if status in ("strike_off", "under_liquidation"):
            words = "struck off" if status == "strike_off" else "under liquidation"
            flags.append(_flag("high", f"Company directories list this company as {words}. A company in that state should not be trading or invoicing.",
                               "Company registry listing", source["link"], source["quote"]))
        elif status == "dormant":
            flags.append(_flag("medium", "Company directories list this company as dormant: it has reported no significant business.", "Company registry listing", source["link"], source["quote"]))
        elif status == "amalgamated":
            flags.append(_flag("medium", "Company directories list this company as amalgamated: it has merged into another company. Ask which company will invoice you, and check that one.",
                               "Company registry listing", source["link"], source["quote"]))
        age = _age_days(incorporated, today)
        if age is not None and 0 <= age < 365:
            flags.append(_flag("medium", f"The company was incorporated on {incorporated}, less than a year ago. Ask for trade references before an advance.",
                               "Company registry listing", source["link"]))

    identity["listing"] = listing
    if not listing:
        flags.append(_flag("low", f"No Google Maps listing found for {gathered['core_name']} in {vendor['city']}. Many small suppliers have none; ask for an address you can visit.", "Google Maps"))
    else:
        if listing["permanently_closed"]:
            flags.append(_flag("high", "Google Maps marks this business as permanently closed.", "Google Maps", listing.get("maps_link")))
        elif listing["temporarily_closed"]:
            flags.append(_flag("medium", "Google Maps marks this business as temporarily closed.", "Google Maps", listing.get("maps_link")))
        if listing.get("older_closed") and not listing["permanently_closed"]:
            flags.append(_flag("low", f"An older Maps listing is marked permanently closed ({listing['older_closed'][0]}); the current one is open. Make sure your invoice shows the current address.", "Google Maps"))
        if not listing["name_matches"]:
            flags.append(_flag("low", f"The closest Maps listing is “{listing['title']}”, which may be a different business.", "Google Maps", listing.get("maps_link")))
        elif gst.get("valid") and gst.get("state") and listing.get("address") and gst["state"].lower() not in listing["address"].lower():
            flags.append(_flag("medium", f"The GSTIN is registered in {gst['state']}, but the Maps listing is at {listing['address']}. A branch is possible; ask which registration will invoice you.", "GSTIN + Google Maps", listing.get("maps_link")))

    about = [j for j in judged if j["about_vendor"] == "yes" and j["severity"] != "none" and j["kind"] not in ("registry_record", "company_record")]
    for j in about:
        if j["severity"] != "low":
            flags.append(_flag(j["severity"], j["finding"] or j["title"], SOURCE_NAMES.get(j["source"], j["source"]), j["link"], j["quote"], j["date"], j["publisher"]))
    # Routine mentions are summarised per source instead of listed one by one
    for kind in dict.fromkeys(j["kind"] for j in about if j["severity"] == "low"):
        group = [j for j in about if j["severity"] == "low" and j["kind"] == kind]
        n = len(group)
        text, label = GROUPS.get(kind, ("{n} other minor mention{s} of this supplier.", "Various sources"))
        flag = _flag("low", text.format(n=n, s="s" if n > 1 else ""), label)
        flag["items"] = [{"text": j["finding"] or j["title"], "link": j["link"], "quote": j["quote"]} for j in group]
        flags.append(flag)
    clashes = [{"text": j["finding"] or j["title"], "source": SOURCE_NAMES.get(j["source"], j["source"]), "link": j["link"], "quote": j["quote"],
                "severity": j["severity"], "date": j["date"], "publisher": j["publisher"]}
               for j in judged if j["about_vendor"] == "unclear" and j["severity"] in ("high", "medium") and j["kind"] not in ("registry_record", "company_record")]
    flags.sort(key=lambda f: RANK[f["severity"]])

    severities = {f["severity"] for f in flags}
    verdict = "hold" if "high" in severities else "verify" if ("medium" in severities or clashes or not gst.get("given")) else "clear"

    steps = []
    if gst.get("given"):
        steps.append({"text": "Confirm the GSTIN's status, legal name and registration date on the GST portal (Search Taxpayer).", "link": "https://services.gst.gov.in/services/searchtp"})
    else:
        steps.append({"text": "Ask for the GSTIN and run this check again. Without it you cannot claim input tax credit on the invoice.", "link": None})
    if gst.get("entity_type") in ("company", "firm or LLP") or identity.get("company"):
        steps.append({"text": "Look the company or LLP up on the MCA portal: is it active, and who are the directors?", "link": "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html"})
    steps.append({"text": "Ask for a cancelled cheque or bank letter in the same legal name as the invoice before you pay.", "link": None})
    if clashes:
        steps.append({"text": f"Rule out the {len(clashes)} result{'s' if len(clashes) > 1 else ''} below about a business with a similar name.", "link": None})
    if verdict != "clear":
        steps.append({"text": "Keep any advance small, or pay against delivery, until the flags are resolved.", "link": None})

    by_source = {}
    for j in judged:
        s = by_source.setdefault(j["source"], {"read": 0, "about_vendor": 0, "unclear": 0})
        s["read"] += 1
        s["about_vendor"] += j["about_vendor"] == "yes"
        s["unclear"] += j["about_vendor"] == "unclear"

    return {
        "id": uuid.uuid4().hex[:12], "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "vendor": vendor,
        "verdict": verdict, "headline": VERDICTS[verdict], "flags": flags, "clashes": clashes, "next_steps": steps,
        "identity": {**identity, "gstin": {k: v for k, v in gst.items() if k != "flags"}},
        "read": by_source, "model": model, "searches": searches,
        "limits": ["Whether the supplier actually files GST returns (the GST portal shows this)",
                   "Who owns the bank account you are about to pay",
                   "Disputes that never reached the news, the courts or online reviews"],
    }
