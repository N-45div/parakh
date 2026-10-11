"""An open-weight model reads every public result and says, with a verbatim quote, whether it is about this supplier.

Qwen3.6-27B runs on Thinking Machines' Tinker through its OpenAI-compatible endpoint. The model never decides the
verdict: it labels each result, and brief.py applies fixed rules to those labels. A quote the model claims is only kept
if it really appears in the result's text.
"""
import hashlib
import json
import os
import re
from pathlib import Path

import httpx
from concurrent.futures import ThreadPoolExecutor

ENDPOINT = os.environ.get("JUDGE_BASE_URL", "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1")
MODEL = os.environ.get("JUDGE_MODEL", "Qwen/Qwen3.6-27B")
KINDS = {"fraud_or_enforcement", "court_case", "customer_complaint", "registry_record", "company_record", "business_listing", "neutral", "positive"}
STATUSES = {"active", "cancelled", "suspended", "inactive", "strike_off", "under_liquidation", "dormant", "amalgamated"}
SEVERITIES = {"high", "medium", "low", "none"}
BATCH = 8

SYSTEM = """You help an Indian small business check a supplier before paying them. You get public search results.
Judge each result only from its own text. Never assume a result is about the supplier because the name is similar.

For every result return:
- about_vendor: "yes" if it clearly refers to this same business (name plus a matching city, GSTIN, address or owner); "no" if it is about a different business or a different meaning of the words; "unclear" if the name matches but nothing confirms it is the same business.
- kind: fraud_or_enforcement (raids, arrests, fake invoices, GST evasion, police complaints, cheating allegations), court_case, customer_complaint, registry_record (GST directory listings), company_record (company or LLP directory listings with a CIN or LLPIN), business_listing, neutral, or positive.
- role: for court_case and fraud_or_enforcement results, the supplier's side: "accused" (accused, respondent in a criminal or cheque case, raided, arrested), "petitioner" (the supplier brought the case), "party" (any other side), or "".
- severity: high (the supplier is accused in a fraud, cheating, fake-invoice or GST-evasion matter; a cancelled or suspended registration; repeated non-delivery or advance-payment complaints), medium (a cheque-bounce case under Section 138 of the Negotiable Instruments Act, insolvency or winding-up against the supplier, one serious complaint), low (consumer disputes, routine civil or tax appeals, cases the supplier brought, an ordinary service complaint), none. Large companies always have routine cases; do not raise severity for that.
- finding: one plain sentence a business owner can act on, saying what the source reports and attributing it ("Indian Kanoon lists a cheque-bounce case..."). Never say the supplier is guilty.
- quote: the shortest phrase copied exactly from the result's title or text that supports the finding, or "".
- status and legal_name: for registry_record results, the status and legal name the text gives for the supplier's own GSTIN ("active", "cancelled", "suspended" or "inactive"); for company_record results, the company's status ("active", "strike_off", "under_liquidation", "dormant" or "amalgamated") and registered name. Else "".
- registered_on: for registry_record and company_record results, the GST registration or incorporation date the text gives, as YYYY-MM-DD (or YYYY-MM or YYYY when that is all it says), else "".
- cin: for company_record results, the CIN or LLPIN if the text shows it, else "".
- A phone-number, UPI-ID or bank-account-number result is about the supplier only if the page ties that number or ID to this business. A page that reports the number, UPI ID or account in a scam, fraud or non-delivery complaint is kind fraud_or_enforcement or customer_complaint with severity high, whoever it names, because that is where the money would go.

Reply with JSON only: {"results": [{"id": ..., "about_vendor": ..., "kind": ..., "role": ..., "severity": ..., "finding": ..., "quote": ..., "status": ..., "legal_name": ..., "registered_on": ..., "cin": ...}]}, one entry for every id."""


def _plain(text: str) -> str:
    # "…" marks text the search engine left out, so a quote may never run across it
    return re.sub(r"\s+", " ", (text or "").replace("...", "…").replace("…", " … ")).strip().lower()


def _verified(quote: str, item: dict) -> str:
    if quote and _plain(quote) in _plain(f"{item['title']} {item['snippet']}"):
        return quote.strip()
    return ""


def fallback(item: dict, vendor: dict) -> dict:
    """Without the model: keyword labels, and nothing is called "about the vendor" without the model's reading."""
    text = f"{item['title']} {item['snippet']}".lower()
    kind = {"registry": "registry_record", "company": "company_record", "court": "court_case", "reviews": "customer_complaint"}.get(item["source"], "neutral")
    if re.search(r"fraud|raid|arrest|fake invoice|evasion|cheat|scam", text):
        kind = "fraud_or_enforcement"
    return {"about_vendor": "unclear", "kind": kind, "role": "", "severity": "none", "finding": "", "quote": "", "status": "", "legal_name": "",
            "registered_on": "", "cin": ""}


LESSONS = Path(__file__).with_name("lessons.txt")


def instructions(lessons: str | None = None) -> str:
    """The labelling instructions, plus the lessons scripts/improve.py kept because they measurably helped."""
    lessons = LESSONS.read_text(encoding="utf-8").strip() if lessons is None and LESSONS.exists() else (lessons or "").strip()
    return f"{SYSTEM}\n\nLessons from earlier mistakes:\n{lessons}" if lessons else SYSTEM


def judge(vendor: dict, items: list[dict], api_key: str | None, store=None, system: str | None = None) -> tuple[list[dict], str]:
    if not items:
        return [], "none"
    if not api_key:
        return [{**i, **fallback(i, vendor)} for i in items], "keywords (no model key)"
    system = system or instructions()
    supplier = {k: vendor.get(k) for k in ("name", "city", "gstin", "phone", "payee") if vendor.get(k)}
    results = [{"id": i["id"], "source": i["source"], "publisher": i.get("publisher"), "date": i.get("date"),
                "title": i["title"][:300], "text": i["snippet"][:600]} for i in items]
    def ask(batch):
        question = json.dumps({"supplier": supplier, "results": batch}, ensure_ascii=False)
        # The same results for the same supplier get the same labels, so a repeat check skips the model
        key = "judge-" + hashlib.sha1(f"{MODEL}\n{system}\n{question}".encode()).hexdigest()[:20]
        hit = store.cached(key) if store is not None else None
        if hit:
            return hit["results"]
        response = httpx.post(f"{ENDPOINT}/chat/completions", timeout=90, headers={"Authorization": f"Bearer {api_key}"}, json={
            "model": MODEL, "temperature": 0, "max_tokens": 1800, "reasoning_effort": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}]})
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        answer = json.loads(re.search(r"\{.*\}", content, re.S).group(0)).get("results", [])
        if store is not None:
            store.remember(key, {"results": answer})
        return answer

    # Small batches in parallel: the same labels, a fraction of the wait
    batches = [results[i:i + BATCH] for i in range(0, len(results), BATCH)]
    with ThreadPoolExecutor(max_workers=len(batches)) as pool:
        labels = {str(r.get("id")): r for answer in pool.map(ask, batches) for r in answer}
    judged = []
    for item in items:
        label = labels.get(item["id"]) or fallback(item, vendor)
        about = label.get("about_vendor") if label.get("about_vendor") in ("yes", "no", "unclear") else "unclear"
        kind = label.get("kind") if label.get("kind") in KINDS else "neutral"
        severity = label.get("severity") if label.get("severity") in SEVERITIES else "none"
        role = label.get("role") if label.get("role") in ("accused", "petitioner", "party") else ""
        status = str(label.get("status") or "").lower().replace(" ", "_").replace("-", "_")
        if kind in ("neutral", "positive", "business_listing"):
            severity = "none"
        if kind == "court_case" and role == "petitioner" and severity in ("high", "medium"):
            severity = "low"
        judged.append({**item, "about_vendor": about, "kind": kind, "role": role, "severity": severity,
                       "finding": str(label.get("finding") or "")[:300], "quote": _verified(str(label.get("quote") or ""), item),
                       "status": status if status in STATUSES else "", "legal_name": str(label.get("legal_name") or "")[:120],
                       "registered_on": str(label.get("registered_on") or "")[:10] if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", str(label.get("registered_on") or "")[:10]) else "",
                       "cin": str(label.get("cin") or "")[:21]})
    return judged, f"{MODEL} on Tinker"
