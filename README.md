# Parakh

**Check a supplier before you pay them.**

[Try it](https://parakh-lemon.vercel.app) (five live checks a day per visitor; the example briefs are free)

*Parakh* (परख) is Hindi for assaying gold: testing what something really is before you accept it.

Indian small businesses pay advances to suppliers they found on IndiaMART, WhatsApp or a referral. Some of those suppliers belong to fake-invoice rackets, have cancelled GST registrations or disappear after the advance. A cancelled or fake GSTIN on your purchase invoice can also cost you the input tax credit you claimed. The warning signs are usually public: a GST directory showing "Cancelled", a news report of a DGGI arrest, a Maps listing marked closed, reviews saying "took advance, never delivered". Nobody has time to look in six places before every payment.

Parakh does that in about a minute and writes a brief:

- **A verdict from fixed rules:** *Hold*, *Verify first* or *No red flags*. A model never decides it.
- **Findings with verbatim quotes**, each linked to its source. A quote is shown only if it really appears in that source.
- **Namesakes kept apart:** results that may be about a different business with a similar name are listed separately and never trigger a hold.
- **What to do before paying:** the GST portal, the MCA portal, a cancelled cheque in the same legal name, a smaller advance.
- **Young registrations flagged:** a GSTIN registered under six months ago, or a company incorporated under a year ago, is a common pattern in fake-invoice rackets.
- **Who the money goes to:** a payee name that doesn't match the supplier is flagged (diverted-payment fraud); a UPI ID is searched for scam reports, and you're told to check the name your UPI app shows.
- **Which branch holds the account:** the IFSC is looked up in the RBI's branch directory. An account in another state from the supplier's GST registration, or at a different branch from the one the quote itself names, is flagged, and the account number is searched for scam reports. Two separate signs that the money would not reach the supplier make a *Hold*.
- **How much is at stake:** the advice scales with the amount: hold it, split it, or confirm bank details by phone for large payments.
- **Website age:** the supplier's domain registration date from RDAP; a site under six months old needs verifying.
- **Drop a quote or invoice PDF:** the open model fills in the seller's name, city, GSTIN, phone, payee, amount and bank details (the buyer's GSTIN on the same page is ignored; an account number or IFSC is kept only if it really appears in the document). Nothing is stored.
- **Shareable:** *Copy for WhatsApp* writes a plain-text summary for a partner or accountant; *Copy link* opens the same brief.
- **What the check cannot tell you**, stated plainly.

## How SerpApi is used

Each check runs six to ten of these searches, in parallel, through the official [`serpapi`](https://pypi.org/project/serpapi/) Python client. Without them there is nothing to check.

| Search | SerpApi engine | Why |
| --- | --- | --- |
| The GSTIN in quotes | Google Search | Public GST directories show the legal name and status (Active, Cancelled, Suspended) |
| Name + city | Google Maps | Does the business exist where it says? Is it marked closed? An old closed pin is told apart from the current one |
| Lowest-rated reviews | Google Maps Reviews (`sort_by=ratingLow`) | Non-delivery and advance-payment complaints surface first |
| Name + raid, arrest, fake invoice, GST evasion… | Google News | Enforcement coverage |
| Name on `site:indiankanoon.org` | Google Search | Court records, with the supplier's role in each case |
| Name + city + complaint, scam, cheated… | Google Search | Complaint sites and forums |
| Name on Zauba, Tofler and other MCA mirrors (companies and LLPs) | Google Search | Company status (active, struck off, in liquidation, amalgamated), incorporation date, CIN |
| The supplier's phone or WhatsApp number (optional) | Google Search | Scam and complaint reports that cite the number |
| The UPI ID you're asked to pay (optional) | Google Search | Scam reports that name the UPI ID, whoever they name |
| The bank account number you're asked to pay (optional) | Google Search | Complaint and cybercrime posts that cite the account |

The IFSC lookup is not a search: it reads the RBI's branch list as published by Razorpay at `ifsc.razorpay.com`, with no key, and is cached like the searches.

Every call is cached on disk by its parameters, so repeating a check costs no credits, and every brief lists the searches behind it.

## How a check works

```
GSTIN ──► offline check: format, official check digit, state, the PAN inside it and its taxpayer type
   │
   ▼
6 to 10 SerpApi searches ──► about 30 public results
   │
   ▼
labeller agent: Qwen3.6-27B (open weights, served by Tinker) labels each result:
   about this supplier / a namesake / unclear, its kind, the supplier's role, severity, a verbatim quote
   │
   ▼
skeptic agent: argues against every serious finding, with a quote, and can only move or soften it
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

## Agents that check each other, and a loop that learns from mistakes

The costliest mistake a supplier check can make is a false alarm: a fraud story or a criminal case about a different business with a similar name, shown as if it were this supplier. Two agents and a measuring loop work on that.

- **The skeptic agent** gets every serious finding the labeller produced, with everything Parakh knows about the supplier (state from the GSTIN, address, legal names, CIN). It argues the case that the result is about a *different* business ("Tata Motors Finance" is not "Tata Motors"), or that the supplier is only a victim, a bystander or the side that brought the case. It must quote the words that show it. Fixed rules then act in one direction only: a finding can be moved to "possibly a different business" or softened, never made worse, and only when the quote really appears in the result. Each finding in the brief shows what the skeptic concluded.
- **The improvement loop** ([scripts/improve.py](scripts/improve.py)) measures the labeller against reference labels for 116 real results (four suppliers, all served from the SerpApi cache, so it costs no searches). An optimizer agent reads the labeller's mistakes on half the results and writes short, general lessons. A lesson set is kept only if it does better on the *other* half, which it never saw, and no worse on the half it learned from. Kept lessons go into [parakh/lessons.txt](parakh/lessons.txt), which the labeller reads.

| On 116 real results ([evaluations/labelling.json](evaluations/labelling.json)) | Wrong holds | Missed holds | False namesake warnings | Missed namesake warnings | "About this supplier" right | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| Labeller alone | 0 | 0 | 2 | 4 | 66% | 28 |
| With the lessons it learned | 0 | 0 | 1 | 4 | 70% | 24 |
| With lessons and the skeptic | 0 | 0 | **0** | 4 | **72%** | **21** |

The skeptic removed both false warnings: a murder case that mentions a "Sri Balaji Traders shop" only as the place it happened, and a case the business itself brought. Of the three rounds of lessons, one was kept; the others were rejected, one because it introduced a wrong hold ([evaluations/improvement.json](evaluations/improvement.json)). The four missed warnings remain: news results whose titles never show the supplier's name. The skeptic cannot fix those by design, since it never escalates.

Honest limits: the reference labels were written by Claude (Anthropic) from each result's own text and spot-checked; 116 results from four suppliers is a small set, so these numbers show direction, not precision.

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
