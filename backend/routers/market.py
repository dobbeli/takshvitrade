"""Market Router — /api/market  (FIXED — returns real Nifty data)"""
from fastapi import APIRouter
import yfinance as yf
import logging

router = APIRouter()

@router.get("/status")
def market_status():
    return {"market": "OPEN", "message": "Market assumed open"}


@router.get("/nifty")
def nifty_price():
    """
    Returns real Nifty50 price + trend from Yahoo Finance.
    FIX: was returning null placeholder — now returns real data
    used by index.html loadMarket() to populate the hero badge.
    """
    try:
        nifty = yf.download("^NSEI", period="5d", interval="1d", progress=False)

        if nifty is None or len(nifty) < 2:
            return {
                "price": None,
                "prev": None,
                "change": None,
                "trend": "SIDEWAYS",
                "bullish": None,
                "verdict": "DATA UNAVAILABLE"
            }

        latest = float(nifty["Close"].iloc[-1])
        prev   = float(nifty["Close"].iloc[-2])
        change = round(((latest - prev) / prev) * 100, 2)
        trend  = "UP" if latest > prev else "DOWN"

        return {
            "price":   round(latest, 2),
            "prev":    round(prev, 2),
            "change":  change,
            "trend":   trend,
            "bullish": trend == "UP",
            "verdict": "BULLISH — market strength" if trend == "UP" else "BEARISH — market caution"
        }

    except Exception as e:
        logging.error(f"Nifty fetch error: {e}")
        return {
            "price": None,
            "prev": None,
            "change": None,
            "trend": "SIDEWAYS",
            "bullish": None,
            "verdict": "DATA ERROR"
        }
