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
        import requests

        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI"

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        res = requests.get(url, headers=headers)
        data = res.json()

        result = data["chart"]["result"][0]
        close_prices = result["indicators"]["quote"][0]["close"]

        price = round(close_prices[-1], 2)
        prev = close_prices[-2]

        trend = "UP" if price > prev else "DOWN"

        return {
            "price": price,
            "trend": trend
        }

    except Exception as e:
        print(f"❌ Market error: {e}")

        # fallback only if API fails
        return {
            "price": 22800,
            "trend": "DOWN"
        }
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

@app.get("/run-scan")
def run_scan(capital: int = 50000):

    import requests

    stocks = [
    "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS","ICICIBANK.NS",
    "SBIN.NS","AXISBANK.NS","KOTAKBANK.NS","LT.NS","ITC.NS",
    "HINDUNILVR.NS","BAJFINANCE.NS","MARUTI.NS","TITAN.NS",
    "SUNPHARMA.NS","ULTRACEMCO.NS","WIPRO.NS","ONGC.NS",
    "POWERGRID.NS","NTPC.NS","ADANIENT.NS","ADANIPORTS.NS",
    "COALINDIA.NS","JSWSTEEL.NS","TATASTEEL.NS","HCLTECH.NS"
]

    results = []

    for stock in stocks:
        try:
            print(f"🔍 Fetching {stock}")

            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock}"
            headers = {"User-Agent": "Mozilla/5.0"}

            res = requests.get(url, headers=headers)
            data = res.json()

            result = data["chart"]["result"][0]
            close_prices = result["indicators"]["quote"][0]["close"]

            # ===============================
            # 📊 DATA VALIDATION
            # ===============================
            if not close_prices or len(close_prices) < 50:
                continue

            prices = close_prices[-50:]

            latest = prices[-1]
            prev = prices[-2]

            # ===============================
            # 📊 EMA CALCULATION
            # ===============================
            def calculate_ema(prices, period):
                k = 2 / (period + 1)
                ema = prices[0]
                for price in prices:
                    ema = price * k + ema * (1 - k)
                return ema

            ema20 = calculate_ema(prices[-20:], 20)
            ema50 = calculate_ema(prices, 50)

            # ===============================
            # 📊 RSI CALCULATION
            # ===============================
            gains = []
            losses = []

            for i in range(1, len(prices)):
                diff = prices[i] - prices[i-1]
                if diff > 0:
                    gains.append(diff)
                else:
                    losses.append(abs(diff))

            avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
            avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else 1

            rs = avg_gain / avg_loss if avg_loss != 0 else 0
            rsi = 100 - (100 / (1 + rs))

            # ===============================
            # 📊 MOMENTUM
            # ===============================
            price_change = latest - prev
            percent_move = (price_change / latest) * 100

            # ===============================
            # 📊 SCORING SYSTEM
            # ===============================
            score = 0

            if latest > ema20:
                score += 20

            if ema20 > ema50:
                score += 20

            if 50 < rsi < 70:
                score += 20

            if price_change > 0:
                score += 20

            if percent_move > 0.5:
                score += 20

            # ❌ FILTER WEAK STOCKS
            if score < 60:
                continue

            # ===============================
            # 💰 TRADE CALCULATION
            # ===============================
            entry = round(latest * 1.002, 2)
            sl = round(latest * 0.98, 2)

            risk = entry - sl
            if risk <= 0:
                continue

            qty = max(1, int((capital * 0.01) / risk))
            target = round(entry + (risk * 2), 2)

            results.append({
                "stock": stock.replace(".NS", ""),
                "entry": entry,
                "sl": sl,
                "target": target,
                "qty": qty,
                "score": score,
                "rsi": round(rsi, 2),
                "ema20": round(ema20, 2),
                "ema50": round(ema50, 2)
            })

        except Exception as e:
            print(f"❌ Error {stock}: {e}")
            continue

    # 🔥 SORT BEST FIRST
    results = sorted(results, key=lambda x: x["score"], reverse=True)

    return {
        "count": len(results),
        "data": results
    }