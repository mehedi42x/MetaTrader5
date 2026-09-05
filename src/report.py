"""
report.py
=========
Full detailed backtest report generator for TFAM on REAL MT5 tick data.

Usage:
    python src/report.py /path/to/XAUUSD.txt

Produces (in results/):
    REAL_DATA_REPORT.md     human readable full report
    real_results.json       every metric as JSON
    real_trades.csv         complete trade blotter
    real_equity.png         equity curve + drawdown + monthly bars

Covers everything requested:
  * total trades, winning trades, losing trades
  * total profit, total loss, net
  * % profitable trades, win rate
  * drawdown (USD, %, duration)
  * MONTH BY MONTH breakdown (profit/loss per month)
  * YEAR by year breakdown
  * max trades in a single day / min trades in a single day
  * best/worst day, best/worst month
  * hold time, streaks, exit reasons, hourly & weekday profile, costs
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy import TFAM, Params, TICK_SIZE, CONTRACT_SIZE, calibrate  # noqa: E402
from mt5_loader import load_ticks                              # noqa: E402

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")


# --------------------------------------------------------------------------- #
def run_backtest(ticks: pd.DataFrame, p: Params, verbose=True) -> TFAM:
    st = TFAM(p)
    ts = ticks["ts"].to_numpy()
    bid = ticks["bid"].to_numpy()
    ask = ticks["ask"].to_numpy()
    hours = ticks["time"].dt.hour.to_numpy().astype(np.int32)
    days = ticks["time"].dt.strftime("%Y-%m-%d").to_numpy()

    n = len(ts)
    step = max(1, n // 20)
    for i in range(n):
        st.on_tick(ts[i], bid[i], ask[i], int(hours[i]), days[i])
        if verbose and i % step == 0:
            print(f"[bt] {100*i/n:5.1f}%  trades={len(st.trades):,}  bal=${st.balance:,.2f}", flush=True)
    if st.pos != 0:
        st._close(ts[-1], bid[-1] if st.pos > 0 else ask[-1], "eod_flat")
    st.finalize()
    return st


# --------------------------------------------------------------------------- #
def build_report(st: TFAM, ticks: pd.DataFrame, p: Params) -> dict:
    tr = pd.DataFrame([asdict(t) for t in st.trades])
    if tr.empty:
        return {"error": "no trades"}

    tr["entry_time"] = pd.to_datetime(tr["entry_ts"], unit="s")
    tr["exit_time"] = pd.to_datetime(tr["exit_ts"], unit="s")
    tr["date"] = tr["entry_time"].dt.strftime("%Y-%m-%d")
    tr["month"] = tr["entry_time"].dt.strftime("%Y-%m")
    tr["year"] = tr["entry_time"].dt.year
    tr["hour"] = tr["entry_time"].dt.hour
    tr["weekday"] = tr["entry_time"].dt.day_name()
    tr["win"] = tr["pnl"] > 0

    pnl = tr["pnl"].to_numpy()
    wins = tr[tr["win"]]
    losses = tr[~tr["win"]]

    R = {}

    # ---------------- data coverage --------------------------------------
    spr = (ticks["ask"] - ticks["bid"])
    R["data"] = {
        "total_ticks": int(len(ticks)),
        "first_tick": str(ticks["time"].iloc[0]),
        "last_tick": str(ticks["time"].iloc[-1]),
        "calendar_days": round((ticks["time"].iloc[-1] - ticks["time"].iloc[0]).days, 2),
        "trading_days_in_data": int(ticks["time"].dt.normalize().nunique()),
        "months_in_data": int(ticks["time"].dt.to_period("M").nunique()),
        "avg_spread": round(float(spr.mean()), 4),
        "median_spread": round(float(spr.median()), 4),
        "min_spread": round(float(spr.min()), 4),
        "p95_spread": round(float(spr.quantile(0.95)), 4),
        "price_min": round(float(ticks["bid"].min()), 2),
        "price_max": round(float(ticks["bid"].max()), 2),
        "price_first": round(float(ticks["bid"].iloc[0]), 2),
        "price_last": round(float(ticks["bid"].iloc[-1]), 2),
    }

    # ---------------- headline -------------------------------------------
    gp = float(wins["pnl"].sum())
    gl = float(losses["pnl"].sum())
    R["summary"] = {
        "initial_balance": p.initial_balance,
        "final_balance": round(st.balance, 2),
        "net_profit": round(st.balance - p.initial_balance, 2),
        "return_pct": round(100 * (st.balance / p.initial_balance - 1), 2),
        "total_trades": int(len(tr)),
        "winning_trades": int(len(wins)),
        "losing_trades": int(len(losses)),
        "profitable_trades_pct": round(100 * len(wins) / len(tr), 2),
        "win_rate_pct": round(100 * len(wins) / len(tr), 2),
        "total_profit": round(gp, 2),
        "total_loss": round(gl, 2),
        "profit_factor": round(gp / abs(gl), 3) if gl else float("inf"),
        "expectancy_per_trade": round(float(pnl.mean()), 4),
        "avg_win": round(float(wins["pnl"].mean()), 4) if len(wins) else 0.0,
        "avg_loss": round(float(losses["pnl"].mean()), 4) if len(losses) else 0.0,
        "payoff_ratio": round(abs(wins["pnl"].mean() / losses["pnl"].mean()), 3) if len(losses) and len(wins) else 0.0,
        "largest_win": round(float(pnl.max()), 2),
        "largest_loss": round(float(pnl.min()), 2),
    }

    # ---------------- drawdown -------------------------------------------
    eq = p.initial_balance + np.cumsum(pnl)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    ddp = 100 * dd / peak
    i_tr = int(np.argmin(dd))
    i_pk = int(np.argmax(eq[: i_tr + 1])) if i_tr > 0 else 0
    # recovery
    rec = None
    after = np.where(eq[i_tr:] >= peak[i_tr])[0]
    if len(after):
        rec = int(after[0])
    # underwater duration in days
    uw_days = None
    if rec is not None:
        uw_days = round((tr["exit_time"].iloc[i_tr + rec] - tr["exit_time"].iloc[i_pk]).total_seconds() / 86400, 2)

    R["drawdown"] = {
        "max_drawdown_usd": round(float(dd.min()), 2),
        "max_drawdown_pct": round(float(ddp.min()), 2),
        "peak_before_dd": round(float(eq[i_pk]), 2),
        "trough": round(float(eq[i_tr]), 2),
        "dd_peak_date": str(tr["exit_time"].iloc[i_pk]),
        "dd_trough_date": str(tr["exit_time"].iloc[i_tr]),
        "recovered": rec is not None,
        "underwater_days": uw_days,
        "recovery_factor": round((st.balance - p.initial_balance) / abs(dd.min()), 3) if dd.min() < 0 else float("inf"),
        "avg_drawdown_usd": round(float(dd[dd < 0].mean()), 3) if (dd < 0).any() else 0.0,
    }

    # ---------------- risk adjusted ---------------------------------------
    sd = pnl.std(ddof=1) if len(pnl) > 1 else 0.0
    neg = pnl[pnl < 0]
    dsd = neg.std(ddof=1) if len(neg) > 1 else 0.0
    ndays = max(1, tr["date"].nunique())
    tpd = len(tr) / ndays
    R["risk"] = {
        "std_dev_per_trade": round(float(sd), 4),
        "sharpe_per_trade": round(float(pnl.mean() / sd), 4) if sd else 0.0,
        "sharpe_annualised": round(float(pnl.mean() / sd * np.sqrt(tpd * 252)), 3) if sd else 0.0,
        "sortino_annualised": round(float(pnl.mean() / dsd * np.sqrt(tpd * 252)), 3) if dsd else 0.0,
        "calmar": round((100 * (st.balance / p.initial_balance - 1)) / abs(ddp.min()), 3) if ddp.min() < 0 else float("inf"),
    }

    # ---------------- streaks ---------------------------------------------
    mw = ml = cw = cl = 0
    bw = bl = 0.0; twin = tloss = 0.0
    for v, w in zip(pnl, tr["win"]):
        if w:
            cw += 1; cl = 0; twin += v; tloss = 0.0
        else:
            cl += 1; cw = 0; tloss += v; twin = 0.0
        mw = max(mw, cw); ml = max(ml, cl)
        bw = max(bw, twin); bl = min(bl, tloss)
    R["streaks"] = {
        "max_consecutive_wins": mw,
        "max_consecutive_losses": ml,
        "largest_winning_streak_usd": round(bw, 2),
        "largest_losing_streak_usd": round(bl, 2),
    }

    # ---------------- hold time --------------------------------------------
    R["holding"] = {
        "avg_hold_seconds": round(float(tr["hold_s"].mean()), 2),
        "median_hold_seconds": round(float(tr["hold_s"].median()), 2),
        "min_hold_seconds": round(float(tr["hold_s"].min()), 2),
        "max_hold_seconds": round(float(tr["hold_s"].max()), 2),
        "avg_hold_winners": round(float(wins["hold_s"].mean()), 2) if len(wins) else 0,
        "avg_hold_losers": round(float(losses["hold_s"].mean()), 2) if len(losses) else 0,
    }

    # ---------------- MONTH BY MONTH ---------------------------------------
    mg = tr.groupby("month")
    monthly = []
    run_bal = p.initial_balance
    for m, g in mg:
        w = g[g["win"]]; l = g[~g["win"]]
        net = float(g["pnl"].sum())
        start = run_bal
        run_bal += net
        monthly.append({
            "month": m,
            "trades": int(len(g)),
            "wins": int(len(w)),
            "losses": int(len(l)),
            "win_rate_pct": round(100 * len(w) / len(g), 2),
            "gross_profit": round(float(w["pnl"].sum()), 2),
            "gross_loss": round(float(l["pnl"].sum()), 2),
            "net_pnl": round(net, 2),
            "return_pct": round(100 * net / start, 2),
            "profit_factor": round(float(w["pnl"].sum() / abs(l["pnl"].sum())), 3) if len(l) and l["pnl"].sum() else None,
            "balance_end": round(run_bal, 2),
            "best_trade": round(float(g["pnl"].max()), 2),
            "worst_trade": round(float(g["pnl"].min()), 2),
            "trading_days": int(g["date"].nunique()),
        })
    R["monthly"] = monthly
    mn = pd.DataFrame(monthly)
    R["monthly_summary"] = {
        "total_months": int(len(mn)),
        "profitable_months": int((mn["net_pnl"] > 0).sum()),
        "losing_months": int((mn["net_pnl"] <= 0).sum()),
        "pct_profitable_months": round(100 * (mn["net_pnl"] > 0).mean(), 2),
        "best_month": mn.loc[mn["net_pnl"].idxmax(), "month"],
        "best_month_pnl": round(float(mn["net_pnl"].max()), 2),
        "worst_month": mn.loc[mn["net_pnl"].idxmin(), "month"],
        "worst_month_pnl": round(float(mn["net_pnl"].min()), 2),
        "avg_month_pnl": round(float(mn["net_pnl"].mean()), 2),
        "median_month_pnl": round(float(mn["net_pnl"].median()), 2),
        "avg_trades_per_month": round(float(mn["trades"].mean()), 1),
    }

    # ---------------- YEAR BY YEAR ------------------------------------------
    yearly = []
    for y, g in tr.groupby("year"):
        w = g[g["win"]]
        yearly.append({
            "year": int(y), "trades": int(len(g)),
            "wins": int(len(w)), "losses": int(len(g) - len(w)),
            "win_rate_pct": round(100 * len(w) / len(g), 2),
            "net_pnl": round(float(g["pnl"].sum()), 2),
            "trading_days": int(g["date"].nunique()),
        })
    R["yearly"] = yearly

    # ---------------- DAILY / trades-per-day --------------------------------
    dg = tr.groupby("date")
    dcount = dg.size()
    dpnl = dg["pnl"].sum()
    R["daily_summary"] = {
        "total_trading_days": int(len(dcount)),
        "max_trades_in_a_day": int(dcount.max()),
        "max_trades_day_date": str(dcount.idxmax()),
        "min_trades_in_a_day": int(dcount.min()),
        "min_trades_day_date": str(dcount.idxmin()),
        "avg_trades_per_day": round(float(dcount.mean()), 2),
        "median_trades_per_day": round(float(dcount.median()), 2),
        "profitable_days": int((dpnl > 0).sum()),
        "losing_days": int((dpnl <= 0).sum()),
        "pct_profitable_days": round(100 * float((dpnl > 0).mean()), 2),
        "best_day_pnl": round(float(dpnl.max()), 2),
        "best_day_date": str(dpnl.idxmax()),
        "worst_day_pnl": round(float(dpnl.min()), 2),
        "worst_day_date": str(dpnl.idxmin()),
        "avg_day_pnl": round(float(dpnl.mean()), 2),
        "median_day_pnl": round(float(dpnl.median()), 2),
        "max_consecutive_losing_days": int(_max_streak(dpnl <= 0)),
        "max_consecutive_winning_days": int(_max_streak(dpnl > 0)),
    }
    R["daily_pnl"] = {str(k): round(float(v), 2) for k, v in dpnl.items()}
    R["daily_trade_counts"] = {str(k): int(v) for k, v in dcount.items()}

    # ---------------- breakdowns ---------------------------------------------
    R["by_exit_reason"] = {
        k: {"trades": int(len(g)), "net_pnl": round(float(g["pnl"].sum()), 2),
            "avg_pnl": round(float(g["pnl"].mean()), 4),
            "win_rate_pct": round(100 * float(g["win"].mean()), 2),
            "pct_of_trades": round(100 * len(g) / len(tr), 2)}
        for k, g in tr.groupby("reason")
    }
    R["by_side"] = {
        ("long" if k == 1 else "short"): {
            "trades": int(len(g)), "net_pnl": round(float(g["pnl"].sum()), 2),
            "win_rate_pct": round(100 * float(g["win"].mean()), 2),
            "avg_pnl": round(float(g["pnl"].mean()), 4)}
        for k, g in tr.groupby("side")
    }
    R["by_hour"] = {
        int(k): {"trades": int(len(g)), "net_pnl": round(float(g["pnl"].sum()), 2),
                 "win_rate_pct": round(100 * float(g["win"].mean()), 2)}
        for k, g in tr.groupby("hour")
    }
    R["by_weekday"] = {
        str(k): {"trades": int(len(g)), "net_pnl": round(float(g["pnl"].sum()), 2),
                 "win_rate_pct": round(100 * float(g["win"].mean()), 2)}
        for k, g in tr.groupby("weekday")
    }

    # ---------------- costs ----------------------------------------------------
    comm = p.commission_per_lot_rt * p.lot * len(tr)
    slip = p.slippage_ticks * TICK_SIZE * p.lot * CONTRACT_SIZE * len(tr)
    sprd = float(tr["spread_at_entry"].sum()) * p.lot * CONTRACT_SIZE
    net = st.balance - p.initial_balance
    R["costs"] = {
        "total_commission": round(comm, 2),
        "total_slippage": round(slip, 2),
        "total_spread_paid": round(sprd, 2),
        "total_cost": round(comm + slip + sprd, 2),
        "gross_before_costs": round(net + comm + slip + sprd, 2),
        "cost_pct_of_gross": round(100 * (comm + slip + sprd) / max(1e-9, net + comm + slip + sprd), 2),
        "avg_cost_per_trade": round((comm + slip + sprd) / len(tr), 4),
        "avg_entry_spread": round(float(tr["spread_at_entry"].mean()), 4),
    }

    # ---------------- account / leverage ----------------------------------------
    avg_px = float(ticks["bid"].mean())
    notional = avg_px * p.lot * CONTRACT_SIZE
    R["account"] = {
        "lot": p.lot,
        "leverage": p.leverage,
        "ounces_per_trade": p.lot * CONTRACT_SIZE,
        "usd_per_0.01_move": round(p.lot * CONTRACT_SIZE * 0.01, 4),
        "avg_notional": round(notional, 2),
        "margin_per_trade": round(notional / p.leverage, 2),
        "margin_pct_of_initial": round(100 * (notional / p.leverage) / p.initial_balance, 4),
    }
    R["signal_stats"] = {"signals_fired": st.signals, "rejects": st.rejects}
    R["params"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(p).items()}
    return R, tr


def _max_streak(mask) -> int:
    m = 0; c = 0
    for v in mask:
        c = c + 1 if v else 0
        m = max(m, c)
    return m


# --------------------------------------------------------------------------- #
def render_markdown(R: dict) -> str:
    s, d, dd, dl, ms = R["summary"], R["data"], R["drawdown"], R["daily_summary"], R["monthly_summary"]
    L = []
    A = L.append
    A("# TFAM — REAL TICK DATA BACKTEST REPORT")
    A("### XAUUSD · 0.01 lot · 800x leverage · real MT5 tick data\n")
    A("---\n## 1. Data coverage\n")
    A("| Item | Value |\n|---|---|")
    A(f"| Total ticks | **{d['total_ticks']:,}** |")
    A(f"| Period | {d['first_tick']} → {d['last_tick']} |")
    A(f"| Calendar days | {d['calendar_days']:,} |")
    A(f"| Trading days in data | {d['trading_days_in_data']:,} |")
    A(f"| Months in data | {d['months_in_data']} |")
    A(f"| Gold price range | ${d['price_min']:,.2f} – ${d['price_max']:,.2f} |")
    A(f"| Avg / median spread | ${d['avg_spread']} / ${d['median_spread']} |")
    A(f"| 95th pct spread | ${d['p95_spread']} |")

    A("\n---\n## 2. Overall results\n")
    A("| Metric | Value |\n|---|---|")
    A(f"| Initial balance | ${s['initial_balance']:,.2f} |")
    A(f"| **Final balance** | **${s['final_balance']:,.2f}** |")
    A(f"| **Net profit** | **${s['net_profit']:,.2f}** |")
    A(f"| **Total return** | **{s['return_pct']:,.2f}%** |")
    A(f"| **Total trades** | **{s['total_trades']:,}** |")
    A(f"| **Winning trades** | **{s['winning_trades']:,}** |")
    A(f"| **Losing trades** | **{s['losing_trades']:,}** |")
    A(f"| **Profitable trades %** | **{s['profitable_trades_pct']}%** |")
    A(f"| **Total profit (gross)** | **${s['total_profit']:,.2f}** |")
    A(f"| **Total loss (gross)** | **${s['total_loss']:,.2f}** |")
    A(f"| **Profit factor** | **{s['profit_factor']}** |")
    A(f"| Expectancy per trade | ${s['expectancy_per_trade']} |")
    A(f"| Avg win / avg loss | ${s['avg_win']} / ${s['avg_loss']} |")
    A(f"| Payoff ratio | {s['payoff_ratio']} |")
    A(f"| Largest win / loss | ${s['largest_win']} / ${s['largest_loss']} |")

    A("\n---\n## 3. Drawdown\n")
    A("| Metric | Value |\n|---|---|")
    A(f"| **Max drawdown (USD)** | **${dd['max_drawdown_usd']:,.2f}** |")
    A(f"| **Max drawdown (%)** | **{dd['max_drawdown_pct']}%** |")
    A(f"| Peak before DD | ${dd['peak_before_dd']:,.2f} ({dd['dd_peak_date']}) |")
    A(f"| Trough | ${dd['trough']:,.2f} ({dd['dd_trough_date']}) |")
    A(f"| Recovered | {dd['recovered']} |")
    A(f"| Underwater duration | {dd['underwater_days']} days |")
    A(f"| Recovery factor | {dd['recovery_factor']} |")
    A(f"| Avg drawdown | ${dd['avg_drawdown_usd']} |")

    A("\n### Risk-adjusted\n")
    A("| Metric | Value |\n|---|---|")
    for k, v in R["risk"].items():
        A(f"| {k} | {v} |")

    A("\n---\n## 4. MONTH BY MONTH\n")
    A("| Month | Trades | Wins | Losses | Win% | Gross profit | Gross loss | **Net P&L** | Return% | PF | Balance |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for m in R["monthly"]:
        A(f"| {m['month']} | {m['trades']:,} | {m['wins']:,} | {m['losses']:,} | {m['win_rate_pct']}% | "
          f"${m['gross_profit']:,.2f} | ${m['gross_loss']:,.2f} | **${m['net_pnl']:,.2f}** | "
          f"{m['return_pct']}% | {m['profit_factor']} | ${m['balance_end']:,.2f} |")
    A("\n**Monthly summary**\n")
    A("| Metric | Value |\n|---|---|")
    A(f"| Total months | {ms['total_months']} |")
    A(f"| **Profitable months** | **{ms['profitable_months']}** |")
    A(f"| **Losing months** | **{ms['losing_months']}** |")
    A(f"| % profitable months | {ms['pct_profitable_months']}% |")
    A(f"| Best month | {ms['best_month']} (${ms['best_month_pnl']:,.2f}) |")
    A(f"| Worst month | {ms['worst_month']} (${ms['worst_month_pnl']:,.2f}) |")
    A(f"| Avg month P&L | ${ms['avg_month_pnl']:,.2f} |")
    A(f"| Median month P&L | ${ms['median_month_pnl']:,.2f} |")
    A(f"| Avg trades / month | {ms['avg_trades_per_month']:,} |")

    if len(R["yearly"]) > 1:
        A("\n---\n## 5. YEAR BY YEAR\n")
        A("| Year | Trades | Wins | Losses | Win% | Net P&L | Trading days |")
        A("|---|---|---|---|---|---|---|")
        for y in R["yearly"]:
            A(f"| {y['year']} | {y['trades']:,} | {y['wins']:,} | {y['losses']:,} | "
              f"{y['win_rate_pct']}% | ${y['net_pnl']:,.2f} | {y['trading_days']} |")

    A("\n---\n## 6. Daily statistics\n")
    A("| Metric | Value |\n|---|---|")
    A(f"| Total trading days | {dl['total_trading_days']:,} |")
    A(f"| **Max trades in one day** | **{dl['max_trades_in_a_day']}** ({dl['max_trades_day_date']}) |")
    A(f"| **Min trades in one day** | **{dl['min_trades_in_a_day']}** ({dl['min_trades_day_date']}) |")
    A(f"| Avg trades / day | {dl['avg_trades_per_day']} |")
    A(f"| Median trades / day | {dl['median_trades_per_day']} |")
    A(f"| **Profitable days** | **{dl['profitable_days']:,}** |")
    A(f"| **Losing days** | **{dl['losing_days']:,}** |")
    A(f"| % profitable days | {dl['pct_profitable_days']}% |")
    A(f"| Best day | ${dl['best_day_pnl']:,.2f} ({dl['best_day_date']}) |")
    A(f"| Worst day | ${dl['worst_day_pnl']:,.2f} ({dl['worst_day_date']}) |")
    A(f"| Avg day P&L | ${dl['avg_day_pnl']:,.2f} |")
    A(f"| Max consecutive winning days | {dl['max_consecutive_winning_days']} |")
    A(f"| Max consecutive losing days | {dl['max_consecutive_losing_days']} |")

    A("\n### Streaks & holding\n")
    A("| Metric | Value |\n|---|---|")
    for k, v in R["streaks"].items():
        A(f"| {k} | {v} |")
    for k, v in R["holding"].items():
        A(f"| {k} | {v} |")

    A("\n---\n## 7. Exit reason breakdown\n")
    A("| Exit | Trades | % of all | Net P&L | Avg | Win% |\n|---|---|---|---|---|---|")
    for k, v in sorted(R["by_exit_reason"].items(), key=lambda x: -x[1]["net_pnl"]):
        A(f"| {k} | {v['trades']:,} | {v['pct_of_trades']}% | ${v['net_pnl']:,.2f} | ${v['avg_pnl']} | {v['win_rate_pct']}% |")

    A("\n## 8. Long vs Short\n")
    A("| Side | Trades | Net P&L | Win% | Avg |\n|---|---|---|---|---|")
    for k, v in R["by_side"].items():
        A(f"| {k} | {v['trades']:,} | ${v['net_pnl']:,.2f} | {v['win_rate_pct']}% | ${v['avg_pnl']} |")

    A("\n## 9. By hour (server time)\n")
    A("| Hour | Trades | Net P&L | Win% |\n|---|---|---|---|")
    for k in sorted(R["by_hour"]):
        v = R["by_hour"][k]
        A(f"| {k:02d} | {v['trades']:,} | ${v['net_pnl']:,.2f} | {v['win_rate_pct']}% |")

    A("\n## 10. By weekday\n")
    A("| Day | Trades | Net P&L | Win% |\n|---|---|---|---|")
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for k in order:
        if k in R["by_weekday"]:
            v = R["by_weekday"][k]
            A(f"| {k} | {v['trades']:,} | ${v['net_pnl']:,.2f} | {v['win_rate_pct']}% |")

    A("\n---\n## 11. Cost analysis\n")
    A("| Item | Value |\n|---|---|")
    c = R["costs"]
    A(f"| Gross profit before costs | ${c['gross_before_costs']:,.2f} |")
    A(f"| Spread paid | −${c['total_spread_paid']:,.2f} |")
    A(f"| Commission | −${c['total_commission']:,.2f} |")
    A(f"| Slippage | −${c['total_slippage']:,.2f} |")
    A(f"| **Total cost** | **−${c['total_cost']:,.2f}** ({c['cost_pct_of_gross']}% of gross) |")
    A(f"| Avg cost per trade | ${c['avg_cost_per_trade']} |")
    A(f"| **Net profit** | **${s['net_profit']:,.2f}** |")

    A("\n## 12. Account / leverage (800x)\n")
    A("| Item | Value |\n|---|---|")
    for k, v in R["account"].items():
        A(f"| {k} | {v} |")

    A("\n---\n> ⚠️ Simulated execution on real historical tick data. Past performance "
      "is not indicative of future results. Leveraged gold trading can lose the full account.")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
def make_charts(R: dict, tr: pd.DataFrame, p: Params, path: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    eq = p.initial_balance + tr["pnl"].cumsum()
    pk = eq.cummax()
    mn = pd.DataFrame(R["monthly"])

    fig, ax = plt.subplots(4, 1, figsize=(14, 15),
                           gridspec_kw={"height_ratios": [3, 1, 1.6, 1.6]})
    ax[0].plot(tr["exit_time"], eq, lw=1.1, color="#c8961e")
    ax[0].set_title(f"TFAM — XAUUSD 0.01 lot @ 800x — REAL TICK DATA "
                    f"({R['data']['total_ticks']:,} ticks)")
    ax[0].set_ylabel("Balance (USD)"); ax[0].grid(alpha=.3)
    ax[1].fill_between(tr["exit_time"], eq - pk, 0, color="#c0392b", alpha=.6)
    ax[1].set_ylabel("Drawdown (USD)"); ax[1].grid(alpha=.3)
    cols = ["#2e8b57" if v > 0 else "#c0392b" for v in mn["net_pnl"]]
    ax[2].bar(range(len(mn)), mn["net_pnl"], color=cols)
    ax[2].set_xticks(range(len(mn))); ax[2].set_xticklabels(mn["month"], rotation=90, fontsize=7)
    ax[2].set_ylabel("Monthly P&L (USD)"); ax[2].grid(alpha=.3)
    h = sorted(R["by_hour"].items())
    ax[3].bar([x[0] for x in h], [x[1]["net_pnl"] for x in h],
              color=["#2e8b57" if x[1]["net_pnl"] > 0 else "#c0392b" for x in h])
    ax[3].set_xlabel("Hour"); ax[3].set_ylabel("P&L by hour (USD)"); ax[3].grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


# --------------------------------------------------------------------------- #
def main():
    if len(sys.argv) < 2:
        print("usage: python src/report.py /path/to/XAUUSD.txt")
        sys.exit(1)
    src = sys.argv[1]
    os.makedirs(RESULTS, exist_ok=True)

    ticks = load_ticks(src)

    # auto-calibrate thresholds to THIS feed's noise level (no P&L used)
    if "--no-calib" in sys.argv:
        p = Params()
    else:
        print("[calib] measuring signal distribution on this feed ...")
        p = calibrate(ticks, Params())

    st = run_backtest(ticks, p)
    R, tr = build_report(st, ticks, p)

    with open(os.path.join(RESULTS, "real_results.json"), "w") as f:
        json.dump(R, f, indent=2, default=str)
    tr.to_csv(os.path.join(RESULTS, "real_trades.csv"), index=False)
    with open(os.path.join(RESULTS, "REAL_DATA_REPORT.md"), "w") as f:
        f.write(render_markdown(R))
    try:
        make_charts(R, tr, p, os.path.join(RESULTS, "real_equity.png"))
    except Exception as e:
        print("chart skipped:", e)

    print("\n=== DONE ===")
    print(json.dumps(R["summary"], indent=2))
    print(json.dumps(R["daily_summary"], indent=2))


if __name__ == "__main__":
    main()
