"""
Takshvi Trade — database.py
Supabase integration with EXACT column names from schema.

Tables:
  scan_history  — one row per scan run
  signals       — one row per signal generated
  alert_logs    — one row per WhatsApp message sent
  users         — registered users
"""

import os
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

# ── Supabase client ────────────────────────────────────────────
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logging.warning("supabase package not installed — pip install supabase")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

_client: Optional["Client"] = None


def get_client() -> Optional["Client"]:
    """Returns a cached Supabase client, or None if not configured."""
    global _client
    if _client:
        return _client
    if not SUPABASE_AVAILABLE:
        logging.error("DB: supabase package not installed")
        return None
    if not SUPABASE_URL or not SUPABASE_KEY:
        logging.error(f"DB: missing env vars — URL={bool(SUPABASE_URL)} KEY={bool(SUPABASE_KEY)}")
        return None
    try:
        logging.info(f"DB: connecting to {SUPABASE_URL[:40]}...")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logging.info("DB: client created successfully")
        return _client
    except Exception as e:
        logging.error(f"DB: create_client failed — {type(e).__name__}: {e}")
        return None


def is_connected() -> bool:
    """Quick health check — returns True if Supabase is reachable."""
    try:
        db = get_client()
        if not db:
            return False
        result = db.table("scan_history").select("id").limit(1).execute()
        logging.info(f"DB: health check OK — {result}")
        return True
    except Exception as e:
        logging.error(f"DB: health check FAILED — {type(e).__name__}: {e}")
        return False


def get_connection_error() -> str:
    """Returns the last connection error string for the /db-status endpoint."""
    try:
        db = get_client()
        if not db:
            return "client_init_failed"
        db.table("scan_history").select("id").limit(1).execute()
        return ""
    except Exception as e:
        return f"{type(e).__name__}: {e}"


# ════════════════════════════════════════════════════════════
# scan_history
# Columns: id, scanned_at, market_trend, nifty_value,
#          change_pct, is_crash, long_count, short_count,
#          pre_bo_count, pre_bd_count, rs_count,
#          scan_time_sec, capital
# ════════════════════════════════════════════════════════════

def save_scan(scan_result: dict, capital: float) -> Optional[str]:
    """
    Inserts one row into scan_history.
    Returns the new scan UUID (used as FK for signals rows), or None on failure.
    """
    db = get_client()
    if not db:
        return None

    scan_id = str(uuid.uuid4())
    row = {
        "id":            scan_id,
        "scanned_at":    datetime.now(timezone.utc).isoformat(),
        "market_trend":  scan_result.get("market_trend", "SIDEWAYS"),
        "nifty_value":   scan_result.get("nifty"),
        "change_pct":    scan_result.get("change_pct"),
        "is_crash":      scan_result.get("is_crash", False),
        "long_count":    len(scan_result.get("long_signals", [])),
        "short_count":   len(scan_result.get("short_signals", [])),
        "pre_bo_count":  len(scan_result.get("pre_breakout", [])),
        "pre_bd_count":  len(scan_result.get("pre_breakdown", [])),
        "rs_count":      len(scan_result.get("relative_strength", [])),
        "scan_time_sec": scan_result.get("scan_time"),
        "capital":       capital,
    }

    try:
        db.table("scan_history").insert(row).execute()
        logging.info(f"Scan saved → scan_id={scan_id}")
        return scan_id
    except Exception as e:
        logging.error(f"save_scan error: {e}")
        return None


def get_recent_scans(limit: int = 10) -> list:
    """Returns the most recent scan_history rows."""
    db = get_client()
    if not db:
        return []
    try:
        res = (
            db.table("scan_history")
            .select("*")
            .order("scanned_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logging.error(f"get_recent_scans error: {e}")
        return []


# ════════════════════════════════════════════════════════════
# signals
# Columns: id, scan_id, generated_at, signal_type, stock,
#          close_price, entry, stop_loss, target, quantity,
#          position_value, risk_reward, score, action,
#          upside_pct, near_52w_high, near_52w_low, caution,
#          market_trend, weekly_ema20, weekly_ema50,
#          outcome, outcome_date, outcome_price,
#          pnl_per_share, pnl_total
# ════════════════════════════════════════════════════════════

def _build_signal_row(signal: dict, scan_id: str, signal_type: str,
                      market_trend: str) -> dict:
    """Maps scanner output dict → exact Supabase column names."""
    return {
        "id":             str(uuid.uuid4()),
        "scan_id":        scan_id,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "signal_type":    signal_type,                         # LONG | SHORT | PRE_BREAKOUT | PRE_BREAKDOWN | RS
        "stock":          signal.get("stock", ""),
        "close_price":    signal.get("close"),
        "entry":          signal.get("entry"),
        "stop_loss":      signal.get("sl"),                    # scanner uses "sl"
        "target":         signal.get("target"),
        "quantity":       signal.get("qty"),                   # scanner uses "qty"
        "position_value": signal.get("position"),              # scanner uses "position"
        "risk_reward":    signal.get("rr"),                    # scanner uses "rr"
        "score":          signal.get("score"),
        "action":         signal.get("action"),
        "upside_pct":     signal.get("upside_pct"),
        "near_52w_high":  signal.get("near_52w_high", False),
        "near_52w_low":   signal.get("near_52w_low", False),
        "caution":        signal.get("caution", False),
        "market_trend":   market_trend,
        "weekly_ema20":   signal.get("weekly_ema20"),
        "weekly_ema50":   signal.get("weekly_ema50"),
        # outcome fields — filled later via update_signal_outcome()
        "outcome":        None,
        "outcome_date":   None,
        "outcome_price":  None,
        "pnl_per_share":  None,
        "pnl_total":      None,
    }


def save_signals(scan_result: dict, scan_id: str) -> int:
    """
    Bulk-inserts all signals from a master scan result into the signals table.
    Returns count of rows saved.
    """
    db = get_client()
    if not db:
        return 0

    market_trend = scan_result.get("market_trend", "SIDEWAYS")
    rows = []

    for sig in scan_result.get("long_signals", []):
        rows.append(_build_signal_row(sig, scan_id, "LONG", market_trend))

    for sig in scan_result.get("short_signals", []):
        rows.append(_build_signal_row(sig, scan_id, "SHORT", market_trend))

    for sig in scan_result.get("pre_breakout", []):
        rows.append(_build_signal_row(sig, scan_id, "PRE_BREAKOUT", market_trend))

    for sig in scan_result.get("pre_breakdown", []):
        rows.append(_build_signal_row(sig, scan_id, "PRE_BREAKDOWN", market_trend))

    for sig in scan_result.get("relative_strength", []):
        rows.append(_build_signal_row(sig, scan_id, "RS", market_trend))

    if not rows:
        return 0

    try:
        db.table("signals").insert(rows).execute()
        logging.info(f"Saved {len(rows)} signals for scan_id={scan_id}")
        return len(rows)
    except Exception as e:
        logging.error(f"save_signals error: {e}")
        return 0


def update_signal_outcome(
    signal_id: str,
    outcome: str,           # "WIN" | "LOSS" | "PARTIAL" | "OPEN"
    outcome_price: float,
    pnl_per_share: float,
    pnl_total: float,
) -> bool:
    """Updates outcome fields for a signal after trade closes."""
    db = get_client()
    if not db:
        return False
    try:
        db.table("signals").update({
            "outcome":       outcome,
            "outcome_date":  datetime.now(timezone.utc).isoformat(),
            "outcome_price": outcome_price,
            "pnl_per_share": pnl_per_share,
            "pnl_total":     pnl_total,
        }).eq("id", signal_id).execute()
        return True
    except Exception as e:
        logging.error(f"update_signal_outcome error: {e}")
        return False


def get_signals_for_scan(scan_id: str) -> list:
    db = get_client()
    if not db:
        return []
    try:
        res = db.table("signals").select("*").eq("scan_id", scan_id).execute()
        return res.data or []
    except Exception as e:
        logging.error(f"get_signals_for_scan error: {e}")
        return []


def get_open_signals(limit: int = 50) -> list:
    """Returns signals where outcome is still NULL (open trades)."""
    db = get_client()
    if not db:
        return []
    try:
        res = (
            db.table("signals")
            .select("*")
            .is_("outcome", "null")
            .order("generated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logging.error(f"get_open_signals error: {e}")
        return []


# ════════════════════════════════════════════════════════════
# alert_logs
# Columns: id, sent_at, phone, alert_type, stock,
#          message_sid, status, error
# ════════════════════════════════════════════════════════════

def log_alert(
    phone: str,
    alert_type: str,    # "LONG" | "SHORT" | "PRE_BREAKOUT" | "SUMMARY" | "TEST"
    stock: str = "",
    message_sid: str = "",
    status: str = "sent",
    error: str = "",
) -> bool:
    """Logs a sent (or failed) WhatsApp alert into alert_logs."""
    db = get_client()
    if not db:
        return False
    try:
        db.table("alert_logs").insert({
            "id":          str(uuid.uuid4()),
            "sent_at":     datetime.now(timezone.utc).isoformat(),
            "phone":       phone,
            "alert_type":  alert_type,
            "stock":       stock,
            "message_sid": message_sid,
            "status":      status,
            "error":       error,
        }).execute()
        return True
    except Exception as e:
        logging.error(f"log_alert error: {e}")
        return False


def get_alert_logs(limit: int = 50) -> list:
    db = get_client()
    if not db:
        return []
    try:
        res = (
            db.table("alert_logs")
            .select("*")
            .order("sent_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logging.error(f"get_alert_logs error: {e}")
        return []


# ════════════════════════════════════════════════════════════
# users
# Columns: id, created_at, email, phone, name, plan,
#          plan_expires_at, is_active, capital, alerts_enabled
# ════════════════════════════════════════════════════════════

def upsert_user(
    email: str,
    name: str = "",
    phone: str = "",
    plan: str = "free",
    capital: float = 100000,
    alerts_enabled: bool = False,
) -> Optional[dict]:
    """Creates or updates a user record. Uses email as the unique key."""
    db = get_client()
    if not db:
        return None
    try:
        row = {
            "id":              str(uuid.uuid4()),
            "created_at":      datetime.now(timezone.utc).isoformat(),
            "email":           email,
            "phone":           phone,
            "name":            name,
            "plan":            plan,
            "plan_expires_at": None,
            "is_active":       True,
            "capital":         capital,
            "alerts_enabled":  alerts_enabled,
        }
        res = db.table("users").upsert(row, on_conflict="email").execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"upsert_user error: {e}")
        return None


def get_user_by_email(email: str) -> Optional[dict]:
    db = get_client()
    if not db:
        return None
    try:
        res = db.table("users").select("*").eq("email", email).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"get_user_by_email error: {e}")
        return None


def get_users_with_alerts() -> list:
    """Returns users who have alerts_enabled = True (for scheduled sends)."""
    db = get_client()
    if not db:
        return []
    try:
        res = (
            db.table("users")
            .select("*")
            .eq("alerts_enabled", True)
            .eq("is_active", True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logging.error(f"get_users_with_alerts error: {e}")
        return []