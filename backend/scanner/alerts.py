"""
TakshviTrade — WhatsApp Alert Service
Sends trade signals to your phone via Twilio
"""
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Load credentials from .env file (never hardcode these) ──
TWILIO_SID   = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM  = os.getenv("TWILIO_FROM", "whatsapp:+14155238886")
TWILIO_TO    = os.getenv("TWILIO_TO",   "whatsapp:+91XXXXXXXXXX")


def send_whatsapp(message: str) -> bool:
    """
    Sends a WhatsApp message via Twilio sandbox
    Returns True if sent, False if failed
    """
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(
            from_ = TWILIO_FROM,
            to    = TWILIO_TO,
            body  = message
        )
        print("✅ WhatsApp alert sent!")
        return True
    except Exception as e:
        print(f"⚠️ WhatsApp failed: {e}")
        return False


def format_signal_message(
    trades: list,
    capital: float,
    market_status: dict
) -> str:
    """
    Builds clean WhatsApp message from scan results
    Designed to be readable on mobile screen
    """
    now      = datetime.now().strftime("%d %b %Y %I:%M %p")
    risk_amt = round(capital * 0.01, 0)

    lines = []
    lines.append(f"📊 *TAKSHVITRADE SIGNAL*")
    lines.append(f"🗓 {now}")
    lines.append(f"💰 Capital: ₹{capital:,.0f} | Risk/trade: ₹{risk_amt:,.0f}")
    lines.append(f"📈 Market: {'✅ BULLISH' if market_status.get('bullish') else '❌ BEARISH'}")
    lines.append(f"🔢 Nifty: {market_status.get('price', 'N/A')} | RSI: {market_status.get('rsi', 'N/A')}")
    lines.append("─" * 28)

    if not trades:
        lines.append("❌ No valid trades today")
        lines.append("Market conditions not ideal")
        lines.append("Check again tomorrow after close")
    else:
        lines.append(f"🎯 *TOP {len(trades)} TRADES FOR TOMORROW*\n")

        total_deploy = 0
        for i, t in enumerate(trades, 1):
            risk_rs   = round((t["entry"] - t["stop_loss"]) * t["qty"], 0)
            reward_rs = round((t["target"] - t["entry"])    * t["qty"], 0)
            total_deploy += t["position"]

            lines.append(f"*{i}. {t['stock']}*  [{t['score']}/100]")
            lines.append(f"   🟢 BUY    : ₹{t['entry']}")
            lines.append(f"   🔴 SL     : ₹{t['stop_loss']}")
            lines.append(f"   🎯 Target : ₹{t['target']}")
            lines.append(f"   📦 Qty    : {t['qty']} shares")
            lines.append(f"   💵 Deploy : ₹{t['position']:,}")
            lines.append(f"   📉 Risk ₹{risk_rs:,} → Reward ₹{reward_rs:,}")
            lines.append(f"   📊 RR: {t['rr']}x | Up: {t['upside_pct']}%\n")

        lines.append("─" * 28)
        lines.append(f"💼 *SUMMARY*")
        lines.append(f"   Deploy : ₹{total_deploy:,.0f} of ₹{capital:,.0f}")
        lines.append(f"   Cash   : ₹{capital - total_deploy:,.0f} kept safe")

    lines.append("")
    lines.append("─" * 28)
    lines.append("⚡ *GROWW STEPS (9:15 AM)*")
    lines.append("1. Check Nifty — skip if -1%")
    lines.append("2. Search stock → CNC → LIMIT")
    lines.append("3. Set GTT after fill")
    lines.append("4. Never remove stop loss!")
    lines.append("─" * 28)
    lines.append("_TakshviTrade.com_")

    return "\n".join(lines)


def send_test_message(to_number: str = None) -> bool:
    """
    Sends a test message to verify setup is working
    Call this first to confirm Twilio is connected
    """
    test_msg = (
        "✅ *TakshviTrade Alert System*\n"
        "Your WhatsApp alerts are working!\n\n"
        "You will receive trade signals\n"
        "every evening after market close.\n\n"
        "_takshvitrade.com_"
    )
    if to_number:
        global TWILIO_TO
        TWILIO_TO = f"whatsapp:{to_number}"

    return send_whatsapp(test_msg)
