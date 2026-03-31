"""
TakshviTrade — Capital Calculator
User enters their capital → system shows exactly what they can buy
"""
from typing import List, Optional


def calculate_capacity(capital: float) -> dict:
    """
    Given a capital amount, returns:
    - Risk per trade (1%)
    - Max positions (based on 15% per trade)
    - Recommended max positions
    - Warning if capital too low
    """
    risk_per_trade   = round(capital * 0.01, 2)   # 1% risk rule
    max_per_position = round(capital * 0.15, 2)    # 15% per stock max
    max_positions    = min(6, int(capital / max_per_position)) if max_per_position > 0 else 0
    cash_buffer      = round(capital * 0.10, 2)    # Keep 10% as GTT buffer
    deployable       = round(capital * 0.90, 2)    # 90% can be deployed

    # Warnings based on capital size
    warnings = []
    if capital < 25000:
        warnings.append("⚠️ Capital too low — brokerage will eat profits")
        warnings.append("⚠️ Minimum recommended: ₹50,000")
    elif capital < 50000:
        warnings.append("⚠️ Low capital — limit to 2 positions max")
    elif capital < 100000:
        warnings.append("✅ Workable — limit to 3 positions")
    else:
        warnings.append("✅ Good capital — full system can run")

    return {
        "capital":          capital,
        "risk_per_trade":   risk_per_trade,
        "max_per_position": max_per_position,
        "max_positions":    max(1, max_positions),
        "deployable":       deployable,
        "cash_buffer":      cash_buffer,
        "monthly_brokerage": round(10 * 40 * 2, 0),  # 10 trades * ₹40 * 2 sides
        "warnings":         warnings,
        "breakeven_winrate": 34  # With 2:1 RR, need >33% wins to profit
    }


def size_trades_to_capital(
    trades: list,
    capital: float,
    max_positions: int = None
) -> List[dict]:
    """
    Takes raw scan results and sizes each trade to the user's capital.
    Respects the 1% risk rule and 15% position limit.
    Returns only trades that fit within capital.
    """
    risk_amount  = capital * 0.01        # 1% of capital = max risk per trade
    max_position = capital * 0.15        # 15% max per position
    cash_limit   = capital * 0.90        # never deploy more than 90%

    if max_positions is None:
        max_positions = min(6, max(1, int(cash_limit / max_position)))

    sized_trades = []
    cash_used    = 0

    for trade in trades:
        if len(sized_trades) >= max_positions:
            break

        entry = trade.get("entry", 0)
        stop  = trade.get("stop_loss", 0)
        if entry <= 0 or stop <= 0:
            continue

        risk_per_share = entry - stop
        if risk_per_share <= 0:
            continue

        # Calculate qty from risk budget
        qty = int(risk_amount / risk_per_share)

        # Cap at 15% of capital
        max_qty_by_capital = int(max_position / entry)
        qty = min(qty, max_qty_by_capital)

        if qty <= 0:
            continue

        position_value = round(entry * qty, 2)

        # Check if this trade fits in remaining capital
        if cash_used + position_value > cash_limit:
            continue

        # Update trade with sized values
        sized_trade = trade.copy()
        sized_trade["qty"]      = qty
        sized_trade["position"] = position_value
        sized_trade["risk_rs"]  = round(risk_per_share * qty, 2)
        sized_trade["reward_rs"]= round((trade["target"] - entry) * qty, 2)

        sized_trades.append(sized_trade)
        cash_used += position_value

    return sized_trades


def get_capital_summary(trades: list, capital: float) -> dict:
    """
    Returns a summary of capital usage across all sized trades
    """
    total_deploy = sum(t.get("position", 0) for t in trades)
    total_risk   = sum(t.get("risk_rs", 0)  for t in trades)
    total_reward = sum(t.get("reward_rs", 0) for t in trades)

    return {
        "capital":       capital,
        "total_deploy":  round(total_deploy, 2),
        "cash_kept":     round(capital - total_deploy, 2),
        "utilization":   round(total_deploy / capital * 100, 1),
        "total_risk":    round(total_risk, 2),
        "total_reward":  round(total_reward, 2),
        "trade_count":   len(trades),
        "portfolio_rr":  round(total_reward / total_risk, 2) if total_risk > 0 else 0
    }
