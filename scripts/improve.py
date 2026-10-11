"""Measure, and improve, how well the open model labels search results, using only cached SerpApi data.

  python scripts/improve.py export      writes evaluations/results.json: every cached result for the test suppliers
  python scripts/improve.py score       scores the labels against evaluations/reference.json, with and without the skeptic
  python scripts/improve.py loop        an optimizer agent turns mistakes into lessons; lessons are kept only if they
                                        score better on results it never saw, and are then written to parakh/lessons.txt

No SerpApi credits are spent: the suppliers' searches are all served from the cache. The model calls go to Tinker.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
import httpx  # noqa: E402

from parakh import evidence, gstin, judge, skeptic  # noqa: E402
from parakh.search import Searches  # noqa: E402
from parakh.store import LocalStore  # noqa: E402

EVALS = ROOT / "evaluations"
KEY = os.environ.get("TINKER_API_KEY")
SUPPLIERS = [
    {"name": "Ecoren Energy India Private Limited", "city": "Hyderabad", "gstin": "", "phone": "040 6699 3333"},
    {"name": "Tata Motors Limited", "city": "Bengaluru", "gstin": "29AAACT2727Q1ZS"},
    {"name": "Sri Balaji Traders", "city": "Bengaluru", "gstin": ""},
    {"name": "SHREE VINAYAKA CORRUGATORS", "city": "Bengaluru", "gstin": "29ABKFS4821L1ZM", "payee": "R MANJUNATH", "account": "38291047664417"},
]
RECORDS = ("registry_record", "company_record")
MONEY = ("payee", "phone", "account")


def gathered(n: int, store) -> tuple[dict, dict, dict]:
    vendor = SUPPLIERS[n]
    gst = gstin.inspect(vendor["gstin"], vendor["name"])
    searches = Searches(None, store, offline=True)
    found = next(e for e in evidence.gather({**vendor, "entity": gst.get("entity_type")}, searches) if e["step"] == "gathered")
    missing = [s["purpose"] for s in searches.log if s.get("error")]
    if missing:
        raise SystemExit(f"{vendor['name']}: not cached: {missing}")
    return vendor, gst, found


def export():
    store, rows = LocalStore(), []
    for n in range(len(SUPPLIERS)):
        _, _, found = gathered(n, store)
        rows += [{"case": f"s{n}-{i['id']}", "supplier": n, **{k: i[k] for k in ("id", "source", "title", "snippet", "link", "date", "publisher")}}
                 for i in found["items"]]
    EVALS.mkdir(exist_ok=True)
    (EVALS / "results.json").write_text(json.dumps({"suppliers": SUPPLIERS, "results": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} results from {len(SUPPLIERS)} suppliers")


def label(system: str, with_skeptic: bool = False) -> dict:
    """Every test result's label under these instructions, keyed by case."""
    store, out = LocalStore(), {}
    for n in range(len(SUPPLIERS)):
        vendor, gst, found = gathered(n, store)
        judged, _ = judge.judge(vendor, found["items"], KEY, store, system=system)
        if with_skeptic:
            judged = skeptic.challenge(vendor, gst, found, judged, KEY, store)
        out.update({f"s{n}-{j['id']}": j for j in judged})
    return out


def raises(about: str, severity: str, kind: str, source: str) -> bool:
    """Whether a result pushes the verdict up: a serious finding about the supplier, or a scam report on where the money goes."""
    if kind in RECORDS:
        return False
    if source in MONEY:
        return kind in ("fraud_or_enforcement", "customer_complaint") and severity in ("high", "medium")
    return about == "yes" and severity in ("high", "medium")


def warns(about: str, severity: str, kind: str) -> bool:
    """Whether a result shows as "possibly a different business": serious, but not confirmed to be the supplier."""
    return kind not in RECORDS and about == "unclear" and severity in ("high", "medium")


def score(labels: dict, cases: list[str] | None = None) -> dict:
    reference = json.loads((EVALS / "reference.json").read_text(encoding="utf-8"))["labels"]
    cases = cases or list(reference)
    m = {"results": len(cases), "false_raises": [], "missed_raises": [], "status_errors": [], "false_warnings": [], "missed_warnings": [],
         "about_wrong": []}
    findings = 0
    for case in cases:
        ref, got = reference[case], labels[case]
        if ref.get("record"):
            if got["status"] in ("cancelled", "suspended", "inactive") and got["status"] != ref.get("status"):
                m["status_errors"].append(case)
            continue
        should = raises(ref["about"], ref["severity"], "", got["source"])
        did = raises(got["about_vendor"], got["severity"], got["kind"], got["source"])
        if did and not should:
            m["false_raises"].append(case)
        if should and not did:
            m["missed_raises"].append(case)
        if warns(got["about_vendor"], got["severity"], got["kind"]) and not warns(ref["about"], ref["severity"], ""):
            m["false_warnings"].append(case)
        if warns(ref["about"], ref["severity"], "") and not warns(got["about_vendor"], got["severity"], got["kind"]) and not did:
            m["missed_warnings"].append(case)
        # "About the supplier?" matters only where the result could appear in a brief
        if ref["severity"] != "none":
            findings += 1
            if got["about_vendor"] != ref["about"]:
                m["about_wrong"].append(case)
    m["about_accuracy"] = round(1 - len(m["about_wrong"]) / max(1, findings), 3)
    # A wrong verdict weighs most (a false raise is a wrong Hold), then a wrong namesake warning, then a wrong label
    m["cost"] = (3 * (len(m["false_raises"]) + len(m["missed_raises"]) + len(m["status_errors"]))
                 + 2 * (len(m["false_warnings"]) + len(m["missed_warnings"])) + len(m["about_wrong"]))
    return m


def summary(m: dict) -> str:
    return (f"false/missed raises {len(m['false_raises'])}/{len(m['missed_raises'])}, status errors {len(m['status_errors'])}, "
            f"false/missed namesake warnings {len(m['false_warnings'])}/{len(m['missed_warnings'])}, "
            f"about right {m['about_accuracy']:.0%} of findings, cost {m['cost']}")


def run_score():
    base = label(judge.instructions(""))
    current = label(judge.instructions())
    checked = label(judge.instructions(), with_skeptic=True)
    report = {"labeller": score(base), "labeller_with_lessons": score(current), "with_skeptic": score(checked)}
    for name, m in report.items():
        print(f"{name:24s} {summary(m)}")
        print(f"{'':24s} false raises {m['false_raises']} · false warnings {m['false_warnings']} · missed warnings {m['missed_warnings']}")
    (EVALS / "labelling.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


OPTIMIZER = """You improve the instructions of a model that labels public search results during a check of an Indian supplier before a payment. For each result it decides whether it is about this supplier (about_vendor), what kind it is, and how serious it is. Its mistakes are below, each with the result, the label it gave and the correct label.

Write lessons that would prevent these kinds of mistakes on other suppliers:
- at most 6 lessons, one sentence each;
- describe the general pattern, never a specific company, person or place from the examples;
- a lesson must not make the model miss genuine fraud, arrest or cancellation reports about the supplier itself.
You may keep, rewrite or drop the current lessons.

Reply with JSON only: {"lessons": ["...", "..."]}"""


def propose(lessons: str, misses: list[dict]) -> str:
    question = json.dumps({"current_lessons": lessons.splitlines(), "mistakes": misses}, ensure_ascii=False)
    response = httpx.post(f"{judge.ENDPOINT}/chat/completions", timeout=120, headers={"Authorization": f"Bearer {KEY}"}, json={
        "model": judge.MODEL, "temperature": 0.4, "max_tokens": 700, "reasoning_effort": False,
        "messages": [{"role": "system", "content": OPTIMIZER}, {"role": "user", "content": question}]})
    response.raise_for_status()
    answer = json.loads(re.search(r"\{.*\}", response.json()["choices"][0]["message"]["content"], re.S).group(0))
    return "\n".join(f"- {str(x).strip().lstrip('- ')}" for x in answer.get("lessons", [])[:6] if str(x).strip())


def mistakes(labels: dict, cases: list[str]) -> list[dict]:
    reference = json.loads((EVALS / "reference.json").read_text(encoding="utf-8"))["labels"]
    rows = {r["case"]: r for r in json.loads((EVALS / "results.json").read_text(encoding="utf-8"))["results"]}
    m = score(labels, cases)
    wrong = dict.fromkeys(m["false_raises"] + m["missed_raises"] + m["status_errors"] + m["about_wrong"])
    out = []
    for case in list(wrong)[:16]:
        got, ref, row = labels[case], reference[case], rows[case]
        out.append({"supplier": SUPPLIERS[row["supplier"]]["name"], "supplier_city": SUPPLIERS[row["supplier"]]["city"],
                    "result": {"source": row["source"], "title": row["title"], "text": row["snippet"][:400]},
                    "model_said": {"about_vendor": got["about_vendor"], "severity": got["severity"], "kind": got["kind"], "status": got["status"]},
                    "correct": {"about_vendor": ref["about"], "severity": ref["severity"], **({"status": ref.get("status", "")} if ref.get("record") else {})}})
    return out


def run_loop(rounds: int = 3):
    reference = json.loads((EVALS / "reference.json").read_text(encoding="utf-8"))["labels"]
    # Half the results teach, the other half judge: alternate cases within each supplier
    train = [c for i, c in enumerate(reference) if i % 2 == 0]
    test = [c for i, c in enumerate(reference) if i % 2 == 1]
    lessons = ""
    labels = label(judge.instructions(lessons))
    best = {"lessons": lessons, "train": score(labels, train), "test": score(labels, test)}
    history = [{"round": 0, "lessons": "", "train": best["train"], "test": best["test"], "kept": True}]
    print(f"round 0  train: {summary(best['train'])}\n         test:  {summary(best['test'])}")
    for r in range(1, rounds + 1):
        candidate = propose(best["lessons"], mistakes(labels, train))
        new = label(judge.instructions(candidate))
        tr, te = score(new, train), score(new, test)
        # Kept only if it does better on results it never saw, and no worse on the ones it learned from
        kept = te["cost"] < best["test"]["cost"] and tr["cost"] <= best["train"]["cost"]
        history.append({"round": r, "lessons": candidate, "train": tr, "test": te, "kept": kept})
        print(f"round {r}  train: {summary(tr)}\n         test:  {summary(te)}  -> {'kept' if kept else 'rejected'}")
        if kept:
            best, labels = {"lessons": candidate, "train": tr, "test": te}, new
    (EVALS / "improvement.json").write_text(json.dumps({"when": time.strftime("%Y-%m-%d"), "history": history}, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    if best["lessons"]:
        judge.LESSONS.write_text(best["lessons"] + "\n", encoding="utf-8")
        print(f"kept lessons written to {judge.LESSONS.relative_to(ROOT)}:\n{best['lessons']}")
    else:
        print("no lessons beat the plain instructions; nothing written")


if __name__ == "__main__":
    {"export": export, "score": run_score, "loop": run_loop}[sys.argv[1]]()
