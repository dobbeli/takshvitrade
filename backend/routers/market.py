"""Market Router — /api/market"""
from fastapi import APIRouter
from scanner.engine import check_market_status
import asyncio
from concurrent.futures import ThreadPoolExecutor

router   = APIRouter()
executor = ThreadPoolExecutor(max_workers=2)

@router.get("/status")
async def market_status():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, check_market_status)

@router.get("/nifty")
async def nifty_price():
    status = await market_status()
    return {
        "price":   status.get("price"),
        "rsi":     status.get("rsi"),
        "verdict": status.get("verdict"),
        "bullish": status.get("bullish"),
    }
