"""XAUUSD — EMA 9/12 crossover on ORIGINAL M1 candles.

System (nothing else):
  * Chart  : original XAUUSD M1 candlestick data (real broker M1, tiumbj/M1_XAUUSD)
  * Entry  : BUY when EMA9 crosses ABOVE EMA12, SELL when it crosses BELOW
  * Exit   : opposite cross closes and reverses (always in market)
  * Lot    : fixed 0.10
  * Cost   : spread ONLY, 20 points = $0.20/oz (no extra slippage)
  * No SL/TP, no filter, no RSI — crossover only.

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

DATA = "data/xauusd_m1_slice.csv"
TF_LABEL = "M1 (original broker candles)"
BALANCE0 = 10_000.0
FIXED_LOT = 0.10
SPREAD = 0.20              # 20 points on XAUUSD = $0.20/oz  (user setting)
SLIPPAGE = 0.00            # spread only
OZ = FIXED_LOT * 100.0     # 0.10 lot = 10 oz

# cost sensitivity shown in the report (per 0.10 lot round trip)
SCENARIOS = [
    ("spread 20 pts only (used here)", 0.20, 0.00),
    ("spread 20 pts + slip 5 pts", 0.20, 0.05),
    ("spread 20 pts + slip 10 pts", 0.20, 0.10),
    ("old setting: 35 pts + slip 10 pts", 0.35, 0.10),
]
PERIODS = [
    ("Feb-2022 (last 30 days)", "2022-02-02 23:45", "2022-03-04 23:59"),
    ("Jan-2022 (validation)", "2022-01-01", "2022-01-31 23:59"),
]


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    df = add_signals(add_indicators(m1))
    print(f"{TF_LABEL}: {len(df)} bars ({df.time.min()} -> {df.time.max()})")
    print(f"cost = spread ${SPREAD}/oz ({int(SPREAD * 100)} points), "
          f"slippage ${SLIPPAGE}/oz -> ${(SPREAD + SLIPPAGE) * OZ:.2f} per 0.10-lot trade\n")

    test_start = df["time"].max() - pd.Timedelta(days=30)
    trades, eq, s = run_backtest(df, test_start, balance0=BALANCE0, spread=SPREAD,
                                 slippage=SLIPPAGE, exit_mode="reverse",
                                 fixed_lot=FIXED_LOT)
    tr_all, eq_all, s_all = run_backtest(df, df["time"].min(), balance0=BALANCE0,
                                        spread=SPREAD, slippage=SLIPPAGE,
                                        exit_mode="reverse", fixed_lot=FIXED_LOT)
    cost_per_trade = (SPREAD + SLIPPAGE) * OZ

    os.makedirs("results", exist_ok=True)
    trades.to_csv("results/trades.csv", index=False)
    eq.to_csv("results/equity_curve.csv", index=False)

    def show(tag, st):
        print(f"== {tag} ==  trades={st['n_trades']}  win={st['win_rate']}%  "
              f"P/L=${st['net_pnl']} ({st['return_pct']:+.2f}%)  PF={st['profit_factor']}  "
              f"DD={st['max_dd_pct']}%  exp=${st['expectancy']}")

    show("Feb-2022 (last 30 days)", s)
    show("full window Jan 2 - Mar 4", s_all)

    # -------- cost sensitivity --------
    print("\nCost sensitivity (Feb-2022, same signals):")
    sens = []
    for tag, sp, sl in SCENARIOS:
        _, _, st = run_backtest(df, test_start, balance0=BALANCE0, spread=sp,
                                slippage=sl, exit_mode="reverse", fixed_lot=FIXED_LOT)
        tot_cost = st["n_trades"] * (sp + sl) * OZ
        gross = st["net_pnl"] + tot_cost
        sens.append((tag, st, tot_cost, gross))
        print(f"  {tag:34s} ${st['net_pnl']:>9.2f} ({st['return_pct']:>7.2f}%) "
              f"PF={st['profit_factor']:>5}  costs=${tot_cost:>8.2f}  gross=${gross:>9.2f}")

    # -------- chart --------
    t = pd.to_datetime(df["time"])
    m = t >= test_start
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(13, 9), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 1.4, 1]})
    ax1.plot(t[m], df.loc[m, "close"], lw=0.6, color="black", label="XAUUSD M1 close")
    ax1.plot(t[m], df.loc[m, "ema_fast"], lw=0.8, color="blue", label=f"EMA{PARAMS['ema_fast']}")
    ax1.plot(t[m], df.loc[m, "ema_slow"], lw=0.8, color="red", label=f"EMA{PARAMS['ema_slow']}")
    if not trades.empty:
        tt = pd.to_datetime(trades["entry_time"])
        longs = trades["direction"] == "LONG"
        ax1.scatter(tt[longs], trades.loc[longs, "entry"], marker="^", s=14, color="green",
                    label=f"Buy ({int(longs.sum())})", zorder=5)
        ax1.scatter(tt[~longs], trades.loc[~longs, "entry"], marker="v", s=14, color="darkred",
                    label=f"Sell ({int((~longs).sum())})", zorder=5)
    ax1.set_title(f"XAUUSD ORIGINAL M1 candles — EMA 9/12 crossover (last 30 days, "
                  f"{s['n_trades']} trades, {s['return_pct']:+.2f}%, "
                  f"spread {int(SPREAD * 100)} pts only)")
    ax1.legend(fontsize=8, loc="upper left", ncol=3)
    ax1.grid(alpha=0.3)

    et = pd.to_datetime(eq["time"])
    ax2.plot(et, eq["equity"], lw=1.0, color="teal")
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

    # -------- report --------
    t0 = pd.to_datetime(df.loc[m, "time"].min())
    t1 = pd.to_datetime(df.loc[m, "time"].max())
    lines = [
        "# XAUUSD Backtest Report — EMA 9/12 crossover on original M1 candles",
        "",
        "**Chart:** original XAUUSD **M1** candles (real broker data, tiumbj/M1_XAUUSD)",
        f"**Cost:** **spread only, {int(SPREAD * 100)} points = ${SPREAD}/oz** "
        f"= ${cost_per_trade:.2f} per 0.10-lot round trip (no slippage added)",
        f"**Test period:** {t0} → {t1} (last 30 days, {int(m.sum())} M1 candles)",
        f"**Balance:** ${BALANCE0:,.0f} | **Lot:** fixed {FIXED_LOT} | "
        "**Exit:** opposite crossover (reverse, always in market)",
        "",
        "## Result (last 30 days, Feb-2022)",
        "",
        f"- Trades: **{s['n_trades']}** (Long {s['longs']} / Short {s['shorts']})",
        f"- Win rate: **{s['win_rate']}%** ({s['wins']}W / {s['losses']}L)",
        f"- Net P/L: **${s['net_pnl']:,.2f} ({s['return_pct']:+.2f}%)** → "
        f"end balance ${s['end_balance']:,.2f}",
        f"- Profit factor: **{s['profit_factor']}** | Expectancy: **${s['expectancy']}/trade**",
        f"- Max drawdown: **{s['max_dd_pct']}%** | Sharpe (daily): **{s['sharpe_daily']}**",
        f"- Spread paid: **${s['n_trades'] * cost_per_trade:,.2f}** "
        f"({s['n_trades']} x ${cost_per_trade:.2f})",
        "",
        "## Full window (Jan 2 – Mar 4, 2 months)",
        "",
        f"- Trades **{s_all['n_trades']}** | win {s_all['win_rate']}% | "
        f"P/L **${s_all['net_pnl']:,.2f} ({s_all['return_pct']:+.2f}%)** | "
        f"PF {s_all['profit_factor']} | max DD {s_all['max_dd_pct']}%",
        "",
        "## Cost sensitivity (same Feb signals, 0.10 lot)",
        "",
        "| cost setting | net P/L | return | PF | spread paid | gross before cost |",
        "|---|---|---|---|---|---|",
    ]
    for tag, st, tot_cost, gross in sens:
        lines.append(f"| {tag} | ${st['net_pnl']:,.2f} | {st['return_pct']:+.2f}% | "
                     f"{st['profit_factor']} | ${tot_cost:,.2f} | ${gross:,.2f} |")
    lines += [
        "",
        "Reading the last column: the raw M1 crossover is roughly break-even *before* "
        "costs, so every point of spread decides profit or loss. At the old 35+10 pts "
        "setting the same signals lose ${:,.2f}; at 20 pts only they lose ${:,.2f}.".format(
            sens[-1][1]["net_pnl"], sens[0][1]["net_pnl"]),
        "",
        "## System rules",
        "",
        "- Original M1 candles; BUY on EMA9 cross above EMA12, SELL on cross below",
        "- Signal on candle close → entry at next candle open (no lookahead)",
        "- Opposite cross closes & reverses. Fixed lot. No SL/TP, no filter, no RSI.",
        "",
        "## Files",
        "",
        "- `data/xauusd_m1_slice.csv` — original M1 candles used here",
        "- `results/trades.csv`, `results/equity_curve.csv`, `results/backtest_chart.png`",
        "- `python3 compare_timeframes.py` — M1/M3/M5/M15 on the same system",
        "- `legacy/` — old Renko experiments",
    ]
    with open("results/backtest_report.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nSaved: results/trades.csv, results/equity_curve.csv, "
          "results/backtest_chart.png, results/backtest_report.md")


if __name__ == "__main__":
    main()
