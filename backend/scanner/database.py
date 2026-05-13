"""
Takshvi Trade — database.py  v4
Uses Render PostgreSQL (internal network) via psycopg2.
Replaces Supabase client — fixes DNS failure on Render free tier.

Tables: scan_history · signals · alert_logs · users
"""

import os
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

# ── Connection ─────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    logging.error("psycopg2 not installed — add psycopg2-binary to requirements.txt")


def get_conn():
    if not PSYCOPG2_AVAILABLE:
        raise RuntimeError("psycopg2 not available")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def is_connected() -> bool:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        conn.close()
        logging.info("DB: health check OK ✅")
        return True
    except Exception as e:
        logging.error(f"DB: health check FAILED — {type(e).__name__}: {e}")
        return False


def get_connection_error() -> str:
    try:
        get_conn().close()
        return ""
    except Exception as e:
        return f"{type(e).__name__}: {e}"


# ── Schema bootstrap ───────────────────────────────────────────
# Call once on startup to create tables if they don't exist.

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS scan_history (
    id            TEXT PRIMARY KEY,
    scanned_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    market_trend  TEXT,
    nifty_value   NUMERIC,
    change_pct    NUMERIC,
    is_crash      BOOLEAN DEFAULT FALSE,
    long_count    INT DEFAULT 0,
    short_count   INT DEFAULT 0,
    pre_bo_count  INT DEFAULT 0,
    pre_bd_count  INT DEFAULT 0,
    rs_count      INT DEFAULT 0,
    scan_time_sec NUMERIC,
    capital       NUMERIC
);

CREATE TABLE IF NOT EXISTS signals (
    id             TEXT PRIMARY KEY,
    scan_id        TEXT REFERENCES scan_history(id),
    generated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal_type    TEXT,
    stock          TEXT,
    close_price    NUMERIC,
    entry          NUMERIC,
    stop_loss      NUMERIC,
    target         NUMERIC,
    quantity       INT,
    position_value NUMERIC,
    risk_reward    NUMERIC,
    score          INT,
    action         TEXT,
    upside_pct     NUMERIC,
    near_52w_high  BOOLEAN DEFAULT FALSE,
    near_52w_low   BOOLEAN DEFAULT FALSE,
    caution        BOOLEAN DEFAULT FALSE,
    market_trend   TEXT,
    weekly_ema20   NUMERIC,
    weekly_ema50   NUMERIC,
    outcome        TEXT,
    outcome_date   TIMESTAMPTZ,
    outcome_price  NUMERIC,
    pnl_per_share  NUMERIC,
    pnl_total      NUMERIC
);

CREATE TABLE IF NOT EXISTS alert_logs (
    id          TEXT PRIMARY KEY,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    phone       TEXT,
    alert_type  TEXT,
    stock       TEXT,
    message_sid TEXT,
    status      TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    email           TEXT UNIQUE,
    phone           TEXT,
    name            TEXT,
    plan            TEXT DEFAULT 'free',
    plan_expires_at TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    capital         NUMERIC DEFAULT 100000,
    alerts_enabled  BOOLEAN DEFAULT FALSE
);
"""


def bootstrap_schema():
    """Creates all tables if they don't exist. Call once at startup."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(CREATE_TABLES_SQL)
        conn.commit()
        conn.close()
        logging.info("DB: schema bootstrap complete ✅")
    except Exception as e:
        logging.error(f"DB: schema bootstrap FAILED — {e}")


# ════════════════════════════════════════════════════════════
# scan_history
# ════════════════════════════════════════════════════════════

def save_scan(scan_result: dict, capital: float) -> Optional[str]:
    scan_id = str(uuid.uuid4())
    sql = """
        INSERT INTO scan_history
            (id, scanned_at, market_trend, nifty_value, change_pct, is_crash,
             long_count, short_count, pre_bo_count, pre_bd_count, rs_count,
             scan_time_sec, capital)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(sql, (
            scan_id,
            datetime.now(timezone.utc),
            scan_result.get("market_trend", "SIDEWAYS"),
            scan_result.get("nifty"),
            scan_result.get("change_pct"),
            scan_result.get("is_crash", False),
            len(scan_result.get("long_signals", [])),
            len(scan_result.get("short_signals", [])),
            len(scan_result.get("pre_breakout", [])),
            len(scan_result.get("pre_breakdown", [])),
            len(scan_result.get("relative_strength", [])),
            scan_result.get("scan_time"),
            capital,
        ))
        conn.commit()
        conn.close()
        logging.info(f"DB: scan saved → {scan_id}")
        return scan_id
    except Exception as e:
        logging.error(f"save_scan error: {e}")
        return None


def get_recent_scans(limit: int = 10) -> list:
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM scan_history ORDER BY scanned_at DESC LIMIT %s", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"get_recent_scans error: {e}")
        return []


# ════════════════════════════════════════════════════════════
# signals
# ════════════════════════════════════════════════════════════

def _build_signal_row(signal: dict, scan_id: str,
                      signal_type: str, market_trend: str) -> tuple:
    return (
        str(uuid.uuid4()), scan_id, datetime.now(timezone.utc),
        signal_type, signal.get("stock", ""),
        signal.get("close"), signal.get("entry"),
        signal.get("sl"),       # scanner key → stop_loss column
        signal.get("target"),
        signal.get("qty"),      # scanner key → quantity column
        signal.get("position"), # scanner key → position_value column
        signal.get("rr"),       # scanner key → risk_reward column
        signal.get("score"), signal.get("action"), signal.get("upside_pct"),
        signal.get("near_52w_high", False), signal.get("near_52w_low", False),
        signal.get("caution", False), market_trend,
        signal.get("weekly_ema20"), signal.get("weekly_ema50"),
        None, None, None, None, None,  # outcome fields
    )


def save_signals(scan_result: dict, scan_id: str) -> int:
    market_trend = scan_result.get("market_trend", "SIDEWAYS")
    rows = []
    for s in scan_result.get("long_signals",      []): rows.append(_build_signal_row(s, scan_id, "LONG",          market_trend))
    for s in scan_result.get("short_signals",     []): rows.append(_build_signal_row(s, scan_id, "SHORT",         market_trend))
    for s in scan_result.get("pre_breakout",      []): rows.append(_build_signal_row(s, scan_id, "PRE_BREAKOUT",  market_trend))
    for s in scan_result.get("pre_breakdown",     []): rows.append(_build_signal_row(s, scan_id, "PRE_BREAKDOWN", market_trend))
    for s in scan_result.get("relative_strength", []): rows.append(_build_signal_row(s, scan_id, "RS",            market_trend))
    if not rows:
        return 0
    sql = """
        INSERT INTO signals
            (id, scan_id, generated_at, signal_type, stock,
             close_price, entry, stop_loss, target, quantity,
             position_value, risk_reward, score, action, upside_pct,
             near_52w_high, near_52w_low, caution, market_trend,
             weekly_ema20, weekly_ema50,
             outcome, outcome_date, outcome_price, pnl_per_share, pnl_total)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, sql, rows)
        conn.commit()
        conn.close()
        logging.info(f"DB: {len(rows)} signals saved for scan_id={scan_id}")
        return len(rows)
    except Exception as e:
        logging.error(f"save_signals error: {e}")
        return 0


def update_signal_outcome(signal_id: str, outcome: str, outcome_price: float,
                           pnl_per_share: float, pnl_total: float) -> bool:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE signals SET outcome=%s, outcome_date=%s,
            outcome_price=%s, pnl_per_share=%s, pnl_total=%s WHERE id=%s
        """, (outcome, datetime.now(timezone.utc), outcome_price,
               pnl_per_share, pnl_total, signal_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"update_signal_outcome error: {e}")
        return False


def get_signals_for_scan(scan_id: str) -> list:
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM signals WHERE scan_id=%s", (scan_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"get_signals_for_scan error: {e}")
        return []


def get_open_signals(limit: int = 50) -> list:
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM signals WHERE outcome IS NULL
            ORDER BY generated_at DESC LIMIT %s
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"get_open_signals error: {e}")
        return []


# ════════════════════════════════════════════════════════════
# alert_logs
# ════════════════════════════════════════════════════════════

def log_alert(phone: str, alert_type: str, stock: str = "",
              message_sid: str = "", status: str = "sent", error: str = "") -> bool:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO alert_logs (id, sent_at, phone, alert_type, stock, message_sid, status, error)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (str(uuid.uuid4()), datetime.now(timezone.utc),
               phone, alert_type, stock, message_sid, status, error))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"log_alert error: {e}")
        return False


def get_alert_logs(limit: int = 50) -> list:
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM alert_logs ORDER BY sent_at DESC LIMIT %s", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"get_alert_logs error: {e}")
        return []


# ════════════════════════════════════════════════════════════
# users
# ════════════════════════════════════════════════════════════

def upsert_user(email: str, name: str = "", phone: str = "", plan: str = "free",
                capital: float = 100000, alerts_enabled: bool = False) -> Optional[dict]:
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO users (id, created_at, email, phone, name, plan, is_active, capital, alerts_enabled)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (email) DO UPDATE SET
                name=EXCLUDED.name, phone=EXCLUDED.phone, plan=EXCLUDED.plan,
                capital=EXCLUDED.capital, alerts_enabled=EXCLUDED.alerts_enabled
            RETURNING *
        """, (str(uuid.uuid4()), datetime.now(timezone.utc),
               email, phone, name, plan, True, capital, alerts_enabled))
        row = dict(cur.fetchone())
        conn.commit()
        conn.close()
        return row
    except Exception as e:
        logging.error(f"upsert_user error: {e}")
        return None


def get_user_by_email(email: str) -> Optional[dict]:
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE email=%s LIMIT 1", (email,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logging.error(f"get_user_by_email error: {e}")
        return None


def get_users_with_alerts() -> list:
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE alerts_enabled=TRUE AND is_active=TRUE")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"get_users_with_alerts error: {e}")
        return []