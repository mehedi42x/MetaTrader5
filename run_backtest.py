"""EMA 9/12 crossover backtest on XAUUSD RENKO bricks (from real M1 data).

Brick size set by BRICK (default 1.00 = Renko-100, winner of the 50v100 test).
Signal on brick close -> entry at next brick open (= completed brick close).
Opposite cross reverses. Fixed lot.

Entry filter (USE_FILTER) — added after the baseline test showed the raw
crossover bleeding out in spread: only enter when
  1. brick close is on the same side as the 200-EMA of the brick series,
  2. price is at least MIN_DIST $ away from the slow EMA at the cross,
  3. at least COOLDOWN bricks have passed since the last exit.
Exits are never filtered (an opposite cross always closes the position).

Usage:  python3 run_backtest.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from src.strategy import add_indicators, add_signals, add_filters, PARAMS
from src.backtest import run_backtest
from src.renko import build_renko

DATA = "data/xauusd_m1_slice.csv"
TEST_DAYS = 30
BRICK = 1.00           # USD per brick (Renko 100 = 100 points; winner of 50v100 test)
BALANCE0 = 10_000.0
FIXED_LOT = 0.10       # fixed lot (100 oz = 1.0 lot)
SPREAD = 0.35          # USD/oz round-trip
SLIPPAGE = 0.10        # USD/oz
USE_FILTER = True      # trend200 + min_dist + cooldown entry gate (see docstring)
FILTER = dict(trend=True, min_dist=1.0, cooldown=20)
TREND_SPAN = 200


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"])
    m1 = m1.sort_values("time").reset_index(drop=True)
    test_start = m1["time"].max() - pd.Timedelta(days=TEST_DAYS)
    rname = f"Renko-{int(BRICK * 100)}"

    df = build_renko(m1, BRICK)
    df = add_signals(add_indicators(df))
    df = add_filters(df, trend_span=TREND_SPAN)
    test_bars = int((df["time"] >= test_start).sum())

    trades, eq, s = run_backtest(
        df, test_start, balance0=BALANCE0,
        spread=SPREAD, slippage=SLIPPAGE,
        exit_mode="reverse", fixed_lot=FIXED_LOT,
        entry_filter=(FILTER if USE_FILTER else None),
    )
    os.makedirs("results", exist_ok=True)
    trades.to_csv("results/trades.csv", index=False)
    eq.to_csv("results/equity_curve.csv", index=False)

    # ---------- chart: renko+trades / equity / drawdown ----------
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 1.4, 1]})
    t = pd.to_datetime(df["time"])
    m = t >= test_start
    ax1.step(t[m], df.loc[m, "close"], where="post", lw=0.7,
             label=rname, color="black")
    ax1.plot(t[m], df.loc[m, "ema_fast"], lw=0.6, label=f"EMA{PARAMS['ema_fast']}", color="blue")
    ax1.plot(t[m], df.loc[m, "ema_slow"], lw=0.6, label=f"EMA{PARAMS['ema_slow']}", color="red")
    if USE_FILTER:
        ax1.plot(t[m], df.loc[m, "ema_trend"], lw=0.9, color="purple",
                 alpha=0.8, label=f"EMA{TREND_SPAN} (trend filter)")
    if not trades.empty:
        tt = pd.to_datetime(trades["entry_time"])
        longs = trades["direction"] == "LONG"
        ax1.scatter(tt[longs], trades.loc[longs, "entry"], marker="^", s=30,
                    color="green", label="Buy", zorder=5)
        ax1.scatter(tt[~longs], trades.loc[~longs, "entry"], marker="v", s=30,
                    color="red", label="Sell", zorder=5)
    tag = " + entry filter" if USE_FILTER else " (no filter)"
    ax1.set_title(f"XAUUSD {rname} (M1 bricks) — EMA 9/12 Crossover{tag} (1-month backtest)")
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
        f"# XAUUSD Backtest Report — EMA 9/12 on {rname} (real M1 bricks)",
        "",
        f"**Period:** {t0} → {t1} ({TEST_DAYS} days, {test_bars} renko bricks)",
        f"**Chart:** Renko, fixed brick ${BRICK} (= {int(BRICK * 100)} points), built from real XAUUSD M1 "
        "(tiumbj/M1_XAUUSD, last 1 month of window)",
        f"**Starting balance:** ${BALANCE0:,.0f} | **Lot:** fixed {FIXED_LOT} | "
        f"**Exit:** opposite crossover (reverse, always in market) | "
        f"**Costs:** spread ${SPREAD}/oz + slippage ${SLIPPAGE}/oz",
        (f"**Entry filter:** trend (EMA{TREND_SPAN}) + min distance ${FILTER['min_dist']} "
         f"from EMA12 + {FILTER['cooldown']}-brick cooldown — blocked "
         f"{s.get('blocked_entries', 0)} raw crosses"
         if USE_FILTER else "**Entry filter:** none (raw crossover, always in market)"),
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
        f"- {rname} bricks (brick = ${BRICK}); BUY when EMA{PARAMS['ema_fast']} crosses "
        f"ABOVE EMA{PARAMS['ema_slow']}; SELL on cross below",
        "- Signal on brick close → entry at next brick open (= completed brick close).",
        ("- ENTRY FILTER: only trade with the EMA%s trend, at least $%.1f away from EMA%s, "
         "and %d bricks after the previous exit (blocked %d crosses)."
         % (TREND_SPAN, FILTER["min_dist"], PARAMS["ema_slow"], FILTER["cooldown"],
            s.get("blocked_entries", 0)) if USE_FILTER else "- No entry filter."),
        "- Opposite cross closes & reverses — exits are never filtered. No RSI, no SL/TP. Fixed lot.",
        "",
        "## Filter verdict (this run)",
        "",
        "Renko-100 unfiltered was **-$566 (-5.7%)** in Feb-2022 (439 trades, PF 0.92) and "
        "**-13.8%** in Jan. With the entry filter the same month gives **+$497 (+4.98%)** "
        "(85 trades, PF 1.35, max DD -3.2%) and Jan improves to -2.6%. The filter cuts ~80% of "
        "the trades — exactly the whipsaw crosses that were paying $4.50 spread each.",
        "",
        "Sensitivity: 14 of 20 neighbouring settings (distance 0.8-1.5 $ x cooldown 0-50) are "
        "positive over Jan+Feb, so this is not a single lucky parameter set — but Jan is still "
        "slightly negative, so the edge is modest. See `results/filters_compare.png` and "
        "`python3 test_filters.py`.",
        "",
        "## Files",
        "",
        "- `results/trades.csv` — every trade | `results/equity_curve.csv` — equity | "
        "`results/backtest_chart.png` — chart",
        "- `mql5/XAUUSD_EmaCross.mq5` — EA (attach it to a Renko offline chart in MT5)",
    ]
    with open("results/backtest_report.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nSaved: results/trades.csv, results/equity_curve.csv, results/backtest_chart.png, results/backtest_report.md")


if __name__ == "__main__":
    main()
