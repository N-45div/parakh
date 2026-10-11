"""A second agent that tries to knock down every finding that would raise the verdict.

The labelling model reads each result once and says whether it is about the supplier. Its costliest mistake is a
false Hold: a fraud story about a different business with a similar name. The skeptic gets only the findings that
would raise the verdict, with everything Parakh knows about the supplier, and argues the case that it is not this
business, or that the supplier is only a victim or a bystander in it. It must quote the words that show it.

Fixed rules then act on its answer, and only in one direction: a finding can be moved to "possibly a different
business" or softened, never made worse, and only when the quoted evidence really appears in the result.
"""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import judge

PROMPT = """You are the skeptic on a check of an Indian supplier before a payment. Another model read the public result below and said it is serious and is, or may be, about this supplier. Your job is to look for a concrete reason that is wrong:
- it is a different business: another city or state, another GSTIN or CIN, a longer or different name (for example "Tata Motors Finance" or "Balaji Glass Agencies" is not "Tata Motors" or "Sri Balaji Traders"), or other owners;
- or the supplier is only the victim, a bystander, a place mentioned, or the side that brought the case, not the one accused.
Judge only from the result's own text and the supplier facts. If the text gives no concrete reason, say so: do not guess.

Reply with JSON only:
{"same_business": "yes" | "no" | "cannot_tell", "role": "accused" | "victim_or_bystander" | "cannot_tell", "reason": one plain sentence, "evidence": the shortest phrase copied exactly from the result's title or text that shows your reason, or ""}"""


def candidates(judged: list[dict]) -> list[dict]:
    """The serious findings that would raise the verdict or warn of a namesake; register listings and money-trail
    reports are left to their own rules."""
    return [j for j in judged if j["about_vendor"] in ("yes", "unclear") and j["severity"] in ("high", "medium")
            and j["kind"] not in ("registry_record", "company_record") and j["source"] not in ("payee", "phone", "account")]


def facts(vendor: dict, gst: dict, gathered: dict, judged: list[dict]) -> dict:
    listing = gathered.get("listing") or {}
    records = [j for j in judged if j["kind"] in ("registry_record", "company_record") and j["about_vendor"] == "yes"]
    known = {"name": vendor["name"], "city": vendor["city"], "gstin": vendor.get("gstin") or None, "state": gst.get("state"),
             "taxpayer_type": gst.get("entity_type"), "address": listing.get("address") if listing.get("name_matches") else None,
             "legal_names": sorted({j["legal_name"] for j in records if j.get("legal_name")})[:3] or None,
             "cin": next((j["cin"] for j in records if j.get("cin")), None)}
    return {k: v for k, v in known.items() if v}


def _ask(supplier: dict, item: dict, api_key: str, store) -> dict:
    question = json.dumps({"supplier": supplier, "result": {"source": item["source"], "publisher": item.get("publisher"), "date": item.get("date"),
                                                             "title": item["title"][:300], "text": item["snippet"][:600]}}, ensure_ascii=False)
    key = "skeptic-" + hashlib.sha1(f"{judge.MODEL}\n{PROMPT}\n{question}".encode()).hexdigest()[:20]
    hit = store.cached(key) if store is not None else None
    if hit:
        return hit
    response = httpx.post(f"{judge.ENDPOINT}/chat/completions", timeout=90, headers={"Authorization": f"Bearer {api_key}"}, json={
        "model": judge.MODEL, "temperature": 0, "max_tokens": 300, "reasoning_effort": False,
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": question}]})
    response.raise_for_status()
    answer = json.loads(re.search(r"\{.*\}", response.json()["choices"][0]["message"]["content"], re.S).group(0))
    if store is not None:
        store.remember(key, answer)
    return answer


def decide(item: dict, answer: dict) -> dict:
    """The fixed rule: act only on a concrete, verified reason, and never make a finding worse."""
    evidence = judge._verified(str(answer.get("evidence") or ""), item)
    reason = str(answer.get("reason") or "")[:300]
    if answer.get("same_business") == "no" and evidence:
        return {"outcome": "moved", "reason": reason, "evidence": evidence}
    if answer.get("role") == "victim_or_bystander" and evidence:
        return {"outcome": "softened", "reason": reason, "evidence": evidence}
    return {"outcome": "upheld", "reason": reason, "evidence": evidence}


def challenge(vendor: dict, gst: dict, gathered: dict, judged: list[dict], api_key: str | None, store=None) -> list[dict]:
    """Returns the labels with each challenged finding moved, softened or upheld, and the challenge attached."""
    targets = candidates(judged)
    if not targets or not api_key:
        return judged
    supplier = facts(vendor, gst, gathered, judged)
    with ThreadPoolExecutor(max_workers=min(6, len(targets))) as pool:
        answers = dict(zip((id(t) for t in targets), pool.map(lambda t: _ask(supplier, t, api_key, store), targets)))
    out = []
    for j in judged:
        if id(j) not in answers:
            out.append(j)
            continue
        verdict = decide(j, answers[id(j)])
        if verdict["outcome"] == "moved":
            # One step down: a finding becomes a possible namesake; a possible namesake is dropped as a different business
            out.append({**j, "about_vendor": "unclear" if j["about_vendor"] == "yes" else "no", "challenge": verdict})
        elif verdict["outcome"] == "softened":
            out.append({**j, "severity": "low", "challenge": verdict})
        else:
            out.append({**j, "challenge": verdict})
    return out
