"""
Takshvi Trade — Core Scanner Engine v2.2

SPEED OPTIMISATION:
- Fetch daily + weekly data in ONE API call per stock using direct Yahoo API
- Weekly EMA computed from same response — no second API call
- RS scan reuses already-fetched close prices — no third API call
- Result: 50 API calls total instead of 150 → target 25-35s on Render

Signal types per scan:
1. LONG         — confirmed breakout (buy tomorrow)
2. PRE-BREAKOUT — within 2% of breakout (BUY STOP tonight)
3. SHORT        — confirmed breakdown (short tomorrow)
4. PRE-BREAKDOWN— within 2% of breakdown (SELL STOP tonight)
5. RS           — beating Nifty today (watchlist)
"""

import time
import logging
import pandas as pd
import numpy as np
import requests
import ta
from typing import Optional, Tuple
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


# ════════════════════════════════════════════════════════════
# MARKET TREND — direct requests, no yfinance
# ════════════════════════════════════════════════════════════
def get_market_trend() -> Tuple[str, Optional[float], Optional[float]]:
    try:
        for base in ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]:
            try:
                res = requests.get(
                    f"{base}/v8/finance/chart/%5ENSEI?range=5d&interval=1d",
                    headers=HEADERS, timeout=10
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
# UNIFIED DATA FETCH
# ONE call returns both daily df AND weekly EMA values
# This eliminates the second yfinance call for weekly data
# ════════════════════════════════════════════════════════════
def fetch_stock_data(symbol: str) -> Tuple[Optional[pd.DataFrame], dict]:
    """
    Fetches daily OHLCV data and weekly close data in ONE API call each.
    Returns (daily_df, weekly_ema_dict).

    Speed trick: uses direct Yahoo Finance API with 2y range.
    Weekly EMA is computed from a separate weekly call but both are
    direct HTTP requests (faster than yfinance library overhead).
    """
    clean = symbol.replace(".NS", "").replace("&", "%26")
    daily_df = None
    weekly   = {"weekly_ok": True, "weekly_ema20": None, "weekly_ema50": None}

    # ── Fetch DAILY (2 year, 1 day interval) ─────────────────
    daily_urls = [
        f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}.NS?range=2y&interval=1d",
        f"https://query2.finance.yahoo.com/v8/finance/chart/{clean}.NS?range=2y&interval=1d",
        f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}.BO?range=2y&interval=1d",
    ]
    for url in daily_urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                result = r.json().get("chart", {}).get("result")
                if result:
                    q  = result[0]["indicators"]["quote"][0]
                    ts = result[0]["timestamp"]
                    df = pd.DataFrame({
                        "Open":   q["open"],   "High":  q["high"],
                        "Low":    q["low"],    "Close": q["close"],
                        "Volume": q["volume"],
                    })
                    df["Date"] = pd.to_datetime(ts, unit="s")
                    df.set_index("Date", inplace=True)
                    # Clean
                    for c in ["Open","High","Low","Close","Volume"]:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                    df = df.dropna().tail(500)
                    if len(df) >= 210:
                        daily_df = df
                        break
        except:
            continue

    if daily_df is None:
        return None, weekly

    # ── Fetch WEEKLY (2 year, 1 week interval) ───────────────
    # Reuse same symbol that worked for daily
    weekly_url = url.replace("interval=1d", "interval=1wk")
    try:
        rw = requests.get(weekly_url, headers=HEADERS, timeout=8)
        if rw.status_code == 200:
            res_w = rw.json().get("chart", {}).get("result")
            if res_w:
                closes_w = [c for c in res_w[0]["indicators"]["quote"][0]["close"] if c is not None]
                if len(closes_w) >= 55:
                    cw    = pd.Series(closes_w, dtype=float).ffill().bfill()
                    w_ema20 = float(ta.trend.ema_indicator(cw, window=20).iloc[-1])
                    w_ema50 = float(ta.trend.ema_indicator(cw, window=50).iloc[-1])
                    weekly = {
                        "weekly_ok":   w_ema20 > w_ema50,
                        "weekly_ema20": round(w_ema20, 2),
                        "weekly_ema50": round(w_ema50, 2),
                    }
    except:
        pass  # weekly fails → default to True (don't block)

    return daily_df, weekly


# ════════════════════════════════════════════════════════════
# INDICATORS
# ════════════════════════════════════════════════════════════
def add_indicators(df: pd.DataFrame) -> Optional[pd.DataFrame]:
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


def get_candle_type(row) -> str:
    body = float(row["Close"]) - float(row["Open"])
    rng  = float(row["High"])  - float(row["Low"])
    if rng == 0: return "Neutral"
    pct = abs(body) / rng
    if body > 0 and pct > 0.5: return "Bullish"
    if body < 0 and pct > 0.5: return "Bearish"
    return "Neutral"


# ════════════════════════════════════════════════════════════
# CORE: SCAN ONE STOCK — all 4 signals + RS in ONE function
# Data fetched ONCE, indicators computed ONCE
# ════════════════════════════════════════════════════════════
def scan_stock_all(symbol: str, nifty_change: float,
                   capital=CAPITAL, risk_amount=RISK_AMOUNT) -> dict:
    """
    Single function per stock:
    1. Fetch daily + weekly data (2 HTTP calls)
    2. Compute indicators once
    3. Check all 4 signal types
    4. Compute relative strength
    Returns all results in one dict.
    """
    empty = {
        "long": None, "pre_breakout": None,
        "short": None, "pre_breakdown": None,
        "rs": None,
    }

    try:
        # ── STEP 1: Fetch once ────────────────────────────────
        daily_df, weekly = fetch_stock_data(symbol)
        if daily_df is None:
            return empty

        # ── STEP 2: Indicators once ───────────────────────────
        df = add_indicators(daily_df)
        if df is None:
            return empty

        # ── STEP 3: Common values ─────────────────────────────
        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        ema20  = float(latest["EMA20"])
        ema50  = float(latest["EMA50"])
        ema200 = float(latest["EMA200"])
        rsi    = float(latest["RSI"])
        vol    = float(latest["Volume"])
        vsma   = float(latest["VOL_SMA"])
        price  = float(latest["Close"])
        atr    = float(latest["ATR"])
        high_52w = float(latest["HIGH_52W"]) if pd.notna(latest["HIGH_52W"]) else None
        low_52w  = float(latest["LOW_52W"])  if pd.notna(latest["LOW_52W"])  else None
        prev_high = float(prev["High"])
        prev_low  = float(prev["Low"])
        ema20_rising  = float(df["EMA20"].iloc[-1]) > float(df["EMA20"].iloc[-2])
        ema20_falling = not ema20_rising
        candle = get_candle_type(latest)
        name   = symbol.replace(".NS","")
        weekly_bullish = weekly["weekly_ok"]
        weekly_bearish = not weekly_bullish

        result = {**empty}

        # ── STEP 4a: RELATIVE STRENGTH ────────────────────────
        # Compute here — reuses already-fetched close prices
        # No extra API call needed
        try:
            prev_close_rs = float(daily_df["Close"].iloc[-2])
            today_close   = float(daily_df["Close"].iloc[-1])
            stock_change  = round(((today_close - prev_close_rs) / prev_close_rs) * 100, 2)
            rs_val        = round(stock_change - nifty_change, 2)
            if rs_val > 0:
                result["rs"] = {
                    "stock":          name,
                    "close":          round(today_close, 2),
                    "today_pct":      stock_change,
                    "nifty_pct":      nifty_change,
                    "outperformance": rs_val,
                    "signal_type":    "RELATIVE_STRENGTH",
                    "action":         "WATCH",
                }
        except:
            pass

        # ── STEP 4b: LONG SIGNAL ──────────────────────────────
        if ema20 > ema50 > ema200 and price > ema20 and ema20_rising and weekly_bullish:
            score = 0
            if ema20 > ema50 > ema200:                     score += 3
            if 55 <= rsi <= 65:                            score += 2
            if abs(price - ema20) / ema20 <= 0.03:        score += 2
            if vsma > 0 and vol > 1.2 * vsma:             score += 1
            if candle == "Bullish":                         score += 1
            if ema20_rising:                                score += 1
            near_52w_high = bool(high_52w and price / high_52w >= 0.85)
            if near_52w_high:                               score += 1

            if score >= 7:
                entry     = round(prev_high * 1.001, 2)
                stop_loss = round(entry - 1.5 * atr, 2)
                risk      = entry - stop_loss
                if (price > prev_high and price <= entry * 1.02 and
                    price <= ema20 * 1.05 and risk > 0 and risk >= entry * 0.002):
                    target = round(entry + 2 * risk, 2)
                    rr     = round((target - entry) / risk, 2)
                    if rr >= 1.5:
                        qty = int(min(risk_amount/risk, (capital*0.20)/entry))
                        qty = min(qty, int((capital*0.25)/entry))
                        if qty > 0:
                            sp = round((score/12)*100)
                            result["long"] = {
                                "stock": name, "close": round(price,2),
                                "entry": entry, "sl": stop_loss, "target": target,
                                "qty": qty, "position": round(qty*entry,2), "rr": rr,
                                "score": sp, "action": "BEST" if sp>=83 else "BUY",
                                "upside_pct": round(((target-entry)/entry)*100,2),
                                "near_52w_high": near_52w_high, "caution": False,
                                "signal_type": "LONG",
                                "weekly_ema20": weekly["weekly_ema20"],
                                "weekly_ema50": weekly["weekly_ema50"],
                            }

        # ── STEP 4c: PRE-BREAKOUT ─────────────────────────────
        if ema20 > ema50 > ema200 and price > ema20 and ema20_rising and weekly_bullish:
            resistance = float(latest["High"])
            if price < resistance:
                proximity = (resistance - price) / price
                if proximity <= 0.02 and 40 <= rsi <= 68 and vsma > 0 and vol > 0.9 * vsma:
                    score = 0
                    if ema20 > ema50 > ema200:             score += 3
                    if 50 <= rsi <= 65:                    score += 2
                    if proximity <= 0.01:                  score += 2
                    elif proximity <= 0.02:                score += 1
                    if vol > 1.1 * vsma:                   score += 1
                    if ema20_rising:                        score += 1
                    if score >= 6:
                        entry     = round(resistance * 1.001, 2)
                        stop_loss = round(entry - 1.5 * atr, 2)
                        risk      = entry - stop_loss
                        if risk > 0:
                            target = round(entry + 2 * risk, 2)
                            rr     = round((target-entry)/risk, 2)
                            if rr >= 1.5:
                                qty = int(min(risk_amount/risk, (capital*0.20)/entry))
                                qty = min(qty, int((capital*0.25)/entry))
                                if qty > 0:
                                    sp = round((score/10)*100)
                                    result["pre_breakout"] = {
                                        "stock": name, "close": round(price,2),
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

        # ── STEP 4d: SHORT SIGNAL ─────────────────────────────
        if ema20 < ema50 < ema200 and price < ema20 and ema20_falling and weekly_bearish:
            score = 0
            if ema20 < ema50 < ema200:                     score += 3
            if 35 <= rsi <= 45:                            score += 2
            if abs(price - ema20) / ema20 <= 0.03:        score += 2
            if vsma > 0 and vol > 1.2 * vsma:             score += 1
            if candle == "Bearish":                         score += 1
            if ema20_falling:                               score += 1
            near_52w_low = bool(low_52w and low_52w > 0 and price/low_52w <= 1.15)
            if near_52w_low:                                score += 1
            if score >= 7:
                entry     = round(prev_low * 0.999, 2)
                stop_loss = round(entry + 1.5 * atr, 2)
                risk      = stop_loss - entry
                if (price < prev_low and price >= entry * 0.98 and
                    price >= ema20 * 0.95 and risk > 0 and risk >= entry * 0.002):
                    target = round(entry - 2 * risk, 2)
                    rr     = round((entry-target)/risk, 2)
                    if rr >= 1.5:
                        qty = int(min(risk_amount/risk, (capital*0.20)/entry))
                        qty = min(qty, int((capital*0.25)/entry))
                        if qty > 0:
                            sp = round((score/12)*100)
                            result["short"] = {
                                "stock": name, "close": round(price,2),
                                "entry": entry, "sl": stop_loss, "target": target,
                                "qty": qty, "position": round(qty*entry,2), "rr": rr,
                                "score": sp, "action": "BEST SHORT" if sp>=83 else "SHORT",
                                "downside_pct": round(((entry-target)/entry)*100,2),
                                "near_52w_low": near_52w_low, "caution": False,
                                "signal_type": "SHORT",
                                "weekly_ema20": weekly["weekly_ema20"],
                                "weekly_ema50": weekly["weekly_ema50"],
                            }

        # ── STEP 4e: PRE-BREAKDOWN ────────────────────────────
        if ema20 < ema50 < ema200 and price < ema20 and ema20_falling and weekly_bearish:
            support = float(latest["Low"])
            if price > support:
                proximity = (price - support) / price
                if proximity <= 0.02 and 32 <= rsi <= 52 and vsma > 0 and vol > 0.9 * vsma:
                    score = 0
                    if ema20 < ema50 < ema200:             score += 3
                    if 32 <= rsi <= 48:                    score += 2
                    if proximity <= 0.01:                  score += 2
                    elif proximity <= 0.02:                score += 1
                    if vol > 1.1 * vsma:                   score += 1
                    if ema20_falling:                       score += 1
                    if score >= 6:
                        entry     = round(support * 0.999, 2)
                        stop_loss = round(entry + 1.5 * atr, 2)
                        risk      = stop_loss - entry
                        if risk > 0:
                            target = round(entry - 2 * risk, 2)
                            rr     = round((entry-target)/risk, 2)
                            if rr >= 1.5:
                                qty = int(min(risk_amount/risk, (capital*0.20)/entry))
                                qty = min(qty, int((capital*0.25)/entry))
                                if qty > 0:
                                    sp = round((score/10)*100)
                                    result["pre_breakdown"] = {
                                        "stock": name, "close": round(price,2),
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
# MASTER SCAN
# ════════════════════════════════════════════════════════════
def run_master_scan(capital=CAPITAL, risk_amount=RISK_AMOUNT) -> dict:
    """
    Complete next-day trading plan in one scan.

    Speed breakdown:
    - 50 stocks × 2 HTTP calls (daily + weekly) = 100 calls total
    - 10 workers run in parallel → ~10 batches × 2s = ~20s
    - No separate RS scan — computed inside same stock loop
    - No yfinance library overhead — pure requests
    Target: 20-35s on Render free tier
    """
    market_trend, nifty_value, change_pct = get_market_trend()
    is_crash = market_trend == "DOWN" and change_pct is not None and change_pct <= -1.5
    nifty_ch = change_pct or 0

    print(f"\n{'='*55}")
    print(f"  MASTER SCAN | {market_trend} | Nifty:{nifty_value} | Change:{change_pct}%")
    print(f"  Crash:{is_crash}")
    print(f"{'='*55}\n")

    stocks     = [s + ".NS" for s in NIFTY50_STOCKS]
    scan_start = time.time()

    long_raw = []; pre_bo_raw = []; short_raw = []
    pre_bd_raw = []; rs_raw = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(scan_stock_all, s, nifty_ch, capital, risk_amount): s
            for s in stocks
        }
        for f in as_completed(futures):
            try:
                res = f.result(timeout=35)
                if res["long"]:         long_raw.append(res["long"])
                if res["pre_breakout"]: pre_bo_raw.append(res["pre_breakout"])
                if res["short"]:        short_raw.append(res["short"])
                if res["pre_breakdown"]:pre_bd_raw.append(res["pre_breakdown"])
                if res["rs"]:           rs_raw.append(res["rs"])
            except Exception as e:
                print(f"Thread error: {e}")

    scan_time = round(time.time() - scan_start, 1)
    print(f"Parallel scan done in {scan_time}s | Raw: L={len(long_raw)} PB={len(pre_bo_raw)} S={len(short_raw)} PD={len(pre_bd_raw)} RS={len(rs_raw)}")

    # ── Apply market filters ──────────────────────────────────
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

    pre_breakdown = []
    for r in pre_bd_raw:
        if r["score"] < 50: continue
        pre_breakdown.append(r)
    pre_breakdown = sorted(pre_breakdown, key=lambda x: x["score"], reverse=True)[:MAX_POSITIONS]

    rs_results = sorted(rs_raw, key=lambda x: x["outperformance"], reverse=True)[:10]

    print(f"Results: L={len(long_signals)} PRE-BO={len(pre_breakout)} S={len(short_signals)} PRE-BD={len(pre_breakdown)} RS={len(rs_results)}")
    print(f"Total time: {scan_time}s\n")

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