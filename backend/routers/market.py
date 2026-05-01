"""Market Router — /api/market (FIXED for cloud deployment)"""
from fastapi import APIRouter
import requests
import pandas as pd

router = APIRouter()

@router.get("/status")
def market_status():
    return {"market": "OPEN", "message": "Market assumed open"}


@router.get("/nifty")
def nifty_price():
    """
    Uses direct Yahoo Finance API instead of yfinance library.
    yfinance fails on cloud servers (Render) — direct requests work.
    """
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5d&interval=1d"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        res = requests.get(url, headers=headers, timeout=10)

        if res.status_code != 200:
            # Try query2 as fallback
            url2 = "https://query2.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5d&interval=1d"
            res = requests.get(url2, headers=headers, timeout=10)

        if res.status_code != 200:
            return {
                "price": None, "prev": None, "change": None,
                "trend": "SIDEWAYS", "bullish": None, "verdict": "DATA UNAVAILABLE"
            }

        data   = res.json()
        result = data.get("chart", {}).get("result")

        if not result:
            return {
                "price": None, "prev": None, "change": None,
                "trend": "SIDEWAYS", "bullish": None, "verdict": "DATA UNAVAILABLE"
            }

        closes = result[0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]

        if len(closes) < 2:
            return {
                "price": None, "prev": None, "change": None,
                "trend": "SIDEWAYS", "bullish": None, "verdict": "DATA UNAVAILABLE"
            }

        latest     = round(closes[-1], 2)
        prev       = round(closes[-2], 2)
        change_pct = round(((latest - prev) / prev) * 100, 2)
        trend      = "UP" if latest > prev else "DOWN"

        return {
            "price":   latest,
            "prev":    prev,
            "change":  change_pct,
            "trend":   trend,
            "bullish": trend == "UP",
            "verdict": "BULLISH — market strength" if trend == "UP" else "BEARISH — market caution"
        }

    except Exception as e:
        return {
            "price": None, "prev": None, "change": None,
            "trend": "SIDEWAYS", "bullish": None,
            "verdict": "DATA UNAVAILABLE"
        }