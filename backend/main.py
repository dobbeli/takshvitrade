"""
Takshvi Trade — FastAPI Backend
"""
import logging

logging.basicConfig(level=logging.INFO)

# ===============================
# IMPORTS
# ===============================

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import io
import csv
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Routers
from routers import signals
from routers import market
from routers import news
from routers import whatsapp

# Engine
from scanner.engine import run_full_scan, get_market_trend  

print("✅ All imports successful")

# ===============================
# APP SETUP
# ===============================

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✅ Takshvi Trade API started")
    yield
    print("🛑 Takshvi Trade API stopped")

app = FastAPI(
    title="Takshvi Trade API",
    version="1.0.0",
    lifespan=lifespan
)

# ===============================
# CORS
# ===============================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===============================
# ROUTERS
# ===============================

app.include_router(signals.router, prefix="/api/signals")
app.include_router(market.router, prefix="/api/market")
app.include_router(news.router, prefix="/api/news")
app.include_router(whatsapp.router, prefix="/api/whatsapp")

# ===============================
# BASIC ROUTES
# ===============================

@app.get("/")
def root():
    return {"status": "ok", "platform": "Takshvi Trade"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# ===============================
# 📊 CHART API
# ===============================

@app.get("/chart")
def get_chart(symbol: str = "INFY.NS"):
    import requests

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=3mo&interval=1d"
        headers = {"User-Agent": "Mozilla/5.0"}

        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()

        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quotes = result["indicators"]["quote"][0]

        chart_data = []

        for i in range(len(timestamps)):
            chart_data.append({
                "time": timestamps[i],
                "open": quotes["open"][i],
                "high": quotes["high"][i],
                "low": quotes["low"][i],
                "close": quotes["close"][i],
            })

        return {"data": chart_data}

    except Exception as e:
        logging.error(f"Chart error: {e}")
        return {"data": []}

# ===============================
# 🔥 SCANNER API
# ===============================

@app.get("/run-scan")
def run_scan(capital: int = 50000):
    try:
        # ✅ MARKET DATA
        market_trend, nifty_value = get_market_trend()

        # ✅ SCAN
        results = run_full_scan(capital=capital)

        return {
            "count": len(results),
            "data": results,
            "market_trend": market_trend,
            "nifty": nifty_value
        }

    except Exception as e:
        logging.error(f"Scan error: {e}")
        return {
            "count": 0,
            "data": [],
            "market_trend": "SIDEWAYS",
            "nifty": None
        }

# ===============================
# 📥 CSV DOWNLOAD API
# ===============================

@app.get("/download-csv")
def download_csv(capital: int = 50000):
    try:
        results = run_full_scan(capital=capital)

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Stock", "Score", "Entry", "SL", "Target",
            "RR", "Qty", "Position"
        ])

        if not results:
            writer.writerow(["No trades", "", "", "", "", "", "", ""])
        else:
            for r in results:
                writer.writerow([
                    r.get("stock", ""),
                    r.get("score", 0),
                    r.get("entry", 0),
                    r.get("sl", 0),
                    r.get("target", 0),
                    r.get("rr", 0),
                    r.get("qty", 0),
                    r.get("position", 0)
                ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=trades.csv"
            }
        )

    except Exception as e:
        logging.error(f"CSV error: {e}")
        return {"message": "CSV generation failed"}