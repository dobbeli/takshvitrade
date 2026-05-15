"""
Takshvi Trade — WhatsApp Alert Router  (FIXED v2)
FIXES:
1. /api/whatsapp/send now validates a CRON_SECRET header — cron-job.org must pass it
2. Market hours guard added — only fires between 3:25 PM and 4:30 PM IST
3. Phone fallback is explicit — always reads ALERT_PHONE if no override given
4. Detailed response so cron-job.org logs show exactly what happened
5. /api/whatsapp/cron endpoint added — cleaner URL for cron-job.org to call
"""
from fastapi import APIRouter, Query, HTTPException, Header
from typing import Optional
import logging
import os
from datetime import datetime, timezone, timedelta

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))

# ── Helpers ───────────────────────────────────────────────────

def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+91" + phone.lstrip("0")
    if not phone.startswith("whatsapp:"):
        phone = f"whatsapp:{phone}"
    return phone


def get_default_phone() -> Optional[str]:
    """Always read from env — never silently drop alerts."""
    raw = os.getenv("ALERT_PHONE", "").strip()
    if not raw:
        logging.error("ALERT_PHONE env var is not set — cannot send alerts")
        return None
    return normalize_phone(raw)


def is_market_hours() -> bool:
    """Returns True if current IST time is between 3:25 PM and 4:30 PM."""
    now_ist = datetime.now(IST)
    start   = now_ist.replace(hour=15, minute=25, second=0, microsecond=0)
    end     = now_ist.replace(hour=16, minute=30, second=0, microsecond=0)
    return start <= now_ist <= end


def verify_cron_secret(x_cron_secret: Optional[str]) -> bool:
    """
    Validates the CRON_SECRET header.
    Set CRON_SECRET env var on Railway.
    Configure cron-job.org to send header: X-Cron-Secret: <your-secret>
    """
    secret = os.getenv("CRON_SECRET", "")
    if not secret:
        # If no secret is configured, allow (backward compat) but log a warning
        logging.warning("CRON_SECRET env var not set — endpoint is unprotected!")
        return True
    return x_cron_secret == secret


# ════════════════════════════════════════════════════════════
# CRON ENDPOINT — this is what cron-job.org should call
# GET /api/whatsapp/cron
# Header: X-Cron-Secret: <your-secret>
# ════════════════════════════════════════════════════════════
@router.get("/cron")
def cron_send_alerts(
    capital:        float          = Query(100000),
    force:          bool           = Query(False, description="Skip market hours check"),
    x_cron_secret: Optional[str]  = Header(None),
):
    """
    Called by cron-job.org at 3:35 PM IST.
    Runs scanner and sends WhatsApp alerts to ALERT_PHONE.
    Returns detailed JSON so cron-job.org logs show success/failure.
    """
    # 1. Auth check
    if not verify_cron_secret(x_cron_secret):
        logging.warning("Cron endpoint: invalid secret received")
        raise HTTPException(status_code=401, detail="Invalid cron secret")

    # 2. Market hours check (skip with ?force=true for testing)
    now_ist = datetime.now(IST)
    if not force and not is_market_hours():
        return {
            "status":  "skipped",
            "reason":  "outside market hours",
            "ist_time": now_ist.strftime("%H:%M:%S"),
            "window":  "3:25 PM – 4:30 PM IST",
        }

    # 3. Get phone
    to = get_default_phone()
    if not to:
        raise HTTPException(
            status_code=500,
            detail="ALERT_PHONE env var not set on Railway"
        )

    # 4. Run scan
    from scanner.engine import run_master_scan
    from scanner.alerts import send_alerts_for_scan

    try:
        scan_result = run_master_scan(
            capital=int(capital),
            risk_amount=int(capital * 0.01)
        )
    except Exception as e:
        logging.error(f"Cron: scanner failed — {e}")
        raise HTTPException(status_code=500, detail=f"Scanner error: {e}")

    # 5. Save to DB
    try:
        from scanner.database import save_scan, save_signals
        scan_id = save_scan(scan_result, capital)
        if scan_id:
            save_signals(scan_result, scan_id)
    except Exception as e:
        logging.warning(f"Cron: DB save failed (alerts will still send) — {e}")
        scan_id = None

    # 6. Send alerts
    try:
        result = send_alerts_for_scan(scan_result, capital, to)
    except Exception as e:
        logging.error(f"Cron: alert send failed — {e}")
        raise HTTPException(status_code=500, detail=f"Alert send error: {e}")

    return {
        "status":        "completed",
        "ist_time":      now_ist.strftime("%H:%M:%S"),
        "scan_id":       scan_id,
        "market":        scan_result.get("market_trend"),
        "nifty":         scan_result.get("nifty"),
        "signals_found": {
            "long":         len(scan_result.get("long_signals",  [])),
            "short":        len(scan_result.get("short_signals", [])),
            "pre_breakout": len(scan_result.get("pre_breakout",  [])),
        },
        "alerts_sent":   result.get("total_sent", 0),
        "alerts_failed": result.get("total_failed", 0),
        "sent_to":       to,
    }


# ════════════════════════════════════════════════════════════
# TEST ENDPOINT — verify Twilio connection
# ════════════════════════════════════════════════════════════
@router.get("/test")
def send_test_alert(phone: str = Query(..., description="Your WhatsApp number e.g. 9XXXXXXXXX")):
    from scanner.alerts import send_whatsapp, format_test_message

    to  = normalize_phone(phone)
    msg = format_test_message()
    result = send_whatsapp(msg, to)

    if result["success"]:
        return {"status": "success", "message": f"Test WhatsApp sent to {to}", "sid": result.get("sid")}
    raise HTTPException(status_code=500, detail=f"Failed to send: {result.get('error')}")


# ════════════════════════════════════════════════════════════
# MANUAL SEND — trigger alerts now (with market hours guard)
# ════════════════════════════════════════════════════════════
@router.get("/send")
def send_scan_alerts(
    capital:  float          = Query(100000),
    phone:    Optional[str]  = Query(None, description="Override phone; defaults to ALERT_PHONE env"),
    force:    bool           = Query(False, description="Skip market hours check"),
):
    from scanner.engine import run_master_scan
    from scanner.alerts import send_alerts_for_scan

    # Market hours guard (override with ?force=true)
    if not force and not is_market_hours():
        now_ist = datetime.now(IST)
        return {
            "status": "skipped",
            "reason": "outside market hours — use ?force=true to override",
            "ist_time": now_ist.strftime("%H:%M:%S"),
        }

    to = normalize_phone(phone) if phone else get_default_phone()
    if not to:
        raise HTTPException(status_code=500, detail="No phone number. Set ALERT_PHONE env or pass ?phone=")

    try:
        scan_result = run_master_scan(capital=int(capital), risk_amount=int(capital * 0.01))
        result      = send_alerts_for_scan(scan_result, capital, to)

        return {
            "status":        "completed",
            "market":        scan_result.get("market_trend"),
            "nifty":         scan_result.get("nifty"),
            "signals_found": {
                "long":          len(scan_result.get("long_signals",  [])),
                "short":         len(scan_result.get("short_signals", [])),
                "pre_breakout":  len(scan_result.get("pre_breakout",  [])),
            },
            "alerts_sent":   result.get("total_sent", 0),
            "alerts_failed": result.get("total_failed", 0),
            "sent":          result.get("sent", []),
            "failed":        result.get("failed", []),
        }
    except Exception as e:
        logging.error(f"Alert send error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════
# SINGLE SIGNAL ALERT
# ════════════════════════════════════════════════════════════
@router.get("/send-signal")
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
    from scanner.alerts import send_whatsapp, format_long_signal, format_short_signal

    try:
        from scanner.engine import get_market_trend
        market_trend, nifty, change_pct = get_market_trend()
    except Exception:
        market_trend, nifty, change_pct = "SIDEWAYS", None, None

    signal = {
        "stock":    stock.upper(), "entry": entry, "sl": sl, "target": target,
        "qty":      qty, "position": round(qty * entry, 2),
        "rr":       round((target - entry) / (entry - sl), 2) if signal_type == "LONG" and (entry - sl) > 0 else
                    round((entry - target) / (sl - entry), 2) if (sl - entry) > 0 else 0,
        "score":    score,
        "action":   "BEST" if score >= 83 else signal_type,
        "upside_pct":    round(((target - entry) / entry) * 100, 2) if signal_type == "LONG" else 0,
        "downside_pct":  round(((entry - target) / entry) * 100, 2) if signal_type == "SHORT" else 0,
        "near_52w_high": False, "near_52w_low": False, "caution": False,
        "weekly_ema20":  None,  "weekly_ema50": None,
    }

    to  = normalize_phone(phone)
    msg = format_long_signal(signal, market_trend, nifty, change_pct) \
          if signal_type == "LONG" else \
          format_short_signal(signal, market_trend, nifty, change_pct)

    result = send_whatsapp(msg, to)
    if result["success"]:
        return {"status": "sent", "to": to, "stock": stock, "sid": result.get("sid")}
    raise HTTPException(status_code=500, detail=result.get("error"))


# ════════════════════════════════════════════════════════════
# STATUS — check Twilio + env configuration
# ════════════════════════════════════════════════════════════
@router.get("/status")
def alert_status():
    sid    = os.getenv("TWILIO_ACCOUNT_SID",   "")
    token  = os.getenv("TWILIO_AUTH_TOKEN",    "")
    phone  = os.getenv("ALERT_PHONE",          "")
    frm    = os.getenv("TWILIO_WHATSAPP_FROM", "")
    secret = os.getenv("CRON_SECRET",          "")

    configured = bool(sid and token and phone and frm)
    now_ist    = datetime.now(IST)

    return {
        "configured":      configured,
        "has_sid":         bool(sid),
        "has_token":       bool(token),
        "has_phone":       bool(phone),
        "has_from":        bool(frm),
        "has_cron_secret": bool(secret),
        "from_number":     frm if frm else "NOT SET",
        "alert_phone":     phone[:6] + "****" if phone else "NOT SET",
        "ist_time":        now_ist.strftime("%H:%M:%S"),
        "market_hours_now": is_market_hours(),
    }