"""
Takshvi Trade — FastAPI Backend v2.1
"""
import logging
logging.basicConfig(level=logging.INFO)

import io
import csv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from routers import market
from routers import news
from routers import whatsapp

from scanner.engine import run_full_scan, run_master_scan, get_market_trend

from scanner.database import (
    save_scan, save_signals, get_recent_scans,
    get_open_signals, get_alert_logs, is_connected,
    get_connection_error, bootstrap_schema
)

print("✅ All imports successful")


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_schema()
    db_ok = is_connected()
    print(f"✅ Takshvi Trade API started | Supabase: {'✅ connected' if db_ok else '❌ not connected'}")
    yield
    print("🛑 Takshvi Trade API stopped")


app = FastAPI(title="Takshvi Trade API", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router,   prefix="/api/market")
app.include_router(news.router,     prefix="/api/news")
app.include_router(whatsapp.router, prefix="/api/whatsapp")


@app.get("/")
def root():
    return {"status": "ok", "platform": "Takshvi Trade", "version": "2.1"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/db-status")
def db_status():
    import os
    connected = is_connected()
    error_msg = "" if connected else get_connection_error()
    return {
        "supabase_connected": connected,
        "has_url":  bool(os.getenv("SUPABASE_URL")),
        "has_key":  bool(os.getenv("SUPABASE_KEY")),
        "status":   "ok" if connected else "not_configured",
        "error":    error_msg,
    }


@app.get("/debug-env")
def debug_env():
    import os, base64, json
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    role = "unknown"
    try:
        payload_b64 = key.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.b64decode(payload_b64))
        role = payload.get("role", "unknown")
    except:
        role = "decode_failed"
    return {
        "url_start":   url[:40],
        "key_start":   key[:30],
        "key_role":    role,
        "key_is_anon": role == "anon",
        "key_is_svc":  role == "service_role",
    }


@app.get("/api/history")
def scan_history(limit: int = 10):
    rows = get_recent_scans(limit=limit)
    return {"count": len(rows), "history": rows}


@app.get("/api/signals/open")
def open_signals(limit: int = 50):
    rows = get_open_signals(limit=limit)
    return {"count": len(rows), "signals": rows}


@app.get("/api/alerts/log")
def alert_log(limit: int = 50):
    rows = get_alert_logs(limit=limit)
    return {"count": len(rows), "logs": rows}


@app.get("/run-master-scan")
def master_scan(capital: int = 100000):
    try:
        result = run_master_scan(
            capital=capital,
            risk_amount=int(capital * 0.01)
        )
        scan_id       = save_scan(result, capital)
        signals_saved = 0
        if scan_id:
            signals_saved = save_signals(result, scan_id)
            logging.info(f"DB save: scan_id={scan_id}, signals={signals_saved}")
        return {
            **result,
            "scan_id":       scan_id,
            "signals_saved": signals_saved,
        }
    except Exception as e:
        logging.error(f"Master scan error: {e}")
        return {
            "market_trend": "SIDEWAYS", "nifty": None, "change_pct": None,
            "scan_time": 0, "is_crash": False,
            "long_signals": [], "pre_breakout": [], "short_signals": [],
            "pre_breakdown": [], "relative_strength": [],
            "scan_id": None, "signals_saved": 0, "error": str(e),
        }


@app.get("/run-scan")
def run_scan(capital: int = 50000):
    try:
        market_trend, nifty_value, change_pct = get_market_trend()
        results = run_full_scan(capital=capital)
        return {
            "count": len(results), "data": results,
            "market_trend": market_trend, "nifty": nifty_value, "change_pct": change_pct,
        }
    except Exception as e:
        logging.error(f"Scan error: {e}")
        return {"count": 0, "data": [], "market_trend": "SIDEWAYS", "nifty": None, "change_pct": None}


@app.get("/chart")
def get_chart(symbol: str = "INFY.NS"):
    import requests
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=3mo&interval=1d"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = res.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quotes = result["indicators"]["quote"][0]
        chart_data = [
            {"time": timestamps[i], "open": quotes["open"][i],
             "high": quotes["high"][i], "low": quotes["low"][i], "close": quotes["close"][i]}
            for i in range(len(timestamps))
        ]
        return {"data": chart_data}
    except Exception as e:
        logging.error(f"Chart error: {e}")
        return {"data": []}


@app.get("/download-csv")
def download_csv(capital: int = 50000):
    try:
        results = run_full_scan(capital=capital)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Stock", "Score", "Entry", "SL", "Target", "RR", "Qty", "Position"])
        if not results:
            writer.writerow(["No trades", "", "", "", "", "", "", ""])
        else:
            for r in results:
                writer.writerow([
                    r.get("stock", ""), r.get("score", 0), r.get("entry", 0),
                    r.get("sl", 0), r.get("target", 0), r.get("rr", 0),
                    r.get("qty", 0), r.get("position", 0)
                ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]), media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=trades.csv"}
        )
    except Exception as e:
        logging.error(f"CSV error: {e}")
        return {"message": "CSV generation failed"}