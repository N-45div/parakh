"""Fill the check from a supplier's quotation or invoice PDF: the open model picks the seller's details out of the text.

Nothing is stored. A GSTIN is accepted only if its check digit is right, and a phone or amount only if it parses.
"""
import io
import json
import re

import httpx
from pypdf import PdfReader

from . import bank, gstin, judge

GSTIN_ANYWHERE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
PROMPT = """This is the text of a quotation, proforma or invoice an Indian business received from a supplier.
Return JSON only, with the SUPPLIER's details (the seller who will be paid, not the buyer or "bill to" party):
{"name": legal or trade name, "city": city of the supplier's address, "gstin": the supplier's 15-character GSTIN or "",
 "phone": the supplier's phone or WhatsApp number or "", "payee": a UPI ID, or the bank account holder name, that payment should go to, or "",
 "amount": the total amount due or the advance asked for, in rupees as a number, or null,
 "account": the bank account number payment should go to, or "", "ifsc": that account's IFSC code, or "",
 "bank": the bank and branch name exactly as the text writes them, or ""}
Use only what the text says; leave a field empty when it does not say."""


def text_of(pdf: bytes, limit: int = 12000) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:4])[:limit]


def fields(text: str, api_key: str | None) -> dict:
    found = [g for g in dict.fromkeys(GSTIN_ANYWHERE.findall(text.upper())) if gstin.inspect(g).get("valid")]
    result = {"name": "", "city": "", "gstin": found[0] if len(found) == 1 else "", "phone": "", "payee": "", "amount": None,
              "account": "", "ifsc": "", "bank": "", "gstins_found": found, "read_by": "pattern match"}
    if not api_key or not text.strip():
        return result
    response = httpx.post(f"{judge.ENDPOINT}/chat/completions", timeout=60, headers={"Authorization": f"Bearer {api_key}"}, json={
        "model": judge.MODEL, "temperature": 0, "max_tokens": 400, "reasoning_effort": False,
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}]})
    response.raise_for_status()
    answer = json.loads(re.search(r"\{.*\}", response.json()["choices"][0]["message"]["content"], re.S).group(0))
    picked = re.sub(r"\s", "", str(answer.get("gstin") or "")).upper()
    amount = answer.get("amount")
    account, ifsc = bank.account_digits(str(answer.get("account") or "")), bank.normalise_ifsc(str(answer.get("ifsc") or ""))
    result.update(
        name=str(answer.get("name") or "")[:120], city=str(answer.get("city") or "")[:60],
        # The model's choice stands only if it is a real GSTIN that appears in the document
        gstin=picked if picked in found else result["gstin"],
        phone=str(answer.get("phone") or "")[:20], payee=str(answer.get("payee") or "")[:120],
        amount=round(float(amount)) if isinstance(amount, (int, float)) and amount > 0 else None,
        # Bank details stand only if they are well formed and really appear in the document
        account=account if account and account in re.sub(r"[\s-]", "", text) else "",
        ifsc=ifsc if bank.IFSC.match(ifsc) and ifsc in text.upper().replace(" ", "") else "",
        bank=str(answer.get("bank") or "")[:120],
        read_by=f"{judge.MODEL} on Tinker")
    return result
