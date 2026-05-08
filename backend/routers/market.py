"""Market Router — /api/market"""
from fastapi import APIRouter
import requests
import logging

router = APIRouter()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

@router.get("/status")
def market_status():
    return {"market": "OPEN", "message": "Market assumed open"}


@router.get("/nifty")
def nifty_price():
    """
    Returns Nifty50 price, prev close, point change, % change.
    Uses direct requests (not yfinance) — works reliably on Render cloud.
    Returns prev so frontend can calculate exact point change.
    """
    try:
        for base in ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]:
            try:
                res = requests.get(
                    f"{base}/v8/finance/chart/%5ENSEI?range=5d&interval=1d",
                    headers=HEADERS, timeout=10
                )
                if res.status_code == 200:
                    break
            except:
                continue

        if res.status_code != 200:
            return {"price": None, "prev": None, "change": None,
                    "trend": "SIDEWAYS", "bullish": None, "verdict": "DATA UNAVAILABLE"}

        closes = [c for c in res.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
        if len(closes) < 2:
            return {"price": None, "prev": None, "change": None,
                    "trend": "SIDEWAYS", "bullish": None, "verdict": "DATA UNAVAILABLE"}

        latest = round(closes[-1], 2)
        prev   = round(closes[-2], 2)
        change = round(((latest - prev) / prev) * 100, 2)
        trend  = "UP" if latest > prev else "DOWN"

        return {
            "price":   latest,
            "prev":    prev,
            "change":  change,
            "trend":   trend,
            "bullish": trend == "UP",
            "verdict": "BULLISH — market strength" if trend == "UP" else "BEARISH — market caution"
        }

    except Exception as e:
        logging.error(f"Nifty fetch error: {e}")
        return {"price": None, "prev": None, "change": None,
                "trend": "SIDEWAYS", "bullish": None, "verdict": "DATA ERROR"}