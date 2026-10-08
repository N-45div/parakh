"""SerpApi calls through the official client, cached by their parameters and logged for the brief's "searches run" panel."""
import hashlib
import json
import os
import threading
import time

import serpapi

from .store import Store

# Live SerpApi calls allowed per day across all visitors; cached results are always free
DAILY_LIVE_SEARCHES = int(os.environ.get("PARAKH_DAILY_SEARCHES", "60"))


class Searches:
    def __init__(self, api_key: str | None, store: Store, offline: bool = False):
        self.client = serpapi.Client(api_key=api_key) if api_key else None
        self.offline = offline or not api_key
        self.store = store
        self.log: list[dict] = []
        self.lock = threading.Lock()

    def run(self, purpose: str, engine: str, shown: str | None = None, **params) -> dict:
        query = {"engine": engine, **params}
        key = hashlib.sha1(json.dumps(query, sort_keys=True).encode()).hexdigest()[:20]
        began = time.monotonic()
        data, cached = self.store.cached(key), True
        if data is None:
            if self.offline:
                data = {"error": "Offline: no cached result for this search."}
            elif not self.store.take("live-searches", DAILY_LIVE_SEARCHES):
                data = {"error": "Today's live-search budget is used up. Cached and example checks still work."}
            else:
                data, cached = self._fetch(query), False
                if "hasn't returned any results" in str(data.get("error", "")):
                    data = {"search_metadata": data.get("search_metadata"), "empty": True}
                if not data.get("error"):
                    data = slim(data)
                    self.store.remember(key, data)
        with self.lock:
            self.log.append({"purpose": purpose, "engine": engine,
                             "query": shown or params.get("q") or params.get("data_id") or "",
                             "results": count(data), "cached": cached, "error": data.get("error"),
                             "seconds": round(time.monotonic() - began, 2),
                             "search_id": (data.get("search_metadata") or {}).get("id")})
        return data

    def last(self, purpose: str) -> dict:
        with self.lock:
            return next(entry for entry in reversed(self.log) if entry["purpose"] == purpose)

    def _fetch(self, query: dict, attempts: int = 2) -> dict:
        for attempt in range(attempts):
            try:
                return dict(self.client.search(query))
            except serpapi.HTTPError as error:
                status = getattr(getattr(error, "response", None), "status_code", 0) or 0
                # A server-side hiccup is worth one retry; a bad request or an exhausted plan is not
                if status < 500 or attempt == attempts - 1:
                    return {"error": f"SerpApi HTTP error: {error}"}
                time.sleep(2)
        return {"error": "SerpApi unavailable"}


KEEP = {
    "organic_results": ("title", "snippet", "link", "date", "source", "displayed_link"),
    "news_results": ("title", "snippet", "link", "date", "source"),
    "local_results": ("title", "address", "rating", "reviews", "type", "website", "phone", "data_id", "place_id",
                      "open_state", "hours", "operating_hours"),
    "reviews": ("rating", "snippet", "extracted_snippet", "link", "iso_date", "date"),
    "topics": ("keyword", "mentions"),
}


def slim(data: dict) -> dict:
    """Only the fields Parakh reads, so a cached response is kilobytes rather than hundreds of them."""
    out = {"search_metadata": {"id": (data.get("search_metadata") or {}).get("id")}}
    for key, fields in KEEP.items():
        if isinstance(data.get(key), list):
            out[key] = [{f: row[f] for f in fields if f in row} for row in data[key]]
    if isinstance(data.get("place_results"), dict):
        out["place_results"] = {f: data["place_results"][f] for f in KEEP["local_results"] if f in data["place_results"]}
    if data.get("empty"):
        out["empty"] = True
    return out


def count(data: dict) -> int:
    for key in ("organic_results", "news_results", "local_results", "reviews"):
        if isinstance(data.get(key), list):
            return len(data[key])
    return 1 if data.get("place_results") else 0
