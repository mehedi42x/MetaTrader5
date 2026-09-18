"""Run Gold Trend-Momentum v1 backtest on 1 month of XAUUSD M15 data.

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

DATA = "data/xauusd_m15_slice.csv"
TEST_DAYS = 30
BALANCE0 = 10_000.0
RISK_PCT = 1.0
SPREAD = 0.35      # USD/oz round-trip
SLIPPAGE = 0.10    # USD/oz


def main():
    df = pd.read_csv(DATA, parse_dates=["time"])
    df = df.sort_values("time").reset_index(drop=True)
    test_start = df["time"].max() - pd.Timedelta(days=TEST_DAYS)
    df = add_signals(add_indicators(df))
    test_bars = int((df["time"] >= test_start).sum())

    trades, eq, s = run_backtest(
        df, test_start, balance0=BALANCE0, risk_pct=RISK_PCT,
        sl_atr_mult=PARAMS["sl_atr_mult"], tp_atr_mult=PARAMS["tp_atr_mult"],
        spread=SPREAD, slippage=SLIPPAGE,
    )
    os.makedirs("results", exist_ok=True)
    trades.to_csv("results/trades.csv", index=False)
    eq.to_csv("results/equity_curve.csv", index=False)

    # ---------- chart: price+trades / equity / drawdown ----------
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 1.4, 1]})
    t = pd.to_datetime(df["time"])
    m = t >= test_start
    ax1.plot(t[m], df.loc[m, "close"], lw=0.8, label="XAUUSD M15", color="black")
    ax1.plot(t[m], df.loc[m, "ema_fast"], lw=0.7, label=f"EMA{PARAMS['ema_fast']}", color="blue")
    ax1.plot(t[m], df.loc[m, "ema_slow"], lw=0.7, label=f"EMA{PARAMS['ema_slow']}", color="red")
    if not trades.empty:
        tt = pd.to_datetime(trades["entry_time"])
        longs = trades["direction"] == "LONG"
        ax1.scatter(tt[longs], trades.loc[longs, "entry"], marker="^", s=30,
                    color="green", label="Buy", zorder=5)
        ax1.scatter(tt[~longs], trades.loc[~longs, "entry"], marker="v", s=30,
                    color="red", label="Sell", zorder=5)
    ax1.set_title("XAUUSD M15 — Gold Trend-Momentum v1 (1-month backtest)")
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
        "# XAUUSD Backtest Report — Gold Trend-Momentum v1 (M15)",
        "",
        f"**Period:** {t0} → {t1} ({TEST_DAYS} days, {test_bars} M15 bars)",
        "**Data:** XAUUSD M15, Dukascopy-sourced (ejtraderLabs/historical-data), last 1 month of file",
        f"**Starting balance:** ${BALANCE0:,.0f} | **Risk/trade:** {RISK_PCT}% | "
        f"**SL:** {PARAMS['sl_atr_mult']}xATR | **TP:** {PARAMS['tp_atr_mult']}xATR (1:2 RR) | "
        f"**Session:** {PARAMS['session_start']:02d}:00-{PARAMS['session_end']:02d}:00 GMT | "
        f"**Costs:** spread ${SPREAD}/oz + slippage ${SLIPPAGE}/oz",
        "",
        "## Results (1 month)",
        "",
        f"- Trades: **{s['n_trades']}** (Long {s['longs']} / Short {s['shorts']})",
        f"- Win rate: **{s['win_rate']}%** ({s['wins']}W / {s['losses']}L; TP exits {s['tp_exits']}, SL exits {s['sl_exits']})",
        f"- Net P/L: **${s['net_pnl']:,.2f} ({s['return_pct']:+.2f}%)** → End balance ${s['end_balance']:,.2f}",
        f"- Profit factor: **{s['profit_factor']}** | Expectancy: **${s['expectancy']}/trade** | Avg R: **{s['avg_r']}R**",
        f"- Avg win ${s['avg_win']} / Avg loss ${s['avg_loss']} | Max win ${s['max_win']} / Max loss ${s['max_loss']}",
        f"- Max drawdown: **${s['max_dd_usd']} ({s['max_dd_pct']}%)** | Sharpe (daily): **{s['sharpe_daily']}**",
        "",
        "## Strategy rules",
        "",
        f"- Trend: Close > EMA{PARAMS['ema_fast']} > EMA{PARAMS['ema_slow']} → LONG only; "
        f"mirror for SHORT",
        f"- Trigger: RSI({PARAMS['rsi_period']}) crosses {PARAMS['rsi_mid']:.0f} in trend direction "
        "(momentum continuation)",
        "- Signal on bar close → entry next bar open. One position at a time. No martingale/grid/hedging.",
        "",
        "## Honesty note (robustness check)",
        "",
        "Same settings on adjacent months: Dec-2021 +3.1% (PF 1.18), "
        "Jan-2022 **-15.0%** (PF 0.47, choppy/range month), Feb-2022 +11.2% (PF 1.77). "
        "This is a trend-following system: it earns in trending months and bleeds in "
        "sideways months. One month is a short sample — forward-test on demo before any "
        "real money, keep risk ≤1%, and consider pausing it in clearly ranging markets.",
        "",
        "## Files",
        "",
        "- `results/trades.csv` — every trade | `results/equity_curve.csv` — equity | "
        "`results/backtest_chart.png` — price + trades + equity + drawdown",
        "- `mql5/XAUUSD_GoldTrendMomentum.mq5` — same strategy as a MetaTrader 5 Expert Advisor",
    ]
    with open("results/backtest_report.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nSaved: results/trades.csv, results/equity_curve.csv, results/backtest_chart.png, results/backtest_report.md")


if __name__ == "__main__":
    main()
