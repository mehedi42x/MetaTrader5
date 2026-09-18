"""Pure EMA 9/12 crossover backtest on XAUUSD RENKO-50 bricks (from M15 data).

Renko-50 = fixed $0.50 brick (50 points on 2-digit gold quote).
Signal on brick close -> entry at next brick open (= completed brick close).
Opposite cross reverses. Fixed lot. No other logic.

Usage:  python3 run_backtest.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from src.strategy import add_indicators, add_signals, PARAMS
from src.backtest import run_backtest
from src.renko import build_renko

DATA = "data/xauusd_m15_slice.csv"
TEST_DAYS = 30
BRICK = 0.50           # USD per brick (Renko 50)
BALANCE0 = 10_000.0
FIXED_LOT = 0.10       # fixed lot (100 oz = 1.0 lot)
SPREAD = 0.35          # USD/oz round-trip
SLIPPAGE = 0.10        # USD/oz


def main():
    m15 = pd.read_csv(DATA, parse_dates=["time"])
    m15 = m15.sort_values("time").reset_index(drop=True)
    test_start = m15["time"].max() - pd.Timedelta(days=TEST_DAYS)

    df = build_renko(m15, BRICK)
    df = add_signals(add_indicators(df))
    test_bars = int((df["time"] >= test_start).sum())

    trades, eq, s = run_backtest(
        df, test_start, balance0=BALANCE0,
        spread=SPREAD, slippage=SLIPPAGE,
        exit_mode="reverse", fixed_lot=FIXED_LOT,
    )
    os.makedirs("results", exist_ok=True)
    df.to_csv("data/xauusd_renko50_bricks.csv", index=False)
    trades.to_csv("results/trades.csv", index=False)
    eq.to_csv("results/equity_curve.csv", index=False)

    # ---------- chart: renko+trades / equity / drawdown ----------
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 1.4, 1]})
    t = pd.to_datetime(df["time"])
    m = t >= test_start
    ax1.step(t[m], df.loc[m, "close"], where="post", lw=0.7,
             label="Renko-50", color="black")
    ax1.plot(t[m], df.loc[m, "ema_fast"], lw=0.6, label=f"EMA{PARAMS['ema_fast']}", color="blue")
    ax1.plot(t[m], df.loc[m, "ema_slow"], lw=0.6, label=f"EMA{PARAMS['ema_slow']}", color="red")
    if not trades.empty:
        tt = pd.to_datetime(trades["entry_time"])
        longs = trades["direction"] == "LONG"
        ax1.scatter(tt[longs], trades.loc[longs, "entry"], marker="^", s=30,
                    color="green", label="Buy", zorder=5)
        ax1.scatter(tt[~longs], trades.loc[~longs, "entry"], marker="v", s=30,
                    color="red", label="Sell", zorder=5)
    ax1.set_title("XAUUSD Renko-50 — EMA 9/12 Crossover ONLY (1-month backtest)")
    ax1.legend(fontsize=8, loc="upper left")
    ax1.grid(alpha=0.3)

    et = pd.to_datetime(eq["time"])
    ax2.plot(et, eq["equity"], lw=1.1, color="teal")
    ax2.axhline(BALANCE0, color="gray", ls="--", lw=0.8)
    ax2.set_ylabel("Equity ($)")
    ax2.grid(alpha=0.3)

    ev = np.append([BALANCE0], eq["equity"].to_numpy())
    dd = (ev - np.maximum.accumulate(ev)) / np.maximum.accumulate(ev) * 100
    ax3.fill_between(et, dd[1:], 0, color="red", alpha=0.35)
    ax3.set_ylabel("DD %")
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.tight_layout()
    fig.savefig("results/backtest_chart.png", dpi=120)
    plt.close(fig)

    # ---------- report ----------
    t0 = pd.to_datetime(df.loc[m, "time"].min())
    t1 = pd.to_datetime(df.loc[m, "time"].max())
    lines = [
        "# XAUUSD Backtest Report — EMA 9/12 on RENKO-50 (M15 source)",
        "",
        f"**Period:** {t0} → {t1} ({TEST_DAYS} days, {test_bars} renko bricks)",
        "**Chart:** Renko, fixed brick $0.50 (= 50 points), built from XAUUSD M15 "
        "(Dukascopy-sourced, last 1 month of file)",
        f"**Starting balance:** ${BALANCE0:,.0f} | **Lot:** fixed {FIXED_LOT} | "
        f"**Exit:** opposite crossover (reverse, always in market) | "
        f"**Costs:** spread ${SPREAD}/oz + slippage ${SLIPPAGE}/oz",
        "",
        "## Results (1 month)",
        "",
        f"- Trades: **{s['n_trades']}** (Long {s['longs']} / Short {s['shorts']})",
        f"- Win rate: **{s['win_rate']}%** ({s['wins']}W / {s['losses']}L)",
        f"- Net P/L: **${s['net_pnl']:,.2f} ({s['return_pct']:+.2f}%)** → End balance ${s['end_balance']:,.2f}",
        f"- Profit factor: **{s['profit_factor']}** | Expectancy: **${s['expectancy']}/trade**",
        f"- Avg win ${s['avg_win']} / Avg loss ${s['avg_loss']} | Max win ${s['max_win']} / Max loss ${s['max_loss']}",
        f"- Max drawdown: **${s['max_dd_usd']} ({s['max_dd_pct']}%)** | Sharpe (daily): **{s['sharpe_daily']}**",
        "",
        "## System rules (Renko + crossover ONLY)",
        "",
        f"- Renko-50 bricks (brick = ${BRICK}); BUY when EMA{PARAMS['ema_fast']} crosses "
        f"ABOVE EMA{PARAMS['ema_slow']}; SELL on cross below",
        "- Signal on brick close → entry at next brick open (= completed brick close).",
        "- Opposite cross closes & reverses. No RSI, no session filter, no SL/TP. Fixed lot.",
        "",
        "## Files",
        "",
        "- `data/xauusd_renko50_bricks.csv` — all renko bricks | `results/trades.csv` — every trade",
        "- `results/equity_curve.csv` — equity | `results/backtest_chart.png` — chart",
        "- `mql5/XAUUSD_EmaCross.mq5` — EA (attach it to a Renko-50 offline chart in MT5)",
    ]
    with open("results/backtest_report.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nSaved results + data/xauusd_renko50_bricks.csv")


if __name__ == "__main__":
    main()
