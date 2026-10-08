"""The searches Parakh runs for one supplier, and the public results they return, normalised."""
import html
import re

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
    """Yields a progress event after each search, then {"step": "gathered", ...} with the results."""
    name, city, gstin = vendor["name"].strip(), vendor["city"].strip(), vendor.get("gstin") or ""
    core = core_name(name)
    items: list[dict] = []
    region = {"gl": "in", "hl": "en"}

    def done(step, detail):
        last = searches.log[-1]
        return {"step": step, "detail": detail, "results": last["results"], "cached": last["cached"], "error": last["error"]}

    if gstin:
        items += _organic("registry", searches.run("GST registry listings", "google", q=f'"{gstin}"', num=10, **region))
        yield done("registry", "Searched GST registry listings for the GSTIN")

    listing = _listing(searches.run("Business listing", "google_maps", q=f"{core} {city}", type="search", **region), name)
    yield done("listing", f"Google Maps: {listing['title']}" if listing else "Google Maps: no listing found")

    if listing and listing.get("data_id") and (listing.get("reviews") or 0) > 0:
        reviews = searches.run("Lowest-rated reviews", "google_maps_reviews", shown=f"reviews of {listing['title']}",
                              data_id=listing["data_id"], sort_by="ratingLow", hl="en")
        items += [_item("reviews", i, f"{r.get('rating')}★ review", r.get("snippet") or (r.get("extracted_snippet") or {}).get("original"),
                        r.get("link"), r.get("iso_date") or r.get("date"), "Google Maps review")
                  for i, r in enumerate((reviews.get("reviews") or [])[:8]) if (r.get("rating") or 5) <= 3]
        yield done("reviews", f"Read the lowest-rated of {listing['reviews']} Google reviews")

    news = searches.run("News: enforcement or fraud", "google_news",
                        q=f'"{core}" (fraud OR raid OR arrested OR "fake invoice" OR "GST evasion" OR cheating OR scam)', **region)
    items += [_item("news", i, n.get("title"), n.get("snippet") or "", n.get("link"), n.get("date"), (n.get("source") or {}).get("name"))
              for i, n in enumerate((news.get("news_results") or [])[:8]) if n.get("link")]
    yield done("news", "Searched news for raids, arrests, fake invoices and fraud")

    items += _organic("court", searches.run("Court records", "google", q=f'"{core}" site:indiankanoon.org', num=10, **region))
    yield done("court", "Searched court records on Indian Kanoon")

    items += _organic("complaints", searches.run("Complaints and scam reports", "google",
                      q=f'"{core}" {city} (complaint OR scam OR fraud OR cheated OR "not delivered")', num=10, **region))

    yield done("complaints", "Searched complaint and scam reports")
    # Two searches can find the same page; it is one piece of evidence
    unique = list({i["link"] or i["id"]: i for i in items if i["title"] or i["snippet"]}.values())
    yield {"step": "gathered", "core_name": core, "listing": listing, "items": unique}
