"""
Takshvi Trade — FastAPI Backend
"""
import logging

logging.basicConfig(level=logging.INFO)

# ===============================
# IMPORTS
# ===============================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Routers
from routers import signals
from routers import market
from routers import news
# from routers import auth   # 🔥 keep this commented for now

# Engine
from scanner.engine import run_full_scan

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

# CORS (ONLY ONCE)
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

#app.include_router(auth.router, prefix="/api/auth")
app.include_router(signals.router, prefix="/api/signals")
app.include_router(market.router, prefix="/api/market")
app.include_router(news.router, prefix="/api/news")

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
# 📊 MARKET API
# ===============================

@app.get("/market")
def market_status():
    import requests

    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI"
        headers = {"User-Agent": "Mozilla/5.0"}

        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()

        result = data["chart"]["result"][0]
        close_prices = result["indicators"]["quote"][0]["close"]

        if not close_prices or len(close_prices) < 2:
            return {"price": 0, "trend": "DOWN", "data": []}

        price = round(close_prices[-1], 2)
        prev = close_prices[-2]

        trend = "UP" if price > prev else "DOWN"

        return {
            "price": price,
            "trend": trend,
            "data": []  # clean response
        }

    except Exception as e:
        print(f"❌ Market error: {e}")
        return {"price": 0, "trend": "DOWN", "data": []}

# ===============================
# 📊 CHART API
# ===============================

@app.get("/chart")
def get_chart(symbol: str = "INFY.NS"):
    import requests

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=3mo&interval=1d"
        headers = {"User-Agent": "Mozilla/5.0"}

        res = requests.get(url, headers=headers)
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
        print(f"❌ Chart error: {e}")
        return {"data": []}

# ===============================
# 🔥 SCANNER API (ENGINE BASED)
# ===============================

@app.get("/run-scan")
def run_scan(capital: int = 50000):
    try:
        results = run_full_scan(capital=capital)

        return {
            "count": len(results),
            "data": results
        }

    except Exception as e:
        print(f"❌ Scan error: {e}")
        return {
            "count": 0,
            "data": []
        }