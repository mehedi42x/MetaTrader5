"""
backtest.py
===========
Tick-by-tick event driven backtester + performance analytics for TFAM.

Realism rules enforced:
  * entries cross the spread (buy@ask / sell@bid)
  * exits cross the spread (sell@bid / buy@ask)
  * fixed adverse slippage on every fill
  * commission charged per round turn
  * no look-ahead: the decision at tick i only uses ticks <= i
  * one position at a time, 0.01 lot fixed
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from strategy import TFAM, Params, TICK_SIZE, CONTRACT_SIZE   # noqa: E402
from tick_data import generate_ticks, load_mt5_ticks          # noqa: E402


# --------------------------------------------------------------------------- #
def run(ticks: pd.DataFrame, p: Params) -> TFAM:
    st = TFAM(p)
    ts = ticks["ts"].to_numpy()
    bid = ticks["bid"].to_numpy()
    ask = ticks["ask"].to_numpy()
    hours = ticks["time"].dt.hour.to_numpy()
    days = ticks["time"].dt.strftime("%Y-%m-%d").to_numpy()

    for i in range(len(ts)):
        st.on_tick(ts[i], bid[i], ask[i], int(hours[i]), days[i])
    if st.pos != 0:
        st._close(ts[-1], bid[-1] if st.pos > 0 else ask[-1], "eod_flat")
    st.finalize()
    return st


# --------------------------------------------------------------------------- #
def stats(st: TFAM, ticks: pd.DataFrame) -> dict:
    p = st.p
    tr = pd.DataFrame([asdict(t) for t in st.trades])
    out = {}
    span_days = (ticks["time"].iloc[-1] - ticks["time"].iloc[0]).total_seconds() / 86400.0
    n_sessions = ticks["time"].dt.normalize().nunique()

    out["ticks"] = int(len(ticks))
    out["period_start"] = str(ticks["time"].iloc[0])
    out["period_end"] = str(ticks["time"].iloc[-1])
    out["calendar_days"] = round(span_days, 2)
    out["trading_days"] = int(n_sessions)
    out["avg_spread"] = float((ticks["ask"] - ticks["bid"]).mean())
    out["median_spread"] = float((ticks["ask"] - ticks["bid"]).median())

    if tr.empty:
        out["trades"] = 0
        return out

    pnl = tr["pnl"].to_numpy()
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    out["trades"] = int(len(tr))
    out["trades_per_day"] = round(len(tr) / max(1, n_sessions), 2)
    out["initial_balance"] = p.initial_balance
    out["final_balance"] = round(st.balance, 2)
    out["net_profit"] = round(st.balance - p.initial_balance, 2)
    out["return_pct"] = round(100 * (st.balance / p.initial_balance - 1), 2)
    out["win_rate"] = round(100 * len(wins) / len(tr), 2)
    out["gross_profit"] = round(float(wins.sum()), 2)
    out["gross_loss"] = round(float(losses.sum()), 2)
    out["profit_factor"] = round(float(wins.sum() / abs(losses.sum())), 3) if losses.sum() else float("inf")
    out["avg_trade"] = round(float(pnl.mean()), 4)
    out["avg_win"] = round(float(wins.mean()), 4) if len(wins) else 0.0
    out["avg_loss"] = round(float(losses.mean()), 4) if len(losses) else 0.0
    out["payoff_ratio"] = round(abs(out["avg_win"] / out["avg_loss"]), 3) if out["avg_loss"] else float("inf")
    out["expectancy_usd"] = out["avg_trade"]
    out["best_trade"] = round(float(pnl.max()), 2)
    out["worst_trade"] = round(float(pnl.min()), 2)
    out["avg_hold_s"] = round(float(tr["hold_s"].mean()), 2)
    out["median_hold_s"] = round(float(tr["hold_s"].median()), 2)
    out["avg_mfe"] = round(float(tr["mfe"].mean()), 4)
    out["avg_mae"] = round(float(tr["mae"].mean()), 4)
    out["avg_entry_spread"] = round(float(tr["spread_at_entry"].mean()), 4)

    # equity / drawdown on the trade-close curve
    eq = p.initial_balance + np.cumsum(pnl)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    ddp = dd / peak
    out["max_drawdown_usd"] = round(float(dd.min()), 2)
    out["max_drawdown_pct"] = round(float(ddp.min()) * 100, 2)
    out["recovery_factor"] = round(out["net_profit"] / abs(out["max_drawdown_usd"]), 3) if dd.min() else float("inf")

    # intra-trade (tick level) drawdown
    if st.equity_curve:
        e = np.array([x[1] for x in st.equity_curve])
        pk = np.maximum.accumulate(e)
        out["max_dd_tick_level_usd"] = round(float((e - pk).min()), 2)

    # risk-adjusted
    sd = pnl.std(ddof=1) if len(pnl) > 1 else 0.0
    out["sharpe_per_trade"] = round(float(pnl.mean() / sd), 4) if sd else 0.0
    tpd = len(tr) / max(1, n_sessions)
    out["sharpe_annual"] = round(float(pnl.mean() / sd * np.sqrt(tpd * 252)), 3) if sd else 0.0
    neg = pnl[pnl < 0]
    dsd = neg.std(ddof=1) if len(neg) > 1 else 0.0
    out["sortino_annual"] = round(float(pnl.mean() / dsd * np.sqrt(tpd * 252)), 3) if dsd else 0.0

    # streaks
    sgn = (pnl > 0).astype(int)
    mw = ml = cw = cl = 0
    for s in sgn:
        if s:
            cw += 1; cl = 0
        else:
            cl += 1; cw = 0
        mw = max(mw, cw); ml = max(ml, cl)
    out["max_consec_wins"] = mw
    out["max_consec_losses"] = ml

    # exit reason breakdown
    out["exit_reasons"] = {
        k: {"n": int(v["pnl"].size), "total_pnl": round(float(v["pnl"].sum()), 2),
            "avg_pnl": round(float(v["pnl"].mean()), 4),
            "win_rate": round(100 * float((v["pnl"] > 0).mean()), 1)}
        for k, v in tr.groupby("reason")
    }

    # by side
    out["by_side"] = {
        ("long" if k == 1 else "short"): {
            "n": int(len(v)), "pnl": round(float(v["pnl"].sum()), 2),
            "win_rate": round(100 * float((v["pnl"] > 0).mean()), 1)}
        for k, v in tr.groupby("side")
    }

    # by hour
    hr = pd.to_datetime(tr["entry_ts"], unit="s").dt.hour
    out["by_hour"] = {
        int(k): {"n": int(len(v)), "pnl": round(float(v["pnl"].sum()), 2),
                 "win_rate": round(100 * float((v["pnl"] > 0).mean()), 1)}
        for k, v in tr.groupby(hr)
    }

    # daily
    dly = pd.Series(st.daily)
    out["daily_pnl"] = {k: round(float(v), 2) for k, v in dly.items()}
    out["profitable_days"] = int((dly > 0).sum())
    out["losing_days"] = int((dly <= 0).sum())
    out["best_day"] = round(float(dly.max()), 2)
    out["worst_day"] = round(float(dly.min()), 2)
    out["avg_day"] = round(float(dly.mean()), 2)

    # costs
    comm = p.commission_per_lot_rt * p.lot * len(tr)
    slip = p.slippage_ticks * TICK_SIZE * p.lot * CONTRACT_SIZE * len(tr)
    sprd = float(tr["spread_at_entry"].sum()) * p.lot * CONTRACT_SIZE
    out["total_commission"] = round(comm, 2)
    out["total_slippage"] = round(slip, 2)
    out["total_spread_paid"] = round(sprd, 2)
    out["total_cost"] = round(comm + slip + sprd, 2)
    out["gross_before_costs"] = round(out["net_profit"] + out["total_cost"], 2)
    out["cost_ratio_pct"] = round(100 * out["total_cost"] / max(1e-9, out["gross_before_costs"]), 2)

    # leverage / margin footprint
    avg_px = float(ticks["bid"].mean())
    notional = avg_px * p.lot * CONTRACT_SIZE
    out["notional_per_trade"] = round(notional, 2)
    out["margin_per_trade_800x"] = round(notional / p.leverage, 2)
    out["margin_pct_of_balance"] = round(100 * (notional / p.leverage) / p.initial_balance, 3)
    out["usd_per_001_move"] = round(p.lot * CONTRACT_SIZE * 0.01, 4)
    out["signals"] = st.signals
    out["rejects"] = st.rejects
    return out


# --------------------------------------------------------------------------- #
def main():
    outdir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(outdir, exist_ok=True)

    p = Params()
    print("Generating tick data ...")
    ticks = generate_ticks(n_days=20, seed=7)
    print(f"  {len(ticks):,} ticks  {ticks['time'].iloc[0]} -> {ticks['time'].iloc[-1]}")

    print("Running in-sample (first 60%) / out-of-sample (last 40%) split ...")
    cut = int(len(ticks) * 0.6)
    tr_in, tr_out = ticks.iloc[:cut].reset_index(drop=True), ticks.iloc[cut:].reset_index(drop=True)

    res = {}
    for name, data in (("full", ticks), ("in_sample", tr_in), ("out_of_sample", tr_out)):
        st = run(data, p)
        res[name] = stats(st, data)
        print(f"  {name:14s} trades={res[name].get('trades',0):5d} "
              f"net=${res[name].get('net_profit',0):9.2f} "
              f"PF={res[name].get('profit_factor',0)} "
              f"DD={res[name].get('max_drawdown_pct',0)}%")
        if name == "full":
            full_st = st

    # ---- multi-seed robustness (walk across different market realisations)
    print("Monte-Carlo over 8 independent market seeds ...")
    mc = []
    for s in range(101, 109):
        d = generate_ticks(n_days=8, seed=s)
        st = run(d, p)
        r = stats(st, d)
        mc.append({"seed": s, "trades": r.get("trades", 0),
                   "net": r.get("net_profit", 0), "pf": r.get("profit_factor", 0),
                   "wr": r.get("win_rate", 0), "dd": r.get("max_drawdown_pct", 0),
                   "ret": r.get("return_pct", 0)})
        print(f"  seed {s}: net=${r.get('net_profit',0):8.2f} PF={r.get('profit_factor',0)} "
              f"WR={r.get('win_rate',0)}% DD={r.get('max_drawdown_pct',0)}%")
    res["monte_carlo"] = mc

    # ---- parameter sensitivity ----------------------------------------
    del tr_in
    import gc; gc.collect()
    print("Parameter sensitivity ...")
    sens = []
    for fz in (1.8, 2.15, 2.5):
        for eff in (0.35, 0.42, 0.50):
            q = Params(flow_z=fz, eff_min=eff)
            st = run(tr_out, q)
            r = stats(st, tr_out)
            sens.append({"flow_z": fz, "eff_min": eff, "trades": r.get("trades", 0),
                         "net": r.get("net_profit", 0), "pf": r.get("profit_factor", 0),
                         "wr": r.get("win_rate", 0)})
    res["sensitivity"] = sens

    res["params"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(p).items()}

    with open(os.path.join(outdir, "backtest_results.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)

    tdf = pd.DataFrame([asdict(t) for t in full_st.trades])
    tdf["entry_time"] = pd.to_datetime(tdf["entry_ts"], unit="s")
    tdf["exit_time"] = pd.to_datetime(tdf["exit_ts"], unit="s")
    tdf.to_csv(os.path.join(outdir, "trades.csv"), index=False)

    # equity curve chart
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        eq = p.initial_balance + tdf["pnl"].cumsum()
        pk = eq.cummax()
        fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                               gridspec_kw={"height_ratios": [3, 1]})
        ax[0].plot(tdf["exit_time"], eq, lw=1.2, color="#c8961e")
        ax[0].set_title("TFAM  XAUUSD 0.01 lot @ 800x  -  Equity Curve")
        ax[0].set_ylabel("Balance (USD)"); ax[0].grid(alpha=.3)
        ax[1].fill_between(tdf["exit_time"], (eq - pk), 0, color="#c0392b", alpha=.6)
        ax[1].set_ylabel("Drawdown (USD)"); ax[1].grid(alpha=.3)
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "equity_curve.png"), dpi=130)
        print("  chart saved")
    except Exception as e:
        print("  chart skipped:", e)

    print("\nDone. results/backtest_results.json + trades.csv written.")
    return res


if __name__ == "__main__":
    main()
