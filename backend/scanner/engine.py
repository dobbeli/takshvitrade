"""
Takshvi Trade — Core Scanner Engine v2.1

SPEED FIX:
- OLD: 4 scanners × 50 stocks × 2 API calls = 400 API calls → 115s
- NEW: 1 fetch per stock, all 4 scanners share data = 50 API calls → 20-30s

Single scan returns complete next-day trading plan:
1. LONG SIGNALS      — confirmed breakout (buy tomorrow)
2. PRE-BREAKOUT      — within 2% of breakout (place BUY STOP tonight)
3. SHORT SIGNALS     — confirmed breakdown (short tomorrow)
4. PRE-BREAKDOWN     — within 2% of breakdown (place SELL STOP tonight)
5. RELATIVE STRENGTH — beating Nifty today (watchlist)
"""

import time
import logging
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import ta
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# ── Config ────────────────────────────────────────────────────
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

# ── Weekly EMA Cache (1 hour TTL) ────────────────────────────
_weekly_cache: dict = {}
_weekly_cache_time: float = 0
WEEKLY_CACHE_TTL = 3600


# ════════════════════════════════════════════════════════════
# MARKET TREND
# ════════════════════════════════════════════════════════════
def get_market_trend():
    """Returns (trend, nifty_value, change_pct) using direct requests."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        for base in ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]:
            try:
                res = requests.get(
                    f"{base}/v8/finance/chart/%5ENSEI?range=5d&interval=1d",
                    headers=headers, timeout=10
                )
                if res.status_code == 200:
                    break
            except:
                continue

        if res.status_code != 200:
            return "SIDEWAYS", None, None

        closes = [c for c in res.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
        if len(closes) < 2:
            return "SIDEWAYS", None, None

        latest     = round(closes[-1], 2)
        prev       = round(closes[-2], 2)
        change_pct = round(((latest - prev) / prev) * 100, 2)
        trend      = "UP" if latest > prev else "DOWN"
        print(f"Nifty: Rs{latest} | Change: {change_pct}%")
        return trend, latest, change_pct
    except Exception as e:
        print(f"Market trend error: {e}")
        return "SIDEWAYS", None, None


# ════════════════════════════════════════════════════════════
# DATA FETCHING
# ════════════════════════════════════════════════════════════
def get_data_from_yahoo(symbol: str):
    try:
        df = yf.Ticker(symbol).history(period="2y", interval="1d")
        return df if df is not None and not df.empty else None
    except:
        return None


def get_data_from_nse(symbol: str):
    try:
        clean = symbol.replace(".NS", "").replace("&", "%26")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
        response = None
        for url in [
            f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}.NS?range=2y&interval=1d",
            f"https://query2.finance.yahoo.com/v8/finance/chart/{clean}.NS?range=2y&interval=1d",
            f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}.BO?range=2y&interval=1d",
        ]:
            try:
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code == 200:
                    response = r
                    break
                time.sleep(0.5)
            except:
                time.sleep(0.5)

        if not response:
            return None

        result = response.json().get("chart", {}).get("result")
        if not result:
            return None

        r = result[0]
        df = pd.DataFrame({
            "Open": r["indicators"]["quote"][0]["open"],
            "High": r["indicators"]["quote"][0]["high"],
            "Low":  r["indicators"]["quote"][0]["low"],
            "Close":r["indicators"]["quote"][0]["close"],
            "Volume":r["indicators"]["quote"][0]["volume"],
        })
        df["Date"] = pd.to_datetime(r["timestamp"], unit="s")
        df.set_index("Date", inplace=True)
        return df.tail(500)
    except Exception as e:
        print(f"NSE fallback error: {symbol} - {e}")
        return None


def get_stock_data(symbol: str) -> Optional[pd.DataFrame]:
    """Fetch daily data — Yahoo first, NSE fallback."""
    df = get_data_from_yahoo(symbol)
    if df is None or df.empty:
        df = get_data_from_nse(symbol)
    if df is None or df.empty:
        return None
    try:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()]
        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in required):
            return None
        df = df[required].copy()
        for c in required:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna().tail(500)
    except:
        return None


def add_indicators(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Add EMA/RSI/ATR/Volume indicators. Needs 210+ rows for valid EMA200."""
    if df is None or len(df) < 210:
        return None
    try:
        close  = pd.Series(df["Close"].values.flatten(), index=df.index, dtype=float).ffill().bfill()
        high   = pd.Series(df["High"].values.flatten(),  index=df.index, dtype=float).ffill().bfill()
        low    = pd.Series(df["Low"].values.flatten(),   index=df.index, dtype=float).ffill().bfill()
        volume = pd.Series(df["Volume"].values.flatten(),index=df.index, dtype=float).fillna(0)

        df = df.copy()
        df["EMA20"]    = ta.trend.ema_indicator(close, window=20).values
        df["EMA50"]    = ta.trend.ema_indicator(close, window=50).values
        df["EMA200"]   = ta.trend.ema_indicator(close, window=200).values
        df["RSI"]      = ta.momentum.rsi(close, window=14).values
        df["ATR"]      = ta.volatility.average_true_range(high, low, close, window=14).values
        df["VOL_SMA"]  = volume.rolling(10).mean().values
        df["HIGH_52W"] = df["High"].rolling(252).max().values
        df["LOW_52W"]  = df["Low"].rolling(252).min().values

        df = df.dropna(subset=["EMA200"]).bfill().ffill()
        df = df.dropna(subset=["EMA20","EMA50","RSI","ATR"])
        return df if len(df) >= 5 else None
    except Exception as e:
        print(f"Indicator error: {e}")
        return None


def get_weekly_ema(symbol: str) -> dict:
    """Weekly EMA20 vs EMA50. Cached for 1 hour to avoid repeated API calls."""
    global _weekly_cache, _weekly_cache_time
    now = time.time()
    if symbol in _weekly_cache and (now - _weekly_cache_time) < WEEKLY_CACHE_TTL:
        return _weekly_cache[symbol]
    try:
        df_w = yf.Ticker(symbol).history(period="2y", interval="1wk")
        if df_w is None or len(df_w) < 55:
            result = {"weekly_ok": True, "weekly_ema20": None, "weekly_ema50": None}
        else:
            cw     = pd.Series(df_w["Close"].values.flatten(), dtype=float).ffill().bfill()
            w20    = float(ta.trend.ema_indicator(cw, window=20).iloc[-1])
            w50    = float(ta.trend.ema_indicator(cw, window=50).iloc[-1])
            result = {"weekly_ok": w20 > w50, "weekly_ema20": round(w20,2), "weekly_ema50": round(w50,2)}
    except:
        result = {"weekly_ok": True, "weekly_ema20": None, "weekly_ema50": None}

    _weekly_cache[symbol] = result
    _weekly_cache_time = now
    return result


def get_candle_type(row) -> str:
    body = float(row["Close"]) - float(row["Open"])
    rng  = float(row["High"])  - float(row["Low"])
    if rng == 0: return "Neutral"
    pct = abs(body) / rng
    if body > 0 and pct > 0.5: return "Bullish"
    if body < 0 and pct > 0.5: return "Bearish"
    return "Neutral"


# ════════════════════════════════════════════════════════════
# CORE: SCAN ONE STOCK — runs all 4 signal types
# ONE fetch, ONE indicator calc, FOUR signal checks
# This is the key speed fix — was 4 fetches before
# ════════════════════════════════════════════════════════════
def scan_stock_all(symbol: str, capital=CAPITAL, risk_amount=RISK_AMOUNT) -> dict:
    """
    Fetches data ONCE and checks all 4 signal types.
    Returns dict with keys: long, pre_breakout, short, pre_breakdown
    Each value is either a signal dict or None.
    """
    empty = {"long": None, "pre_breakout": None, "short": None, "pre_breakdown": None}

    try:
        # ── STEP 1: Fetch data ONCE ───────────────────────────
        df = get_stock_data(symbol)
        if df is None:
            return empty

        # ── STEP 2: Calculate indicators ONCE ────────────────
        df = add_indicators(df)
        if df is None:
            return empty

        # ── STEP 3: Get weekly EMA ONCE (cached) ─────────────
        weekly = get_weekly_ema(symbol)

        # ── STEP 4: Extract common values ────────────────────
        latest    = df.iloc[-1]
        prev      = df.iloc[-2]

        ema20     = float(latest["EMA20"])
        ema50     = float(latest["EMA50"])
        ema200    = float(latest["EMA200"])
        rsi       = float(latest["RSI"])
        vol       = float(latest["Volume"])
        vsma      = float(latest["VOL_SMA"])
        price     = float(latest["Close"])
        atr       = float(latest["ATR"])
        high_52w  = float(latest["HIGH_52W"]) if pd.notna(latest["HIGH_52W"]) else None
        low_52w   = float(latest["LOW_52W"])  if pd.notna(latest["LOW_52W"])  else None
        prev_high = float(prev["High"])
        prev_low  = float(prev["Low"])
        ema20_rising  = float(df["EMA20"].iloc[-1]) > float(df["EMA20"].iloc[-2])
        ema20_falling = float(df["EMA20"].iloc[-1]) < float(df["EMA20"].iloc[-2])
        candle        = get_candle_type(latest)
        stock_name    = symbol.replace(".NS","")

        result = {"long": None, "pre_breakout": None, "short": None, "pre_breakdown": None}

        # ════════════════════════════════════════════════════
        # CHECK 1: LONG SIGNAL
        # Conditions: full uptrend + weekly bullish + score ≥ 7
        # ════════════════════════════════════════════════════
        if ema20 > ema50 > ema200 and price > ema20 and ema20_rising and weekly["weekly_ok"]:
            score = 0
            if ema20 > ema50 > ema200:                              score += 3
            if 55 <= rsi <= 65:                                     score += 2
            if abs(price - ema20) / ema20 <= 0.03:                 score += 2
            if vsma > 0 and vol > 1.2 * vsma:                      score += 1
            if candle == "Bullish":                                  score += 1
            if ema20_rising:                                         score += 1
            near_52w_high = bool(high_52w and price / high_52w >= 0.85)
            if near_52w_high:                                        score += 1

            if score >= 7:
                entry     = round(prev_high * 1.001, 2)
                stop_loss = round(entry - 1.5 * atr, 2)
                risk      = entry - stop_loss

                # Confirmed breakout, not stale, not too extended
                if (price > prev_high and
                    price <= entry * 1.02 and
                    price <= ema20 * 1.05 and
                    risk > 0 and risk >= entry * 0.002):

                    target    = round(entry + 2 * risk, 2)
                    rr        = round((target - entry) / risk, 2)
                    if rr >= 1.5:
                        qty = int(min(risk_amount / risk, (capital * 0.20) / entry))
                        qty = min(qty, int((capital * 0.25) / entry))
                        if qty > 0:
                            sp = round((score / 12) * 100)
                            result["long"] = {
                                "stock": stock_name, "close": round(price,2),
                                "entry": entry, "sl": stop_loss, "target": target,
                                "qty": qty, "position": round(qty*entry,2), "rr": rr,
                                "score": sp, "action": "BEST" if sp >= 83 else "BUY",
                                "upside_pct": round(((target-entry)/entry)*100,2),
                                "near_52w_high": near_52w_high, "caution": False,
                                "signal_type": "LONG",
                                "weekly_ema20": weekly["weekly_ema20"],
                                "weekly_ema50": weekly["weekly_ema50"],
                            }

        # ════════════════════════════════════════════════════
        # CHECK 2: PRE-BREAKOUT
        # Conditions: uptrend + within 2% of today's high + weekly bullish
        # ════════════════════════════════════════════════════
        if ema20 > ema50 > ema200 and price > ema20 and ema20_rising and weekly["weekly_ok"]:
            resistance = float(latest["High"])  # today's high as resistance
            if price < resistance:              # not broken out yet
                proximity = (resistance - price) / price
                if proximity <= 0.02 and 40 <= rsi <= 68 and vsma > 0 and vol > 0.9 * vsma:
                    score = 0
                    if ema20 > ema50 > ema200:              score += 3
                    if 50 <= rsi <= 65:                     score += 2
                    if proximity <= 0.01:                   score += 2
                    elif proximity <= 0.02:                 score += 1
                    if vol > 1.1 * vsma:                    score += 1
                    if ema20_rising:                         score += 1

                    if score >= 6:
                        entry     = round(resistance * 1.001, 2)
                        stop_loss = round(entry - 1.5 * atr, 2)
                        risk      = entry - stop_loss
                        if risk > 0:
                            target = round(entry + 2 * risk, 2)
                            rr     = round((target - entry) / risk, 2)
                            if rr >= 1.5:
                                qty = int(min(risk_amount / risk, (capital * 0.20) / entry))
                                qty = min(qty, int((capital * 0.25) / entry))
                                if qty > 0:
                                    sp = round((score / 10) * 100)
                                    result["pre_breakout"] = {
                                        "stock": stock_name, "close": round(price,2),
                                        "resistance": round(resistance,2),
                                        "distance_to_breakout": round(proximity*100,2),
                                        "entry": entry, "sl": stop_loss, "target": target,
                                        "qty": qty, "position": round(qty*entry,2),
                                        "rr": rr, "score": sp, "action": "BUY STOP",
                                        "upside_pct": round(((target-entry)/entry)*100,2),
                                        "caution": False, "signal_type": "PRE_BREAKOUT",
                                        "weekly_ema20": weekly["weekly_ema20"],
                                        "weekly_ema50": weekly["weekly_ema50"],
                                    }

        # ════════════════════════════════════════════════════
        # CHECK 3: SHORT SIGNAL
        # Conditions: full downtrend + weekly bearish + score ≥ 7
        # ════════════════════════════════════════════════════
        weekly_bearish = not weekly["weekly_ok"]
        if ema20 < ema50 < ema200 and price < ema20 and ema20_falling and weekly_bearish:
            score = 0
            if ema20 < ema50 < ema200:                              score += 3
            if 35 <= rsi <= 45:                                     score += 2
            if abs(price - ema20) / ema20 <= 0.03:                 score += 2
            if vsma > 0 and vol > 1.2 * vsma:                      score += 1
            if candle == "Bearish":                                  score += 1
            if ema20_falling:                                        score += 1
            near_52w_low = bool(low_52w and low_52w > 0 and price / low_52w <= 1.15)
            if near_52w_low:                                         score += 1

            if score >= 7:
                entry     = round(prev_low * 0.999, 2)
                stop_loss = round(entry + 1.5 * atr, 2)
                risk      = stop_loss - entry

                if (price < prev_low and
                    price >= entry * 0.98 and
                    price >= ema20 * 0.95 and
                    risk > 0 and risk >= entry * 0.002):

                    target = round(entry - 2 * risk, 2)
                    rr     = round((entry - target) / risk, 2)
                    if rr >= 1.5:
                        qty = int(min(risk_amount / risk, (capital * 0.20) / entry))
                        qty = min(qty, int((capital * 0.25) / entry))
                        if qty > 0:
                            sp = round((score / 12) * 100)
                            result["short"] = {
                                "stock": stock_name, "close": round(price,2),
                                "entry": entry, "sl": stop_loss, "target": target,
                                "qty": qty, "position": round(qty*entry,2), "rr": rr,
                                "score": sp, "action": "BEST SHORT" if sp >= 83 else "SHORT",
                                "downside_pct": round(((entry-target)/entry)*100,2),
                                "near_52w_low": near_52w_low, "caution": False,
                                "signal_type": "SHORT",
                                "weekly_ema20": weekly["weekly_ema20"],
                                "weekly_ema50": weekly["weekly_ema50"],
                            }

        # ════════════════════════════════════════════════════
        # CHECK 4: PRE-BREAKDOWN
        # Conditions: downtrend + within 2% of today's low + weekly bearish
        # ════════════════════════════════════════════════════
        if ema20 < ema50 < ema200 and price < ema20 and ema20_falling and weekly_bearish:
            support = float(latest["Low"])
            if price > support:
                proximity = (price - support) / price
                if proximity <= 0.02 and 32 <= rsi <= 52 and vsma > 0 and vol > 0.9 * vsma:
                    score = 0
                    if ema20 < ema50 < ema200:              score += 3
                    if 32 <= rsi <= 48:                     score += 2
                    if proximity <= 0.01:                   score += 2
                    elif proximity <= 0.02:                 score += 1
                    if vol > 1.1 * vsma:                    score += 1
                    if ema20_falling:                        score += 1

                    if score >= 6:
                        entry     = round(support * 0.999, 2)
                        stop_loss = round(entry + 1.5 * atr, 2)
                        risk      = stop_loss - entry
                        if risk > 0:
                            target = round(entry - 2 * risk, 2)
                            rr     = round((entry - target) / risk, 2)
                            if rr >= 1.5:
                                qty = int(min(risk_amount / risk, (capital * 0.20) / entry))
                                qty = min(qty, int((capital * 0.25) / entry))
                                if qty > 0:
                                    sp = round((score / 10) * 100)
                                    result["pre_breakdown"] = {
                                        "stock": stock_name, "close": round(price,2),
                                        "support": round(support,2),
                                        "distance_to_breakdown": round(proximity*100,2),
                                        "entry": entry, "sl": stop_loss, "target": target,
                                        "qty": qty, "position": round(qty*entry,2),
                                        "rr": rr, "score": sp, "action": "SELL STOP",
                                        "downside_pct": round(((entry-target)/entry)*100,2),
                                        "caution": False, "signal_type": "PRE_BREAKDOWN",
                                        "weekly_ema20": weekly["weekly_ema20"],
                                        "weekly_ema50": weekly["weekly_ema50"],
                                    }

        return result

    except Exception as e:
        print(f"Scan error {symbol}: {e}")
        return empty


# ════════════════════════════════════════════════════════════
# RELATIVE STRENGTH SCAN
# ════════════════════════════════════════════════════════════
def scan_relative_strength(nifty_change: float, capital=CAPITAL) -> list:
    """Finds stocks outperforming Nifty today."""
    results = []

    def get_rs(symbol):
        try:
            df = get_stock_data(symbol)
            if df is None or len(df) < 2:
                return None
            today_close = float(df["Close"].iloc[-1])
            prev_close  = float(df["Close"].iloc[-2])
            stock_change = round(((today_close - prev_close) / prev_close) * 100, 2)
            rs = round(stock_change - nifty_change, 2)
            if rs <= 0:
                return None
            return {
                "stock":          symbol.replace(".NS",""),
                "close":          round(today_close,2),
                "today_pct":      stock_change,
                "nifty_pct":      nifty_change,
                "outperformance": rs,
                "signal_type":    "RELATIVE_STRENGTH",
                "action":         "WATCH",
            }
        except:
            return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(get_rs, s+".NS"): s for s in NIFTY50_STOCKS}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: x["outperformance"], reverse=True)
    return results[:10]


# ════════════════════════════════════════════════════════════
# MASTER SCAN — single entry point
# ════════════════════════════════════════════════════════════
def run_master_scan(capital=CAPITAL, risk_amount=RISK_AMOUNT) -> dict:
    """
    One scan, complete next-day plan.
    Speed: ~20-30s (was 115s) because data fetched once per stock.
    """
    market_trend, nifty_value, change_pct = get_market_trend()
    is_crash = market_trend == "DOWN" and change_pct is not None and change_pct <= -1.5

    print(f"\n{'='*55}")
    print(f"  MASTER SCAN | {market_trend} | Nifty:{nifty_value} | Change:{change_pct}%")
    print(f"  Crash: {is_crash}")
    print(f"{'='*55}\n")

    stocks    = [s + ".NS" for s in NIFTY50_STOCKS]
    scan_start = time.time()

    # ── Run all stocks in parallel, each stock fetched ONCE ──
    long_raw    = []
    pre_bo_raw  = []
    short_raw   = []
    pre_bd_raw  = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(scan_stock_all, s, capital, risk_amount): s for s in stocks}
        for f in as_completed(futures):
            try:
                res = f.result(timeout=40)
                if res["long"]:         long_raw.append(res["long"])
                if res["pre_breakout"]: pre_bo_raw.append(res["pre_breakout"])
                if res["short"]:        short_raw.append(res["short"])
                if res["pre_breakdown"]:pre_bd_raw.append(res["pre_breakdown"])
            except Exception as e:
                print(f"Thread error: {e}")

    scan_time = round(time.time() - scan_start, 1)
    print(f"Parallel scan done in {scan_time}s | Raw: L={len(long_raw)} PB={len(pre_bo_raw)} S={len(short_raw)} PD={len(pre_bd_raw)}")

    # ── Apply market filters ──────────────────────────────────

    # LONG
    long_signals = []
    for r in long_raw:
        if is_crash: continue
        if market_trend == "UP" and r["score"] < 80: continue
        if market_trend == "DOWN":
            if r["score"] < 60: continue
            r["qty"]      = max(1, r["qty"] // 2)
            r["position"] = round(r["qty"] * r["entry"], 2)
            r["caution"]  = True
        long_signals.append(r)
    long_signals = sorted(long_signals, key=lambda x: x["score"], reverse=True)[:MAX_POSITIONS]

    # PRE-BREAKOUT
    pre_breakout = []
    for r in pre_bo_raw:
        if is_crash: continue
        if r["score"] < 50: continue
        if market_trend == "DOWN":
            r["qty"]      = max(1, r["qty"] // 2)
            r["position"] = round(r["qty"] * r["entry"], 2)
            r["caution"]  = True
        pre_breakout.append(r)
    pre_breakout = sorted(pre_breakout, key=lambda x: x["score"], reverse=True)[:MAX_POSITIONS]

    # SHORT
    short_signals = []
    for r in short_raw:
        if market_trend == "UP":
            if r["score"] < 80: continue
            r["caution"] = True
        else:
            if r["score"] < 60: continue
            r["caution"] = False
        short_signals.append(r)
    short_signals = sorted(short_signals, key=lambda x: x["score"], reverse=True)[:MAX_POSITIONS]

    # PRE-BREAKDOWN
    pre_breakdown = []
    for r in pre_bd_raw:
        if r["score"] < 50: continue
        pre_breakdown.append(r)
    pre_breakdown = sorted(pre_breakdown, key=lambda x: x["score"], reverse=True)[:MAX_POSITIONS]

    # RELATIVE STRENGTH
    rs_results = scan_relative_strength(change_pct or 0, capital) if change_pct is not None else []

    print(f"""
Results: L={len(long_signals)} PRE-BO={len(pre_breakout)} S={len(short_signals)} PRE-BD={len(pre_breakdown)} RS={len(rs_results)}
Total time: {scan_time}s
""")

    return {
        "market_trend":      market_trend,
        "nifty":             nifty_value,
        "change_pct":        change_pct,
        "scan_time":         scan_time,
        "is_crash":          is_crash,
        "long_signals":      long_signals,
        "pre_breakout":      pre_breakout,
        "short_signals":     short_signals,
        "pre_breakdown":     pre_breakdown,
        "relative_strength": rs_results,
    }


# ── Backward compatibility ────────────────────────────────────
def run_full_scan(capital=CAPITAL, risk_amount=RISK_AMOUNT) -> list:
    return run_master_scan(capital, risk_amount)["long_signals"]