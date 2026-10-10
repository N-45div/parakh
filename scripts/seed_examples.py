"""Copy the local search cache into the configured store and save the shared example briefs.

  DATABASE_URL=... python scripts/seed_examples.py

Every example runs through the same pipeline as a visitor's check; with the cache copied first, it spends no
SerpApi credits.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from parakh import pipeline  # noqa: E402  (keys load first)
from parakh.search import slim  # noqa: E402
from parakh.store import Store  # noqa: E402

EXAMPLES = [
    ({"name": "Ecoren Energy India Private Limited", "city": "Hyderabad", "gstin": ""}, "MD's arrest reported in the news"),
    ({"name": "Tata Motors Limited", "city": "Bengaluru", "gstin": "29AAACT2727Q1ZS"}, "a large, established supplier"),
    ({"name": "Tata Motors Limited", "city": "Bengaluru", "gstin": "29AAACT2727Q1ZT"}, "one wrong character in the GSTIN"),
    ({"name": "Sri Balaji Traders", "city": "Bengaluru", "gstin": ""}, "a very common business name"),
    ({"name": "SHREE VINAYAKA CORRUGATORS", "city": "Bengaluru", "gstin": "29ABKFS4821L1ZM", "payee": "R MANJUNATH", "amount": 92500,
      "account": "38291047664417", "ifsc": "SBIN0000011", "bank": "State Bank of India, Peenya Branch"},
     "fictional quote: account in another name, at a branch in another state"),
]

store = Store()
copied = 0
for path in sorted((ROOT / "cache").glob("*.json")):
    if store.cached(path.stem) is None:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Model labels and IFSC lookups are stored as they are; only search responses are slimmed
        store.remember(path.stem, data if path.stem.startswith(("judge-", "ifsc-")) else slim(data))
        copied += 1
print(f"copied {copied} cached searches")
for vendor, note in EXAMPLES:
    brief = next(e["brief"] for e in pipeline.run(vendor, store) if e["step"] == "done")
    live = [s for s in brief["searches"] if not s["cached"]]
    brief.update(example=True, example_note=note, id=f"example{EXAMPLES.index((vendor, note)) + 1}")
    store.save(brief)
    print(f"{brief['id']}: {vendor['name']} -> {brief['verdict']} ({len(live)} live searches)")
