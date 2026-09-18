"""Bar-by-bar backtest engine for XAUUSD (long/short, ATR SL/TP, % risk sizing)."""
import numpy as np
import pandas as pd

CONTRACT_OZ_PER_LOT = 100.0  # 1.00 lot XAUUSD = 100 oz


def run_backtest(
    df: pd.DataFrame,
    test_start,
    balance0: float = 10_000.0,
    risk_pct: float = 1.0,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 3.0,
    spread: float = 0.35,      # USD per oz, full round-trip cost
    slippage: float = 0.10,    # USD per oz, total extra slippage
    max_lot: float = 5.0,
    min_lot: float = 0.01,
    exit_mode: str = "sltp",   # "sltp" or "reverse" (exit on opposite signal)
    fixed_lot: float = 0.10,   # used when exit_mode="reverse"
    entry_filter: dict | None = None,  # see note below
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Returns (trades, equity_curve, stats). Entry on bar open AFTER signal bar.
    exit_mode="reverse": pure crossover system — opposite signal closes the
    position and opens a new one (always in market), fixed lot, no SL/TP.

    entry_filter (optional) gates NEW ENTRIES only; exits always run:
      dict(trend=True, min_dist=1.0, cooldown=20)
        trend    : only buy above / sell below column "ema_trend" (EMA200 of the
                   brick series) — needs src.strategy.add_filters()
        min_dist : require column "dist" (|close - EMA12| in $) >= this
        cooldown : minimum number of bars between the previous exit and a new entry
    After a blocked cross the system stays flat until the next cross that passes.
    """
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    t = pd.to_datetime(df["time"]).to_numpy()
    sig = df["signal"].to_numpy()
    atr = df["atr"].to_numpy() if "atr" in df.columns else np.zeros(len(df))

    # ---- optional entry filter ----
    flt = entry_filter or {}
    f_trend = bool(flt.get("trend") and "ema_trend" in df.columns)
    f_dist = flt.get("min_dist") if "dist" in df.columns else None
    f_cool = int(flt.get("cooldown", 0) or 0)
    trend_arr = df["ema_trend"].to_numpy() if f_trend else None
    dist_arr = df["dist"].to_numpy() if f_dist is not None else None
    close_arr = df["close"].to_numpy()
    n_blocked = 0
    last_exit_i = -10 ** 9

    def entry_ok(i, d):
        """i = signal bar (entry happens on bar i+1)."""
        nonlocal n_blocked
        if f_trend and not ((close_arr[i] > trend_arr[i]) if d == 1 else (close_arr[i] < trend_arr[i])):
            n_blocked += 1
            return False
        if dist_arr is not None and dist_arr[i] < f_dist:
            n_blocked += 1
            return False
        if f_cool and (i - last_exit_i) < f_cool:
            n_blocked += 1
            return False
        return True

    cost_per_oz = spread + slippage
    bal = balance0
    equity_ts, equity_val = [], []
    trades = []
    pos = None  # dict(direction, entry, sl, tp, oz, entry_time, entry_idx, risk_usd)

    def close_pos(exit_price, exit_time, exit_idx, reason):
        nonlocal bal, pos, last_exit_i
        d = pos["dir"]
        gross = (exit_price - pos["entry"]) * d * pos["oz"]
        pnl = gross - cost_per_oz * pos["oz"]
        bal += pnl
        r_mult = pnl / pos["risk_usd"] if pos["risk_usd"] > 0 else 0.0
        trades.append(dict(
            entry_time=pos["entry_time"], exit_time=exit_time,
            direction="LONG" if d == 1 else "SHORT",
            entry=round(pos["entry"], 2), exit=round(exit_price, 2),
            sl=round(pos.get("sl", float("nan")), 2),
            tp=round(pos.get("tp", float("nan")), 2),
            lot=round(pos["oz"] / CONTRACT_OZ_PER_LOT, 2),
            pnl=round(pnl, 2), r_multiple=round(r_mult, 2),
            bars_held=int(exit_idx - pos["entry_idx"]),
            exit_reason=reason,
        ))
        pos = None
        last_exit_i = exit_idx

    def open_pos(d, i):
        nonlocal pos
        if exit_mode == "reverse":
            oz = fixed_lot * CONTRACT_OZ_PER_LOT
            pos = dict(dir=d, entry=o[i], oz=oz,
                       entry_time=t[i], entry_idx=i, risk_usd=0.0)
        else:
            sl_dist = sl_atr_mult * atr[i - 1]
            tp_dist = tp_atr_mult * atr[i - 1]
            risk_usd = bal * risk_pct / 100.0
            oz = risk_usd / sl_dist
            oz = float(np.clip(oz, min_lot * CONTRACT_OZ_PER_LOT, max_lot * CONTRACT_OZ_PER_LOT))
            entry = o[i]
            if d == 1:
                sl, tp = entry - sl_dist, entry + tp_dist
            else:
                sl, tp = entry + sl_dist, entry - tp_dist
            pos = dict(dir=d, entry=entry, sl=sl, tp=tp, oz=oz,
                       entry_time=t[i], entry_idx=i, risk_usd=risk_usd)

    test_mask_start = pd.to_datetime(t) >= pd.to_datetime(test_start)

    for i in range(1, len(df)):
        # --- manage open position on bar i (SL/TP check; conservative: SL first) ---
        if exit_mode == "sltp" and pos is not None:
            d = pos["dir"]
            if d == 1:
                hit_sl = l[i] <= pos["sl"]
                hit_tp = h[i] >= pos["tp"]
            else:
                hit_sl = h[i] >= pos["sl"]
                hit_tp = l[i] <= pos["tp"]
            if hit_sl:
                close_pos(pos["sl"], t[i], i, "SL")
            elif hit_tp:
                close_pos(pos["tp"], t[i], i, "TP")

        # --- signal on bar i-1 traded at bar i open (test window only) ---
        if test_mask_start[i] and sig[i - 1] != 0 and (exit_mode == "reverse" or atr[i - 1] > 0):
            d = int(sig[i - 1])
            if exit_mode == "reverse":
                if pos is not None and pos["dir"] != d:
                    close_pos(o[i], t[i], i, "REV")   # close & reverse
                if pos is None and entry_ok(i - 1, d):
                    open_pos(d, i)
            elif pos is None and entry_ok(i - 1, d):
                open_pos(d, i)
                # same-bar SL/TP resolution (conservative: SL first)
                if d == 1:
                    hit_sl = l[i] <= pos["sl"]
                    hit_tp = h[i] >= pos["tp"]
                else:
                    hit_sl = h[i] >= pos["sl"]
                    hit_tp = l[i] <= pos["tp"]
                if hit_sl:
                    close_pos(pos["sl"], t[i], i, "SL")
                elif hit_tp:
                    close_pos(pos["tp"], t[i], i, "TP")

        equity_ts.append(t[i])
        equity_val.append(bal)

    # close any leftover at last close
    if pos is not None:
        close_pos(df["close"].iloc[-1], t[-1], len(df) - 1, "END")

    trades_df = pd.DataFrame(trades)
    eq = pd.DataFrame({"time": pd.to_datetime(equity_ts), "equity": equity_val})
    eq = eq[eq["time"] >= pd.to_datetime(test_start)].reset_index(drop=True)
    stats = compute_stats(trades_df, eq, balance0)
    stats["blocked_entries"] = n_blocked
    return trades_df, eq, stats


def compute_stats(trades: pd.DataFrame, eq: pd.DataFrame, balance0: float) -> dict:
    if trades.empty:
        return dict(n_trades=0)
    wins = trades[trades.pnl > 0]
    losses = trades[trades.pnl <= 0]
    gross_profit = wins.pnl.sum()
    gross_loss = -losses.pnl.sum()
    eqv = eq["equity"].to_numpy()
    peak = np.maximum.accumulate(np.insert(eqv, 0, balance0))
    dd = (np.append([balance0], eqv) - peak)
    dd_pct = dd / peak * 100
    # daily Sharpe (risk-free 0)
    eod = eq.set_index("time")["equity"].resample("1D").last().dropna()
    drets = eod.pct_change().dropna()
    sharpe = (drets.mean() / drets.std() * np.sqrt(252)) if len(drets) > 2 and drets.std() > 0 else 0.0
    net = trades.pnl.sum()
    return dict(
        n_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(trades) * 100, 1),
        net_pnl=round(net, 2),
        return_pct=round(net / balance0 * 100, 2),
        profit_factor=round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
        expectancy=round(net / len(trades), 2),
        avg_win=round(wins.pnl.mean(), 2) if len(wins) else 0.0,
        avg_loss=round(losses.pnl.mean(), 2) if len(losses) else 0.0,
        max_win=round(trades.pnl.max(), 2),
        max_loss=round(trades.pnl.min(), 2),
        avg_r=round(trades.r_multiple.mean(), 2),
        max_dd_usd=round(dd.min(), 2),
        max_dd_pct=round(dd_pct.min(), 2),
        sharpe_daily=round(float(sharpe), 2),
        end_balance=round(balance0 + net, 2),
        longs=int((trades.direction == "LONG").sum()),
        shorts=int((trades.direction == "SHORT").sum()),
        sl_exits=int((trades.exit_reason == "SL").sum()),
        tp_exits=int((trades.exit_reason == "TP").sum()),
        rev_exits=int((trades.exit_reason == "REV").sum()),
    )
