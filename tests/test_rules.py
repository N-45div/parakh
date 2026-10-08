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
    monkeypatch.delenv("MONGODB_URI", raising=False)
    import importlib
    from fastapi.testclient import TestClient
    import parakh.app
    importlib.reload(parakh.app)
    client = TestClient(parakh.app.app)
    assert client.get("/api/examples").json() == []
    assert client.get("/api/checks/nope").status_code == 404
    assert client.get("/").status_code == 200
