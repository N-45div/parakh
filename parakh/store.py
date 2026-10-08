"""Where Parakh keeps search results, briefs and daily counters.

Upstash Redis when its REST settings are present (as on Vercel, whose disk does not persist), MongoDB Atlas when
MONGODB_URI is set, local folders otherwise. All three offer the same six operations.
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 5.5 * 3600))  # India's day


def summary(brief: dict) -> dict:
    v = brief["vendor"]
    return {"id": brief["id"], "name": v["name"], "city": v["city"], "verdict": brief["verdict"], "gstin": v.get("gstin"),
            "note": brief.get("example_note", ""), "created_at": brief["created_at"]}


class RedisStore:
    def __init__(self, url: str, token: str):
        self.http = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=10)

    def _run(self, *command):
        response = self.http.post("/", json=[str(c) for c in command])
        response.raise_for_status()
        return response.json().get("result")

    def cached(self, key):
        raw = self._run("GET", f"parakh:cache:{key}")
        return json.loads(raw) if raw else None

    def remember(self, key, data):
        self._run("SET", f"parakh:cache:{key}", json.dumps(data, ensure_ascii=False), "EX", 30 * DAY)

    def save(self, brief):
        self._run("SET", f"parakh:check:{brief['id']}", json.dumps(brief, ensure_ascii=False), "EX", 180 * DAY)
        if brief.get("example"):
            self._run("SADD", "parakh:examples", brief["id"])

    def load(self, check_id):
        raw = self._run("GET", f"parakh:check:{check_id}")
        return json.loads(raw) if raw else None

    def examples(self):
        found = [self.load(i) for i in sorted(self._run("SMEMBERS", "parakh:examples") or [])]
        return [summary(b) for b in found if b]

    def take(self, name, limit):
        key = f"parakh:count:{name}:{today()}"
        n = int(self._run("INCR", key))
        if n == 1:
            self._run("EXPIRE", key, 2 * DAY)
        return n <= limit


class MongoStore:
    def __init__(self, uri: str):
        from pymongo import MongoClient
        db = MongoClient(uri, serverSelectionTimeoutMS=8000)[os.environ.get("PARAKH_DATABASE", "parakh")]
        self.cache, self.checks, self.counts = db["cache"], db["checks"], db["counters"]

    def cached(self, key):
        doc = self.cache.find_one({"_id": key})
        return doc["data"] if doc else None

    def remember(self, key, data):
        self.cache.replace_one({"_id": key}, {"_id": key, "data": data, "at": time.time()}, upsert=True)

    def save(self, brief):
        self.checks.replace_one({"_id": brief["id"]}, {"_id": brief["id"], **brief}, upsert=True)

    def load(self, check_id):
        return self.checks.find_one({"_id": check_id}, {"_id": 0})

    def examples(self):
        return [summary(b) for b in self.checks.find({"example": True}, {"_id": 0}).sort("id", 1)]

    def take(self, name, limit):
        from pymongo import ReturnDocument
        doc = self.counts.find_one_and_update({"_id": f"{name}:{today()}"}, {"$inc": {"n": 1}}, upsert=True,
                                              return_document=ReturnDocument.AFTER)
        return doc["n"] <= limit


class LocalStore:
    def __init__(self):
        self.lock, self.counters = threading.Lock(), {}
        self.cache_dir = Path(os.environ.get("PARAKH_CACHE", ROOT / "cache"))
        self.check_dir = Path(os.environ.get("PARAKH_CHECKS", ROOT / "checks"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.check_dir.mkdir(parents=True, exist_ok=True)

    def cached(self, key):
        path = self.cache_dir / f"{key}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def remember(self, key, data):
        (self.cache_dir / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def save(self, brief):
        (self.check_dir / f"{brief['id']}.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")

    def load(self, check_id):
        path = self.check_dir / f"{check_id}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def examples(self):
        docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.check_dir.glob("*.json"))]
        return [summary(d) for d in docs if d.get("example")]

    def take(self, name, limit):
        with self.lock:
            key = f"{name}:{today()}"
            self.counters[key] = self.counters.get(key, 0) + 1
            return self.counters[key] <= limit


def Store():
    url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    if url and token:
        return RedisStore(url, token)
    if os.environ.get("MONGODB_URI"):
        return MongoStore(os.environ["MONGODB_URI"])
    return LocalStore()


def visitor(ip: str) -> str:
    return hashlib.sha256(f"{os.environ.get('PARAKH_SALT', 'parakh')}:{ip}".encode()).hexdigest()[:16]
