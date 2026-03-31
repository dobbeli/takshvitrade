"""
TakshviTrade — Signals Router
/api/signals endpoints with capital-aware sizing
"""
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from scanner.engine  import run_full_scan, check_market_status, NIFTY50_STOCKS
from scanner.capital import calculate_capacity, size_trades_to_capital, get_capital_summary
from scanner.alerts  import send_whatsapp, format_signal_message, send_test_message

router = APIRouter()

class ScanRequest(BaseModel):
    capital:         float = 100000
    max_positions:   Optional[int] = None
    send_whatsapp:   bool = False
    whatsapp_number: Optional[str] = None

class AlertRequest(BaseModel):
    phone_number: str
    capital:      float

@router.get("/capacity")
def get_capacity(capital: float = Query(50000)):
    return calculate_capacity(capital)

@router.post("/scan")
def scan_signals(req: ScanRequest):
    if req.capital < 10000:
        raise HTTPException(400, "Minimum capital is Rs 10,000")
    market     = check_market_status()
    raw_trades = run_full_scan(capital=req.capital, risk_amount=req.capital * 0.01)
    sized      = size_trades_to_capital(raw_trades, req.capital, req.max_positions)
    summary    = get_capital_summary(sized, req.capital)
    summary["capacity"] = calculate_capacity(req.capital)
    alert_sent = False
    if req.send_whatsapp and sized:
        msg = format_signal_message(sized[:5], req.capital, market)
        alert_sent = send_whatsapp(msg)
    return {"market": market, "trades": sized, "summary": summary,
            "total_found": len(raw_trades), "alert_sent": alert_sent}

@router.get("/quick")
def quick_scan(capital: float = Query(50000)):
    market     = check_market_status()
    raw_trades = run_full_scan(capital=capital, risk_amount=capital * 0.01)
    sized      = size_trades_to_capital(raw_trades, capital)
    summary    = get_capital_summary(sized, capital)
    return {"market": market, "trades": sized[:5], "summary": summary, "capital": capital}

@router.post("/alert/test")
def test_alert(req: AlertRequest):
    number = req.phone_number
    if not number.startswith("+91"):
        number = "+91" + number.lstrip("0")
    success = send_test_message(f"whatsapp:{number}")
    if success:
        return {"success": True, "message": f"Test sent to {number}"}
    raise HTTPException(500, "WhatsApp failed — check .env credentials")

@router.post("/alert/send")
def send_alert(req: ScanRequest):
    req.send_whatsapp = True
    return scan_signals(req)
