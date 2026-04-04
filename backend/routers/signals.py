"""
TakshviTrade — Signals Router
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Any
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from scanner.engine  import run_full_scan, check_market_status, NIFTY50_STOCKS
from scanner.capital import calculate_capacity, size_trades_to_capital, get_capital_summary
from scanner.alerts  import send_whatsapp, format_signal_message, send_test_message

router = APIRouter()

@router.get("/capacity")
def get_capacity(capital: float = Query(50000)):
    return calculate_capacity(capital)

@router.get("/quick")
def quick_scan(capital: float = Query(50000)):
    market     = check_market_status()
    raw_trades = run_full_scan(capital=capital, risk_amount=capital * 0.01)
    sized      = size_trades_to_capital(raw_trades, capital)
    summary    = get_capital_summary(sized, capital)
    return {"market": market, "trades": sized[:5], "summary": summary, "capital": capital}

@router.post("/scan")
def scan_signals(
    capital: float = Query(50000),
    send_alert: bool = Query(False),
    phone: Optional[str] = Query(None)
):
    if capital < 10000:
        raise HTTPException(400, "Minimum capital is Rs 10,000")
    market     = check_market_status()
    raw_trades = run_full_scan(capital=capital, risk_amount=capital * 0.01)
    sized      = size_trades_to_capital(raw_trades, capital, None)
    summary    = get_capital_summary(sized, capital)
    summary["capacity"] = calculate_capacity(capital)
    alert_sent = False
    if send_alert and sized:
        msg = format_signal_message(sized[:5], capital, market)
        alert_sent = send_whatsapp(msg)
    return {"market": market, "trades": sized, "summary": summary,
            "total_found": len(raw_trades), "alert_sent": alert_sent}

@router.post("/alert/test")
def test_alert(
    phone_number: str = Query(...),
    capital: float = Query(50000)
):
    number = phone_number
    if not number.startswith("+91"):
        number = "+91" + number.lstrip("0")
    success = send_test_message(f"whatsapp:{number}")
    if success:
        return {"success": True, "message": f"Test sent to {number}"}
    raise HTTPException(500, "WhatsApp failed — check credentials")
