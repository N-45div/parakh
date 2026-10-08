"""Parakh: check a supplier before you pay them.

  uvicorn parakh.app:app --reload        then open http://127.0.0.1:8000
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from . import brief, evidence, gstin, judge  # noqa: E402  (settings load first)
from .search import Searches  # noqa: E402
from .store import Store, visitor  # noqa: E402

STATIC = Path(__file__).parent / "static"
CHECKS_PER_VISITOR = int(os.environ.get("PARAKH_DAILY_CHECKS", "5"))
store = Store()
app = FastAPI(title="Parakh")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class Vendor(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=60)
    gstin: str = Field(default="", max_length=20)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return {"serpapi": bool(os.environ.get("SERPAPI_API_KEY")), "model": judge.MODEL if os.environ.get("TINKER_API_KEY") else None,
            "offline": os.environ.get("PARAKH_OFFLINE") == "1"}


@app.post("/api/check")
def check(vendor: Vendor, request: Request):
    v = vendor.model_dump()
    v["gstin"] = v["gstin"].replace(" ", "").upper()
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    if not store.take(f"visitor:{visitor(ip)}", CHECKS_PER_VISITOR):
        return JSONResponse({"detail": f"You've run {CHECKS_PER_VISITOR} checks today. The example briefs are still open, or run Parakh yourself from GitHub."}, 429)

    def events():
        emit = lambda event: json.dumps(event, ensure_ascii=False) + "\n"
        yield emit({"step": "gstin", "detail": "Reading what the GSTIN says about itself" if v["gstin"] else "No GSTIN given"})
        gst = gstin.inspect(v["gstin"], v["name"])
        searches = Searches(os.environ.get("SERPAPI_API_KEY"), store, offline=os.environ.get("PARAKH_OFFLINE") == "1")
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
        store.save(result)
        yield emit({"step": "done", "brief": result})

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/api/examples")
def examples():
    return store.examples()


@app.get("/api/checks/{check_id}")
def one(check_id: str):
    found = store.load(check_id) if check_id.isalnum() and len(check_id) <= 32 else None
    if not found:
        raise HTTPException(404, "No such check.")
    return found
