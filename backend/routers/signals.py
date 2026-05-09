"""
TakshviTrade — Signals Router (FIXED)
Removed broken imports of format_signal_message, send_test_message
These functions are now in scanner.alerts with different names
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

router = APIRouter()

@router.get("/quick")
def quick_scan(capital: float = Query(50000)):
    from scanner.engine import run_master_scan
    result = run_master_scan(capital=int(capital), risk_amount=int(capital * 0.01))
    return {
        "market": result.get("market_trend"),
        "trades": result.get("long_signals", [])[:5],
        "capital": capital
    }

@router.post("/scan")
def scan_signals(
    capital: float = Query(50000),
    send_alert: bool = Query(False),
    phone: Optional[str] = Query(None)
):
    if capital < 10000:
        raise HTTPException(400, "Minimum capital is Rs 10,000")

    from scanner.engine import run_master_scan
    result = run_master_scan(capital=int(capital), risk_amount=int(capital * 0.01))

    alert_sent = False
    if send_alert and phone:
        from scanner.alerts import send_alerts_for_scan
        to = f"whatsapp:+91{phone}" if not phone.startswith("+") else f"whatsapp:{phone}"
        alert_result = send_alerts_for_scan(result, capital, to)
        alert_sent = alert_result["total_sent"] > 0

    return {
        "market":       result.get("market_trend"),
        "long_signals": result.get("long_signals", []),
        "short_signals":result.get("short_signals", []),
        "pre_breakout": result.get("pre_breakout", []),
        "alert_sent":   alert_sent
    }
