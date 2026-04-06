"""
Takshvi Trade — FastAPI Backend
Domain: takshvitrade.com / takshvitrade.in
"""
"""
Takshvi Trade — FastAPI Backend
"""
import sys
import traceback

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
    print(f"❌ Router import failed: {e}")
    traceback.print_exc()
    sys.exit(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✅ Takshvi Trade API started")
    yield
    print("🛑 Takshvi Trade API stopped")

app = FastAPI(
    title="Takshvi Trade API",
    description="NSE Swing Signal Intelligence Platform",
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

app.include_router(auth.router,    prefix="/api/auth",    tags=["Auth"])
app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])
app.include_router(market.router,  prefix="/api/market",  tags=["Market"])
app.include_router(news.router,    prefix="/api/news",    tags=["News"])

@app.get("/")
def root():
    return {"status": "ok", "platform": "Takshvi Trade", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}
# ===============================
# 🔥 TEMP SCANNER (STABLE VERSION)
# ===============================

from pydantic import BaseModel
import yfinance as yf
import pandas as pd
import ta

class ScanRequest(BaseModel):
    capital: int


def quick_scan(capital):
    stocks = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]
    results = []

    for stock in stocks:
        try:
            print(f"🔍 Scanning {stock}")

            df = yf.download(stock, period="3mo", interval="1d", progress=False)

            if df is None or df.empty:
                print(f"❌ No data: {stock}")
                continue

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
                continue

            entry = round(latest["Close"] * 1.002, 2)
            sl = round(latest["Low"], 2)
            risk = entry - sl

            if risk <= 0:
                continue

            qty = int((capital * 0.01) / risk)
            target = round(entry + (risk * 2), 2)

            results.append({
                "stock": stock.replace(".NS", ""),
                "entry": entry,
                "sl": sl,
                "target": target,
                "qty": qty,
                "score": score
            })

        except Exception as e:
            print(f"❌ Error {stock}: {e}")

    return results


@app.post("/run-scan")
def run_scan(req: ScanRequest):
    print("🚀 Running scanner...")
    data = quick_scan(req.capital)

    return {
        "count": len(data),
        "data": data
    }


# ===============================
# 📊 MARKET API (FIX NIFTY ISSUE)
# ===============================

@app.get("/market")
def market_status():
    try:
        df = yf.download("^NSEI", period="5d", interval="1d", progress=False)

        if df is None or df.empty:
            return {"price": 0, "trend": "NA"}

        price = round(df["Close"].iloc[-1], 2)
        prev = df["Close"].iloc[-2]

        return {
            "price": price,
            "trend": "UP" if price > prev else "DOWN"
        }

    except Exception as e:
        print(f"❌ Market error: {e}")
        return {"price": 0, "trend": "NA"}