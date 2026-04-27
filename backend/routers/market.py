"""Market Router — /api/market"""
from fastapi import APIRouter

router = APIRouter()


# 🔹 BASIC MARKET STATUS (TEMP STABLE VERSION)
@router.get("/status")
def market_status():
    return {
        "market": "OPEN",
        "message": "Market assumed open (no live check yet)"
    }


# 🔹 NIFTY PLACEHOLDER (WILL UPGRADE LATER)
@router.get("/nifty")
def nifty_price():
    return {
        "price": None,
        "rsi": None,
        "verdict": "N/A",
        "bullish": None,
        "note": "Nifty data not connected yet"
    }