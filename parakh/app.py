"""Parakh: check a supplier before you pay them.

  uvicorn parakh.app:app --reload        then open http://127.0.0.1:8000
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import brief, evidence, gstin, judge
from .search import Searches

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
CHECKS = Path(os.environ.get("PARAKH_CHECKS", ROOT / "checks"))
CHECKS.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="Parakh")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class Vendor(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=60)
    gstin: str = Field(default="", max_length=20)


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/status")
def status():
    return {"serpapi": bool(os.environ.get("SERPAPI_API_KEY")), "model": judge.MODEL if os.environ.get("TINKER_API_KEY") else None,
            "offline": os.environ.get("PARAKH_OFFLINE") == "1"}


@app.post("/api/check")
def check(vendor: Vendor):
    v = vendor.model_dump()
    v["gstin"] = v["gstin"].replace(" ", "").upper()

    def events():
        emit = lambda event: json.dumps(event, ensure_ascii=False) + "\n"
        yield emit({"step": "gstin", "detail": "Reading what the GSTIN says about itself" if v["gstin"] else "No GSTIN given"})
        gst = gstin.inspect(v["gstin"], v["name"])
        searches = Searches(os.environ.get("SERPAPI_API_KEY"), offline=os.environ.get("PARAKH_OFFLINE") == "1")
        # The registry search only makes sense for a well-formed GSTIN
        for event in evidence.gather({**v, "gstin": v["gstin"] if gst.get("valid") else ""}, searches):
            if event["step"] == "gathered":
                gathering = event
            else:
                yield emit(event)
        yield emit({"step": "judge", "detail": f"Reading {len(gathering['items'])} public results with an open model"})
        try:
            judged, model = judge.judge(v, gathering["items"], os.environ.get("TINKER_API_KEY"))
        except Exception as error:  # the brief still works on keyword labels
            judged, model = [{**i, **judge.fallback(i, v)} for i in gathering["items"]], f"keywords (model unavailable: {type(error).__name__})"
        result = brief.build(v, gst, gathering, judged, model, searches.log)
        (CHECKS / f"{result['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        yield emit({"step": "done", "brief": result})

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/api/checks")
def recent():
    items = []
    for path in sorted(CHECKS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:12]:
        b = json.loads(path.read_text(encoding="utf-8"))
        items.append({"id": b["id"], "name": b["vendor"]["name"], "city": b["vendor"]["city"], "verdict": b["verdict"], "created_at": b["created_at"]})
    return items


@app.get("/api/checks/{check_id}")
def one(check_id: str):
    path = CHECKS / f"{check_id}.json"
    if not check_id.isalnum() or not path.exists():
        raise HTTPException(404, "No such check.")
    return json.loads(path.read_text(encoding="utf-8"))
