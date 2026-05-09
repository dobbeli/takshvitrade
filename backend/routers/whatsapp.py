"""
Takshvi Trade — WhatsApp Alert Router
Endpoints for sending and managing WhatsApp alerts
"""
from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from typing import Optional
import logging

router = APIRouter()


# ── Helper: normalise phone number ────────────────────────────
def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+91" + phone.lstrip("0")
    if not phone.startswith("whatsapp:"):
        phone = f"whatsapp:{phone}"
    return phone


# ════════════════════════════════════════════════════════════
# TEST ENDPOINT — verify Twilio connection
# ════════════════════════════════════════════════════════════
@router.get("/test")
def send_test_alert(phone: str = Query(..., description="Your WhatsApp number e.g. 9XXXXXXXXX")):
    """
    Sends a test WhatsApp message to verify Twilio is connected.
    Use this before running the full scanner.
    """
    from scanner.alerts import send_whatsapp, format_test_message

    to = normalize_phone(phone)
    msg = format_test_message()
    result = send_whatsapp(msg, to)

    if result["success"]:
        return {
            "status":  "success",
            "message": f"Test WhatsApp sent to {to}",
            "sid":     result.get("sid")
        }
    raise HTTPException(
        status_code=500,
        detail=f"Failed to send: {result.get('error')}"
    )


# ════════════════════════════════════════════════════════════
# MANUAL ALERT — trigger alerts for latest scan
# ════════════════════════════════════════════════════════════
@router.post("/send")
def send_scan_alerts(
    capital:    float = Query(100000),
    phone:      Optional[str] = Query(None, description="Override phone number"),
    background: BackgroundTasks = None
):
    """
    Runs master scan and sends WhatsApp alerts.
    Sends: market summary + individual signal messages.
    """
    from scanner.engine import run_master_scan
    from scanner.alerts import send_alerts_for_scan

    try:
        # Run scan
        scan_result = run_master_scan(
            capital=int(capital),
            risk_amount=int(capital * 0.01)
        )

        to = normalize_phone(phone) if phone else None

        # Send alerts
        result = send_alerts_for_scan(scan_result, capital, to)

        return {
            "status":        "completed",
            "market":        scan_result.get("market_trend"),
            "nifty":         scan_result.get("nifty"),
            "signals_found": {
                "long":          len(scan_result.get("long_signals", [])),
                "short":         len(scan_result.get("short_signals", [])),
                "pre_breakout":  len(scan_result.get("pre_breakout", [])),
            },
            "alerts_sent":   result["total_sent"],
            "alerts_failed": result["total_failed"],
            "sent":          result["sent"],
            "failed":        result["failed"],
        }

    except Exception as e:
        logging.error(f"Alert send error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════
# SINGLE SIGNAL ALERT — send alert for one specific stock
# ════════════════════════════════════════════════════════════
@router.post("/send-signal")
def send_single_signal_alert(
    phone:       str   = Query(...),
    stock:       str   = Query(...),
    entry:       float = Query(...),
    sl:          float = Query(...),
    target:      float = Query(...),
    qty:         int   = Query(...),
    signal_type: str   = Query("LONG"),
    score:       int   = Query(75),
):
    """
    Sends a WhatsApp alert for a single signal.
    Called when user clicks "Send Alert" on a specific signal row.
    """
    from scanner.alerts import (send_whatsapp, format_long_signal,
                                 format_short_signal, get_market_trend)

    try:
        from scanner.engine import get_market_trend
        market_trend, nifty, change_pct = get_market_trend()
    except:
        market_trend, nifty, change_pct = "SIDEWAYS", None, None

    signal = {
        "stock":    stock.upper(),
        "entry":    entry,
        "sl":       sl,
        "target":   target,
        "qty":      qty,
        "position": round(qty * entry, 2),
        "rr":       round((target - entry) / (entry - sl), 2) if signal_type == "LONG" else round((entry - target) / (sl - entry), 2),
        "score":    score,
        "action":   "BEST" if score >= 83 else ("BEST SHORT" if signal_type == "SHORT" and score >= 83 else signal_type),
        "upside_pct":   round(((target - entry) / entry) * 100, 2) if signal_type == "LONG" else 0,
        "downside_pct": round(((entry - target) / entry) * 100, 2) if signal_type == "SHORT" else 0,
        "near_52w_high": False,
        "near_52w_low":  False,
        "caution":  False,
        "weekly_ema20": None,
        "weekly_ema50": None,
    }

    to  = normalize_phone(phone)
    msg = format_long_signal(signal, market_trend, nifty, change_pct) \
          if signal_type == "LONG" \
          else format_short_signal(signal, market_trend, nifty, change_pct)

    result = send_whatsapp(msg, to)

    if result["success"]:
        return {"status": "sent", "to": to, "stock": stock, "sid": result.get("sid")}
    raise HTTPException(status_code=500, detail=result.get("error"))


# ════════════════════════════════════════════════════════════
# STATUS — check Twilio configuration
# ════════════════════════════════════════════════════════════
@router.get("/status")
def alert_status():
    """Check if Twilio credentials are configured."""
    import os
    sid   = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    phone = os.getenv("ALERT_PHONE", "")
    frm   = os.getenv("TWILIO_WHATSAPP_FROM", "")

    configured = bool(sid and token and phone and frm)

    return {
        "configured":    configured,
        "has_sid":       bool(sid),
        "has_token":     bool(token),
        "has_phone":     bool(phone),
        "has_from":      bool(frm),
        "from_number":   frm if frm else "NOT SET",
        "alert_phone":   phone[:10] + "****" if phone else "NOT SET",
    }
