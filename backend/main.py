"""
Takshvi Trade — FastAPI Backend
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

print("✅ All imports successful")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✅ Takshvi Trade API started")
    yield
    print("🛑 Takshvi Trade API stopped")

app = FastAPI(title="Takshvi Trade API", version="2.0.0", lifespan=lifespan)

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
app.include_router(market.router,    prefix="/api/market")
app.include_router(news.router,      prefix="/api/news")
app.include_router(whatsapp.router,  prefix="/api/whatsapp")

# ── Basic routes ──────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "platform": "Takshvi Trade", "version": "2.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# ── Master Scan (new — all 5 signal types) ───────────────────
@app.get("/run-master-scan")
def master_scan(capital: int = 100000):
    try:
        result = run_master_scan(
            capital=capital,
            risk_amount=int(capital * 0.01)
        )
        return result
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
            "error":             str(e)
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
        writer.writerow(["Stock","Score","Entry","SL","Target","RR","Qty","Position"])
        if not results:
            writer.writerow(["No trades","","","","","","",""])
        else:
            for r in results:
                writer.writerow([
                    r.get("stock",""), r.get("score",0),
                    r.get("entry",0),  r.get("sl",0),
                    r.get("target",0), r.get("rr",0),
                    r.get("qty",0),    r.get("position",0)
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