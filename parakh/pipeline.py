"""One supplier check, start to finish, as a stream of progress events ending in {"step": "done", "brief": ...}."""
import os
from collections.abc import Iterator

from . import bank, brief, domain, evidence, gstin, judge
from .search import Searches
from .store import Store


def _bank(v: dict, store: Store) -> tuple[dict, str]:
    code = bank.normalise_ifsc(v.get("ifsc"))
    if not bank.IFSC.match(code):
        return {"ifsc": code, "valid_format": False, "branch": None, "claimed": ""}, f"{code} is not a valid IFSC"
    found = bank.branch(code, store)
    checked = {"ifsc": code, "valid_format": True, "branch": found, "claimed": (v.get("bank") or "").strip()}
    if found:
        return checked, f"IFSC {code}: {found['bank']}, {found['branch'].title()} branch, {found['state'].title()}"
    return checked, f"IFSC {code}: no bank branch has this code" if found == {} else "The IFSC directory could not be reached"


def run(vendor: dict, store: Store) -> Iterator[dict]:
    v = {**vendor, "gstin": (vendor.get("gstin") or "").replace(" ", "").upper()}
    yield {"step": "gstin", "detail": "Reading what the GSTIN says about itself" if v["gstin"] else "No GSTIN given"}
    gst = gstin.inspect(v["gstin"], v["name"])
    # Which branch holds the account the money would go to
    checked = None
    if v.get("ifsc"):
        checked, detail = _bank(v, store)
        yield {"step": "bank", "detail": detail}
    searches = Searches(os.environ.get("SERPAPI_API_KEY"), store, offline=os.environ.get("PARAKH_OFFLINE") == "1")
    # The registry search only makes sense for a well-formed GSTIN
    for event in evidence.gather({**v, "gstin": v["gstin"] if gst.get("valid") else "", "entity": gst.get("entity_type")}, searches):
        if event["step"] == "gathered":
            gathering = event
        else:
            yield event
    gathering["bank"] = checked
    # A website is the supplier's only when the Maps listing it came from is really this business
    listing = gathering.get("listing") or {}
    site = domain.domain_of(listing.get("website")) if listing.get("name_matches") else None
    if site:
        gathering["website"] = {"domain": site, "registered": domain.registered(site)}
        yield {"step": "website", "detail": f"{site}: registered {gathering['website']['registered'] or 'date not published'}"}
    yield {"step": "judge", "detail": f"Reading {len(gathering['items'])} public results with an open model"}
    try:
        judged, model = judge.judge(v, gathering["items"], os.environ.get("TINKER_API_KEY"), store)
    except Exception as error:  # the brief still works on keyword labels
        judged, model = [{**i, **judge.fallback(i, v)} for i in gathering["items"]], f"keywords (model unavailable: {type(error).__name__})"
    result = brief.build(v, gst, gathering, judged, model, searches.log)
    store.save(result)
    yield {"step": "done", "brief": result}
