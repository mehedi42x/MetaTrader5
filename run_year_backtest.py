"""Full-year (2022) test of the LuxAlgo SMC systems on XAUUSD.

Data: real broker M1 from tiumbj/M1_XAUUSD (DAT_MT_XAUUSD_M1_2022.csv) ->
data/xauusd_m1_2022.csv, 354,628 bars, Jan 2 - Dec 30 2022.

Same settings as the previous SMC test: 0.01 lot (1 oz), spread 20 points =
$0.20/oz = $0.20 per round trip, leverage 1:1000, signals on closed bars only.

Reported: whole year + H1/H2 split (H1 = development, H2 = out-of-sample) and a
month-by-month table, plus an EMA 9/12 reference on the same data.

Usage:  python3 run_year_backtest.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import run_smc_backtest as SMC
from src.smc import compute_structure, premium_discount, order_blocks
from src.strategy import add_indicators, add_signals
from src.backtest import run_backtest

DATA = "data/xauusd_m1_2022.csv"
BALANCE0 = 10_000.0
TFS = [1, 5, 15]
PERIODS = [
    ("Full year 2022", "2022-01-01", "2022-12-31"),
    ("H1 2022 (Jan-Jun, development)", "2022-01-01", "2022-06-30 23:59"),
    ("H2 2022 (Jul-Dec, out-of-sample)", "2022-07-01", "2022-12-31"),
]
SYSTEMS = ["S1 swing bias flip", "S2 CHoCH only", "S3 BOS entry / CHoCH exit",
           "S4 internal bias flip", "S5 internal CHoCH only",
           "S6 pullback zone entry", "S7 order block retest"]


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    print(f"data/{os.path.basename(DATA)}: {len(m1)} M1 bars "
          f"({m1.time.min()} -> {m1.time.max()})")
    print(f"sizing: 0.01 lot = {SMC.OZ:.0f} oz | ${SMC.COST:.2f} per round trip "
          f"(spread 20 pts) | leverage 1:1000\n")

    results = {}
    curves = {}
    for tf in TFS:
        df = SMC.resample_ohlc(m1, tf)
        swing = compute_structure(df, 50)
        internal = compute_structure(df, 5, swing=swing)
        zone = premium_discount(df, swing)
        obs = order_blocks(df, swing)
        systems = SMC.build_signals(df, swing, internal, zone)
        systems["S4 internal bias flip"] = dict(long_entry=internal["event"] == 1,
                                                short_entry=internal["event"] == -1)
        n_break = int((swing["event"] != 0).sum())
        print(f"M{tf}: {len(df)} bars | swing breaks {n_break} | internal breaks "
              f"{int((internal['event'] != 0).sum())} | order blocks {len(obs)}")

        for label, t0, t1 in PERIODS:
            for name, kw in systems.items():
                tr, eq, st = SMC.bt(df, t0, t1, **kw)
                results[(tf, name, label)] = (st, tr)
                if label == PERIODS[0][0]:
                    curves.setdefault(name, {})[tf] = eq
            tr, eq, st = SMC.bt_ob_retest(df, t0, t1, swing, obs)
            results[(tf, "S7 order block retest", label)] = (st, tr)
            if label == PERIODS[0][0]:
                curves.setdefault("S7 order block retest", {})[tf] = eq

        # ---- EMA 9/12 reference on the same candles ----
        for label, t0, t1 in PERIODS:
            d = add_signals(add_indicators(df))
            d = d[d.time <= t1].reset_index(drop=True)
            tr, eq, st = run_backtest(d, t0, balance0=BALANCE0, spread=0.20, slippage=0.0,
                                      exit_mode="reverse", fixed_lot=0.01)
            st["costs"] = round(st.get("n_trades", 0) * SMC.COST, 2)
            results[(tf, "EMA 9/12 (reference)", label)] = (st, tr)
            if label == PERIODS[0][0]:
                curves.setdefault("EMA 9/12 (reference)", {})[tf] = eq
    print()

    # ------------------------------------------------ tables ----------------
    all_systems = SYSTEMS + ["EMA 9/12 (reference)"]
    for label, _, _ in PERIODS:
        print("=" * 104)
        print(f"{label}")
        print("=" * 104)
        print(f"{'system':28s}" + "".join(f"{'M' + str(tf) + ' P/L':>13s}{'trd':>7s}{'PF':>6s}"
                                          for tf in TFS))
        for name in all_systems:
            row = f"{name:28s}"
            for tf in TFS:
                st = results[(tf, name, label)][0]
                row += f"{st['net_pnl']:>13.2f}{st['n_trades']:>7d}{st['profit_factor']:>6}"
            print(row)
        print()

    # H1 vs H2 consistency for every system/timeframe
    print("H1 (dev) vs H2 (out-of-sample) — net P/L by system and timeframe:")
    print(f"{'system':28s}" + "".join(f"{'M' + str(tf) + ' H1':>12s}{'M' + str(tf) + ' H2':>12s}"
                                      for tf in TFS))
    for name in all_systems:
        row = f"{name:28s}"
        for tf in TFS:
            h1 = results[(tf, name, PERIODS[1][0])][0]["net_pnl"]
            h2 = results[(tf, name, PERIODS[2][0])][0]["net_pnl"]
            row += f"{h1:>12.2f}{h2:>12.2f}"
        print(row)
    print()

    # monthly P/L for the main candidates
    print("Month-by-month net P/L (best candidates):")
    months = pd.date_range("2022-01-01", "2022-12-01", freq="MS")
    focus = [(1, "S7 order block retest"), (5, "S7 order block retest"),
             (5, "S1 swing bias flip"), (5, "S4 internal bias flip"),
             (1, "EMA 9/12 (reference)")]
    print(f"{'month':8s}" + "".join(f"{'M' + str(tf) + ' ' + n.split()[0]:>14s}" for tf, n in focus))
    monthly = {}
    for tf, name in focus:
        df = SMC.resample_ohlc(m1, tf)
        swing = compute_structure(df, 50)
        internal = compute_structure(df, 5, swing=swing)
        zone = premium_discount(df, swing)
        if name == "S7 order block retest":
            obs = order_blocks(df, swing)
        rows = []
        for m0 in months:
            m1t = m0 + pd.offsets.MonthEnd(0)
            if name == "S7 order block retest":
                tr, eq, st = SMC.bt_ob_retest(df, m0, m1t, swing, obs)
            elif name == "EMA 9/12 (reference)":
                d = add_signals(add_indicators(df))
                d = d[d.time <= m1t].reset_index(drop=True)
                tr, eq, st = run_backtest(d, m0, balance0=BALANCE0, spread=0.20, slippage=0.0,
                                          exit_mode="reverse", fixed_lot=0.01)
            else:
                if name.startswith("S4"):
                    kw = dict(long_entry=internal["event"] == 1,
                              short_entry=internal["event"] == -1)
                else:
                    kw = dict(long_entry=swing["event"] == 1,
                              short_entry=swing["event"] == -1)
                tr, eq, st = SMC.bt(df, m0, m1t, **kw)
            rows.append(st["net_pnl"])
        monthly[(tf, name)] = rows
    for k, m0 in enumerate(months):
        row = f"{m0.strftime('%b %Y'):8s}"
        for tf, name in focus:
            row += f"{monthly[(tf, name)][k]:>14.2f}"
        print(row)
    totals = "".join(f"{sum(monthly[k]):>14.2f}" for k in monthly)
    print(f"{'TOTAL':8s}{totals}")
    winners = {k: sum(v) for k, v in monthly.items()}
    best_key = max(winners, key=winners.get)
    print(f"\n>>> best over 12 months: M{best_key[0]} / {best_key[1]} -> ${winners[best_key]:.2f}")

    # ------------------------------------------------ charts -----------------
    show = [(1, "S7 order block retest"), (5, "S1 swing bias flip"),
            (5, "S4 internal bias flip"), (15, "S6 pullback zone entry"),
            (1, "EMA 9/12 (reference)")]
    colors = ["#1f77b4", "#2ca02c", "#d62728", "#ff7f0e", "#888888"]
    fig = plt.figure(figsize=(14, 9))
    ax1 = fig.add_subplot(2, 1, 1)
    for (tf, name), c in zip(show, colors):
        eq = curves[name][tf]
        st = results[(tf, name, PERIODS[0][0])][0]
        ax1.plot(pd.to_datetime(eq["time"]), eq["equity"], color=c, lw=1.4,
                 label=f"{name} (M{tf}): {st['return_pct']:+.2f}% ({st['n_trades']} trd, "
                       f"PF {st['profit_factor']})")
    ax1.axhline(BALANCE0, color="k", ls=":", lw=1)
    ax1.set_ylabel("Equity ($)")
    ax1.set_title("XAUUSD 2022 full year — LuxAlgo SMC systems (0.01 lot, $0.20/trade) "
                  "vs EMA 9/12 reference", fontsize=12)
    ax1.legend(fontsize=8.5, loc="upper left")
    ax1.grid(alpha=0.3)

    monthly_all = {}
    for (tf, name) in focus:
        if (tf, name) in monthly:
            monthly_all[(tf, name)] = monthly[(tf, name)]
        else:
            df = SMC.resample_ohlc(m1, tf)
            swing = compute_structure(df, 50)
            internal = compute_structure(df, 5, swing=swing)
            obs = order_blocks(df, swing) if name.startswith("S7") else None
            vals = []
            for m0 in months:
                m1t = m0 + pd.offsets.MonthEnd(0)
                if name.startswith("S7"):
                    tr, eq, st = SMC.bt_ob_retest(df, m0, m1t, swing, obs)
                elif name.startswith("S4"):
                    tr, eq, st = SMC.bt(df, m0, m1t,
                                        long_entry=internal["event"] == 1,
                                        short_entry=internal["event"] == -1)
                else:
                    tr, eq, st = SMC.bt(df, m0, m1t,
                                        long_entry=swing["event"] == 1,
                                        short_entry=swing["event"] == -1)
                vals.append(st["net_pnl"])
            monthly_all[(tf, name)] = vals

    ax2 = fig.add_subplot(2, 1, 2)          # own x-axis: month index (not dates)
    width = 0.16
    x = np.arange(len(months))
    bar_keys = focus                                  # same order as the table above
    for k, ((tf, name), c) in enumerate(zip(bar_keys, colors)):
        ax2.bar(x + (k - 2) * width, monthly_all[(tf, name)], width, color=c,
                label=f"M{tf} {name.split()[0]}")
    ax2.axhline(0, color="k", lw=1)
    ax2.set_ylabel("Monthly P/L ($)")
    ax2.set_xticks(x)
    ax2.set_xticklabels([m.strftime("%b") for m in months])
    ax2.legend(fontsize=8, ncol=5)
    ax2.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig("results/year_2022.png", dpi=120)
    plt.close(fig)
    print("Saved results/year_2022.png")

    # ------------------------------------------------ robustness ------------
    print("\nS7 order-block retest — swing-size robustness (full-year net P/L):")
    for size in (20, 34, 50, 100):
        row = f"  swing {size:<4d}"
        for tf in (1, 5):
            df = SMC.resample_ohlc(m1, tf)
            sw = compute_structure(df, size)
            obs = order_blocks(df, sw)
            tr, eq, st = SMC.bt_ob_retest(df, PERIODS[0][1], PERIODS[0][2], sw, obs)
            row += f" | M{tf}: ${st['net_pnl']:>8.2f} ({st['n_trades']} trd)"
        print(row)

    # ------------------------------------------------ report ----------------
    lines = ["# XAUUSD 2022 — full-year backtest (LuxAlgo SMC systems)",
             "",
             f"Data: **data/xauusd_m1_2022.csv** — real broker M1, {len(m1):,} bars, "
             f"{m1.time.min().date()} → {m1.time.max().date()} (source tiumbj/M1_XAUUSD, "
             "DAT_MT_XAUUSD_M1_2022.csv).",
             f"Sizing: 0.01 lot (1 oz), cost ${SMC.COST:.2f} per round trip "
             "(spread 20 points only), leverage 1:1000. Signals on closed bars only.",
             "",
             "## Whole year", "",
             "| system | TF | net P/L | return | trades | win% | PF | max DD $ |",
             "|---|---|---|---|---|---|---|---|"]
    for tf in TFS:
        for name in all_systems:
            st = results[(tf, name, PERIODS[0][0])][0]
            if st.get("n_trades", 0) == 0:
                continue
            lines.append(f"| {name} | M{tf} | ${st['net_pnl']:,.2f} | {st['return_pct']:+.2f}% "
                         f"| {st['n_trades']} | {st['win_rate']}% | {st['profit_factor']} "
                         f"| ${st['max_dd_usd']:,.2f} |")
    lines += ["", "## H1 (development) vs H2 (out-of-sample)", "",
              "| system | TF | H1 P/L | H2 P/L |", "|---|---|---|---|"]
    for tf in TFS:
        for name in all_systems:
            h1 = results[(tf, name, PERIODS[1][0])][0]["net_pnl"]
            h2 = results[(tf, name, PERIODS[2][0])][0]["net_pnl"]
            lines.append(f"| {name} | M{tf} | ${h1:,.2f} | ${h2:,.2f} |")
    lines += ["", "## Month by month (main candidates)", "",
              "| month | " + " | ".join(f"M{tf} {n.split()[0]}" for tf, n in focus) + " |",
              "|---" * (len(focus) + 1) + "|"]
    for k, m0 in enumerate(months):
        lines.append(f"| {m0.strftime('%b %Y')} | "
                     + " | ".join(f"${monthly[(tf, name)][k]:,.2f}" for tf, name in focus) + " |")
    lines.append("| **TOTAL** | " + " | ".join(f"**${winners[k]:,.2f}**" for k in focus) + " |")
    lines += ["",
              "Charts: `results/year_2022.png` (equity + monthly bars).",
              "",
              "## Caveats",
              "",
              "* Single instrument, single year (2022). 2022 was a strong trending gold year;",
              "  2023-2025 regimes are not covered.",
              "* Spread fixed at 20 points; gold spreads widen at news and rollover.",
              "* No MT5 EA yet.",
              ]
    with open("results/year_report.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("Saved results/year_report.md")


if __name__ == "__main__":
    main()
