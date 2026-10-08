"""Where Parakh keeps search results, briefs and daily counters.

Postgres when DATABASE_URL is set (Neon on Vercel, whose disk does not persist), local folders otherwise. Both offer
the same six operations.
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = """
create table if not exists parakh_cache (key text primary key, data jsonb not null, at timestamptz not null default now());
create table if not exists parakh_checks (id text primary key, brief jsonb not null, example boolean not null default false,
                                          created_at timestamptz not null default now());
create table if not exists parakh_counters (key text primary key, n integer not null);
"""


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 5.5 * 3600))  # India's day


def summary(brief: dict) -> dict:
    v = brief["vendor"]
    return {"id": brief["id"], "name": v["name"], "city": v["city"], "verdict": brief["verdict"], "gstin": v.get("gstin"),
            "note": brief.get("example_note", ""), "created_at": brief["created_at"]}


class PostgresStore:
    def __init__(self, url: str):
        self.url, self.conn, self.lock = url, None, threading.Lock()

    def _run(self, sql: str, params: tuple = (), fetch: bool = False):
        import psycopg
        from psycopg.types.json import Jsonb
        params = tuple(Jsonb(p) if isinstance(p, dict) else p for p in params)
        with self.lock:
            for attempt in range(2):
                try:
                    if self.conn is None or self.conn.closed:
                        # Neon's pooled endpoint runs PgBouncer in transaction mode: no server-side prepared statements
                        self.conn = psycopg.connect(self.url, autocommit=True, prepare_threshold=None, connect_timeout=10)
                        self.conn.execute(SCHEMA)
                    cursor = self.conn.execute(sql, params)
                    return cursor.fetchall() if fetch else None
                except psycopg.OperationalError:
                    self.conn = None  # a serverless instance may wake to a closed connection; reconnect once
                    if attempt:
                        raise

    def cached(self, key):
        rows = self._run("select data from parakh_cache where key = %s", (key,), fetch=True)
        return rows[0][0] if rows else None

    def remember(self, key, data):
        self._run("insert into parakh_cache (key, data) values (%s, %s) on conflict (key) do update set data = excluded.data, at = now()", (key, data))

    def save(self, brief):
        self._run("insert into parakh_checks (id, brief, example) values (%s, %s, %s) on conflict (id) do update set brief = excluded.brief, example = excluded.example",
                  (brief["id"], brief, bool(brief.get("example"))))

    def load(self, check_id):
        rows = self._run("select brief from parakh_checks where id = %s", (check_id,), fetch=True)
        return rows[0][0] if rows else None

    def examples(self):
        return [summary(row[0]) for row in self._run("select brief from parakh_checks where example order by id", fetch=True)]

    def take(self, name, limit):
        rows = self._run("insert into parakh_counters (key, n) values (%s, 1) on conflict (key) do update set n = parakh_counters.n + 1 returning n",
                         (f"{name}:{today()}",), fetch=True)
        return rows[0][0] <= limit


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
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    return PostgresStore(url) if url else LocalStore()


def visitor(ip: str) -> str:
    return hashlib.sha256(f"{os.environ.get('PARAKH_SALT', 'parakh')}:{ip}".encode()).hexdigest()[:16]
