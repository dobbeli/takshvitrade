"""
Takshvi Trade — Core Scanner Engine
Integrates user's Block 4–7 scanner code into FastAPI
"""

import time
import logging
import yfinance as yf
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed 

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
#GLOBAL FUNCTION
def flatten_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})
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
    df = None
    
    # 🔁 Retry logic (3 attempts)
    for i in range(3):
        try:
            print(f"Trying fetch: {symbol}")

            df = yf.download(
                symbol,
                period="1y",
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=False
            )

            if df is not None and not df.empty:
                break
            else:
                print(f"⚠️ Empty response, retrying... ({i+1})")
                time.sleep(0.3)

        except Exception as e:
            print(f"⚠️ Fetch error for {symbol}: {e}")
            df = None
            time.sleep(0.3)


    # ❌ If still empty → reject
    if df is None or df.empty:
        print(f"❌ Yahoo returned empty for {symbol}")
        return None

    try:
        # ✅ Flatten columns (IMPORTANT FIX)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # ✅ Remove duplicate columns
        df = df.loc[:, ~df.columns.duplicated()]

        # ✅ Required columns check
        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required):
            print(f"❌ Missing required columns for {symbol}")
            return None

        # ✅ Keep only required columns
        df = df[required].copy()

        # ✅ Convert to numeric
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # ✅ Drop NaN rows
        df = df.dropna()

        # ✅ Minimum data check (EMA 200 safe)
        if len(df) < 200:
            print(f"❌ Not enough data for {symbol}")
            return None

        print(f"✅ Data OK: {symbol} | Rows: {len(df)}")

        return df

    except Exception as e:
        print(f"❌ Processing error for {symbol}: {e}")
        return None
    

# ── BLOCK 5: Technical indicators ────────────────────────────
def add_indicators(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty or len(df) < 200:
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
        df = df.fillna(method="bfill").fillna(method="ffill")
        df = df.dropna(subset=["EMA20","EMA50","EMA200","RSI","ATR"])
        if len(df) < 5:
            return None
        return df
    except Exception as e:
        print(f"⚠️ Indicator error: {e}")
        print(f"After indicators rows: {len(df)}")
        return None


# ── BLOCK 6: Scoring system ───────────────────────────────────
def score_stock(df: pd.DataFrame):
    latest = df.iloc[-1]
    prev   = df.iloc[-2]

    score = 0
    reasons = []

    ema20  = float(latest["EMA20"])
    ema50  = float(latest["EMA50"])
    ema200 = float(latest["EMA200"])
    rsi    = float(latest["RSI"])
    vol    = float(latest["Volume"])
    vsma   = float(latest["VOL_SMA"])

 # TREND
    if ema20 > ema50 > ema200:
      score += 30
      reasons.append("Strong Uptrend")
    elif ema20 > ema50:
        score += 15
        reasons.append("Moderate Uptrend")
    else:
        score += 5
        reasons.append("Weak Trend")

    # PULLBACK
    pullback = abs(latest["Close"] - ema20) / ema20
    if pullback <= 0.03:
        score += 20
        reasons.append("Near EMA20")

    # MOMENTUM
    if latest["Close"] > prev["Close"]:
        score += 15
        reasons.append("Bullish candle")

    # RSI
    if 50 < rsi < 70:
        score += 15
        reasons.append("Healthy RSI")

    # VOLUME
    if vsma > 0 and vol > vsma:
        score += 10
        reasons.append("Volume support")

    # EMA slope
    if df["EMA20"].iloc[-1] > df["EMA20"].iloc[-2]:
        score += 10
        reasons.append("EMA rising")

    return score, reasons

# ── BLOCK 7: Trade level calculator ──────────────────────────
def calculate_trade_levels(df: pd.DataFrame, capital=CAPITAL, risk_amount=RISK_AMOUNT):
    if len(df) < 3:
        return None

    latest = df.iloc[-1]
    prev   = df.iloc[-2]

    close = float(latest["Close"])
    atr   = float(latest["ATR"])

    if atr <= 0 or close <= 0:
        return None

    # ── Entry (breakout above previous high)
    entry = round(float(prev["High"]) * 1.001, 2)

    # ── Stop loss (ATR based)
    stop = round(entry - 1.5 * atr, 2)

    # ── Target (2R–3R zone)
    target = round(entry + 3.0 * atr, 2)

    # ── Risk per share
    risk = entry - stop
    if risk <= 0:
        return None

    # ── Risk-Reward check
    rr = (target - entry) / risk
    if rr < 1.5:
        return None

    # ── Position sizing (BEST PRACTICE)
    # Risk-based qty
    qty_risk = risk_amount / risk

    # Capital cap (20% allocation per trade)
    qty_cap = (capital * 0.20) / entry

    # Final qty
    qty = int(min(qty_risk, qty_cap))
    if qty <= 0:
        return None

    return {
        "entry":    entry,
        "stop":     stop,
        "target":   target,
        "qty":      qty,
        "atr":      round(atr, 2),
        "rr":       round(rr, 2),
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

    #  ADD BELOW IMPORTS OR ABOVE scan_stock()

def get_news_sentiment(news_list):
    positive_keywords = [
        "growth", "profit", "bullish", "strong", "upgrade",
        "record", "expansion", "beat", "surge", "positive"
    ]

    negative_keywords = [
        "loss", "decline", "bearish", "weak", "downgrade",
        "fall", "drop", "miss", "crash", "negative"
    ]

    score = 0

    for news in news_list:
        text = news.get("title", "").lower()

        for word in positive_keywords:
            if word in text:
                score += 1

        for word in negative_keywords:
            if word in text:
                score -= 1

    return score


# ── Full pipeline: scan one stock ────────────────────────────
def scan_stock(symbol: str, capital=CAPITAL, risk_amount=RISK_AMOUNT) -> Optional[dict]:
    try:
        df = get_stock_data(symbol)

        if df is None:
            print(f"⚠️ Data fetch failed: {symbol}")
            return None
        else:
            print(f"📊 Data OK: {symbol}, Rows: {len(df)}")

        # Indicators
        df = add_indicators(df)
        if df is None:
            print(f"❌ Indicators failed: {symbol}")
            return None
        else:
            print(f"✅ Indicators OK: {symbol}, rows: {len(df)}")

        # 👉 FORCE RETURN TEST (IMPORTANT)
        latest = df.iloc[-1]

        print(f"🔥 FINAL RETURN HIT: {symbol}")

        return {
            "stock": symbol.replace(".NS", ""),
            "close": float(latest["Close"]),
            "entry": float(latest["Close"]),
            "stop_loss": float(latest["Close"]) * 0.97,
            "target": float(latest["Close"]) * 1.05,
            "qty": 1,
            "position": float(latest["Close"]),
            "rr": 1.2,
            "score": 50
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
            df.columns = df.columns.get_level_values(0)

            df = df.loc[:, ~df.columns.duplicated()]
        print("NIFTY DF COLUMNS:", df.columns.tolist())

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

    print(f"🚀 Running parallel scan for {len(stocks)} stocks...")

    start = time.time()
    MAX_SCAN_TIME = 25   # ⏱️ total scan timeout

    # 🔥 Parallel execution
    # 🔥 Sequential execution (FIXED)
    for stock in stocks:
        print(f"🚀 Scanning: {stock}")

    r = scan_stock(stock, capital, risk_amount)

    print(f"🔥 RESULT: {r}")

    if r is not None:
        print(f"✅ ADDED: {stock}")
        results.append(r)
    else:
        print(f"❌ SKIPPED: {stock}")
    # Filter (relaxed for testing)
    results = results

    print(f"📊 Total Passed Stocks: {len(results)}")

    if not results:
        print("⚠️ No stocks passed, returning empty list")

    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:MAX_POSITIONS]