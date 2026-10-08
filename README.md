# Parakh

**Check a supplier before you pay them.**

*Parakh* (परख) is Hindi for assaying gold: testing what something really is before you accept it.

Indian small businesses pay advances to suppliers they found on IndiaMART, WhatsApp or a referral. Some of those suppliers belong to fake-invoice rackets, have cancelled GST registrations or disappear after the advance. A cancelled or fake GSTIN on your purchase invoice can also cost you the input tax credit you claimed. The warning signs are usually public: a GST directory showing "Cancelled", a news report of a DGGI arrest, a Maps listing marked closed, reviews saying "took advance, never delivered". Nobody has time to look in six places before every payment.

Parakh does that in about a minute and writes a brief:

- **A verdict from fixed rules:** *Hold*, *Verify first* or *No red flags*. A model never decides it.
- **Findings with verbatim quotes**, each linked to its source. A quote is shown only if it really appears in that source.
- **Namesakes kept apart:** results that may be about a different business with a similar name are listed separately and never trigger a hold.
- **What to do before paying:** the GST portal, the MCA portal, a cancelled cheque in the same legal name, a smaller advance.
- **What the check cannot tell you**, stated plainly.

## How SerpApi is used

Each check runs these searches through the official [`serpapi`](https://pypi.org/project/serpapi/) Python client. Without them there is nothing to check.

| Search | SerpApi engine | Why |
| --- | --- | --- |
| The GSTIN in quotes | Google Search | Public GST directories show the legal name and status (Active, Cancelled, Suspended) |
| Name + city | Google Maps | Does the business exist where it says? Is it marked closed? An old closed pin is told apart from the current one |
| Lowest-rated reviews | Google Maps Reviews (`sort_by=ratingLow`) | Non-delivery and advance-payment complaints surface first |
| Name + raid, arrest, fake invoice, GST evasion… | Google News | Enforcement coverage |
| Name on `site:indiankanoon.org` | Google Search | Court records, with the supplier's role in each case |
| Name + city + complaint, scam, cheated… | Google Search | Complaint sites and forums |

Every call is cached on disk by its parameters, so repeating a check costs no credits, and every brief lists the searches behind it.

## How a check works

```
GSTIN ──► offline check: format, official check digit, state, the PAN inside it and its taxpayer type
   │
   ▼
6 SerpApi searches ──► about 30 public results
   │
   ▼
Qwen3.6-27B (open weights, served by Tinker) labels each result:
   about this supplier / a namesake / unclear, its kind, the supplier's role, severity, a verbatim quote
   │
   ▼
fixed rules ──► verdict, findings, namesakes, next steps, limits
```

- **The GSTIN check is offline arithmetic.** A typo or a made-up number fails the official check digit. A company name over an individual's PAN is flagged.
- **The model labels; it does not judge.** It says what each result is and quotes it. The quote is checked against the source text, and never across an ellipsis the search engine inserted.
- **The rules are calibrated for real companies.** Large companies always have consumer disputes and cases they brought themselves; those are summarised as routine. A hold needs something serious and specific:
  - the supplier accused in a fraud, fake-invoice or GST-evasion matter;
  - a cancelled registration;
  - a broken GSTIN;
  - a business that has closed.

## Run it

Requirements: Python 3.11+, a SerpApi key (the free plan's 250 searches a month is about 40 checks) and, optionally, a Tinker key for the model. Without a Tinker key, results get keyword labels and nothing is marked as about the supplier.

```bash
git clone https://github.com/N-45div/parakh.git
cd parakh
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -r requirements.txt
cp .env.example .env          # add SERPAPI_API_KEY and TINKER_API_KEY
uvicorn parakh.app:app
```

Open http://127.0.0.1:8000, enter a supplier's name, city and (ideally) GSTIN, and choose *Check this supplier*. Past checks are listed on the left; *Save as PDF* prints the brief.

Tests cover the GSTIN arithmetic, the quote check and the verdict rules, and need no keys:

```bash
python -m pytest
```

## Limits

- Public records only. Parakh cannot see whether a supplier files its GST returns (the GST portal shows that), who owns the bank account you are paying, or disputes that never reached the news, the courts or reviews.
- Directory listings and news can be wrong or out of date. Every finding links to its source so you can judge it yourself.
- Reports of arrests and raids are allegations, and Parakh words them that way.
- Common names produce namesakes. Parakh separates them, but you decide.

## Licence

MIT
