"""One supplier check, start to finish, as a stream of progress events ending in {"step": "done", "brief": ...}."""
import os
from collections.abc import Iterator

from . import brief, evidence, gstin, judge
from .search import Searches
from .store import Store


def run(vendor: dict, store: Store) -> Iterator[dict]:
    v = {**vendor, "gstin": (vendor.get("gstin") or "").replace(" ", "").upper()}
    yield {"step": "gstin", "detail": "Reading what the GSTIN says about itself" if v["gstin"] else "No GSTIN given"}
    gst = gstin.inspect(v["gstin"], v["name"])
    searches = Searches(os.environ.get("SERPAPI_API_KEY"), store, offline=os.environ.get("PARAKH_OFFLINE") == "1")
    # The registry search only makes sense for a well-formed GSTIN
    for event in evidence.gather({**v, "gstin": v["gstin"] if gst.get("valid") else ""}, searches):
        if event["step"] == "gathered":
            gathering = event
        else:
            yield event
    yield {"step": "judge", "detail": f"Reading {len(gathering['items'])} public results with an open model"}
    try:
        judged, model = judge.judge(v, gathering["items"], os.environ.get("TINKER_API_KEY"))
    except Exception as error:  # the brief still works on keyword labels
        judged, model = [{**i, **judge.fallback(i, v)} for i in gathering["items"]], f"keywords (model unavailable: {type(error).__name__})"
    result = brief.build(v, gst, gathering, judged, model, searches.log)
    store.save(result)
    yield {"step": "done", "brief": result}
