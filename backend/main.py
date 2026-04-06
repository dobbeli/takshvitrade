"""
Takshvi Trade — FastAPI Backend
"""

import sys
import traceback
import logging

logging.basicConfig(level=logging.INFO)

# ===============================
# IMPORTS
# ===============================

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from contextlib import asynccontextmanager
    print("✅ FastAPI imported")
except Exception as e:
    print(f"❌ FastAPI import failed: {e}")
    sys.exit(1)

try:
    from routers import signals, market, auth, news
    print("✅ Routers imported")
except Exception as e:
    print(f"⚠️ Router import failed (continuing): {e}")

import yfinance as yf
import pandas as pd
import ta
from pydantic import BaseModel

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===============================
# ROUTERS (SAFE LOAD)
# ===============================

try:
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(signals.router, prefix="/api/signals")
    app.include_router(market.router, prefix="/api/market")
    app.include_router(news.router, prefix="/api/news")
    print("✅ Routers loaded")
except:
    print("⚠️ Some routers skipped")

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
# 📊 MARKET API (FIXED)
# ===============================
@app.get("/market")
def market_status():
    try:
        import yfinance as yf

        ticker = yf.Ticker("NIFTYBEES.NS")
        df = ticker.history(period="5d")

        print("📊 Market Data:")
        print(df.tail())

        if df is None or df.empty:
            return {"price": 0, "trend": "NA"}

        close = df["Close"]

        price = round(close.iloc[-1], 2)
        prev = close.iloc[-2]

        return {
            "price": price,
            "trend": "UP" if price > prev else "DOWN"
        }

    except Exception as e:
        print(f"❌ Market error: {e}")
        return {"price": 0, "trend": "NA"}
# ===============================
# 🔥 SCANNER API
# ===============================

class ScanRequest(BaseModel):
    capital: int


def scan_stock(symbol, capital):
    try:
        logging.info(f"Scanning {symbol}")

        df = yf.download(symbol, period="3mo", interval="1d", progress=False)

        if df is None or df.empty:
            return None

        df["EMA20"] = ta.trend.ema_indicator(df["Close"], 20)
        df["EMA50"] = ta.trend.ema_indicator(df["Close"], 50)
        df["RSI"] = ta.momentum.rsi(df["Close"], 14)

        df = df.dropna()
        latest = df.iloc[-1]

        score = 0

        if latest["EMA20"] > latest["EMA50"]:
            score += 30

        if 50 < latest["RSI"] < 70:
            score += 30

        if score < 50:
            return None

        entry = round(latest["Close"] * 1.002, 2)
        sl = round(latest["Low"], 2)
        risk = entry - sl

        if risk <= 0:
            return None

        qty = max(1, int((capital * 0.01) / risk))
        target = round(entry + (risk * 2), 2)

        return {
            "stock": symbol.replace(".NS", ""),
            "entry": entry,
            "sl": sl,
            "target": target,
            "qty": qty,
            "score": score
        }

    except Exception as e:
        logging.error(f"Error scanning {symbol}: {e}")
        return None


@app.post("/run-scan")
def run_scan(req: ScanRequest):

    stocks = [
        "RELIANCE.NS",
        "TCS.NS",
        "INFY.NS",
        "HDFCBANK.NS",
        "ICICIBANK.NS"
    ]

    results = []

    for stock in stocks:
        r = scan_stock(stock, req.capital)
        if r:
            results.append(r)

    results.sort(key=lambda x: x["score"], reverse=True)

    return {
        "count": len(results),
        "data": results
    }