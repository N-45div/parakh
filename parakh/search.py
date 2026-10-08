"""SerpApi calls through the official client, cached on disk and logged for the brief's "searches run" panel."""
import hashlib
import json
import os
import time
from pathlib import Path

import serpapi

CACHE = Path(os.environ.get("PARAKH_CACHE", Path(__file__).resolve().parents[1] / "cache"))


class Searches:
    def __init__(self, api_key: str | None, offline: bool = False):
        self.client = serpapi.Client(api_key=api_key) if api_key else None
        self.offline = offline or not api_key
        self.log: list[dict] = []
        CACHE.mkdir(parents=True, exist_ok=True)

    def run(self, purpose: str, engine: str, shown: str | None = None, **params) -> dict:
        query = {"engine": engine, **params}
        path = CACHE / (hashlib.sha1(json.dumps(query, sort_keys=True).encode()).hexdigest()[:20] + ".json")
        began = time.monotonic()
        if path.exists():
            data, cached = json.loads(path.read_text(encoding="utf-8")), True
        elif self.offline:
            data, cached = {"error": "Offline: no cached result for this search."}, True
        else:
            try:
                data = dict(self.client.search(query))
            except serpapi.HTTPError as error:
                data = {"error": f"SerpApi HTTP error: {error}"}
            cached = False
            if not data.get("error"):
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.log.append({"purpose": purpose, "engine": engine,
                         "query": shown or params.get("q") or params.get("data_id") or "",
                         "results": count(data), "cached": cached, "error": data.get("error"),
                         "seconds": round(time.monotonic() - began, 2),
                         "search_id": (data.get("search_metadata") or {}).get("id")})
        return data


def count(data: dict) -> int:
    for key in ("organic_results", "news_results", "local_results", "reviews"):
        if isinstance(data.get(key), list):
            return len(data[key])
    return 1 if data.get("place_results") else 0
