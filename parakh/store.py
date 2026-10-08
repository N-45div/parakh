"""Where Parakh keeps search results, briefs and daily counters: MongoDB Atlas when MONGODB_URI is set
(as on Vercel, whose disk does not persist), local folders otherwise."""
import hashlib
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 5.5 * 3600))  # India's day


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.counters: dict[str, int] = {}
        uri = os.environ.get("MONGODB_URI")
        if uri:
            from pymongo import MongoClient
            db = MongoClient(uri, serverSelectionTimeoutMS=8000)[os.environ.get("PARAKH_DATABASE", "parakh")]
            self.cache, self.checks, self.counts = db["cache"], db["checks"], db["counters"]
        else:
            self.cache = self.checks = self.counts = None
            self.cache_dir = Path(os.environ.get("PARAKH_CACHE", ROOT / "cache"))
            self.check_dir = Path(os.environ.get("PARAKH_CHECKS", ROOT / "checks"))
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.check_dir.mkdir(parents=True, exist_ok=True)

    # Search results, keyed by their parameters
    def cached(self, key: str) -> dict | None:
        if self.cache is not None:
            doc = self.cache.find_one({"_id": key})
            return doc["data"] if doc else None
        path = self.cache_dir / f"{key}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def remember(self, key: str, data: dict):
        if self.cache is not None:
            self.cache.replace_one({"_id": key}, {"_id": key, "data": data, "at": time.time()}, upsert=True)
        else:
            (self.cache_dir / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # Briefs
    def save(self, brief: dict):
        if self.checks is not None:
            self.checks.replace_one({"_id": brief["id"]}, {"_id": brief["id"], **brief}, upsert=True)
        else:
            (self.check_dir / f"{brief['id']}.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")

    def load(self, check_id: str) -> dict | None:
        if self.checks is not None:
            doc = self.checks.find_one({"_id": check_id}, {"_id": 0})
            return doc
        path = self.check_dir / f"{check_id}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def examples(self) -> list[dict]:
        if self.checks is not None:
            docs = list(self.checks.find({"example": True}, {"_id": 0}).sort("created_at", 1))
        else:
            docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.check_dir.glob("*.json"))]
            docs = [d for d in docs if d.get("example")]
        return [{"id": d["id"], "name": d["vendor"]["name"], "city": d["vendor"]["city"], "verdict": d["verdict"],
                 "gstin": d["vendor"].get("gstin"), "note": d.get("example_note", "")} for d in docs]

    # Daily counters: live SerpApi calls across everyone, and checks per visitor
    def take(self, name: str, limit: int) -> bool:
        key = f"{name}:{today()}"
        if self.counts is not None:
            from pymongo import ReturnDocument
            doc = self.counts.find_one_and_update({"_id": key}, {"$inc": {"n": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
            return doc["n"] <= limit
        with self.lock:
            self.counters[key] = self.counters.get(key, 0) + 1
            return self.counters[key] <= limit


def visitor(ip: str) -> str:
    return hashlib.sha256(f"{os.environ.get('PARAKH_SALT', 'parakh')}:{ip}".encode()).hexdigest()[:16]
