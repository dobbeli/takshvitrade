"""
Takshvi Trade — WhatsApp Alert System
Uses Twilio WhatsApp API to send trading signals

Setup required:
1. Create Twilio account at twilio.com
2. Get Account SID, Auth Token from Twilio Console
3. Enable WhatsApp Sandbox or Business API
4. Add these to Render environment variables:
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your_auth_token
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886  (Twilio sandbox number)
   ALERT_PHONE=whatsapp:+91XXXXXXXXXX          (your WhatsApp number)
"""

import os
import logging
from datetime import datetime
from typing import Optional

# ── Twilio client ──────────────────────────────────────────────
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    logging.warning("twilio not installed — run: pip install twilio")

TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
FROM_NUMBER  = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
TO_NUMBER    = os.getenv("ALERT_PHONE", "")   # whatsapp:+91XXXXXXXXXX


# ════════════════════════════════════════════════════════════
# MESSAGE FORMATTERS
# ════════════════════════════════════════════════════════════

def format_long_signal(signal: dict, market_trend: str, nifty: float,
                        change_pct: float) -> str:
    """
    Formats a LONG signal WhatsApp message with all required fields.

    Example output:
    ╔══════════════════════════════╗
    🔥 TAKSHVI TRADE — BUY SIGNAL
    ╚══════════════════════════════╝
    📈 Stock: APOLLOHOSP
    ...
    """
    now      = datetime.now().strftime("%d %b %Y, %I:%M %p IST")
    stock    = signal.get("stock", "")
    entry    = signal.get("entry", 0)
    sl       = signal.get("sl", 0)
    target   = signal.get("target", 0)
    qty      = signal.get("qty", 0)
    position = signal.get("position", 0)
    rr       = signal.get("rr", 2.0)
    score    = signal.get("score", 0)
    action   = signal.get("action", "BUY")
    upside   = signal.get("upside_pct", 0)
    near_52w = signal.get("near_52w_high", False)
    w_ema20  = signal.get("weekly_ema20", None)
    w_ema50  = signal.get("weekly_ema50", None)

    # Risk calculation
    risk_per_share  = round(entry - sl, 2)
    reward_per_share= round(target - entry, 2)
    total_risk      = round(risk_per_share * qty, 2)
    total_reward    = round(reward_per_share * qty, 2)

    # EMA trend confirmation
    weekly_status = "✅ Weekly EMA20 > EMA50 (Bullish)" if (
        w_ema20 and w_ema50 and w_ema20 > w_ema50
    ) else "📊 Weekly data not available"

    # Volume confirmation
    vol_status = "✅ Volume above 1.2× 10-day average" if score >= 70 else "📊 Check volume on chart"

    # Entry status
    entry_status = "🟢 ACTIVE — Entry above previous high"
    if signal.get("caution"):
        entry_status = "⚠️ CAUTION — Bearish market, 50% position size"

    # 52W high
    high_52w_txt = "★ Near 52-Week High (strong trend)" if near_52w else ""

    # Market context
    nifty_fmt  = f"{nifty:,.2f}" if nifty else "--"
    chg_arrow  = "▲" if market_trend == "UP" else "▼"
    chg_color  = "🟢" if market_trend == "UP" else "🔴"
    mkt_status = f"{chg_color} {market_trend} {chg_arrow} {abs(change_pct):.2f}% today" if change_pct else f"{chg_color} {market_trend}"

    action_emoji = "🔥" if "BEST" in action else "📈"

    msg = f"""╔══════════════════════════════╗
{action_emoji} *TAKSHVI TRADE — {"BEST SIGNAL" if "BEST" in action else "BUY SIGNAL"}*
╚══════════════════════════════╝

📊 *{stock}* {'★ 52W High' if near_52w else ''}
🕐 {now}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 *TRADE LEVELS*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟡 Buy Trigger:  ₹{entry:,.2f}
🔴 Stop Loss:    ₹{sl:,.2f}
🟢 Target:       ₹{target:,.2f}
📦 Quantity:     {qty} {'share' if qty == 1 else 'shares'}
💰 Position:     ₹{position:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 *RISK — REWARD*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  Risk/share:  ₹{risk_per_share:,.2f}
✅ Reward/share: ₹{reward_per_share:,.2f}
📐 R:R Ratio:    1:{rr}
📉 Total Risk:   ₹{total_risk:,.2f}
📈 Total Reward: ₹{total_reward:,.2f}
🚀 Upside:       +{upside}%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 *CONFIRMATIONS*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📉 EMA Trend:    ✅ EMA20 > EMA50 > EMA200
📅 Weekly EMA:   {weekly_status}
📊 Volume:       {vol_status}
🏆 Signal Score: {score}/100
{'🏔️  52W High:    ' + high_52w_txt if near_52w else ''}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚦 *STATUS*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📥 Entry Status: {entry_status}
📤 Exit Status:  🔴 Exit if price closes below ₹{sl:,.2f}
🎯 Profit Exit:  🟢 Book at ₹{target:,.2f} (+{upside}%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌍 *MARKET CONTEXT*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Nifty50:      ₹{nifty_fmt}
📈 Market:       {mkt_status}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ *DISCLAIMER*
Signals are for educational purposes only.
Not investment advice. Trade at your own risk.
Takshvi Trade is not SEBI registered (RA pending).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📱 takshvitrade.com"""

    return msg.strip()


def format_short_signal(signal: dict, market_trend: str, nifty: float,
                         change_pct: float) -> str:
    """Formats a SHORT signal WhatsApp message."""
    now      = datetime.now().strftime("%d %b %Y, %I:%M %p IST")
    stock    = signal.get("stock", "")
    entry    = signal.get("entry", 0)
    sl       = signal.get("sl", 0)
    target   = signal.get("target", 0)
    qty      = signal.get("qty", 0)
    position = signal.get("position", 0)
    rr       = signal.get("rr", 2.0)
    score    = signal.get("score", 0)
    action   = signal.get("action", "SHORT")
    downside = signal.get("downside_pct", 0)
    near_52w_low = signal.get("near_52w_low", False)
    w_ema20  = signal.get("weekly_ema20", None)
    w_ema50  = signal.get("weekly_ema50", None)
    caution  = signal.get("caution", False)

    risk_per_share   = round(sl - entry, 2)
    reward_per_share = round(entry - target, 2)
    total_risk       = round(risk_per_share * qty, 2)
    total_reward     = round(reward_per_share * qty, 2)

    weekly_status = "✅ Weekly EMA20 < EMA50 (Bearish)" if (
        w_ema20 and w_ema50 and w_ema20 < w_ema50
    ) else "📊 Weekly data not available"

    nifty_fmt = f"{nifty:,.2f}" if nifty else "--"
    chg_arrow = "▲" if market_trend == "UP" else "▼"
    chg_color = "🟢" if market_trend == "UP" else "🔴"
    mkt_status = f"{chg_color} {market_trend} {chg_arrow} {abs(change_pct):.2f}% today" if change_pct else f"{chg_color} {market_trend}"

    counter_trend_note = "\n⚠️ COUNTER-TREND — Market is UP. High risk short." if caution else ""

    msg = f"""╔══════════════════════════════╗
📉 *TAKSHVI TRADE — {"BEST SHORT" if "BEST" in action else "SHORT SIGNAL"}*
╚══════════════════════════════╝

📊 *{stock}* {'↓ Near 52W Low' if near_52w_low else ''}{counter_trend_note}
🕐 {now}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📉 *TRADE LEVELS*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟡 Sell Trigger: ₹{entry:,.2f}
🔴 Stop Loss:    ₹{sl:,.2f}  ← Exit if price RISES here
🟢 Target:       ₹{target:,.2f}
📦 Quantity:     {qty} {'share' if qty == 1 else 'shares'}
💰 Position:     ₹{position:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 *RISK — REWARD*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  Risk/share:  ₹{risk_per_share:,.2f}
✅ Reward/share: ₹{reward_per_share:,.2f}
📐 R:R Ratio:    1:{rr}
📉 Total Risk:   ₹{total_risk:,.2f}
📈 Total Reward: ₹{total_reward:,.2f}
📉 Downside:     -{downside}%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 *CONFIRMATIONS*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📉 EMA Trend:    ✅ EMA20 < EMA50 < EMA200
📅 Weekly EMA:   {weekly_status}
📊 Volume:       ✅ Volume above 1.2× 10-day average
🏆 Signal Score: {score}/100
{'📉 52W Low:     Near yearly low — sustained weakness' if near_52w_low else ''}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚦 *STATUS*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📥 Entry Status: 🔴 ACTIVE — Breakdown below previous low
📤 Exit Status:  🟢 Cover if price RISES above ₹{sl:,.2f}
🎯 Profit Exit:  🟢 Cover at ₹{target:,.2f} (-{downside}%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌍 *MARKET CONTEXT*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Nifty50:      ₹{nifty_fmt}
📈 Market:       {mkt_status}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ *DISCLAIMER*
Signals are for educational purposes only.
Not investment advice. Trade at your own risk.
Takshvi Trade is not SEBI registered (RA pending).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📱 takshvitrade.com"""

    return msg.strip()


def format_prebreakout_signal(signal: dict, market_trend: str) -> str:
    """Formats a PRE-BREAKOUT signal — place BUY STOP order tonight."""
    stock    = signal.get("stock", "")
    entry    = signal.get("entry", 0)
    sl       = signal.get("sl", 0)
    target   = signal.get("target", 0)
    qty      = signal.get("qty", 0)
    distance = signal.get("distance_to_breakout", 0)
    score    = signal.get("score", 0)
    now      = datetime.now().strftime("%d %b %Y, %I:%M %p IST")

    msg = f"""╔══════════════════════════════╗
⏳ *TAKSHVI TRADE — BUY STOP ALERT*
╚══════════════════════════════╝

📊 *{stock}*  — {distance}% away from breakout
🕐 {now}

ACTION REQUIRED TONIGHT:
Place a BUY STOP order at ₹{entry:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 *ORDER DETAILS*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟡 BUY STOP at: ₹{entry:,.2f}
🔴 Stop Loss:   ₹{sl:,.2f}
🟢 Target:      ₹{target:,.2f}
📦 Quantity:    {qty} {'share' if qty == 1 else 'shares'}
🏆 Score:       {score}/100

If stock breaks out tomorrow → order fills automatically.
If stock does not break out → order expires, no trade.

📱 takshvitrade.com
⚠️ Not investment advice."""

    return msg.strip()


def format_market_summary(scan_result: dict) -> str:
    """
    Daily market summary message sent after full scan.
    Shows counts of all signal types found.
    """
    now        = datetime.now().strftime("%d %b %Y, %I:%M %p IST")
    trend      = scan_result.get("market_trend", "SIDEWAYS")
    nifty      = scan_result.get("nifty")
    change_pct = scan_result.get("change_pct")
    scan_time  = scan_result.get("scan_time", 0)
    longs      = scan_result.get("long_signals", [])
    pre_bo     = scan_result.get("pre_breakout", [])
    shorts     = scan_result.get("short_signals", [])
    pre_bd     = scan_result.get("pre_breakdown", [])
    rs         = scan_result.get("relative_strength", [])
    is_crash   = scan_result.get("is_crash", False)

    nifty_fmt = f"₹{nifty:,.2f}" if nifty else "--"
    arrow     = "▲" if trend == "UP" else "▼"
    chg_txt   = f"{arrow} {abs(change_pct):.2f}% today" if change_pct else ""
    mkt_emoji = "🟢" if trend == "UP" else ("🚨" if is_crash else "🔴")

    long_names  = ", ".join([s["stock"] for s in longs[:3]])  or "None"
    short_names = ", ".join([s["stock"] for s in shorts[:3]]) or "None"
    pre_bo_names= ", ".join([s["stock"] for s in pre_bo[:3]]) or "None"
    rs_names    = ", ".join([s["stock"] for s in rs[:3]])      or "None"

    crash_warning = "\n🚨 EXTREME CRASH DAY — No long trades. Consider shorts only.\n" if is_crash else ""

    msg = f"""╔══════════════════════════════╗
📊 *TAKSHVI TRADE — DAILY SCAN*
╚══════════════════════════════╝

🕐 {now}
{crash_warning}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌍 *MARKET STATUS*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{mkt_emoji} Nifty50:  {nifty_fmt} {chg_txt}
📊 Trend:    {trend}
{'⚠️  Bearish: Long positions at 50% size' if trend == 'DOWN' and not is_crash else ''}
{'✅ Bullish: Full position size, score ≥80 only' if trend == 'UP' else ''}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 *SIGNALS FOUND TODAY*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 Long Signals:    {len(longs)} → {long_names}
⏳ Pre-Breakout:    {len(pre_bo)} → {pre_bo_names}
🔴 Short Signals:   {len(shorts)} → {short_names}
⚡ Rel. Strength:   {len(rs)} → {rs_names}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱ Scan time: {scan_time}s | 50 Nifty stocks scanned
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📱 View full signals: takshvitrade.com

⚠️ Not investment advice. SEBI RA registration pending."""

    return msg.strip()


def format_test_message() -> str:
    return """✅ *TAKSHVI TRADE — WhatsApp Alert Active*

Your trading alerts are now connected!

You will receive:
📈 Buy signals with entry/SL/target
📉 Short signals with breakdown levels
⏳ Pre-breakout BUY STOP alerts
📊 Daily market summary

📱 takshvitrade.com
⚠️ Not investment advice."""


# ════════════════════════════════════════════════════════════
# TWILIO SENDER
# ════════════════════════════════════════════════════════════

def send_whatsapp(message: str, to_number: str = None) -> dict:
    """
    Sends a WhatsApp message via Twilio API.

    Args:
        message:   Formatted message string
        to_number: WhatsApp number in format whatsapp:+91XXXXXXXXXX
                   If None, uses ALERT_PHONE env variable

    Returns:
        {"success": True/False, "sid": "...", "error": "..."}
    """
    if not TWILIO_AVAILABLE:
        return {"success": False, "error": "twilio package not installed"}

    if not TWILIO_SID or not TWILIO_TOKEN:
        return {"success": False, "error": "TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN not set in environment"}

    to = to_number or TO_NUMBER
    if not to:
        return {"success": False, "error": "No phone number provided. Set ALERT_PHONE env variable"}

    # Ensure proper format
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"

    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg    = client.messages.create(
            body=message,
            from_=FROM_NUMBER,
            to=to
        )
        logging.info(f"WhatsApp sent: {msg.sid} to {to}")
        return {"success": True, "sid": msg.sid, "to": to}

    except Exception as e:
        logging.error(f"Twilio error: {e}")
        return {"success": False, "error": str(e)}


def send_alerts_for_scan(scan_result: dict, capital: float,
                          to_number: str = None) -> dict:
    """
    Master alert sender — called after run_master_scan().
    Sends:
    1. Market summary message (always)
    2. Individual long signal messages
    3. Individual short signal messages
    4. Pre-breakout BUY STOP messages

    Returns summary of what was sent.
    """
    market_trend = scan_result.get("market_trend", "SIDEWAYS")
    nifty        = scan_result.get("nifty")
    change_pct   = scan_result.get("change_pct", 0)
    longs        = scan_result.get("long_signals", [])
    shorts       = scan_result.get("short_signals", [])
    pre_bo       = scan_result.get("pre_breakout", [])
    sent         = []
    failed       = []

    # 1. Market summary
    summary_msg = format_market_summary(scan_result)
    r = send_whatsapp(summary_msg, to_number)
    if r["success"]:
        sent.append("market_summary")
    else:
        failed.append(f"market_summary: {r.get('error')}")

    import time

    # 2. Long signals (max 3)
    for sig in longs[:3]:
        time.sleep(1)  # avoid rate limiting
        msg = format_long_signal(sig, market_trend, nifty, change_pct)
        r   = send_whatsapp(msg, to_number)
        if r["success"]:
            sent.append(f"long:{sig['stock']}")
        else:
            failed.append(f"long:{sig['stock']}: {r.get('error')}")

    # 3. Short signals (max 3)
    for sig in shorts[:3]:
        time.sleep(1)
        msg = format_short_signal(sig, market_trend, nifty, change_pct)
        r   = send_whatsapp(msg, to_number)
        if r["success"]:
            sent.append(f"short:{sig['stock']}")
        else:
            failed.append(f"short:{sig['stock']}: {r.get('error')}")

    # 4. Pre-breakout BUY STOP alerts (max 3)
    for sig in pre_bo[:3]:
        time.sleep(1)
        msg = format_prebreakout_signal(sig, market_trend)
        r   = send_whatsapp(msg, to_number)
        if r["success"]:
            sent.append(f"pre_bo:{sig['stock']}")
        else:
            failed.append(f"pre_bo:{sig['stock']}: {r.get('error')}")

    return {
        "sent":   sent,
        "failed": failed,
        "total_sent":   len(sent),
        "total_failed": len(failed),
    }
