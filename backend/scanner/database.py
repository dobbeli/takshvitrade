"""
Takshvi Trade — database.py  v4  (FIXED)
FIXES:
1. _build_signal_row now handles both 'sl' and 'stop_loss' field names from engine
2. save_signals logs each failure clearly so you can see WHY signals aren't saving
3. is_connected() failure now prints a human-readable diagnosis
4. save_scan returns scan_id even if some fields are None (was silently failing)
"""

import os
import logging
import uuid
import requests
from datetime import datetime, timezone
from typing import Optional

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
}
TIMEOUT = 10


def _url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def _insert(table: str, row: dict):
    try:
        r = requests.post(_url(table), json=row, headers=HEADERS, timeout=TIMEOUT)
        if not r.ok:
            logging.error(f"DB insert {table} FAILED: HTTP {r.status_code} — {r.text[:300]}")
            return None
        data = r.json()
        return data[0] if isinstance(data, list) and data else data
    except Exception as e:
        logging.error(f"DB insert {table}: {type(e).__name__}: {e}")
        return None


def _insert_many(table: str, rows: list) -> int:
    if not rows:
        return 0
    try:
        r = requests.post(_url(table), json=rows, headers=HEADERS, timeout=TIMEOUT)
        if not r.ok:
            logging.error(f"DB insert_many {table} FAILED: HTTP {r.status_code} — {r.text[:400]}")
            return 0
        return len(rows)
    except Exception as e:
        logging.error(f"DB insert_many {table}: {type(e).__name__}: {e}")
        return 0


def _select(table: str, params: dict) -> list:
    try:
        r = requests.get(_url(table), params=params, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json() or []
    except Exception as e:
        logging.error(f"DB select {table}: {type(e).__name__}: {e}")
        return []


def _update(table: str, filter_params: dict, data: dict) -> bool:
    try:
        r = requests.patch(_url(table), params=filter_params, json=data,
                           headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"DB update {table}: {type(e).__name__}: {e}")
        return False


def _upsert(table: str, row: dict, on_conflict: str):
    hdrs = {**HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"}
    try:
        r = requests.post(
            f"{_url(table)}?on_conflict={on_conflict}",
            json=row, headers=hdrs, timeout=TIMEOUT
        )
        r.raise_for_status()
        data = r.json()
        return data[0] if isinstance(data, list) and data else data
    except Exception as e:
        logging.error(f"DB upsert {table}: {type(e).__name__}: {e}")
        return None


def is_connected() -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        logging.error("DB: SUPABASE_URL or SUPABASE_KEY not set — check Railway Variables")
        return False
    try:
        r = requests.get(
            _url("scan_history"),
            params={"select": "id", "limit": "1"},
            headers=HEADERS,
            timeout=TIMEOUT
        )
        ok = r.status_code in (200, 206)
        if ok:
            logging.info("DB: Supabase health check OK ✅")
        else:
            logging.error(f"DB: Supabase health FAILED — HTTP {r.status_code}: {r.text[:200]}")
        return ok
    except Exception as e:
        logging.error(f"DB: Supabase health FAILED — {type(e).__name__}: {e}")
        return False


def get_connection_error() -> str:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return "missing env vars: SUPABASE_URL or SUPABASE_KEY"
    try:
        r = requests.get(
            _url("scan_history"),
            params={"select": "id", "limit": "1"},
            headers=HEADERS, timeout=TIMEOUT
        )
        if r.status_code in (200, 206):
            return ""
        return f"HTTP {r.status_code}: {r.text[:300]}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def bootstrap_schema():
    logging.info("DB: using Supabase — schema managed in dashboard")


# ════════════════════════════════════════════════════════════
# scan_history
# ════════════════════════════════════════════════════════════

def save_scan(scan_result: dict, capital: float) -> Optional[str]:
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
    result = _insert("scan_history", row)
    if result is not None:
        logging.info(f"DB: scan saved ✅ → scan_id={scan_id}")
        return scan_id
    logging.error("DB: save_scan FAILED — scan_id not saved")
    return None


def get_recent_scans(limit: int = 10) -> list:
    return _select("scan_history", {
        "select": "*", "order": "scanned_at.desc", "limit": str(limit)
    })


# ════════════════════════════════════════════════════════════
# signals — FIXED field mapping
# ════════════════════════════════════════════════════════════

def _g(signal: dict, *keys):
    """Try multiple field name variants — handles engine field name differences."""
    for k in keys:
        v = signal.get(k)
        if v is not None:
            return v
    return None


def _build_signal_row(signal: dict, scan_id: str,
                      signal_type: str, market_trend: str) -> dict:
    """
    FIXED: engine may return 'sl' or 'stop_loss', 'close' or 'close_price'.
    We try both variants with _g() helper.
    """
    entry  = _g(signal, "entry")
    sl     = _g(signal, "sl", "stop_loss")
    target = _g(signal, "target")

    # Calculate upside_pct if not provided by engine
    upside = _g(signal, "upside_pct")
    if upside is None and entry and target:
        try:
            upside = round(((target - entry) / entry) * 100, 2)
        except Exception:
            upside = None

    return {
        "id":             str(uuid.uuid4()),
        "scan_id":        scan_id,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "signal_type":    signal_type,
        "stock":          _g(signal, "stock", "symbol") or "",
        "close_price":    _g(signal, "close", "close_price"),
        "entry":          entry,
        "stop_loss":      sl,
        "target":         target,
        "quantity":       _g(signal, "qty", "quantity"),
        "position_value": _g(signal, "position", "position_value"),
        "risk_reward":    _g(signal, "rr", "risk_reward"),
        "score":          _g(signal, "score"),
        "action":         _g(signal, "action"),
        "upside_pct":     upside,
        "near_52w_high":  signal.get("near_52w_high", False),
        "near_52w_low":   signal.get("near_52w_low", False),
        "caution":        signal.get("caution", False),
        "market_trend":   market_trend,
        "weekly_ema20":   _g(signal, "weekly_ema20"),
        "weekly_ema50":   _g(signal, "weekly_ema50"),
        "outcome":        None,
        "outcome_date":   None,
        "outcome_price":  None,
        "pnl_per_share":  None,
        "pnl_total":      None,
    }


def save_signals(scan_result: dict, scan_id: str) -> int:
    market_trend = scan_result.get("market_trend", "SIDEWAYS")
    rows = []

    type_map = [
        ("long_signals",      "LONG"),
        ("short_signals",     "SHORT"),
        ("pre_breakout",      "PRE_BREAKOUT"),
        ("pre_breakdown",     "PRE_BREAKDOWN"),
        ("relative_strength", "RS"),
    ]

    for key, signal_type in type_map:
        signals = scan_result.get(key, [])
        for s in signals:
            rows.append(_build_signal_row(s, scan_id, signal_type, market_trend))

    if not rows:
        logging.info(f"DB: save_signals — no signals to save for scan_id={scan_id}")
        return 0

    saved = _insert_many("signals", rows)
    if saved > 0:
        logging.info(f"DB: {saved} signals saved ✅ for scan_id={scan_id}")
    else:
        logging.error(f"DB: save_signals FAILED — 0 rows saved for scan_id={scan_id}")
    return saved


def update_signal_outcome(signal_id: str, outcome: str, outcome_price: float,
                           pnl_per_share: float, pnl_total: float) -> bool:
    return _update("signals", {"id": f"eq.{signal_id}"}, {
        "outcome":       outcome,
        "outcome_date":  datetime.now(timezone.utc).isoformat(),
        "outcome_price": outcome_price,
        "pnl_per_share": pnl_per_share,
        "pnl_total":     pnl_total,
    })


def get_signals_for_scan(scan_id: str) -> list:
    return _select("signals", {"select": "*", "scan_id": f"eq.{scan_id}"})


def get_open_signals(limit: int = 50) -> list:
    return _select("signals", {
        "select": "*", "outcome": "is.null",
        "order": "generated_at.desc", "limit": str(limit)
    })


# ════════════════════════════════════════════════════════════
# alert_logs
# ════════════════════════════════════════════════════════════

def log_alert(phone: str, alert_type: str, stock: str = "",
              message_sid: str = "", status: str = "sent", error: str = "") -> bool:
    return _insert("alert_logs", {
        "id":          str(uuid.uuid4()),
        "sent_at":     datetime.now(timezone.utc).isoformat(),
        "phone":       phone,
        "alert_type":  alert_type,
        "stock":       stock,
        "message_sid": message_sid,
        "status":      status,
        "error":       error,
    }) is not None


def get_alert_logs(limit: int = 50) -> list:
    return _select("alert_logs", {
        "select": "*", "order": "sent_at.desc", "limit": str(limit)
    })


# ════════════════════════════════════════════════════════════
# users
# ════════════════════════════════════════════════════════════

def upsert_user(email: str, name: str = "", phone: str = "", plan: str = "free",
                capital: float = 100000, alerts_enabled: bool = False,
                password_hash: str = ""):
    row = {
        "id":             str(uuid.uuid4()),
        "created_at":     datetime.now(timezone.utc).isoformat(),
        "email":          email, "phone": phone, "name": name,
        "plan":           plan, "plan_expires_at": None,
        "is_active":      True, "capital": capital,
        "alerts_enabled": alerts_enabled,
    }
    if password_hash:
        row["password_hash"] = password_hash
    return _upsert("users", row, on_conflict="email")


def get_user_by_email(email: str) -> Optional[dict]:
    rows = _select("users", {"select": "*", "email": f"eq.{email}", "limit": "1"})
    return rows[0] if rows else None


def get_users_with_alerts() -> list:
    return _select("users", {
        "select": "*", "alerts_enabled": "eq.true", "is_active": "eq.true"
    })