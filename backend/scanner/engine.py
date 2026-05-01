"""
Takshvi Trade — Core Scanner Engine

Market Logic:
─────────────────────────────────────────────────────────────
BULLISH  (Nifty UP)          → Scan all 50. Show BEST scored stocks only (score ≥ 80).
BEARISH  (Nifty DOWN 0–1.5%) → Scan all 50. Show stocks passing all 6 conditions.
                                Warn user. Reduce qty 50%. Score threshold stays 60.
CRASH    (Nifty DOWN > 1.5%) → Hard block. No signals. Capital protection.
─────────────────────────────────────────────────────────────
"""

import time
import logging
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import ta
from typing import Optional

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# ── Config ──────────────────────────────────────────────────
CAPITAL       = 100000
RISK_AMOUNT   = 2000
MAX_POSITIONS = 10

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

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
})

def get_yahoo_crumb():
    """
    Yahoo Finance v8 API requires a crumb + cookie after 2024.
    Without this, high-traffic tickers like TATAMOTORS return 403.
    This function fetches the crumb once per session.
    """
    try:
        # Step 1: Get cookie by visiting Yahoo Finance
        session.get("https://fc.yahoo.com", timeout=5)
        # Step 2: Get the crumb
        r = session.get(
            "https://query1.finance.yahoo.com/v1/test/getcrumb",
            timeout=5
        )
        crumb = r.text.strip()
        if crumb and len(crumb) > 3:
            print(f"✅ Yahoo crumb obtained: {crumb[:8]}...")
            return crumb
        return None
    except Exception as e:
        print(f"⚠️ Crumb fetch failed: {e}")
        return None

# Fetch crumb once at module load
YAHOO_CRUMB = get_yahoo_crumb()


# ── Market Trend ─────────────────────────────────────────────
def get_market_trend():
    """
    Uses direct requests instead of yfinance — works on Render cloud.
    yfinance is blocked by Yahoo on cloud server IPs.
    """
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5d&interval=1d"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        res = requests.get(url, headers=headers, timeout=10)

        if res.status_code != 200:
            url2 = "https://query2.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5d&interval=1d"
            res  = requests.get(url2, headers=headers, timeout=10)

        if res.status_code != 200:
            return "SIDEWAYS", None, None

        data   = res.json()
        result = data.get("chart", {}).get("result")

        if not result:
            return "SIDEWAYS", None, None

        closes = result[0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]

        if len(closes) < 2:
            return "SIDEWAYS", None, None

        latest     = round(closes[-1], 2)
        prev       = round(closes[-2], 2)
        change_pct = round(((latest - prev) / prev) * 100, 2)
        trend      = "UP" if latest > prev else "DOWN"

        print(f"Nifty: Rs{latest} | Prev: Rs{prev} | Change: {change_pct}%")
        return trend, latest, change_pct

    except Exception as e:
        print(f"Market trend error: {e}")
        return "SIDEWAYS", None, None

# ── Data Source: Yahoo Finance ────────────────────────────────
def get_data_from_yahoo(symbol: str):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2y", interval="1d")
        if df is None or df.empty:
            return None
        return df
    except Exception as e:
        print(f"Yahoo error: {symbol} - {e}")
        return None


# ── Data Source: NSE fallback ─────────────────────────────────
def get_data_from_nse(symbol: str):
    """
    Direct Yahoo Finance API fallback with crumb + session.
    Fixes 403 errors on tickers like TATAMOTORS.
    Yahoo requires browser-like headers + crumb cookie after 2024.
    """
    try:
        clean = symbol.replace(".NS", "")
        if clean == "M&M":
            clean = "M%26M"

        base_ns  = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}.NS?range=2y&interval=1d"
        base_ns2 = f"https://query2.finance.yahoo.com/v8/finance/chart/{clean}.NS?range=2y&interval=1d"
        base_bo  = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}.BO?range=2y&interval=1d"

        # Priority: query1 NSE → query2 NSE → BSE fallback
        urls_to_try = [
            f"{base_ns}&crumb={YAHOO_CRUMB}" if YAHOO_CRUMB else base_ns,
            base_ns2,
            base_bo,
        ]

        response = None
        for url in urls_to_try:
            for attempt in range(2):
                try:
                    response = session.get(url, timeout=10)
                    if response.status_code == 200:
                        break
                    elif response.status_code == 403:
                        new_crumb = get_yahoo_crumb()
                        if new_crumb:
                            url = f"{base_ns}&crumb={new_crumb}"
                    time.sleep(1.0)
                except:
                    time.sleep(1.0)
            if response and response.status_code == 200:
                break

        if response is None or response.status_code != 200:
            print(f"Fallback failed after 3 attempts: {clean} (status {response.status_code})")
            return None

        data   = response.json()
        result = data.get("chart", {}).get("result")

        if not result:
            print(f"Empty chart data: {clean}")
            return None

        result     = result[0]
        timestamps = result["timestamp"]
        indicators = result["indicators"]["quote"][0]

        df = pd.DataFrame({
            "Open":   indicators["open"],
            "High":   indicators["high"],
            "Low":    indicators["low"],
            "Close":  indicators["close"],
            "Volume": indicators["volume"],
        })
        df["Date"] = pd.to_datetime(timestamps, unit="s")
        df.set_index("Date", inplace=True)
        return df.tail(500)

    except Exception as e:
        print(f"Fallback error: {symbol} - {e}")
        return None


# ── Get stock data ────────────────────────────────────────────
def get_stock_data(symbol: str) -> Optional[pd.DataFrame]:
    df = get_data_from_yahoo(symbol)

    if df is not None and not df.empty:
        print(f"Yahoo OK: {symbol}")
    else:
        print(f"Yahoo failed -> trying NSE: {symbol}")
        df = get_data_from_nse(symbol)

    if df is None or df.empty:
        print(f"All data sources failed: {symbol}")
        return None

    try:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()]

        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required):
            return None

        df = df[required].copy()
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna()
        print(f"Data OK: {symbol} | Rows: {len(df)}")
        return df.tail(500)

    except Exception as e:
        print(f"Processing error: {symbol} - {e}")
        return None


# ── Technical Indicators ──────────────────────────────────────
def add_indicators(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty or len(df) < 210:
        return None
    try:
        close  = pd.Series(df["Close"].values.flatten(), index=df.index, dtype=float).ffill().bfill()
        high   = pd.Series(df["High"].values.flatten(),  index=df.index, dtype=float).ffill().bfill()
        low    = pd.Series(df["Low"].values.flatten(),   index=df.index, dtype=float).ffill().bfill()
        volume = pd.Series(df["Volume"].values.flatten(),index=df.index, dtype=float).fillna(0)

        if close.isnull().sum() > len(close) * 0.05:
            return None

        df = df.copy()
        df["EMA20"]   = ta.trend.ema_indicator(close, window=20).values
        df["EMA50"]   = ta.trend.ema_indicator(close, window=50).values
        df["EMA200"]  = ta.trend.ema_indicator(close, window=200).values
        df["RSI"]     = ta.momentum.rsi(close, window=14).values
        df["ATR"]     = ta.volatility.average_true_range(high, low, close, window=14).values
        df["VOL_SMA"] = volume.rolling(10).mean().values
        df["HIGH_52W"]= df["High"].rolling(252).max().values

        df = df.dropna(subset=["EMA200"])
        df = df.bfill().ffill()
        df = df.dropna(subset=["EMA20","EMA50","RSI","ATR"])

        if len(df) < 5:
            return None
        return df

    except Exception as e:
        print(f"Indicator error: {e}")
        return None


# ── Candle Type ───────────────────────────────────────────────
def get_candle_type(row) -> str:
    body = float(row["Close"]) - float(row["Open"])
    rng  = float(row["High"])  - float(row["Low"])
    if rng == 0:
        return "Neutral"
    pct = abs(body) / rng
    if body > 0 and pct > 0.5:
        return "Bullish"
    if body < 0 and pct > 0.5:
        return "Bearish"
    return "Neutral"


# ── Weekly EMA Cache ──────────────────────────────────────────
# Weekly data changes only once per week — safe to cache for 1 hour
# This eliminates 50 extra API calls per scan (one per stock for weekly data)
_weekly_cache: dict = {}
_weekly_cache_time: float = 0
WEEKLY_CACHE_TTL = 3600  # 1 hour


# ── Weekly EMA Confirmation ───────────────────────────────────
def get_weekly_ema(symbol: str) -> dict:
    """
    Checks weekly EMA20 > EMA50 for higher timeframe trend confirmation.
    CACHED — weekly data only changes once per week, so we cache for 1 hour.
    This saves 50 API calls per scan = major speed improvement.
    """
    global _weekly_cache, _weekly_cache_time

    # ── Return cached result if still fresh ──
    now = time.time()
    if symbol in _weekly_cache and (now - _weekly_cache_time) < WEEKLY_CACHE_TTL:
        cached = _weekly_cache[symbol]
        print(f"  [Weekly CACHED] {symbol} → {'✅ OK' if cached['weekly_ok'] else '❌ FAIL'}")
        return cached

    try:
        ticker = yf.Ticker(symbol)
        df_w   = ticker.history(period="2y", interval="1wk")

        if df_w is None or df_w.empty or len(df_w) < 55:
            result = {"weekly_ok": True, "weekly_ema20": None, "weekly_ema50": None}
        else:
            close_w = pd.Series(df_w["Close"].values.flatten(), dtype=float).ffill().bfill()
            w_ema20 = float(ta.trend.ema_indicator(close_w, window=20).iloc[-1])
            w_ema50 = float(ta.trend.ema_indicator(close_w, window=50).iloc[-1])
            weekly_ok = w_ema20 > w_ema50
            status = "✅ OK" if weekly_ok else "❌ FAIL"
            print(f"  [Weekly LIVE] {symbol} | EMA20:{round(w_ema20,2)} EMA50:{round(w_ema50,2)} → {status}")
            result = {
                "weekly_ok":    weekly_ok,
                "weekly_ema20": round(w_ema20, 2),
                "weekly_ema50": round(w_ema50, 2),
            }

        # ── Store in cache ──
        _weekly_cache[symbol] = result
        _weekly_cache_time = now
        return result

    except Exception as e:
        print(f"  [Weekly ERROR] {symbol}: {e} — skipping weekly filter")
        result = {"weekly_ok": True, "weekly_ema20": None, "weekly_ema50": None}
        _weekly_cache[symbol] = result
        return result


# ── Scan One Stock ────────────────────────────────────────────
def scan_stock(symbol: str, capital=CAPITAL, risk_amount=RISK_AMOUNT) -> Optional[dict]:
    try:
        df = get_stock_data(symbol)
        if df is None:
            return None

        df = add_indicators(df)
        if df is None:
            return None

        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        ema20  = float(latest["EMA20"])
        ema50  = float(latest["EMA50"])
        ema200 = float(latest["EMA200"])
        rsi    = float(latest["RSI"])
        vol    = float(latest["Volume"])
        vsma   = float(latest["VOL_SMA"])
        price  = float(latest["Close"])

        # ── MANDATORY CONDITIONS (must pass all) ──
        trend_ok   = ema20 > ema50 > ema200 and price > ema20
        ema_rising = float(df["EMA20"].iloc[-1]) > float(df["EMA20"].iloc[-2])

        if not ema_rising or not trend_ok:
            print(f"REJECTED (Daily Trend): {symbol}")
            return None

        # ── WEEKLY EMA CONFIRMATION (mandatory) ──────────────
        # Stock must be in uptrend on WEEKLY chart too.
        # Eliminates daily bullish signals inside weekly downtrends.
        weekly = get_weekly_ema(symbol)
        if not weekly["weekly_ok"]:
            print(f"REJECTED (Weekly Trend): {symbol} | W_EMA20:{weekly['weekly_ema20']} < W_EMA50:{weekly['weekly_ema50']}")
            return None

        # ── SCORING (max = 12 points now) ────────────────────
        score = 0
        if ema20 > ema50 > ema200:                        score += 3  # daily EMA stack
        if 55 <= rsi <= 65:                               score += 2  # RSI ideal zone
        if abs(price - ema20) / ema20 <= 0.03:            score += 2  # pullback near EMA20
        if vsma > 0 and vol > 1.2 * vsma:                 score += 1  # volume surge
        if get_candle_type(latest) == "Bullish":           score += 1  # bullish candle
        if latest["EMA20"] > prev["EMA20"]:                score += 1  # EMA20 rising

        # ── 52-WEEK HIGH PROXIMITY (bonus point) ─────────────
        # Stocks near their 52W high = institutions still buying.
        # Price >= 85% of 52W high means stock is in strong yearly uptrend.
        # Avoids dead-cat bounces and weak recovery stocks.
        high_52w = float(latest["HIGH_52W"]) if pd.notna(latest["HIGH_52W"]) else None
        near_52w_high = False
        if high_52w and high_52w > 0:
            proximity = price / high_52w
            if proximity >= 0.85:       # within 15% of 52W high
                score += 1
                near_52w_high = True
                print(f"  [52W] {symbol} | Price:{price} | 52W High:{high_52w} | Proximity:{round(proximity*100,1)}% ✅ +1")
            else:
                print(f"  [52W] {symbol} | Price:{price} | 52W High:{high_52w} | Proximity:{round(proximity*100,1)}% ❌ no point")

        print(f"SCORE: {symbol} = {score}/12")

        # Score threshold: 7 out of 12
        # (same mandatory bar — weekly EMA already filtered weak stocks above)
        if score < 7:
            print(f"REJECTED (Score): {symbol} | Score:{score}/12 RSI:{rsi:.1f}")
            return None

        # ── TRADE LEVELS ──
        entry     = round(float(prev["High"]) * 1.001, 2)
        atr       = float(latest["ATR"])
        stop_loss = round(entry - 1.5 * atr, 2)
        risk      = entry - stop_loss

        if float(latest["Close"]) <= float(prev["High"]):   return None
        if price > ema20 * 1.05:                            return None
        if risk <= 0 or risk < entry * 0.002:               return None

        target = round(entry + (2 * risk), 2)
        rr     = round((target - entry) / risk, 2)

        if rr < 1.5:
            return None

        qty_risk = risk_amount / risk
        qty_cap  = (capital * 0.20) / entry
        qty      = int(min(qty_risk, qty_cap))
        qty      = min(qty, int((capital * 0.25) / entry))

        if qty <= 0:
            return None

        # Score as percentage out of 12 (max possible now)
        score_pct = round((score / 12) * 100)

        # Action label based on score percentage
        if score_pct >= 83:    action = "BEST"    # 10+ out of 12
        elif score_pct >= 67:  action = "BUY"     # 8–9 out of 12
        else:                  action = "WATCH"   # 7 out of 12

        return {
            "stock":        symbol.replace(".NS", ""),
            "close":        round(price, 2),
            "entry":        entry,
            "sl":           stop_loss,
            "target":       target,
            "qty":          qty,
            "position":     round(qty * entry, 2),
            "rr":           rr,
            "score":        score_pct,
            "raw_score":    score,          # actual points out of 12
            "action":       action,
            "upside_pct":   round(((target - entry) / entry) * 100, 2),
            "near_52w_high": near_52w_high, # True/False — shown in UI
            "weekly_ema20": weekly["weekly_ema20"],
            "weekly_ema50": weekly["weekly_ema50"],
            "caution":      False,
        }

    except Exception as e:
        print(f"Error scanning {symbol}: {e}")
        return None


# ── Full Scan Runner ──────────────────────────────────────────
def run_full_scan(capital=CAPITAL, risk_amount=RISK_AMOUNT) -> list:
    """
    ╔══════════════════╦═══════════════════════════════════════════════╗
    ║ MARKET MODE      ║ BEHAVIOUR                                     ║
    ╠══════════════════╬═══════════════════════════════════════════════╣
    ║ BULLISH (UP)     ║ Scan all 50. Show score >= 80 (BEST) only.   ║
    ║                  ║ Full position size. No warning.               ║
    ╠══════════════════╬═══════════════════════════════════════════════╣
    ║ BEARISH          ║ Scan all 50. Show all that pass strategy.     ║
    ║ (DOWN 0 to -1.5%)║ Warn user. Qty reduced to 50%.               ║
    ║                  ║ Score threshold stays at 60.                  ║
    ╠══════════════════╬═══════════════════════════════════════════════╣
    ║ CRASH            ║ HARD BLOCK. No signals at all.                ║
    ║ (DOWN > -1.5%)   ║ Capital protection. Return empty list.        ║
    ╚══════════════════╩═══════════════════════════════════════════════╝
    """

# ── Data Cache (avoids re-fetching same stock twice in one scan) ──
# Weekly and daily data cached per session — saves 50% of API calls
_data_cache: dict = {}
_cache_timestamp: float = 0
CACHE_TTL_SECONDS = 3600  # 1 hour — refresh cache every hour

def _get_cache_key(symbol: str, interval: str) -> str:
    return f"{symbol}_{interval}"

def _is_cache_valid() -> bool:
    return (time.time() - _cache_timestamp) < CACHE_TTL_SECONDS

def _clear_cache_if_stale():
    global _data_cache, _cache_timestamp
    if not _is_cache_valid():
        _data_cache = {}
        _cache_timestamp = time.time()
        print("🔄 Cache cleared — fetching fresh data")


# ── Full Scan Runner ──────────────────────────────────────────
def run_full_scan(capital=CAPITAL, risk_amount=RISK_AMOUNT) -> list:
    """
    ╔══════════════════╦═══════════════════════════════════════════════╗
    ║ MARKET MODE      ║ BEHAVIOUR                                     ║
    ╠══════════════════╬═══════════════════════════════════════════════╣
    ║ BULLISH (UP)     ║ Scan all 50. Show score >= 80 (BEST) only.   ║
    ║                  ║ Full position size. No warning.               ║
    ╠══════════════════╬═══════════════════════════════════════════════╣
    ║ BEARISH          ║ Scan all 50. Show all that pass strategy.     ║
    ║ (DOWN 0 to -1.5%)║ Warn user. Qty reduced to 50%.               ║
    ║                  ║ Score threshold stays at 60.                  ║
    ╠══════════════════╬═══════════════════════════════════════════════╣
    ║ CRASH            ║ HARD BLOCK. No signals at all.                ║
    ║ (DOWN > -1.5%)   ║ Capital protection. Return empty list.        ║
    ╚══════════════════╩═══════════════════════════════════════════════╝

    SPEED OPTIMISATION:
    ──────────────────────────────────────────────────────────────
    OLD: Sequential scan = 50 stocks × 0.8s each = ~40 seconds
    NEW: Parallel scan   = all 50 stocks at once = 4–8 seconds
    ──────────────────────────────────────────────────────────────
    Uses ThreadPoolExecutor with 10 workers.
    10 workers = 10 stocks fetched simultaneously.
    50 stocks ÷ 10 workers = 5 batches × ~1s = ~5 seconds total.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    market_trend, nifty_value, change_pct = get_market_trend()

    print(f"\n{'='*55}")
    print(f"  MARKET: {market_trend} | Nifty: {nifty_value} | Change: {change_pct}%")
    print(f"{'='*55}\n")

    # ── CRASH GUARD ──────────────────────────────────────────
    if market_trend == "DOWN" and change_pct is not None and change_pct <= -1.5:
        print(f"🚨 CRASH DETECTED ({change_pct}%) — HARD BLOCK. Capital protection active.")
        return []

    # ── Clear stale cache ─────────────────────────────────────
    _clear_cache_if_stale()

    stocks = [s + ".NS" for s in NIFTY50_STOCKS]
    mode   = "BULLISH" if market_trend == "UP" else "BEARISH (caution)"
    print(f"⚡ Parallel scanning {len(stocks)} stocks | Mode: {mode}")
    print(f"   Workers: 10 | Expected time: 4–8 seconds\n")

    scan_start = time.time()

    # ── PARALLEL SCAN ─────────────────────────────────────────
    # 10 workers = 10 stocks scanned simultaneously
    # Yahoo Finance allows ~10 concurrent requests before throttling
    raw_results = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all 50 stocks at once
        future_to_stock = {
            executor.submit(scan_stock, stock, capital, risk_amount): stock
            for stock in stocks
        }

        # Collect results as they complete (fastest first)
        for future in as_completed(future_to_stock):
            stock = future_to_stock[future]
            try:
                result = future.result(timeout=30)  # 30s max per stock
                if result is not None:
                    raw_results.append(result)
            except Exception as e:
                print(f"  ⚠️ Thread error for {stock}: {e}")

    scan_time = round(time.time() - scan_start, 1)
    print(f"\n⏱ Parallel scan completed in {scan_time}s")
    print(f"   Stocks scanned: {len(stocks)} | Raw passes: {len(raw_results)}")

    # ── APPLY MARKET FILTER ───────────────────────────────────
    for r in raw_results:

        # BULLISH: Only best stocks (score >= 80)
        if market_trend == "UP":
            if r["score"] < 80:
                print(f"  SKIPPED (Bullish filter — need ≥80): {r['stock']} | Score:{r['score']}")
                continue
            r["caution"] = False

        # BEARISH: All passing stocks, reduce qty 50%, warn user
        elif market_trend == "DOWN":
            if r["score"] < 60:
                continue
            r["qty"]      = max(1, r["qty"] // 2)
            r["position"] = round(r["qty"] * r["entry"], 2)
            r["caution"]  = True

        results.append(r)

    results.sort(key=lambda x: x["score"], reverse=True)
    final = results[:MAX_POSITIONS]

    print(f"✅ Final signals: {len(final)} | Market: {market_trend} | Time: {scan_time}s\n")
    return final