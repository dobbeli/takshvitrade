"""
Takshvi Trade — Core Scanner Engine v2.0

Single scan gives complete next-day trading plan:
1. LONG SIGNALS      — confirmed breakout setups (buy tomorrow)
2. PRE-BREAKOUT      — stocks within 2% of breakout (place BUY STOP tonight)
3. SHORT SIGNALS     — confirmed breakdown setups (short tomorrow)
4. PRE-BREAKDOWN     — stocks within 2% of breakdown (place SELL STOP tonight)
5. RELATIVE STRENGTH — stocks beating Nifty today (future long watchlist)

Market modes:
BULLISH (UP)         → Long signals score ≥ 80. Short signals score ≥ 60 (counter-trend, warned).
BEARISH (DOWN 0-1.5%)→ Long signals score ≥ 60 + 50% qty. Short signals score ≥ 60 (best environment).
CRASH   (DOWN >1.5%) → No long signals. Short signals score ≥ 70 (best short environment).
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
})

# ── Weekly EMA Cache ──────────────────────────────────────────
_weekly_cache: dict = {}
_weekly_cache_time: float = 0
WEEKLY_CACHE_TTL = 3600


# ── Market Trend ─────────────────────────────────────────────
def get_market_trend():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5d&interval=1d"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            url2 = "https://query2.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5d&interval=1d"
            res = requests.get(url2, headers=headers, timeout=10)
        if res.status_code != 200:
            return "SIDEWAYS", None, None
        data   = res.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return "SIDEWAYS", None, None
        closes = [c for c in result[0]["indicators"]["quote"][0]["close"] if c is not None]
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


# ── Data Sources ─────────────────────────────────────────────
def get_data_from_yahoo(symbol: str):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2y", interval="1d")
        if df is None or df.empty:
            return None
        return df
    except:
        return None


def get_data_from_nse(symbol: str):
    try:
        clean = symbol.replace(".NS", "")
        if clean == "M&M":
            clean = "M%26M"
        urls = [
            f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}.NS?range=2y&interval=1d",
            f"https://query2.finance.yahoo.com/v8/finance/chart/{clean}.NS?range=2y&interval=1d",
            f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}.BO?range=2y&interval=1d",
        ]
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "application/json"}
        response = None
        for url in urls:
            for attempt in range(2):
                try:
                    response = requests.get(url, headers=headers, timeout=10)
                    if response.status_code == 200:
                        break
                    time.sleep(1.0)
                except:
                    time.sleep(1.0)
            if response and response.status_code == 200:
                break
        if response is None or response.status_code != 200:
            return None
        data   = response.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        result     = result[0]
        timestamps = result["timestamp"]
        indicators = result["indicators"]["quote"][0]
        df = pd.DataFrame({
            "Open": indicators["open"], "High": indicators["high"],
            "Low": indicators["low"],   "Close": indicators["close"],
            "Volume": indicators["volume"],
        })
        df["Date"] = pd.to_datetime(timestamps, unit="s")
        df.set_index("Date", inplace=True)
        return df.tail(500)
    except Exception as e:
        print(f"Fallback error: {symbol} - {e}")
        return None


def get_stock_data(symbol: str) -> Optional[pd.DataFrame]:
    df = get_data_from_yahoo(symbol)
    if df is not None and not df.empty:
        pass
    else:
        df = get_data_from_nse(symbol)
    if df is None or df.empty:
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
        return df.tail(500)
    except:
        return None


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
        df["EMA20"]    = ta.trend.ema_indicator(close, window=20).values
        df["EMA50"]    = ta.trend.ema_indicator(close, window=50).values
        df["EMA200"]   = ta.trend.ema_indicator(close, window=200).values
        df["RSI"]      = ta.momentum.rsi(close, window=14).values
        df["ATR"]      = ta.volatility.average_true_range(high, low, close, window=14).values
        df["VOL_SMA"]  = volume.rolling(10).mean().values
        df["HIGH_52W"] = df["High"].rolling(252).max().values
        df["LOW_52W"]  = df["Low"].rolling(252).min().values
        df = df.dropna(subset=["EMA200"])
        df = df.bfill().ffill()
        df = df.dropna(subset=["EMA20","EMA50","RSI","ATR"])
        if len(df) < 5:
            return None
        return df
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


def get_weekly_ema(symbol: str) -> dict:
    global _weekly_cache, _weekly_cache_time
    now = time.time()
    if symbol in _weekly_cache and (now - _weekly_cache_time) < WEEKLY_CACHE_TTL:
        return _weekly_cache[symbol]
    try:
        ticker = yf.Ticker(symbol)
        df_w   = ticker.history(period="2y", interval="1wk")
        if df_w is None or df_w.empty or len(df_w) < 55:
            result = {"weekly_ok": True, "weekly_ema20": None, "weekly_ema50": None}
        else:
            close_w = pd.Series(df_w["Close"].values.flatten(), dtype=float).ffill().bfill()
            w_ema20 = float(ta.trend.ema_indicator(close_w, window=20).iloc[-1])
            w_ema50 = float(ta.trend.ema_indicator(close_w, window=50).iloc[-1])
            result  = {"weekly_ok": w_ema20 > w_ema50, "weekly_ema20": round(w_ema20,2), "weekly_ema50": round(w_ema50,2)}
        _weekly_cache[symbol] = result
        _weekly_cache_time = now
        return result
    except:
        result = {"weekly_ok": True, "weekly_ema20": None, "weekly_ema50": None}
        _weekly_cache[symbol] = result
        return result


# ════════════════════════════════════════════════════════════
# SCANNER 1 — LONG SIGNAL (confirmed breakout)
# ════════════════════════════════════════════════════════════
def scan_stock_long(symbol: str, capital=CAPITAL, risk_amount=RISK_AMOUNT) -> Optional[dict]:
    try:
        df = get_stock_data(symbol)
        if df is None: return None
        df = add_indicators(df)
        if df is None: return None

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

        # Mandatory: full uptrend
        if not (ema20 > ema50 > ema200 and price > ema20): return None
        if not (float(df["EMA20"].iloc[-1]) > float(df["EMA20"].iloc[-2])): return None

        # Weekly must be bullish
        weekly = get_weekly_ema(symbol)
        if not weekly["weekly_ok"]: return None

        # Scoring
        score = 0
        if ema20 > ema50 > ema200:                       score += 3
        if 55 <= rsi <= 65:                              score += 2
        if abs(price - ema20) / ema20 <= 0.03:          score += 2
        if vsma > 0 and vol > 1.2 * vsma:               score += 1
        if get_candle_type(latest) == "Bullish":         score += 1
        if latest["EMA20"] > prev["EMA20"]:              score += 1

        # 52W high bonus
        high_52w = float(latest["HIGH_52W"]) if pd.notna(latest["HIGH_52W"]) else None
        near_52w_high = False
        if high_52w and high_52w > 0 and price / high_52w >= 0.85:
            score += 1
            near_52w_high = True

        if score < 7: return None

        entry     = round(float(prev["High"]) * 1.001, 2)
        stop_loss = round(entry - 1.5 * atr, 2)
        risk      = entry - stop_loss

        # Breakout confirmed and not stale
        if price <= float(prev["High"]): return None
        if price > entry * 1.02:
            print(f"REJECTED (Stale): {symbol}")
            return None
        if price > ema20 * 1.05: return None
        if risk <= 0 or risk < entry * 0.002: return None

        target = round(entry + 2 * risk, 2)
        rr     = round((target - entry) / risk, 2)
        if rr < 1.5: return None

        qty = int(min(risk_amount / risk, (capital * 0.20) / entry))
        qty = min(qty, int((capital * 0.25) / entry))
        if qty <= 0: return None

        score_pct = round((score / 12) * 100)
        action    = "BEST" if score_pct >= 83 else "BUY"

        return {
            "stock": symbol.replace(".NS",""), "close": round(price,2),
            "entry": entry, "sl": stop_loss, "target": target,
            "qty": qty, "position": round(qty*entry,2), "rr": rr,
            "score": score_pct, "action": action,
            "upside_pct": round(((target-entry)/entry)*100,2),
            "near_52w_high": near_52w_high, "caution": False,
            "signal_type": "LONG",
            "weekly_ema20": weekly["weekly_ema20"],
            "weekly_ema50": weekly["weekly_ema50"],
        }
    except Exception as e:
        print(f"Long scan error {symbol}: {e}")
        return None


# ════════════════════════════════════════════════════════════
# SCANNER 2 — PRE-BREAKOUT (about to break out tomorrow)
# ════════════════════════════════════════════════════════════
def scan_stock_prebreakout(symbol: str, capital=CAPITAL, risk_amount=RISK_AMOUNT) -> Optional[dict]:
    try:
        df = get_stock_data(symbol)
        if df is None: return None
        df = add_indicators(df)
        if df is None: return None

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
        prev_high = float(latest["High"])  # today's high as resistance

        # Mandatory: uptrend
        if not (ema20 > ema50 > ema200 and price > ema20): return None
        if not (float(df["EMA20"].iloc[-1]) > float(df["EMA20"].iloc[-2])): return None

        # KEY: price NOT yet broken out (below today's high)
        # and within 2% of breaking out
        resistance = prev_high
        if price >= resistance: return None  # already broken out
        proximity  = (resistance - price) / price
        if proximity > 0.02: return None     # too far from breakout

        # RSI building up (not yet at breakout momentum)
        if not (40 <= rsi <= 68): return None

        # Volume picking up
        if not (vsma > 0 and vol > 0.9 * vsma): return None

        # Weekly must be bullish
        weekly = get_weekly_ema(symbol)
        if not weekly["weekly_ok"]: return None

        # Scoring
        score = 0
        if ema20 > ema50 > ema200:              score += 3
        if 50 <= rsi <= 65:                     score += 2
        if proximity <= 0.01:                   score += 2  # very close
        elif proximity <= 0.02:                 score += 1  # close
        if vol > 1.1 * vsma:                    score += 1
        if latest["EMA20"] > prev["EMA20"]:     score += 1

        if score < 6: return None

        entry     = round(resistance * 1.001, 2)  # BUY STOP order level
        stop_loss = round(entry - 1.5 * atr, 2)
        risk      = entry - stop_loss
        if risk <= 0: return None

        target = round(entry + 2 * risk, 2)
        rr     = round((target - entry) / risk, 2)
        if rr < 1.5: return None

        qty = int(min(risk_amount / risk, (capital * 0.20) / entry))
        qty = min(qty, int((capital * 0.25) / entry))
        if qty <= 0: return None

        score_pct = round((score / 10) * 100)

        return {
            "stock": symbol.replace(".NS",""), "close": round(price,2),
            "resistance": round(resistance,2),
            "distance_to_breakout": round(proximity * 100, 2),
            "entry": entry, "sl": stop_loss, "target": target,
            "qty": qty, "position": round(qty*entry,2), "rr": rr,
            "score": score_pct, "action": "BUY STOP",
            "upside_pct": round(((target-entry)/entry)*100,2),
            "caution": False, "signal_type": "PRE_BREAKOUT",
            "weekly_ema20": weekly["weekly_ema20"],
            "weekly_ema50": weekly["weekly_ema50"],
        }
    except Exception as e:
        print(f"Pre-breakout error {symbol}: {e}")
        return None


# ════════════════════════════════════════════════════════════
# SCANNER 3 — SHORT SIGNAL (confirmed breakdown)
# ════════════════════════════════════════════════════════════
def scan_stock_short(symbol: str, capital=CAPITAL, risk_amount=RISK_AMOUNT) -> Optional[dict]:
    try:
        df = get_stock_data(symbol)
        if df is None: return None
        df = add_indicators(df)
        if df is None: return None

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

        # Mandatory: full downtrend (mirror of long)
        if not (ema20 < ema50 < ema200 and price < ema20): return None
        if not (float(df["EMA20"].iloc[-1]) < float(df["EMA20"].iloc[-2])): return None

        # Weekly must be bearish (EMA20 < EMA50 on weekly)
        weekly = get_weekly_ema(symbol)
        if weekly["weekly_ok"]: return None  # weekly bullish = not a short

        # Scoring (mirror of long scoring)
        score = 0
        if ema20 < ema50 < ema200:                       score += 3
        if 35 <= rsi <= 45:                              score += 2
        if abs(price - ema20) / ema20 <= 0.03:          score += 2
        if vsma > 0 and vol > 1.2 * vsma:               score += 1
        if get_candle_type(latest) == "Bearish":         score += 1
        if float(latest["EMA20"]) < float(prev["EMA20"]): score += 1

        # 52W low bonus (mirror of 52W high bonus)
        low_52w = float(latest["LOW_52W"]) if pd.notna(latest["LOW_52W"]) else None
        near_52w_low = False
        if low_52w and low_52w > 0 and price / low_52w <= 1.15:
            score += 1
            near_52w_low = True

        if score < 7: return None

        entry     = round(float(prev["Low"]) * 0.999, 2)   # breakdown below prev low
        stop_loss = round(entry + 1.5 * atr, 2)             # SL ABOVE entry for short
        risk      = stop_loss - entry

        # Breakdown confirmed and not stale
        if price >= float(prev["Low"]): return None
        if price < entry * 0.98:  # already moved 2% below entry = stale
            print(f"SHORT REJECTED (Stale): {symbol}")
            return None
        if price < ema20 * 0.95: return None
        if risk <= 0 or risk < entry * 0.002: return None

        target = round(entry - 2 * risk, 2)
        rr     = round((entry - target) / risk, 2)
        if rr < 1.5: return None

        qty = int(min(risk_amount / risk, (capital * 0.20) / entry))
        qty = min(qty, int((capital * 0.25) / entry))
        if qty <= 0: return None

        score_pct    = round((score / 12) * 100)
        action       = "BEST SHORT" if score_pct >= 83 else "SHORT"
        downside_pct = round(((entry - target) / entry) * 100, 2)

        return {
            "stock": symbol.replace(".NS",""), "close": round(price,2),
            "entry": entry, "sl": stop_loss, "target": target,
            "qty": qty, "position": round(qty*entry,2), "rr": rr,
            "score": score_pct, "action": action,
            "downside_pct": downside_pct,
            "near_52w_low": near_52w_low, "caution": False,
            "signal_type": "SHORT",
            "weekly_ema20": weekly["weekly_ema20"],
            "weekly_ema50": weekly["weekly_ema50"],
        }
    except Exception as e:
        print(f"Short scan error {symbol}: {e}")
        return None


# ════════════════════════════════════════════════════════════
# SCANNER 4 — PRE-BREAKDOWN (about to break down tomorrow)
# ════════════════════════════════════════════════════════════
def scan_stock_prebreakdown(symbol: str, capital=CAPITAL, risk_amount=RISK_AMOUNT) -> Optional[dict]:
    try:
        df = get_stock_data(symbol)
        if df is None: return None
        df = add_indicators(df)
        if df is None: return None

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
        support = float(latest["Low"])  # today's low as support

        # Mandatory: downtrend
        if not (ema20 < ema50 < ema200 and price < ema20): return None
        if not (float(df["EMA20"].iloc[-1]) < float(df["EMA20"].iloc[-2])): return None

        # KEY: price NOT yet broken down (above today's low)
        if price <= support: return None  # already broke down
        proximity = (price - support) / price
        if proximity > 0.02: return None  # too far from breakdown

        # RSI weak but not yet at breakdown momentum
        if not (32 <= rsi <= 52): return None

        # Volume picking up on downside
        if not (vsma > 0 and vol > 0.9 * vsma): return None

        # Weekly must be bearish
        weekly = get_weekly_ema(symbol)
        if weekly["weekly_ok"]: return None

        # Scoring
        score = 0
        if ema20 < ema50 < ema200:              score += 3
        if 32 <= rsi <= 48:                     score += 2
        if proximity <= 0.01:                   score += 2
        elif proximity <= 0.02:                 score += 1
        if vol > 1.1 * vsma:                    score += 1
        if float(latest["EMA20"]) < float(prev["EMA20"]): score += 1

        if score < 6: return None

        entry     = round(support * 0.999, 2)  # SELL STOP order level
        stop_loss = round(entry + 1.5 * atr, 2)
        risk      = stop_loss - entry
        if risk <= 0: return None

        target = round(entry - 2 * risk, 2)
        rr     = round((entry - target) / risk, 2)
        if rr < 1.5: return None

        qty = int(min(risk_amount / risk, (capital * 0.20) / entry))
        qty = min(qty, int((capital * 0.25) / entry))
        if qty <= 0: return None

        score_pct = round((score / 10) * 100)

        return {
            "stock": symbol.replace(".NS",""), "close": round(price,2),
            "support": round(support,2),
            "distance_to_breakdown": round(proximity * 100, 2),
            "entry": entry, "sl": stop_loss, "target": target,
            "qty": qty, "position": round(qty*entry,2), "rr": rr,
            "score": score_pct, "action": "SELL STOP",
            "downside_pct": round(((entry-target)/entry)*100,2),
            "caution": False, "signal_type": "PRE_BREAKDOWN",
            "weekly_ema20": weekly["weekly_ema20"],
            "weekly_ema50": weekly["weekly_ema50"],
        }
    except Exception as e:
        print(f"Pre-breakdown error {symbol}: {e}")
        return None


# ════════════════════════════════════════════════════════════
# SCANNER 5 — RELATIVE STRENGTH (beating Nifty today)
# ════════════════════════════════════════════════════════════
def scan_relative_strength(nifty_change: float, capital=CAPITAL) -> list:
    """
    Finds stocks outperforming Nifty today.
    Relative Strength = stock % change - Nifty % change
    These are future long candidates when market turns bullish.
    """
    results = []
    stocks  = [s + ".NS" for s in NIFTY50_STOCKS]

    def get_rs(symbol):
        try:
            df = get_stock_data(symbol)
            if df is None or len(df) < 2: return None
            close_today = float(df["Close"].iloc[-1])
            close_prev  = float(df["Close"].iloc[-2])
            stock_change = round(((close_today - close_prev) / close_prev) * 100, 2)
            rs = round(stock_change - nifty_change, 2)
            if rs <= 0: return None  # not outperforming
            return {
                "stock":          symbol.replace(".NS",""),
                "close":          round(close_today, 2),
                "today_pct":      stock_change,
                "nifty_pct":      nifty_change,
                "outperformance": rs,
                "signal_type":    "RELATIVE_STRENGTH",
                "action":         "WATCH",
            }
        except:
            return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(get_rs, s): s for s in stocks}
        for f in as_completed(futures):
            r = f.result()
            if r: results.append(r)

    results.sort(key=lambda x: x["outperformance"], reverse=True)
    return results[:10]


# ════════════════════════════════════════════════════════════
# MASTER SCAN — runs all 5 scanners in ONE call
# ════════════════════════════════════════════════════════════
def run_master_scan(capital=CAPITAL, risk_amount=RISK_AMOUNT) -> dict:
    """
    Single scan that returns complete next-day trading plan:
    {
      market_trend, nifty, change_pct,
      long_signals:      [...],   confirmed breakout — buy tomorrow
      pre_breakout:      [...],   place BUY STOP tonight
      short_signals:     [...],   confirmed breakdown — short tomorrow
      pre_breakdown:     [...],   place SELL STOP tonight
      relative_strength: [...],   beating market — watchlist
    }
    """
    market_trend, nifty_value, change_pct = get_market_trend()

    print(f"\n{'='*60}")
    print(f"  MASTER SCAN | MARKET: {market_trend} | Nifty: {nifty_value} | Change: {change_pct}%")
    print(f"{'='*60}\n")

    stocks     = [s + ".NS" for s in NIFTY50_STOCKS]
    scan_start = time.time()

    # Run all 4 stock-level scanners in parallel simultaneously
    long_raw    = []
    pre_bo_raw  = []
    short_raw   = []
    pre_bd_raw  = []

    def scan_all(symbol):
        return {
            "long":     scan_stock_long(symbol, capital, risk_amount),
            "pre_bo":   scan_stock_prebreakout(symbol, capital, risk_amount),
            "short":    scan_stock_short(symbol, capital, risk_amount),
            "pre_bd":   scan_stock_prebreakdown(symbol, capital, risk_amount),
        }

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(scan_all, s): s for s in stocks}
        for f in as_completed(futures):
            try:
                res = f.result(timeout=45)
                if res["long"]:   long_raw.append(res["long"])
                if res["pre_bo"]: pre_bo_raw.append(res["pre_bo"])
                if res["short"]:  short_raw.append(res["short"])
                if res["pre_bd"]: pre_bd_raw.append(res["pre_bd"])
            except Exception as e:
                print(f"Thread error: {e}")

    scan_time = round(time.time() - scan_start, 1)
    print(f"Parallel scan done in {scan_time}s")

    # ── Apply market filters ──────────────────────────────────

    # LONG signals
    long_signals = []
    is_crash = market_trend == "DOWN" and change_pct is not None and change_pct <= -1.5
    for r in long_raw:
        if is_crash:
            continue  # no longs in crash
        if market_trend == "UP" and r["score"] < 80:
            continue
        if market_trend == "DOWN":
            if r["score"] < 60: continue
            r["qty"]      = max(1, r["qty"] // 2)
            r["position"] = round(r["qty"] * r["entry"], 2)
            r["caution"]  = True
        long_signals.append(r)
    long_signals.sort(key=lambda x: x["score"], reverse=True)
    long_signals = long_signals[:MAX_POSITIONS]

    # PRE-BREAKOUT signals
    pre_breakout = []
    for r in pre_bo_raw:
        if is_crash: continue
        if r["score"] < 50: continue
        if market_trend == "DOWN":
            r["qty"]      = max(1, r["qty"] // 2)
            r["position"] = round(r["qty"] * r["entry"], 2)
            r["caution"]  = True
        pre_breakout.append(r)
    pre_breakout.sort(key=lambda x: x["score"], reverse=True)
    pre_breakout = pre_breakout[:MAX_POSITIONS]

    # SHORT signals
    short_signals = []
    for r in short_raw:
        if market_trend == "UP":
            if r["score"] < 80: continue  # very strict for counter-trend shorts
            r["caution"] = True  # warn: counter-trend
        if market_trend == "DOWN":
            if r["score"] < 60: continue
            r["caution"] = False
        if is_crash:
            if r["score"] < 70: continue  # good short environment but still filter
            r["caution"] = False
        short_signals.append(r)
    short_signals.sort(key=lambda x: x["score"], reverse=True)
    short_signals = short_signals[:MAX_POSITIONS]

    # PRE-BREAKDOWN signals
    pre_breakdown = []
    for r in pre_bd_raw:
        if r["score"] < 50: continue
        pre_breakdown.append(r)
    pre_breakdown.sort(key=lambda x: x["score"], reverse=True)
    pre_breakdown = pre_breakdown[:MAX_POSITIONS]

    # RELATIVE STRENGTH
    rs_results = []
    if change_pct is not None:
        rs_results = scan_relative_strength(change_pct, capital)

    print(f"""
Master Scan Complete ({scan_time}s):
  Long signals:      {len(long_signals)}
  Pre-breakout:      {len(pre_breakout)}
  Short signals:     {len(short_signals)}
  Pre-breakdown:     {len(pre_breakdown)}
  Relative strength: {len(rs_results)}
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


# ── Keep backward compatibility ───────────────────────────────
def run_full_scan(capital=CAPITAL, risk_amount=RISK_AMOUNT) -> list:
    """Legacy function — returns long signals only for backward compat"""
    result = run_master_scan(capital, risk_amount)
    return result["long_signals"]