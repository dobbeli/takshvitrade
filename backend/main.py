"""
Takshvi Trade — FastAPI Backend v2.1
Changes from v2.0:
- Auto-saves scan results to Supabase after every master scan
- Auto-logs WhatsApp alerts to alert_logs table
- /db-status endpoint for health checking Supabase connection
- /api/history endpoint to retrieve past scans
- /api/signals/open  endpoint for open trade monitoring
"""
import logging
logging.basicConfig(level=logging.INFO)

import io
import csv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Routers
from routers import market
from routers import news
from routers import whatsapp

# Engine
from scanner.engine import run_full_scan, run_master_scan, get_market_trend

# Database
from scanner.database import (
    save_scan, save_signals, get_recent_scans,
    get_open_signals, get_alert_logs, is_connected, get_connection_error
)

print("✅ All imports successful")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_ok = is_connected()
    print(f"✅ Takshvi Trade API started | Supabase: {'✅ connected' if db_ok else '❌ not connected'}")
    yield
    print("🛑 Takshvi Trade API stopped")


app = FastAPI(title="Takshvi Trade API", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://takshvitrade.vercel.app",
        "https://takshvitrade.com",
        "https://www.takshvitrade.com",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(market.router,   prefix="/api/market")
app.include_router(news.router,     prefix="/api/news")
app.include_router(whatsapp.router, prefix="/api/whatsapp")


# ── Basic routes ──────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "platform": "Takshvi Trade", "version": "2.1"}


@app.get("/health")
def health():
    return {"status": "healthy"}


# ── DB Health ─────────────────────────────────────────────────
@app.get("/db-status")
def db_status():
    """Check Supabase connection and return env var presence."""
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


# ── Scan History ──────────────────────────────────────────────
@app.get("/api/history")
def scan_history(limit: int = 10):
    """Returns the last N scan results from Supabase."""
    rows = get_recent_scans(limit=limit)
    return {"count": len(rows), "history": rows}


@app.get("/api/signals/open")
def open_signals(limit: int = 50):
    """Returns signals that haven't been marked with an outcome yet."""
    rows = get_open_signals(limit=limit)
    return {"count": len(rows), "signals": rows}


@app.get("/api/alerts/log")
def alert_log(limit: int = 50):
    """Returns recent WhatsApp alert logs."""
    rows = get_alert_logs(limit=limit)
    return {"count": len(rows), "logs": rows}


# ── Master Scan (auto-saves to Supabase) ─────────────────────
@app.get("/run-master-scan")
def master_scan(capital: int = 100000):
    """
    Runs full master scan across 50 Nifty stocks.
    Automatically saves scan + signals to Supabase.
    """
    try:
        result = run_master_scan(
            capital=capital,
            risk_amount=int(capital * 0.01)
        )

        # ── Auto-save to Supabase ──────────────────────────────
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
            "market_trend":      "SIDEWAYS",
            "nifty":             None,
            "change_pct":        None,
            "scan_time":         0,
            "is_crash":          False,
            "long_signals":      [],
            "pre_breakout":      [],
            "short_signals":     [],
            "pre_breakdown":     [],
            "relative_strength": [],
            "scan_id":           None,
            "signals_saved":     0,
            "error":             str(e),
        }


# ── Legacy scan (backward compat) ────────────────────────────
@app.get("/run-scan")
def run_scan(capital: int = 50000):
    try:
        market_trend, nifty_value, change_pct = get_market_trend()
        results = run_full_scan(capital=capital)
        return {
            "count":        len(results),
            "data":         results,
            "market_trend": market_trend,
            "nifty":        nifty_value,
            "change_pct":   change_pct,
        }
    except Exception as e:
        logging.error(f"Scan error: {e}")
        return {"count": 0, "data": [], "market_trend": "SIDEWAYS", "nifty": None, "change_pct": None}


# ── Chart data ────────────────────────────────────────────────
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
            {
                "time":  timestamps[i],
                "open":  quotes["open"][i],
                "high":  quotes["high"][i],
                "low":   quotes["low"][i],
                "close": quotes["close"][i],
            }
            for i in range(len(timestamps))
        ]
        return {"data": chart_data}
    except Exception as e:
        logging.error(f"Chart error: {e}")
        return {"data": []}


# ── CSV Download ──────────────────────────────────────────────
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
                    r.get("stock", ""),  r.get("score", 0),
                    r.get("entry", 0),   r.get("sl", 0),
                    r.get("target", 0),  r.get("rr", 0),
                    r.get("qty", 0),     r.get("position", 0)
                ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=trades.csv"}
        )
    except Exception as e:
        logging.error(f"CSV error: {e}")
        return {"message": "CSV generation failed"}

@app.get("/ping-supabase")
def ping_supabase():
    import requests, os
    url = os.getenv("SUPABASE_URL","") + "/rest/v1/scan_history?select=id&limit=1"
    try:
        r = requests.get(url, headers={
            "apikey": os.getenv("SUPABASE_KEY",""),
            "Authorization": "Bearer " + os.getenv("SUPABASE_KEY","")
        }, timeout=15)
        return {"status": r.status_code, "body": r.text[:200]}
    except Exception as e:
        return {"error": str(e)}