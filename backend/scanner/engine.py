"""
Takshvi Trade — Core Scanner Engine
Integrates user's Block 4–7 scanner code into FastAPI
"""
import yfinance as yf
import pandas as pd
import numpy as np
import ta
from datetime import datetime
from typing import Optional

# ── Config ──────────────────────────────────────────────────
CAPITAL      = 100000   # ₹ default, overridden per user
RISK_AMOUNT  = 2000     # ₹ max risk per trade
MAX_POSITIONS = 5

NIFTY50_STOCKS = [
    "RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK",
    "HINDUNILVR","SBIN","BHARTIARTL","KOTAKBANK","ITC",
    "LT","AXISBANK","BAJFINANCE","ASIANPAINT","MARUTI",
    "TITAN","SUNPHARMA","ULTRACEMCO","WIPRO","HCLTECH",
    "NESTLEIND","POWERGRID","NTPC","ONGC","TECHM",
    "ADANIENT","ADANIPORTS","BAJAJFINSV","DIVISLAB","DRREDDY",
    "EICHERMOT","GRASIM","HEROMOTOCO","HINDALCO","INDUSINDBK",
    "JSWSTEEL","M&M","SBILIFE","SHREECEM","TATACONSUM",
    "TATAMOTORS","TATASTEEL","COALINDIA","BPCL","CIPLA",
    "APOLLOHOSP","BAJAJ-AUTO","BRITANNIA","HDFCLIFE","UPL"
]


# ── BLOCK 4: Download price history ─────────────────────────
def get_stock_data(symbol: str) -> Optional[pd.DataFrame]:
    try:
        df = yf.download(
            symbol, period="2y", interval="1d",
            progress=False, auto_adjust=True, threads=False
        )
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in required):
            return None
        df = df[required].copy()
        for col in required:
            df[col] = pd.to_numeric(df[col].values.flatten(), errors="coerce")
        df = df.dropna()
        if len(df) < 210:
            return None
        return df
    except Exception:
        return None


# ── BLOCK 5: Technical indicators ────────────────────────────
def add_indicators(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty or len(df) < 220:
        return None
    try:
        close  = pd.Series(df["Close"].values.flatten(),  index=df.index, dtype=float).ffill().bfill()
        high   = pd.Series(df["High"].values.flatten(),   index=df.index, dtype=float).ffill().bfill()
        low    = pd.Series(df["Low"].values.flatten(),    index=df.index, dtype=float).ffill().bfill()
        volume = pd.Series(df["Volume"].values.flatten(), index=df.index, dtype=float).fillna(0)

        if close.isnull().sum() > len(close) * 0.05:
            return None

        df = df.copy()
        df["EMA20"]    = ta.trend.ema_indicator(close, window=20).values
        df["EMA50"]    = ta.trend.ema_indicator(close, window=50).values
        df["EMA200"]   = ta.trend.ema_indicator(close, window=200).values
        df["RSI"]      = ta.momentum.rsi(close, window=14).values
        df["ATR"]      = ta.volatility.average_true_range(high, low, close, window=14).values
        df["VOL_SMA"]  = volume.rolling(10).mean().values
        df["HIGH_52W"] = df["High"].rolling(252).max().values
        df = df.dropna()
        if len(df) < 5:
            return None
        return df
    except Exception as e:
        print(f"⚠️ Indicator error: {e}")
        return None


# ── BLOCK 6: Scoring system ───────────────────────────────────
def score_stock(df: pd.DataFrame):
    latest  = df.iloc[-1]
    score   = 0
    reasons = []

    # Trend (40 pts)
    if latest["EMA20"] > latest["EMA50"] > latest["EMA200"]:
        score += 40; reasons.append("✅ Full EMA stack (20>50>200)")
    elif latest["EMA20"] > latest["EMA50"]:
        score += 25; reasons.append("⚠️ Partial trend (20>50 only)")
    elif latest["EMA50"] > latest["EMA200"]:
        score += 10; reasons.append("⚠️ Weak trend (50>200 only)")
    else:
        score += 0      # ← Allow weak stocks through, score will be low
        reasons.append("❌ No EMA alignment")
    # Remove the hard return 0 — let other factors decide

    # RSI (20 pts)
    rsi = latest["RSI"]
    if 55 < rsi < 70:
        score += 20; reasons.append(f"✅ RSI strong ({rsi:.0f})")
    elif 45 < rsi <= 55:
        score += 12; reasons.append(f"⚠️ RSI neutral ({rsi:.0f})")
    elif 40 < rsi <= 45:
        score += 5;  reasons.append(f"⚠️ RSI soft ({rsi:.0f})")
    elif rsi >= 70:
        score -= 5;  reasons.append(f"⚠️ RSI overbought ({rsi:.0f})")
    else:
        return 0, []

    # Volume (20 pts)
    vol_ratio = latest["Volume"] / latest["VOL_SMA"] if latest["VOL_SMA"] > 0 else 0
    if vol_ratio >= 1.5:
        score += 20; reasons.append(f"✅ Volume surge ({vol_ratio:.1f}x)")
    elif vol_ratio >= 1.0:
        score += 12; reasons.append(f"⚠️ Volume average ({vol_ratio:.1f}x)")
    elif vol_ratio >= 0.7:
        score += 5;  reasons.append(f"⚠️ Volume soft ({vol_ratio:.1f}x)")

    # 52W High proximity (20 pts)
    proximity = latest["Close"] / latest["HIGH_52W"] if latest["HIGH_52W"] > 0 else 0
    if proximity >= 0.95:
        score += 20; reasons.append(f"✅ Near 52W high ({proximity*100:.0f}%)")
    elif proximity >= 0.85:
        score += 12; reasons.append(f"⚠️ Moderate from 52W high ({proximity*100:.0f}%)")
    elif proximity >= 0.75:
        score += 5;  reasons.append(f"⚠️ Away from 52W high ({proximity*100:.0f}%)")

    if score < 25:
        return 0, []
    return score, reasons


# ── BLOCK 7: Trade level calculator ──────────────────────────
def calculate_trade_levels(df: pd.DataFrame, capital=CAPITAL, risk_amount=RISK_AMOUNT):
    latest = df.iloc[-1]
    close  = float(latest["Close"])
    atr    = float(latest["ATR"])
    if atr <= 0 or close <= 0:
        return None

    entry  = round(close * 1.002, 2)
    stop   = round(entry - 1.5 * atr, 2)
    target = round(entry + 3.0 * atr, 2)
    risk   = entry - stop

    if risk <= 0: return None

    qty = int(risk_amount / risk)
    if qty <= 0: return None

    if entry * qty > capital * 0.20:
        qty = int((capital * 0.20) / entry)
    if qty <= 0: return None

    return {
        "entry":    entry,
        "stop":     stop,
        "target":   target,
        "qty":      qty,
        "atr":      round(atr, 2),
        "rr":       round((target - entry) / risk, 2),
        "position": round(entry * qty, 2)
    }


# ── Pre-approval helpers ──────────────────────────────────────
def get_candle_type(row) -> str:
    body = float(row["Close"]) - float(row["Open"])
    rng  = float(row["High"])  - float(row["Low"])
    if rng == 0: return "Neutral"
    pct = abs(body) / rng
    if body > 0 and pct > 0.5: return "Bullish"
    if body < 0 and pct > 0.5: return "Bearish"
    return "Neutral"

def is_ema20_rising(df: pd.DataFrame) -> bool:
    if len(df) < 4: return False
    e = df["EMA20"].values
    return bool(e[-1] > e[-2] > e[-3] > e[-4])

def is_pullback_to_ema20(df: pd.DataFrame) -> bool:
    r = df.iloc[-1]
    ema20 = float(r["EMA20"])
    return float(r["Low"]) <= ema20 * 1.02 and float(r["Close"]) > ema20


# ── Full pipeline: scan one stock ────────────────────────────
def scan_stock(symbol: str, capital=CAPITAL, risk_amount=RISK_AMOUNT) -> Optional[dict]:
    try:
        df = get_stock_data(symbol)
        if df is None: return None
        df = add_indicators(df)
        if df is None: return None
        score, reasons = score_stock(df)
        if score == 0: return None
        trade = calculate_trade_levels(df, capital, risk_amount)
        if trade is None: return None

        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        if abs(trade["entry"] - float(latest["Close"])) / float(latest["Close"]) > 0.05:
            return None

        # Pre-approval checklist
        ema20  = float(latest["EMA20"])
        ema50  = float(latest["EMA50"])
        ema200 = float(latest["EMA200"])
        rsi    = float(latest["RSI"])
        vol    = float(latest["Volume"])
        vsma   = float(latest["VOL_SMA"])

        checklist = {
            "ema_stack":    bool(ema20 > ema50 > ema200),
            "ema20_rising": is_ema20_rising(df),
            "rsi_healthy":  bool(50 < rsi < 70),
            "volume_above": bool(vol > vsma),
            "candle_ok":    get_candle_type(latest) != "Bearish",
            "pullback":     is_pullback_to_ema20(df),
        }
        checks_passed = sum(checklist.values())
        upside_pct = round(((trade["target"] - trade["entry"]) / trade["entry"]) * 100, 2)

        return {
            "stock":          symbol.replace(".NS", ""),
            "close":          round(float(latest["Close"]), 2),
            "prev_high":      round(float(prev["High"]), 2),
            "prev_low":       round(float(prev["Low"]), 2),
            "entry":          trade["entry"],
            "stop_loss":      trade["stop"],
            "target":         trade["target"],
            "qty":            trade["qty"],
            "position":       trade["position"],
            "atr":            trade["atr"],
            "rr":             trade["rr"],
            "score":          score,
            "upside_pct":     upside_pct,
            "reasons":        reasons,
            "checklist":      checklist,
            "checks_passed":  checks_passed,
            "ema20":          round(ema20, 2),
            "ema50":          round(ema50, 2),
            "ema200":         round(ema200, 2),
            "rsi":            round(rsi, 1),
            "vol_ratio":      round(vol / vsma, 2) if vsma > 0 else 0,
            "candle":         get_candle_type(latest),
            "scanned_at":     datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"⚠️ Error scanning {symbol}: {e}")
        return None


# ── Market health check ───────────────────────────────────────
def check_market_status() -> dict:
    try:
        df = yf.download("^NSEI", period="3mo", interval="1d",
                         progress=False, auto_adjust=False,threads=False)
        if df is None or df.empty:
            return {"bullish": True, "error": "Could not fetch NIFTY"}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        close  = pd.Series(df["Close"].values.flatten(), index=df.index, dtype=float)
        ema50  = float(ta.trend.ema_indicator(close, window=50).iloc[-1])
        ema200 = float(ta.trend.ema_indicator(close, window=200).iloc[-1])
        rsi    = float(ta.momentum.rsi(close, window=14).iloc[-1])
        price  = float(close.iloc[-1])

        bullish = price > ema50 and price > ema200 and rsi > 40

        return {
            "price":   round(price, 2),
            "ema50":   round(ema50, 2),
            "ema200":  round(ema200, 2),
            "rsi":     round(rsi, 1),
            "bullish": bullish,
            "verdict": "BULLISH" if bullish else "BEARISH",
            "above_ema50":  price > ema50,
            "above_ema200": price > ema200,
            "checked_at":   datetime.now().isoformat(),
        }
    except Exception as e:
        return {"bullish": True, "error": str(e)}


# ── Full scan runner ──────────────────────────────────────────
def run_full_scan(capital=CAPITAL, risk_amount=RISK_AMOUNT) -> list:
    results = []
    stocks  = [s + ".NS" for s in NIFTY50_STOCKS]
    for stock in stocks:
        r = scan_stock(stock, capital, risk_amount)
        if r:
            results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results
