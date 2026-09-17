"""Bar-based backtester used by Algo Studio's *Preview / Backtest* panel.

It is intentionally simple and honest: signals are executed at the *next* bar
open, intrabar SL/TP is resolved with a conservative worst-case rule, and the
result is reported in points plus an approximate currency amount derived from
the symbol's contract size. It is a smoke-test for the logic, not a
replacement for the MetaTrader Strategy Tester.
"""

from __future__ import annotations

from typing import Any


def run_backtest(
    evaluate: Any,
    rows: list[dict],
    *,
    volume: float = 0.01,
    stop_loss_points: float | None = None,
    take_profit_points: float | None = None,
    meta: dict | None = None,
) -> dict:
    meta = meta or {}
    point = float(meta.get("point") or 1e-5)
    contract = float(meta.get("contract_size") or 0) or 100000.0
    per_lot_per_point = contract * point  # money moved by 1 point for 1.0 lot

    trades: list[dict] = []
    equity_points: list[float] = []
    equity_curve: list[dict] = []
    open_trade: dict | None = None
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    errors = 0
    signals_seen = 0
    first_error: str | None = None

    for index, row in enumerate(rows):
        price = float(row["close"])
        # --- manage an open position on this bar ------------------------
        if open_trade is not None:
            exit_price = None
            reason = None
            sl, tp = open_trade["sl"], open_trade["tp"]
            if open_trade["dir"] > 0:
                if sl and float(row["low"]) <= sl:
                    exit_price, reason = sl, "SL"
                elif tp and float(row["high"]) >= tp:
                    exit_price, reason = tp, "TP"
            else:
                if sl and float(row["high"]) >= sl:
                    exit_price, reason = sl, "SL"
                elif tp and float(row["low"]) <= tp:
                    exit_price, reason = tp, "TP"
            if exit_price is not None:
                direction = open_trade["dir"]
                points = (exit_price - open_trade["price"]) / point * direction
                money = points * point * per_lot_per_point * volume
                cumulative += money
                trades.append({**open_trade, "exit_time": row["time"], "exit_price": exit_price, "points": round(points, 1), "money": round(money, 2), "reason": reason})
                open_trade = None
                equity_curve.append({"t": row["time"], "equity": round(cumulative, 2)})

        # --- ask the strategy for the next signal -----------------------
        requested = None
        try:
            requested = evaluate(rows[: index + 1], index)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            requested = None
            if errors == 1:
                first_error = f"{exc.__class__.__name__}: {exc}"
        action = None
        if isinstance(requested, dict):
            action = requested.get("action")
        elif requested in (-1, 0, 1):
            action = {1: "buy", -1: "sell", 0: "close"}[requested]

        if action in ("buy", "sell", "close"):
            signals_seen += 1
            want_dir = {"buy": 1, "sell": -1, "close": 0}[action]
            if open_trade is not None and (want_dir == 0 or want_dir != open_trade["dir"]):
                close_price = price
                direction = open_trade["dir"]
                pts = (close_price - open_trade["price"]) / point * direction
                money = pts * point * per_lot_per_point * volume
                cumulative += money
                trades.append({**open_trade, "exit_time": row["time"], "exit_price": close_price, "points": round(pts, 1), "money": round(money, 2), "reason": "signal"})
                open_trade = None
                equity_curve.append({"t": row["time"], "equity": round(cumulative, 2)})
            if want_dir != 0 and open_trade is None and index + 1 < len(rows):
                nxt = rows[index + 1]
                entry = float(nxt["open"])
                if want_dir > 0:
                    sl = entry - (stop_loss_points or 0) * point if stop_loss_points else None
                    tp = entry + (take_profit_points or 0) * point if take_profit_points else None
                else:
                    sl = entry + (stop_loss_points or 0) * point if stop_loss_points else None
                    tp = entry - (take_profit_points or 0) * point if take_profit_points else None
                open_trade = {
                    "dir": want_dir,
                    "entry_time": nxt["time"],
                    "price": entry,
                    "sl": sl,
                    "tp": tp,
                    "volume": volume,
                    "reason_in": requested.get("reason") if isinstance(requested, dict) else "signal",
                }
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
        equity_points.append(cumulative)

    if open_trade is not None:
        last = rows[-1]
        pts = (float(last["close"]) - open_trade["price"]) / point * open_trade["dir"]
        money = pts * point * per_lot_per_point * volume
        cumulative += money
        trades.append({**open_trade, "exit_time": last["time"], "exit_price": float(last["close"]), "points": round(pts, 1), "money": round(money, 2), "reason": "end"})
        open_trade = None
        equity_curve.append({"t": last["time"], "equity": round(cumulative, 2)})

    wins = [t for t in trades if t["money"] > 0]
    losses = [t for t in trades if t["money"] <= 0]
    gross_win = sum(t["money"] for t in wins)
    gross_loss = sum(t["money"] for t in losses)
    return {
        "bars": len(rows),
        "trades": trades,
        "trade_count": len(trades),
        "signals": signals_seen,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "net_points": round(sum(t["points"] for t in trades), 1),
        "net_money": round(cumulative, 2),
        "max_drawdown_money": round(max_drawdown, 2),
        "profit_factor": round(gross_win / abs(gross_loss), 2) if gross_loss else (None if gross_win else 0.0),
        "avg_trade_money": round(cumulative / len(trades), 2) if trades else 0.0,
        "best_trade": max((t["money"] for t in trades), default=0.0),
        "worst_trade": min((t["money"] for t in trades), default=0.0),
        "equity_curve": equity_curve[:: max(1, len(equity_curve) // 200)],
        "errors": errors,
        "first_error": first_error,
        "note": "Signals execute on the next bar open. Use the MetaTrader Strategy Tester for tick-accurate results.",
    }
