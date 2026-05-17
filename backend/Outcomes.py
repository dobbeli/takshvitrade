"""
Takshvi Trade — Outcomes Router /api/outcomes

Saves WIN/LOSS/OPEN trade outcomes to Supabase.
Fills: outcome, pnl_per_share, pnl_total, exit_price, exit_date, notes columns.

SUPABASE TABLE REQUIRED — run this SQL in Supabase SQL editor:

    CREATE TABLE IF NOT EXISTS trade_outcomes (
        id              BIGSERIAL PRIMARY KEY,
        email           TEXT NOT NULL,
        stock           TEXT NOT NULL,
        direction       TEXT NOT NULL DEFAULT 'LONG',   -- LONG or SHORT
        entry           NUMERIC(12,2),
        sl              NUMERIC(12,2),
        target          NUMERIC(12,2),
        qty             INT,
        exit_price      NUMERIC(12,2),
        exit_date       DATE,
        outcome         TEXT,                           -- WIN / LOSS / OPEN
        pnl_per_share   NUMERIC(12,2),
        pnl_total       NUMERIC(12,2),
        notes           TEXT,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    );

    -- Index for fast per-user queries
    CREATE INDEX IF NOT EXISTS idx_outcomes_email ON trade_outcomes(email);

REGISTER IN main.py:
    from outcomes import router as outcomes_router
    app.include_router(outcomes_router, prefix="/api/outcomes")
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime, timezone
import jwt, os, logging

router = APIRouter()
bearer = HTTPBearer(auto_error=False)

# Explicit OPTIONS handler for CORS preflight
@router.options("")
def outcomes_options():
    return {}

@router.options("/{path:path}")
def outcomes_options_path(path: str):
    return {}

SECRET = os.getenv("JWT_SECRET", "takshvi-trade-secret-change-in-prod")
ALGO   = "HS256"


# ── Request model ─────────────────────────────────────────────
class OutcomeRequest(BaseModel):
    stock:          str
    direction:      str = "LONG"          # LONG or SHORT
    entry:          float
    sl:             float
    target:         float
    qty:            int
    exit_price:     Optional[float] = None
    exit_date:      Optional[str]   = None   # ISO date string e.g. "2025-05-17"
    outcome:        str                       # WIN / LOSS / OPEN
    pnl_per_share:  Optional[float] = None
    pnl_total:      Optional[float] = None
    notes:          Optional[str]   = None


# ── Auth helper ───────────────────────────────────────────────
def get_email_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer)
) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=[ALGO])
        return payload.get("sub", "")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired — please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── POST /api/outcomes — save or update outcome ───────────────
@router.post("")
def save_outcome(body: OutcomeRequest, email: str = Depends(get_email_from_token)):
    """
    Upserts a trade outcome for the authenticated user.
    If a row with the same (email, stock, entry) exists, it updates it.
    Otherwise it inserts a new row.
    """
    from scanner.database import get_supabase_client

    if not email:
        raise HTTPException(status_code=401, detail="Could not identify user")

    # Validate outcome value
    if body.outcome not in ("WIN", "LOSS", "OPEN"):
        raise HTTPException(status_code=400, detail="outcome must be WIN, LOSS, or OPEN")

    # Parse exit_date
    exit_date_val = None
    if body.exit_date:
        try:
            exit_date_val = body.exit_date[:10]  # keep only YYYY-MM-DD
        except Exception:
            exit_date_val = None

    row = {
        "email":         email,
        "stock":         body.stock.upper().strip(),
        "direction":     body.direction.upper(),
        "entry":         body.entry,
        "sl":            body.sl,
        "target":        body.target,
        "qty":           body.qty,
        "exit_price":    body.exit_price,
        "exit_date":     exit_date_val,
        "outcome":       body.outcome,
        "pnl_per_share": body.pnl_per_share,
        "pnl_total":     body.pnl_total,
        "notes":         body.notes,
        "updated_at":    datetime.now(timezone.utc).isoformat(),
    }

    try:
        sb = get_supabase_client()

        # Check if row already exists for this trade
        existing = (
            sb.table("trade_outcomes")
            .select("id")
            .eq("email", email)
            .eq("stock", row["stock"])
            .eq("entry", body.entry)
            .execute()
        )

        if existing.data:
            # Update existing row
            result = (
                sb.table("trade_outcomes")
                .update(row)
                .eq("id", existing.data[0]["id"])
                .execute()
            )
        else:
            # Insert new row
            result = (
                sb.table("trade_outcomes")
                .insert(row)
                .execute()
            )

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to save outcome to database")

        saved = result.data[0]
        return {
            "success":   True,
            "outcome":   body.outcome,
            "stock":     body.stock,
            "pnl_total": body.pnl_total,
            "id":        saved.get("id"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Outcome save error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# ── GET /api/outcomes — fetch all outcomes for logged-in user ──
@router.get("")
def get_outcomes(email: str = Depends(get_email_from_token)):
    """Returns all tracked outcomes for the authenticated user."""
    from scanner.database import get_supabase_client

    try:
        sb = get_supabase_client()
        result = (
            sb.table("trade_outcomes")
            .select("*")
            .eq("email", email)
            .order("created_at", desc=True)
            .execute()
        )
        trades = result.data or []

        # Compute summary stats
        wins   = [t for t in trades if t.get("outcome") == "WIN"]
        losses = [t for t in trades if t.get("outcome") == "LOSS"]
        total  = len(wins) + len(losses)

        return {
            "trades":    trades,
            "summary": {
                "total_tracked": total,
                "wins":          len(wins),
                "losses":        len(losses),
                "win_rate":      round(len(wins) / total * 100, 1) if total > 0 else 0,
                "total_pnl":     round(sum(t.get("pnl_total") or 0 for t in trades), 2),
                "avg_win":       round(sum(t.get("pnl_total") or 0 for t in wins)   / len(wins),   2) if wins   else 0,
                "avg_loss":      round(sum(t.get("pnl_total") or 0 for t in losses) / len(losses), 2) if losses else 0,
            }
        }

    except Exception as e:
        logging.error(f"Outcome fetch error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# ── DELETE /api/outcomes/{id} — remove a tracked trade ────────
@router.delete("/{outcome_id}")
def delete_outcome(outcome_id: int, email: str = Depends(get_email_from_token)):
    """Deletes a specific outcome by ID (only if it belongs to the user)."""
    from scanner.database import get_supabase_client

    try:
        sb = get_supabase_client()
        result = (
            sb.table("trade_outcomes")
            .delete()
            .eq("id", outcome_id)
            .eq("email", email)   # security: can only delete own records
            .execute()
        )
        return {"success": True, "deleted_id": outcome_id}
    except Exception as e:
        logging.error(f"Outcome delete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))