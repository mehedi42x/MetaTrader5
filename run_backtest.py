"""XAUUSD — EMA 9/12 crossover on normal M3 CANDLES (no Renko).

System (nothing else):
  * Chart  : normal candlestick, 3-minute timeframe (built from real XAUUSD M1)
  * Entry  : BUY when EMA9 crosses ABOVE EMA12, SELL when it crosses BELOW
  * Exit   : opposite cross closes and reverses (always in market)
  * Lot    : fixed 0.10
  * Costs  : spread $0.35/oz + slippage $0.10/oz
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

M1_DATA = "data/xauusd_m1_slice.csv"
M3_DATA = "data/xauusd_m3_slice.csv"
TF_MIN = 3                 # 3-minute candles
TEST_DAYS = 30
BALANCE0 = 10_000.0
FIXED_LOT = 0.10
SPREAD = 0.35              # USD/oz round-trip
SLIPPAGE = 0.10            # USD/oz


def resample_ohlc(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """M1 bars -> N-minute candles (open=first, high=max, low=min, close=last)."""
    g = (m1.set_index("time")
            .resample(f"{minutes}min")
            .agg(open=("open", "first"), high=("high", "max"),
                 low=("low", "min"), close=("close", "last"), n=("close", "size")))
    g = g[g.n > 0].drop(columns="n")
    return g.reset_index()


def main():
    m1 = pd.read_csv(M1_DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    m3 = resample_ohlc(m1, TF_MIN)
    os.makedirs("data", exist_ok=True)
    m3.to_csv(M3_DATA, index=False)
    print(f"M1 source: {len(m1)} bars ({m1.time.min()} -> {m1.time.max()})")
    print(f"{TF_MIN}-min candles: {len(m3)} bars -> {M3_DATA}\n")

    df = add_signals(add_indicators(m3))
    test_start = df["time"].max() - pd.Timedelta(days=TEST_DAYS)

    trades, eq, s = run_backtest(
        df, test_start, balance0=BALANCE0, spread=SPREAD, slippage=SLIPPAGE,
        exit_mode="reverse", fixed_lot=FIXED_LOT,
    )
    # whole available window as a second (longer) sample
    tr_all, eq_all, s_all = run_backtest(
        df, df["time"].min(), balance0=BALANCE0, spread=SPREAD, slippage=SLIPPAGE,
        exit_mode="reverse", fixed_lot=FIXED_LOT,
    )

    os.makedirs("results", exist_ok=True)
    trades.to_csv("results/trades.csv", index=False)
    eq.to_csv("results/equity_curve.csv", index=False)

    t = pd.to_datetime(df["time"])
    m = t >= test_start

    # ---------------- print ----------------
    def show(tag, st):
        print(f"== {tag} ==  trades={st['n_trades']}  win={st['win_rate']}%  "
              f"P/L=${st['net_pnl']} ({st['return_pct']:+.2f}%)  PF={st['profit_factor']}  "
              f"DD={st['max_dd_pct']}%  exp=${st['expectancy']}")

    show(f"last {TEST_DAYS} days (Feb-2022)", s)
    show("full 2-month window (Jan 2 - Mar 4)", s_all)

    # ---------------- chart ----------------
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(13, 9), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 1.4, 1]})
    ax1.plot(t[m], df.loc[m, "close"], lw=0.7, color="black", label="XAUUSD M3 close")
    ax1.plot(t[m], df.loc[m, "ema_fast"], lw=0.9, color="blue", label=f"EMA{PARAMS['ema_fast']}")
    ax1.plot(t[m], df.loc[m, "ema_slow"], lw=0.9, color="red", label=f"EMA{PARAMS['ema_slow']}")
    if not trades.empty:
        tt = pd.to_datetime(trades["entry_time"])
        longs = trades["direction"] == "LONG"
        ax1.scatter(tt[longs], trades.loc[longs, "entry"], marker="^", s=28, color="green",
                    label=f"Buy ({int(longs.sum())})", zorder=5)
        ax1.scatter(tt[~longs], trades.loc[~longs, "entry"], marker="v", s=28, color="darkred",
                    label=f"Sell ({int((~longs).sum())})", zorder=5)
    ax1.set_title(f"XAUUSD M3 candles — EMA 9/12 crossover (last {TEST_DAYS} days, "
                  f"{s['n_trades']} trades, {s['return_pct']:+.2f}%)")
    ax1.legend(fontsize=8, loc="upper left", ncol=2)
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

    # ---------------- report ----------------
    t0 = pd.to_datetime(df.loc[m, "time"].min())
    t1 = pd.to_datetime(df.loc[m, "time"].max())
    lines = [
        f"# XAUUSD Backtest Report — EMA 9/12 crossover on M{TF_MIN} candles",
        "",
        f"**Timeframe:** normal candlestick **M{TF_MIN}** (built by resampling real XAUUSD M1, "
        "tiumbj/M1_XAUUSD)",
        f"**Test period:** {t0} → {t1} ({TEST_DAYS} days, {int(m.sum())} M{TF_MIN} candles)",
        f"**Balance:** ${BALANCE0:,.0f} | **Lot:** fixed {FIXED_LOT} | "
        f"**Exit:** opposite crossover (reverse, always in market) | "
        f"**Costs:** spread ${SPREAD}/oz + slippage ${SLIPPAGE}/oz",
        "",
        f"## Result ({TEST_DAYS} days)",
        "",
        f"- Trades: **{s['n_trades']}** (Long {s['longs']} / Short {s['shorts']})",
        f"- Win rate: **{s['win_rate']}%** ({s['wins']}W / {s['losses']}L)",
        f"- Net P/L: **${s['net_pnl']:,.2f} ({s['return_pct']:+.2f}%)** → "
        f"end balance ${s['end_balance']:,.2f}",
        f"- Profit factor: **{s['profit_factor']}** | Expectancy: **${s['expectancy']}/trade**",
        f"- Avg win ${s['avg_win']} / avg loss ${s['avg_loss']}",
        f"- Max drawdown: **${s['max_dd_usd']} ({s['max_dd_pct']}%)** | "
        f"Sharpe (daily): **{s['sharpe_daily']}**",
        f"- Spread+slippage paid: **${s['n_trades'] * (SPREAD + SLIPPAGE) * FIXED_LOT * 100:,.2f}** "
        f"({s['n_trades']} trades x ${(SPREAD + SLIPPAGE) * FIXED_LOT * 100:.2f})",
        "",
        f"## Full 2-month window (Jan 2 – Mar 4, sanity check)",
        "",
        f"- Trades: **{s_all['n_trades']}** | Win rate {s_all['win_rate']}% | "
        f"P/L **${s_all['net_pnl']:,.2f} ({s_all['return_pct']:+.2f}%)** | "
        f"PF {s_all['profit_factor']} | max DD {s_all['max_dd_pct']}%",
        "",
        "## System rules",
        "",
        f"- M{TF_MIN} candles; BUY on EMA{PARAMS['ema_fast']} cross above "
        f"EMA{PARAMS['ema_slow']}, SELL on cross below",
        "- Signal on candle close → entry at next candle open (no lookahead)",
        "- Opposite cross closes & reverses. Fixed lot. No SL/TP, no filter, no RSI.",
        "",
        "## Note",
        "",
        "This replaces the Renko experiments (see `legacy/`). Renko-100 with a 3-part entry "
        "filter had shown +4.98% for Feb-2022, but on plain M3 candles the raw crossover gives "
        "the numbers above — compare the trade count and spread cost before choosing.",
        "",
        "## Files",
        "",
        "- `data/xauusd_m3_slice.csv` — M3 candles used here",
        "- `results/trades.csv`, `results/equity_curve.csv`, `results/backtest_chart.png`",
        "- `python3 compare_timeframes.py` — M1 vs M3 vs M5 vs M15 on the same system",
    ]
    with open("results/backtest_report.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nSaved: results/trades.csv, results/equity_curve.csv, "
          "results/backtest_chart.png, results/backtest_report.md")


if __name__ == "__main__":
    main()
