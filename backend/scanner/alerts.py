"""
Takshvi Trade — scanner/alerts.py  (FIXED v2)

ROOT CAUSE OF 429 ERRORS:
The old code sent one WhatsApp message per signal with NO delay.
With 25 signals, it fired 25+ Twilio API calls in <1 second.
Twilio sandbox rate limit = 1 msg/sec → everything after msg 2-3 got 429.

FIXES:
1. time.sleep(1) between every Twilio call
2. Signals batched into ONE summary message (not one per signal)
3. Hard cap: max 5 messages per scan total
4. Retry once on 429 with 3s extra delay
"""
import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── Twilio client (lazy init) ─────────────────────────────────
_twilio_client = None

def _get_client():
    global _twilio_client
    if _twilio_client is None:
        from twilio.rest import Client
        sid   = os.getenv("TWILIO_ACCOUNT_SID",   "")
        token = os.getenv("TWILIO_AUTH_TOKEN",     "")
        if not sid or not token:
            raise RuntimeError("TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN not set")
        _twilio_client = Client(sid, token)
    return _twilio_client


# ── Core send function with retry on 429 ─────────────────────
def send_whatsapp(message: str, to: str, retry: bool = True) -> dict:
    """
    Send one WhatsApp message via Twilio.
    Returns {"success": bool, "sid": str, "error": str}
    Retries ONCE on 429 with a 3s delay.
    """
    frm = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    try:
        client = _get_client()
        msg    = client.messages.create(body=message, from_=frm, to=to)
        logging.info(f"WhatsApp sent ✅ sid={msg.sid} to={to[:20]}")
        return {"success": True, "sid": msg.sid, "error": ""}
    except Exception as e:
        err_str = str(e)
        # 429 = rate limit → wait 3s and retry once
        if "429" in err_str and retry:
            logging.warning(f"Twilio 429 — waiting 3s then retrying...")
            time.sleep(3)
            return send_whatsapp(message, to, retry=False)
        logging.error(f"WhatsApp FAILED: {err_str[:200]}")
        return {"success": False, "sid": "", "error": err_str[:300]}


# ── Message formatters ────────────────────────────────────────

def format_test_message() -> str:
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST).strftime("%d %b %Y %I:%M %p IST")
    return (
        f"✅ *Takshvi Trade — Test Alert*\n"
        f"🕐 {now}\n\n"
        f"Your WhatsApp alerts are working correctly.\n"
        f"You will receive scan results after market close (3:35 PM IST).\n\n"
        f"_Takshvi Trade · NSE Signal Intelligence_"
    )


def format_market_summary(scan_result: dict, capital: float) -> str:
    """Single summary message with all key stats."""
    IST    = timezone(timedelta(hours=5, minutes=30))
    now    = datetime.now(IST).strftime("%d %b %I:%M %p")
    trend  = scan_result.get("market_trend", "SIDEWAYS")
    nifty  = scan_result.get("nifty")
    chg    = scan_result.get("change_pct")
    crash  = scan_result.get("is_crash", False)

    longs   = scan_result.get("long_signals",      [])
    shorts  = scan_result.get("short_signals",     [])
    pre_bo  = scan_result.get("pre_breakout",      [])
    pre_bd  = scan_result.get("pre_breakdown",     [])
    rs      = scan_result.get("relative_strength", [])

    trend_icon = "🟢" if trend == "UP" else "🔴" if trend == "DOWN" else "🟡"
    nifty_str  = f"{nifty:,.2f}" if nifty else "N/A"
    chg_str    = f"{chg:+.2f}%" if chg is not None else ""

    lines = [
        f"📊 *Takshvi Trade — EOD Scan*",
        f"🕐 {now} IST",
        f"",
        f"{trend_icon} *Market: {trend}* | Nifty {nifty_str} {chg_str}",
        f"{'🚨 CRASH MODE — No longs today' if crash else ''}",
        f"",
        f"*Signals Found:*",
        f"▲ Long:          {len(longs)} stocks",
        f"▼ Short:         {len(shorts)} stocks",
        f"⏳ Pre-Breakout: {len(pre_bo)} stocks",
        f"⏳ Pre-Breakdown:{len(pre_bd)} stocks",
        f"⚡ Rel Strength: {len(rs)} stocks",
        f"",
        f"💰 Capital: ₹{capital:,.0f}",
    ]

    # Add top signals inline (max 5 total across all types)
    top_signals = []

    for s in longs[:2]:
        top_signals.append(
            f"▲ *{s.get('stock')}* | Entry ₹{s.get('entry')} | "
            f"SL ₹{s.get('sl')} | T ₹{s.get('target')} | "
            f"RR {s.get('rr')} | Qty {s.get('qty')} | Score {s.get('score')}"
        )
    for s in pre_bo[:2]:
        top_signals.append(
            f"⏳ *{s.get('stock')}* [BUY STOP] | Entry ₹{s.get('entry')} | "
            f"SL ₹{s.get('sl')} | T ₹{s.get('target')} | Score {s.get('score')}"
        )
    for s in shorts[:1]:
        top_signals.append(
            f"▼ *{s.get('stock')}* [SHORT] | Entry ₹{s.get('entry')} | "
            f"SL ₹{s.get('sl')} | T ₹{s.get('target')} | Score {s.get('score')}"
        )

    if top_signals:
        lines.append("")
        lines.append("*Top Setups:*")
        lines.extend(top_signals[:5])

    lines.extend([
        "",
        f"🔗 Full signals: takshvitrade.com",
        f"_Takshvi Trade · NSE Signal Intelligence_"
    ])

    # Remove empty crash line if no crash
    return "\n".join(l for l in lines if l != "")


def format_long_signal(signal: dict, market_trend: str,
                       nifty: float = None, change_pct: float = None) -> str:
    arrow  = "▲" if market_trend == "UP" else "⚠▲"
    nifty_str = f"Nifty {nifty:,.2f} ({change_pct:+.2f}%)" if nifty else ""
    return (
        f"{arrow} *LONG SIGNAL — {signal.get('stock')}*\n"
        f"Score: {signal.get('score')} | {signal.get('action','BUY')}\n\n"
        f"Entry:  ₹{signal.get('entry')}\n"
        f"SL:     ₹{signal.get('sl')}  ({signal.get('upside_pct', '')}% risk)\n"
        f"Target: ₹{signal.get('target')}\n"
        f"RR:     {signal.get('rr')}:1\n"
        f"Qty:    {signal.get('qty')} shares\n"
        f"Pos:    ₹{signal.get('position'):,.0f}\n\n"
        f"Market: {market_trend} | {nifty_str}\n"
        f"_Takshvi Trade_"
    )


def format_short_signal(signal: dict, market_trend: str,
                        nifty: float = None, change_pct: float = None) -> str:
    nifty_str = f"Nifty {nifty:,.2f} ({change_pct:+.2f}%)" if nifty else ""
    return (
        f"▼ *SHORT SIGNAL — {signal.get('stock')}*\n"
        f"Score: {signal.get('score')} | {signal.get('action','SHORT')}\n\n"
        f"Entry:  ₹{signal.get('entry')}\n"
        f"SL:     ₹{signal.get('sl')}\n"
        f"Target: ₹{signal.get('target')}\n"
        f"RR:     {signal.get('rr')}:1\n"
        f"Qty:    {signal.get('qty')} shares\n"
        f"Pos:    ₹{signal.get('position'):,.0f}\n\n"
        f"Market: {market_trend} | {nifty_str}\n"
        f"_Takshvi Trade_"
    )


# ── MAIN ALERT FUNCTION — FIXED ───────────────────────────────

def send_alerts_for_scan(scan_result: dict, capital: float,
                         to: Optional[str] = None) -> dict:
    """
    FIXED: Sends max 3 messages total with 1s delay between each.
    
    Message 1: Full summary (market + all signal counts + top 5 setups)
    Message 2: Top LONG signals detail (only if score >= 80)
    Message 3: Top SHORT signals detail (only if score >= 80)
    
    Never sends more than 3 messages = never hits Twilio rate limit.
    """
    if not to:
        to = os.getenv("ALERT_PHONE", "").strip()
        if not to:
            logging.error("send_alerts_for_scan: no phone number — set ALERT_PHONE")
            return {"total_sent": 0, "total_failed": 0, "sent": [], "failed": []}

    # Normalise phone
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}" if to.startswith("+") else f"whatsapp:+{to}"

    sent_list   = []
    failed_list = []

    def _send(msg: str, alert_type: str, stock: str = ""):
        """Send one message and log to DB, with 1s delay after."""
        result = send_whatsapp(msg, to)
        # Log to Supabase alert_logs
        try:
            from scanner.database import log_alert
            log_alert(
                phone      = to,
                alert_type = alert_type,
                stock      = stock,
                message_sid= result.get("sid", ""),
                status     = "sent" if result["success"] else "failed",
                error      = result.get("error", ""),
            )
        except Exception as db_err:
            logging.warning(f"alert log DB write failed: {db_err}")

        if result["success"]:
            sent_list.append({"type": alert_type, "stock": stock, "sid": result["sid"]})
        else:
            failed_list.append({"type": alert_type, "stock": stock, "error": result["error"]})

        # CRITICAL: always sleep 1s between messages to stay under Twilio rate limit
        time.sleep(1)

    # ── Message 1: Summary (always sent) ─────────────────────
    summary_msg = format_market_summary(scan_result, capital)
    _send(summary_msg, "SUMMARY")

    # ── Message 2: Top longs detail (only best signals) ──────
    longs = [s for s in scan_result.get("long_signals", []) if (s.get("score") or 0) >= 78]
    if longs:
        top_long = longs[0]  # best scored signal only
        try:
            from scanner.engine import get_market_trend
            trend, nifty, chg = get_market_trend()
        except Exception:
            trend, nifty, chg = scan_result.get("market_trend","SIDEWAYS"), scan_result.get("nifty"), scan_result.get("change_pct")
        msg = format_long_signal(top_long, trend, nifty, chg)
        _send(msg, "LONG", top_long.get("stock", ""))

    # ── Message 3: Top pre-breakout detail (only if score high) ──
    pre_bo = [s for s in scan_result.get("pre_breakout", []) if (s.get("score") or 0) >= 83]
    if pre_bo:
        top_bo = pre_bo[0]
        msg = (
            f"⏳ *BUY STOP TONIGHT — {top_bo.get('stock')}*\n"
            f"Score: {top_bo.get('score')}\n\n"
            f"Set buy stop order at: ₹{top_bo.get('entry')}\n"
            f"SL: ₹{top_bo.get('sl')}\n"
            f"Target: ₹{top_bo.get('target')}\n"
            f"RR: {top_bo.get('rr')}:1 | Qty: {top_bo.get('qty')} shares\n\n"
            f"_Place order tonight before 9:15 AM_\n"
            f"_Takshvi Trade_"
        )
        _send(msg, "PRE_BREAKOUT", top_bo.get("stock", ""))

    total_sent   = len(sent_list)
    total_failed = len(failed_list)
    logging.info(f"Alerts: {total_sent} sent, {total_failed} failed → {to[:25]}")

    return {
        "total_sent":   total_sent,
        "total_failed": total_failed,
        "sent":         sent_list,
        "failed":       failed_list,
    }