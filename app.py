"""
National Disaster Relief Command — risk assessment + automatic fund allocation.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:8000
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from blockchain import ReliefChain
from contract import ReliefFundContract
from ethereum_adapter import EthereumAdapter
from risk_adapter import RiskAdapter


STATIC = Path(__file__).resolve().parent / "static"
SOL_PATH = Path(__file__).resolve().parent / "contracts" / "ReliefFund.sol"

adapter = RiskAdapter()
chain = ReliefChain()
fund = ReliefFundContract()
ethereum = EthereumAdapter()
events: deque = deque(maxlen=200)
listeners: list[asyncio.Queue] = []
lock = threading.Lock()

def treasury_snapshot() -> dict:
    """Use real on-chain values when Ethereum mode is enabled."""
    return ethereum.snapshot() if ethereum.enabled else fund.snapshot()


def add_ethereum_metadata(tx: dict, decision: dict) -> None:
    """Adds public Ethereum proof to the local audit-ledger transaction."""
    if decision.get("on_chain"):
        tx["ethereum_tx_hash"] = decision["tx_hash"]
        tx["ethereum_block_number"] = decision["block_number"]
        tx["ethereum_receipt_status"] = decision["receipt_status"]
        tx["explorer_url"] = decision["explorer_url"]
        tx["contract_address"] = ethereum.contract_address

def publish(event: dict) -> None:
    event = {**event, "ts": time.time()}
    events.appendleft(event)
    for q in list(listeners):
        try:
            q.put_nowait(event)
        except Exception:
            pass


class RainfallIn(BaseModel):
    JUN: float = 0
    JUL: float = 0
    AUG: float = 0


class AssessIn(BaseModel):
    region: str = "Coastal Karnataka"
    hazard: str = "multi"
    lat: float | None = 12.9141
    lon: float | None = 74.8560
    month: int | None = None
    eq_region: str | None = "Northeast India"
    eq_month: int | str | None = None
    rainfall: RainfallIn | None = None
    auto_disburse: bool = True


class DepositIn(BaseModel):
    amount: float = Field(gt=0, le=500_000_000)


class NowcastIn(BaseModel):
    lat: float = 12.9141
    lon: float = 74.8560
    region: str = "Coastal Karnataka"


app = FastAPI(title="Smart Fund Allocation")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _dominant(report: dict) -> tuple[str, dict]:
    best_name, best = "multi", {"risk_score": 0, "risk_category": "LOW", "advice": ""}
    for name in ("flood", "cyclone", "earthquake"):
        if name in report and report[name].get("risk_score", 0) >= best.get("risk_score", 0):
            best_name, best = name, report[name]
    return best_name, adapter.normalize(best, best_name)

def maybe_disburse(
    report: dict,
    region: str,
    auto: bool,
    record_on_chain: bool = True,
) -> dict:
    """Evaluates risk, optionally writes a real Ethereum transaction, and audits it."""
    hazard, norm = _dominant(report)
    assessment_id = "0x" + uuid.uuid4().hex[:24]

    with lock:
        if ethereum.enabled:
            if auto and record_on_chain:
                decision = ethereum.execute_disbursal(
                    assessment_id=assessment_id,
                    region=region,
                    hazard=hazard,
                    risk_score=norm["risk_score"],
                    category=norm["risk_category"],
                )
            elif not auto:
                decision = {
                    "status": "held",
                    "reason": "manual review (auto-disburse off)",
                    "amount": 0,
                    "on_chain": False,
                }
            else:
                decision = {
                    "status": "held",
                    "reason": "monitoring-only assessment; not sent on-chain",
                    "amount": 0,
                    "on_chain": False,
                }
        else:
            # Keeps your original local simulator working when Ethereum is off.
            decision = fund.execute_disbursal(
                assessment_id=assessment_id,
                region=region,
                hazard=hazard,
                risk_score=norm["risk_score"],
                category=norm["risk_category"],
            ) if auto else {
                "status": "held",
                "reason": "manual review (auto-disburse off)",
                "amount": 0,
            }

        if decision.get("status") == "executed":
            tx = {
                "type": "DISBURSE",
                "assessment_id": assessment_id,
                "region": region,
                "hazard": hazard,
                "risk_score": norm["risk_score"],
                "risk_category": norm["risk_category"],
                "amount": decision["amount"],
                "treasury_after": treasury_snapshot()["treasury"],
                "contract": "ReliefFund.sol",
            }
            add_ethereum_metadata(tx, decision)
            block = chain.append(tx)
        else:
            tx = {
                "type": "ASSESS",
                "assessment_id": assessment_id,
                "region": region,
                "hazard": hazard,
                "risk_score": norm["risk_score"],
                "risk_category": norm["risk_category"],
                "decision": decision.get("reason"),
            }
            add_ethereum_metadata(tx, decision)
            block = chain.append(tx)

    publish({
        "kind": "disbursal" if decision.get("status") == "executed" else "assessment",
        "region": region,
        "hazard": hazard,
        "risk": norm,
        "decision": decision,
        "block": block["hash"],
    })

    return {
        "assessment_id": assessment_id,
        "dominant_hazard": hazard,
        "normalized": norm,
        "decision": decision,
        "block": block,
        "treasury": treasury_snapshot(),
        "chain": chain.verify(),
    }

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def state():
    return {
        "engine_mode": adapter.mode,
        "watchlist": adapter.WATCHLIST,
        "eq_regions": adapter.EQ_REGIONS,
        "treasury": treasury_snapshot(),
        "ethereum": ethereum.status(),
        "chain": chain.verify(),
        "ledger": chain.recent(40),
        "events": list(events)[:30],
        "objectives": [
            "Real-Time Monitoring",
            "Automated Fund Disbursal",
            "Smart Contract Execution",
            "Transparency and Accountability",
        ],
    }


@app.get("/api/contract")
def contract_source():
    return {
        "solidity": SOL_PATH.read_text(encoding="utf-8"),
        **treasury_snapshot(),
        "ethereum": ethereum.status(),
    }


@app.post("/api/assess")
def assess(body: AssessIn):
    payload = {
        "lat": body.lat,
        "lon": body.lon,
        "month": body.month,
        "eq_region": body.eq_region,
        "eq_month": body.eq_month,
        "rainfall": body.rainfall.model_dump() if body.rainfall else None,
    }
    if body.hazard == "flood":
        r = body.rainfall or RainfallIn()
        report = {"flood": adapter.flood(r.JUN, r.JUL, r.AUG), "engine_mode": adapter.mode}
        report["overall_regional_risk_index"] = report["flood"]["risk_score"]
        report["overall_regional_risk_category"] = report["flood"]["risk_category"]
    elif body.hazard == "cyclone":
        if body.lat is None or body.lon is None:
            raise HTTPException(400, "lat/lon required")
        c = adapter.cyclone(body.lat, body.lon, body.month)
        report = {"cyclone": c, "engine_mode": adapter.mode,
                  "overall_regional_risk_index": c["risk_score"],
                  "overall_regional_risk_category": c["risk_category"]}
    elif body.hazard == "earthquake":
        e = adapter.earthquake(body.eq_month or body.month or 8, body.eq_region or "Northeast India")
        report = {"earthquake": e, "engine_mode": adapter.mode,
                  "overall_regional_risk_index": e["risk_score"],
                  "overall_regional_risk_category": e.get("risk_category") or e.get("risk_level")}
    else:
        if payload["rainfall"] is None:
            payload["rainfall"] = {"JUN": 280, "JUL": 420, "AUG": 310}
        report = adapter.combined(payload)
    allocation = maybe_disburse(report, body.region, body.auto_disburse)
    return {"report": report, "allocation": allocation, "location": {"lat": body.lat, "lon": body.lon, "region": body.region}}


@app.post("/api/deposit")
def deposit(body: DepositIn):
    with lock:
        if ethereum.enabled:
            try:
                receipt = ethereum.deposit(body.amount)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            tx = {
                "type": "DEPOSIT",
                "amount": receipt["amount"],
                "treasury_after": treasury_snapshot()["treasury"],
            }
            add_ethereum_metadata(tx, receipt)
            block = chain.append(tx)
        else:
            snap = fund.deposit(body.amount)
            block = chain.append({
                "type": "DEPOSIT",
                "amount": body.amount,
                "treasury_after": snap["treasury"],
            })

    publish({
        "kind": "deposit",
        "amount": body.amount,
        "treasury": treasury_snapshot()["treasury"],
    })

    return {
        "treasury": treasury_snapshot(),
        "block": block,
        }


@app.post("/api/nowcast")
def nowcast(body: NowcastIn):
    result = adapter.nowcast(body.lat, body.lon)
    if "error" not in result:
        publish({
            "kind": "nowcast",
            "region": body.region,
            "forecast_mm": result.get("forecast_10day_total_mm"),
            "threshold_mm": result.get("flood_threshold_mm"),
            "flood_expected": result.get("flood_expected_this_month"),
        })
    return result


@app.get("/api/verify")
def verify():
    return chain.verify()


@app.get("/api/stream")
async def stream():
    q: asyncio.Queue = asyncio.Queue()
    listeners.append(q)

    async def gen():
        try:
            yield f"data: {json.dumps({'kind': 'hello', 'mode': adapter.mode})}\n\n"
            while True:
                evt = await q.get()
                yield f"data: {json.dumps(evt, default=str)}\n\n"
        finally:
            if q in listeners:
                listeners.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _monitor_loop() -> None:
    """Simulated real-time sensor poll across the watchlist."""
    i = 0
    while True:
        time.sleep(11)
        site = adapter.WATCHLIST[i % len(adapter.WATCHLIST)]
        i += 1
        tick = int(time.time()) % 17
        # Mostly routine ticks; a few HIGH/SEVERE pulses so auto-disbursal is visible
        if site["hazard"] == "flood":
            base = 160 + (tick * 18) + (90 if tick in {14, 15, 16} else 0)
            report = {"flood": adapter.flood(base, base + 40, base - 20)}
            report["overall_regional_risk_index"] = report["flood"]["risk_score"]
            report["overall_regional_risk_category"] = report["flood"]["risk_category"]
        elif site["hazard"] == "cyclone":
            month = 11 if tick > 8 else 7
            c = adapter.cyclone(site["lat"], site["lon"], month)
            report = {"cyclone": c, "overall_regional_risk_index": c["risk_score"],
                      "overall_regional_risk_category": c["risk_category"]}
        else:
            e = adapter.earthquake(tick % 12 + 1, "Himalayan Region" if "Srinagar" in site["name"] else "Northeast India")
            if "Bhuj" in site["name"]:
                e = adapter.earthquake(1, "Gujarat (Kutch)")
            if "Port Blair" in site["name"]:
                e = adapter.earthquake(12, "Andaman & Nicobar Islands")
            report = {"earthquake": e, "overall_regional_risk_index": e["risk_score"],
                      "overall_regional_risk_category": e.get("risk_category") or e.get("risk_level")}
        maybe_disburse(report,site["name"],auto=True,record_on_chain=False)
        publish({
            "kind": "monitor",
            "site": site,
            "score": report.get("overall_regional_risk_index"),
            "category": report.get("overall_regional_risk_category"),
        })


@app.on_event("startup")
def startup():
    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()
    publish({"kind": "system", "message": "Command center online — oracle linked to ReliefFund"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)