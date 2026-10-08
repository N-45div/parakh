"""The searches Parakh runs for one supplier, and the public results they return, normalised."""
import html
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .search import Searches

SUFFIXES = re.compile(r"(?:^|(?<=\s))(m/s\.?|ms\.|private|pvt\.?|limited|ltd\.?|llp)(?=\s|,|$)", re.I)


def core_name(name: str) -> str:
    """The distinctive part of a business name, so a search matches "Pvt Ltd" and "Private Limited" alike."""
    core = re.sub(r"\s+", " ", SUFFIXES.sub(" ", name)).strip(" .,&")
    return core or name.strip()


def _item(source: str, n: int, title: str, snippet: str, link: str | None, date: str | None = None, publisher: str | None = None):
    return {"id": f"{source}-{n}", "source": source, "title": (title or "").strip(), "snippet": (snippet or "").strip(),
            "link": link, "date": date, "publisher": publisher}


def _organic(source: str, data: dict, limit: int = 8):
    return [_item(source, i, r.get("title"), r.get("snippet"), r.get("link"), r.get("date"), r.get("source") or r.get("displayed_link"))
            for i, r in enumerate((data.get("organic_results") or [])[:limit])]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def _closed(place: dict, words: str) -> bool:
    return words in f"{place.get('open_state', '')} {place.get('hours', '')}".lower()


def _listing(data: dict, name: str) -> dict | None:
    # The result whose name shares most words with the supplier, not simply the first pin
    wanted = _words(core_name(name))
    candidates = [data["place_results"]] if data.get("place_results") else (data.get("local_results") or [])[:6]
    if not candidates:
        return None
    best = max(len(wanted & _words(c.get("title"))) for c in candidates)
    # Listings that carry the name; a business often keeps an old, closed pin beside its current one
    matched = [c for c in candidates if best and len(wanted & _words(c.get("title"))) >= max(1, min(best, len(wanted) - 1))]
    open_ones = [c for c in matched if not _closed(c, "permanently closed")]
    place = (open_ones or matched or candidates)[0]
    old = [c for c in matched if c is not place and _closed(c, "permanently closed")]
    state = f"{place.get('open_state', '')} {' '.join(str(v) for v in (place.get('operating_hours') or {}).values())}"
    return {"title": html.unescape(place.get("title") or ""), "address": html.unescape(place.get("address") or ""), "rating": place.get("rating"),
            "reviews": place.get("reviews"), "type": place.get("type"), "website": place.get("website"),
            "phone": place.get("phone"), "data_id": place.get("data_id"), "place_id": place.get("place_id"),
            "permanently_closed": "permanently closed" in state.lower(),
            "temporarily_closed": "temporarily closed" in state.lower(),
            "name_matches": bool(matched) and place in matched,
            "older_closed": [html.unescape(f"{c.get('title')}, {c.get('address') or ''}") for c in old],
            "maps_link": f"https://www.google.com/maps/place/?q=place_id:{place['place_id']}" if place.get("place_id") else None}


def gather(vendor: dict, searches: Searches):
    """Runs the searches in parallel and yields a progress event as each one lands, then {"step": "gathered", ...}."""
    name, city, gstin = vendor["name"].strip(), vendor["city"].strip(), vendor.get("gstin") or ""
    core = core_name(name)
    region = {"gl": "in", "hl": "en"}
    plan = {
        "listing": ("Business listing", "google_maps", {"q": f"{core} {city}", "type": "search", **region}),
        "news": ("News: enforcement or fraud", "google_news",
                 {"q": f'"{core}" (fraud OR raid OR arrested OR "fake invoice" OR "GST evasion" OR cheating OR scam)', **region}),
        "court": ("Court records", "google", {"q": f'"{core}" site:indiankanoon.org', "num": 10, **region}),
        "complaints": ("Complaints and scam reports", "google",
                       {"q": f'"{core}" {city} (complaint OR scam OR fraud OR cheated OR "not delivered")', "num": 10, **region}),
    }
    if gstin:
        plan["registry"] = ("GST registry listings", "google", {"q": f'"{gstin}"', "num": 10, **region})
    if is_company(name, vendor.get("entity")):
        # Company directories (Zauba, Tofler and others) carry MCA status, incorporation date and CIN in their snippets
        plan["company"] = ("Company registry listings", "google",
                           {"q": f'"{core}" ({" OR ".join(f"site:{s}" for s in COMPANY_SITES)})', "num": 10, **region})
    phone = phone_digits(vendor.get("phone"))
    if phone:
        spaced = f"{phone[:5]} {phone[5:]}"
        typed = re.sub(r"\s+", " ", vendor["phone"]).strip()
        # Mobiles are written as 98450 12345; landlines keep the STD code's 0, as in 040 6699 3333, so the number as typed goes in too
        variants = dict.fromkeys([typed, phone, spaced, f"+91 {spaced}", f"0{phone}"] if not phone.startswith(("6", "7", "8", "9"))
                                 else [phone, spaced, f"+91 {spaced}", f"+91{phone}", typed])
        plan["phone"] = ("Phone number reports", "google", {"q": " OR ".join(f'"{v}"' for v in variants), "num": 10, **region})
    results, listing = {}, None
    with ThreadPoolExecutor(max_workers=6) as pool:
        running = {pool.submit(searches.run, purpose, engine, **params): step for step, (purpose, engine, params) in plan.items()}
        while running:
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                step = running.pop(future)
                results[step] = future.result()
                if step == "listing":
                    listing = _listing(results[step], name)
                    detail = f"Google Maps: {listing['title']}" if listing else "Google Maps: no listing found"
                    # The reviews lookup needs the listing's Maps ID, so it starts as soon as the listing lands
                    if listing and listing.get("data_id") and (listing.get("reviews") or 0) > 0:
                        plan["reviews"] = ("Lowest-rated reviews", "google_maps_reviews", {})
                        running[pool.submit(searches.run, "Lowest-rated reviews", "google_maps_reviews", shown=f"reviews of {listing['title']}",
                                            data_id=listing["data_id"], sort_by="ratingLow", hl="en")] = "reviews"
                else:
                    detail = DETAILS[step](listing)
                entry = searches.last(plan[step][0])
                yield {"step": step, "detail": detail, "results": entry["results"], "cached": entry["cached"], "error": entry["error"]}

    items = _organic("registry", results.get("registry", {}))
    items += [_item("reviews", i, f"{r.get('rating')}★ review", r.get("snippet") or (r.get("extracted_snippet") or {}).get("original"),
                    r.get("link"), r.get("iso_date") or r.get("date"), "Google Maps review")
              for i, r in enumerate((results.get("reviews", {}).get("reviews") or [])[:8]) if (r.get("rating") or 5) <= 3]
    items += [_item("news", i, n.get("title"), n.get("snippet") or "", n.get("link"), n.get("date"), (n.get("source") or {}).get("name"))
              for i, n in enumerate((results["news"].get("news_results") or [])[:8]) if n.get("link")]
    items += _organic("court", results["court"]) + _organic("complaints", results["complaints"])
    items += _organic("company", results.get("company", {})) + _organic("phone", results.get("phone", {}))
    # Two searches can find the same page; it is one piece of evidence
    unique = list({i["link"] or i["id"]: i for i in items if i["title"] or i["snippet"]}.values())
    yield {"step": "gathered", "core_name": core, "listing": listing, "items": unique}


DETAILS = {
    "registry": lambda listing: "Searched GST registry listings for the GSTIN",
    "reviews": lambda listing: f"Read the lowest-rated of {listing['reviews']} Google reviews",
    "news": lambda listing: "Searched news for raids, arrests, fake invoices and fraud",
    "court": lambda listing: "Searched court records on Indian Kanoon",
    "complaints": lambda listing: "Searched complaint and scam reports",
    "company": lambda listing: "Searched company registry listings for MCA status",
    "phone": lambda listing: "Searched reports about the phone number",
}
COMPANY = re.compile(r"\b(pvt|private|ltd|limited|llp)\b", re.I)
# Public mirrors of the MCA register whose snippets carry the CIN, status and incorporation date
COMPANY_SITES = ("zaubacorp.com", "tofler.in", "thecompanycheck.com", "instafinancials.com", "falconebiz.com")


def is_company(name: str, entity: str | None) -> bool:
    return bool(COMPANY.search(name)) or entity in ("company", "firm or LLP")


def phone_digits(phone: str | None) -> str:
    """The 10-digit Indian mobile or landline number, without +91 or a leading 0; empty if it isn't one."""
    digits = re.sub(r"\D", "", phone or "")
    digits = digits[2:] if len(digits) == 12 and digits.startswith("91") else digits[1:] if len(digits) == 11 and digits.startswith("0") else digits
    return digits if len(digits) == 10 else ""
