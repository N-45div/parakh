"""Offline checks of the parts that decide the verdict: GSTIN arithmetic and the brief's fixed rules."""
from parakh import brief, gstin
from parakh.evidence import core_name
from parakh.judge import _verified

REAL = ["29AAACT2727Q1ZS", "06AAACT2727Q1Z0", "21AAACT2727Q1Z8", "33AAACT2727Q1Z3", "36AAACT2727Q1ZX"]


def test_check_digit_matches_real_gstins_and_catches_typos():
    for g in REAL:
        assert gstin.check_digit(g[:14]) == g[14]
    typo = gstin.inspect("29AAACT2727Q1ZT", "Tata Motors Limited")
    assert typo["valid"] is False and typo["flags"][0]["severity"] == "high"
    assert gstin.inspect("29AAACT272", "x")["flags"][0]["text"].startswith("This is not a valid GSTIN")


def test_gstin_facts_and_entity_mismatch():
    facts = gstin.inspect("29AAACT2727Q1ZS", "Tata Motors Limited")
    assert facts["state"] == "Karnataka" and facts["entity_type"] == "company" and facts["flags"] == []
    # A company name over an individual's PAN: build a valid GSTIN for PAN ABCPK1234Q
    first14 = "29ABCPK1234Q1Z"
    individual = gstin.inspect(first14 + gstin.check_digit(first14), "Sri Balaji Steels Pvt Ltd")
    assert individual["valid"] and individual["entity_type"] == "individual"
    assert individual["flags"][0]["severity"] == "medium"


def test_core_name_keeps_the_distinctive_part():
    assert core_name("M/s Sri Balaji Steels Pvt. Ltd.") == "Sri Balaji Steels"
    assert core_name("MSquare Traders") == "MSquare Traders"
    assert core_name("Ramesh & Co.") == "Ramesh & Co"


def test_quotes_are_kept_only_when_they_appear_in_the_source():
    item = {"title": "GST officials raid Acme Steel", "snippet": "Officials searched the premises…  over fake invoices."}
    assert _verified("raid Acme Steel", item) == "raid Acme Steel"
    assert _verified("searched the premises over fake invoices", item) == ""
    assert _verified("Acme was convicted", item) == ""


def _judged(**kw):
    base = {"id": "news-0", "source": "news", "title": "t", "snippet": "s", "link": "https://x", "date": None, "publisher": None,
            "about_vendor": "yes", "kind": "fraud_or_enforcement", "role": "accused", "severity": "high", "finding": "f", "quote": "",
            "status": "", "legal_name": ""}
    return {**base, **kw}


def _build(judged, gst=None, listing=None):
    gst = gst if gst is not None else gstin.inspect("29AAACT2727Q1ZS", "Acme Steel Ltd")
    gathered = {"core_name": "Acme Steel", "listing": listing or {"title": "Acme Steel", "address": "Peenya, Bengaluru, Karnataka", "name_matches": True,
                                                                   "permanently_closed": False, "temporarily_closed": False, "maps_link": None},
                "items": judged}
    return brief.build({"name": "Acme Steel Ltd", "city": "Bengaluru", "gstin": gst.get("gstin", "")}, gst, gathered, judged, "m", [])


def test_verdict_rules():
    registry = _judged(id="registry-0", source="registry", kind="registry_record", severity="none", status="active", legal_name="ACME STEEL LTD")
    assert _build([registry])["verdict"] == "clear"
    assert _build([registry, _judged()])["verdict"] == "hold"
    # Severe-sounding news about a different business, or one that may be different, never holds a payment
    assert _build([registry, _judged(about_vendor="no")])["verdict"] == "clear"
    unclear = _build([registry, _judged(about_vendor="unclear")])
    assert unclear["verdict"] == "verify" and len(unclear["clashes"]) == 1
    cancelled = _build([_judged(id="registry-0", source="registry", kind="registry_record", severity="none", status="cancelled")])
    assert cancelled["verdict"] == "hold"
    assert _build([registry], gst=gstin.inspect("29AAACT2727Q1ZT", "Acme"))["verdict"] == "hold"
    assert _build([], gst={"given": False})["verdict"] == "verify"


def test_routine_mentions_are_grouped():
    registry = _judged(id="registry-0", source="registry", kind="registry_record", severity="none", status="active")
    cases = [_judged(id=f"court-{i}", source="court", kind="court_case", role="party", severity="low") for i in range(3)]
    result = _build([registry, *cases])
    grouped = [f for f in result["flags"] if f.get("items")]
    assert result["verdict"] == "clear" and len(grouped) == 1 and len(grouped[0]["items"]) == 3


def test_listing_prefers_the_open_pin_over_an_old_closed_one():
    from parakh.evidence import _listing
    data = {"local_results": [
        {"title": "Ecoren Energy India Pvt Ltd", "open_state": "Permanently closed", "address": "Old office"},
        {"title": "Ecoren Energy", "open_state": "Closes soon · 6:30 pm", "address": "Current office", "place_id": "p1"},
        {"title": "Some Solar Shop", "open_state": "Open"}]}
    listing = _listing(data, "Ecoren Energy India Private Limited")
    assert listing["title"] == "Ecoren Energy" and not listing["permanently_closed"]
    assert listing["older_closed"] == ["Ecoren Energy India Pvt Ltd, Old office"]
    only_closed = _listing({"local_results": data["local_results"][:1]}, "Ecoren Energy India Private Limited")
    assert only_closed["permanently_closed"]


def test_app_imports_and_serves_examples(tmp_path, monkeypatch):
    monkeypatch.setenv("PARAKH_CHECKS", str(tmp_path / "checks"))
    monkeypatch.setenv("PARAKH_CACHE", str(tmp_path / "cache"))
    for name in ("DATABASE_URL", "POSTGRES_URL", "MONGODB_URI"):
        monkeypatch.delenv(name, raising=False)
    import importlib
    from fastapi.testclient import TestClient
    import parakh.app
    importlib.reload(parakh.app)
    client = TestClient(parakh.app.app)
    assert client.get("/api/examples").json() == []
    assert client.get("/api/checks/nope").status_code == 404
    assert client.get("/").status_code == 200


def test_company_status_and_young_registrations():
    from datetime import date
    gst = gstin.inspect("29AAACT2727Q1ZS", "Acme Steel Ltd")
    registry = _judged(id="registry-0", source="registry", kind="registry_record", severity="none", status="active", registered_on="2026-08-01")
    young = _build_on([registry], gst, date(2026, 10, 9))
    assert young["verdict"] == "verify" and "under six months ago" in young["flags"][0]["text"]
    company = _judged(id="company-0", source="company", kind="company_record", severity="none", status="strike_off", registered_on="2015-04-02", cin="U27100KA2015PTC000001")
    struck = _build_on([_judged(id="registry-0", source="registry", kind="registry_record", severity="none", status="active"), company], gst, date(2026, 10, 9))
    assert struck["verdict"] == "hold" and struck["identity"]["company"]["cin"] == "U27100KA2015PTC000001"
    new_company = _judged(id="company-0", source="company", kind="company_record", severity="none", status="active", registered_on="2026-03")
    assert _build_on([new_company], gst, date(2026, 10, 9))["verdict"] == "verify"


def _build_on(judged, gst, today):
    gathered = {"core_name": "Acme Steel", "listing": {"title": "Acme Steel", "address": "Peenya, Bengaluru, Karnataka", "name_matches": True,
                                                         "permanently_closed": False, "temporarily_closed": False, "maps_link": None}, "items": judged}
    return brief.build({"name": "Acme Steel Ltd", "city": "Bengaluru", "gstin": gst["gstin"]}, gst, gathered, judged, "m", [], today=today)


def test_phone_numbers_and_company_names():
    from parakh.evidence import is_company, phone_digits
    assert phone_digits("+91 98450 12345") == phone_digits("09845012345") == phone_digits("9845012345") == "9845012345"
    assert phone_digits("12345") == ""
    assert is_company("Acme Steel Pvt Ltd", None) and is_company("Acme Steel", "company") and not is_company("Ramesh & Co", "individual")


def test_an_amalgamated_company_needs_verifying():
    from datetime import date
    gst = gstin.inspect("29AAACT2727Q1ZS", "Acme Steel Ltd")
    merged = _judged(id="company-0", source="company", kind="company_record", severity="none", status="amalgamated", registered_on="2010-01-13")
    result = _build_on([merged], gst, date(2026, 10, 9))
    assert result["verdict"] == "verify" and "merged into another company" in result["flags"][0]["text"]


def _build_money(judged, vendor_extra, website=None, bank=None):
    from datetime import date
    gst = gstin.inspect("29AAACT2727Q1ZS", "Acme Steel Ltd")
    gathered = {"core_name": "Acme Steel", "website": website, "bank": bank,
                "listing": {"title": "Acme Steel", "address": "Peenya, Bengaluru, Karnataka", "name_matches": True,
                            "permanently_closed": False, "temporarily_closed": False, "maps_link": None}, "items": judged}
    vendor = {"name": "Acme Steel Ltd", "city": "Bengaluru", "gstin": gst["gstin"], **vendor_extra}
    return brief.build(vendor, gst, gathered, judged, "m", [], today=date(2026, 10, 10))


def test_payee_name_upi_and_amount():
    registry = _judged(id="registry-0", source="registry", kind="registry_record", severity="none", status="active", legal_name="ACME STEEL LIMITED")
    same = _build_money([registry], {"payee": "ACME STEEL LIMITED", "amount": 185000})
    assert same["verdict"] == "clear" and not any("does not match" in f["text"] for f in same["flags"])
    other = _build_money([registry], {"payee": "Ramesh Kumar", "amount": 185000})
    assert other["verdict"] == "verify" and "Ramesh Kumar" in other["flags"][0]["text"]
    assert any("Split the ₹1,85,000" in s["text"] for s in other["next_steps"])
    upi = _build_money([registry], {"payee": "acmesteel@okaxis", "amount": 250000})
    assert "acmesteel@okaxis" in upi["next_steps"][0]["text"] and "ACME STEEL LIMITED" in upi["next_steps"][0]["text"]
    assert any("₹2,50,000" in s["text"] for s in upi["next_steps"])


def test_a_scam_report_on_the_upi_id_holds_whoever_it_names():
    report = _judged(id="payee-0", source="payee", kind="fraud_or_enforcement", about_vendor="no", severity="high", finding="A complaint names this UPI ID")
    held = _build_money([report], {"payee": "acmesteel@okaxis", "amount": 90000})
    assert held["verdict"] == "hold" and held["next_steps"][0]["text"] == "Don't send the ₹90,000 yet."
    assert not held["clashes"]


def test_a_new_website_needs_verifying():
    young = _build_money([], {}, website={"domain": "acme-steel.in", "registered": "2026-08-20"})
    assert any("acme-steel.in" in f["text"] for f in young["flags"]) and young["identity"]["website"]["domain"] == "acme-steel.in"
    old = _build_money([], {}, website={"domain": "acme.com", "registered": "2009-01-01"})
    assert not any("acme.com" in f["text"] for f in old["flags"])


def test_upi_ids_and_domains():
    from parakh.domain import domain_of
    from parakh.evidence import upi_id
    assert upi_id(" Acme.Steel@OKAXIS ") == "acme.steel@okaxis" and upi_id("Ramesh Kumar") == "" and upi_id("a@b@c") == ""
    assert domain_of("https://www.shop.acme.co.in/x") == "acme.co.in" and domain_of("https://acme.business.site") is None


def test_a_shared_name_prefix_is_not_the_same_business():
    from parakh.evidence import _listing
    other = _listing({"local_results": [{"title": "Shree Vinayaka Packaging", "website": "https://shreevinayakapackaging.com"}]}, "Shree Vinayaka Corrugators")
    assert other["name_matches"] is False
    same = _listing({"local_results": [{"title": "Sri Balaji Traders - Wholesale Dealers in Hardware Items"}]}, "Sri Balaji Traders")
    assert same["name_matches"] is True


ASANSOL = {"bank": "State Bank of India", "branch": "ASANSOL", "city": "BARDHAMAN", "district": "ASANSOL", "state": "WEST BENGAL",
           "address": "DNR MORE, ASANSOL, BURDWAN"}


def test_the_ifsc_says_where_the_account_is():
    from parakh import bank
    assert bank.IFSC.match("SBIN0000011") and not bank.IFSC.match("SBIN1000011") and not bank.IFSC.match("SBI00000011")
    assert bank.account_digits("3829 1047 6644 17") == "38291047664417" and bank.account_digits("12345") == "" and bank.account_digits("XXXX4417") == ""
    assert bank.names_branch("State Bank of India, Peenya Branch", ASANSOL) is False
    assert bank.names_branch("SBI Asansol", ASANSOL) is True
    assert bank.names_branch("State Bank of India", ASANSOL) is None
    assert bank.same_state("Karnataka", "KARNATAKA") and not bank.same_state("Karnataka", "WEST BENGAL")
    checked = {"ifsc": "SBIN0000011", "valid_format": True, "branch": ASANSOL, "claimed": "State Bank of India, Peenya Branch"}
    far = _build_money([], {"payee": "Acme Steel Ltd", "account": "38291047664417", "ifsc": "SBIN0000011"}, bank=checked)
    texts = [f["text"] for f in far["flags"]]
    assert far["identity"]["bank"]["branch"]["branch"] == "ASANSOL"
    assert any("Peenya Branch" in t and "Asansol branch" in t for t in texts)
    assert any("West Bengal" in t and "Karnataka" in t for t in texts)
    # Two signs that the money goes elsewhere make a hold; the payee check adds a third
    assert far["verdict"] == "hold" and far["flags"][0]["text"].startswith("2 separate signs")
    diverted = _build_money([], {"payee": "Ramesh Kumar", "amount": 92500}, bank=checked)
    assert diverted["flags"][0]["text"].startswith("3 separate signs") and diverted["next_steps"][0]["text"] == "Don't send the ₹92,500 yet."
    one = _build_money([], {"payee": "Ramesh Kumar"})
    assert one["verdict"] == "verify"
    assert any("beneficiary name" in s["text"] for s in far["next_steps"])
    local = {**ASANSOL, "branch": "PEENYA", "state": "KARNATAKA", "address": "PEENYA INDUSTRIAL AREA, BENGALURU"}
    near = _build_money([], {"payee": "Acme Steel Ltd"}, bank={**checked, "branch": local, "claimed": "SBI Peenya"})
    assert near["verdict"] == "clear"
    unknown = _build_money([], {}, bank={**checked, "branch": {}})
    assert any("No bank branch has the IFSC SBIN0000011" in f["text"] for f in unknown["flags"])
    bad = _build_money([], {}, bank={"ifsc": "SBIN00XXXXX", "valid_format": False, "branch": None, "claimed": ""})
    assert "not a valid IFSC" in bad["flags"][0]["text"]


def test_ifsc_lookups_are_cached_including_a_missing_branch(monkeypatch):
    from parakh import bank

    class Memory(dict):
        cached, remember = dict.get, dict.__setitem__

    class NotFound:
        status_code, is_success = 404, False

    calls = []
    monkeypatch.setattr(bank.httpx, "get", lambda url, **k: calls.append(url) or NotFound())
    store = Memory()
    assert bank.branch("ABCD0123456", store) == {} and bank.branch("ABCD0123456", store) == {}
    assert calls == ["https://ifsc.razorpay.com/ABCD0123456"]

    def offline(url, **k):
        raise bank.httpx.ConnectError("offline")
    monkeypatch.setattr(bank.httpx, "get", offline)
    assert bank.branch("SBIN0000011", Memory()) is None


def test_bank_details_read_from_a_quote_must_appear_in_it(monkeypatch):
    import json
    from parakh import document
    text = "SHREE VINAYAKA CORRUGATORS, Peenya, Bengaluru. GSTIN 29ABKFS4821L1ZM. Account no: 3829 1047 6644 17. IFSC: SBIN0000011"

    def answering(answer):
        class Reply:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": json.dumps(answer)}}]}
        return lambda *a, **k: Reply()

    monkeypatch.setattr(document.httpx, "post", answering({"name": "Shree Vinayaka Corrugators", "account": "38291047664417", "ifsc": "SBIN0000011",
                                                           "bank": "State Bank of India, Peenya Branch"}))
    read = document.fields(text, "key")
    assert (read["account"], read["ifsc"], read["bank"]) == ("38291047664417", "SBIN0000011", "State Bank of India, Peenya Branch")
    monkeypatch.setattr(document.httpx, "post", answering({"name": "x", "account": "50100012345678", "ifsc": "HDFC0000001"}))
    invented = document.fields(text, "key")
    assert invented["account"] == "" and invented["ifsc"] == ""


def test_a_repeat_check_reuses_the_models_labels(monkeypatch):
    from parakh import judge

    class Memory(dict):
        cached, remember = dict.get, dict.__setitem__

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"results": [{"id": "news-0", "about_vendor": "yes", "kind": "neutral"}]}'}}]}

    calls = []
    monkeypatch.setattr(judge.httpx, "post", lambda *a, **k: calls.append(1) or Reply())
    item = {"id": "news-0", "source": "news", "title": "Acme Steel opens a plant", "snippet": "", "link": None}
    store = Memory()
    first, _ = judge.judge({"name": "Acme Steel", "city": "Pune"}, [item], "key", store)
    again, _ = judge.judge({"name": "Acme Steel", "city": "Pune"}, [item], "key", store)
    assert len(calls) == 1 and first == again and first[0]["about_vendor"] == "yes"
    judge.judge({"name": "Acme Steels", "city": "Pune"}, [item], "key", store)
    assert len(calls) == 2  # a different supplier is a different question
