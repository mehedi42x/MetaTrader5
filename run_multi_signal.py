"""MULTI-SIGNAL system: every strategy keeps its own signals, one account.

Each strategy below runs independently — its own position, its own trade log, its
own 0.01-lot sizing and $0.20/trade cost. All of them feed the SAME account, so the
account equity is the sum of the strategies' cumulative P/L (they can be in a trade
at the same time).

Strategies (from this repo's earlier tests, unchanged rules):
  S7  order block retest        M1   - order block tapped after a structure break
  S1  swing BOS/CHoCH flip      M5   - swing structure break reverses the position
  S4  internal structure flip   M5   - internal (size 5) structure break reverses
  S6  pullback zone entry       M15  - break taken only in discount/premium zones
  EMA 9/12 reverse (reference)  M1   - plain crossover, always in market (optional)

Higher-timeframe signals are mapped to the M1 timeline without lookahead: a 5/15
minute candle's signal only affects M1 bars at/after that candle's close.

Reported: each strategy alone, every combination, the combined account curve, the
number of concurrently open positions, and the daily P/L correlation between
strategies. Data: data/xauusd_m1_2022.csv (354,628 real M1 bars, 2022).

Usage:  python3 run_multi_signal.py
"""
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
COST = SMC.COST                       # $0.20 per round trip (0.01 lot, spread 20 pts)
PERIODS = [
    ("Full year 2022", "2022-01-01", "2022-12-31 23:59"),
    ("H1 2022", "2022-01-01", "2022-06-30 23:59"),
    ("H2 2022", "2022-07-01", "2022-12-31 23:59"),
]
TF_MIN = {"M1": 1, "M5": 5, "M15": 15}


# --------------------------------------------------------------------------
def strategy_trades(m1, frames, specs):
    """Returns {key: dict(name, tf, trades, cum_pl_on_m1)}."""
    out = {}
    for spec in specs:
        key, name, tf = spec["key"], spec["name"], spec["tf"]
        df = frames[tf]
        if spec["kind"] == "ob":
            swing = compute_structure(df, 50)
            obs = order_blocks(df, swing)
            tr, eq, st = SMC.bt_ob_retest(df, PERIODS[0][1], PERIODS[0][2], swing, obs)
        elif spec["kind"] == "ema":
            d = add_signals(add_indicators(df))
            tr, eq, st = run_backtest(d, PERIODS[0][1], balance0=BALANCE0, spread=0.20,
                                      slippage=0.0, exit_mode="reverse", fixed_lot=0.01)
        else:
            swing = compute_structure(df, 50)
            internal = compute_structure(df, 5, swing=swing)
            zone = premium_discount(df, swing)
            if spec["kind"] == "swing_flip":
                kw = dict(long_entry=swing["event"] == 1, short_entry=swing["event"] == -1)
            elif spec["kind"] == "internal_flip":
                kw = dict(long_entry=internal["event"] == 1, short_entry=internal["event"] == -1)
            elif spec["kind"] == "zone_pullback":
                close = df["close"].to_numpy(float)
                kw = dict(long_entry=(swing["event"] == 1) & (close < zone["equilibrium"] * 1.02),
                          short_entry=(swing["event"] == -1) & (close > zone["equilibrium"] * 0.98))
            else:
                raise ValueError(spec["kind"])
            tr, eq, st = SMC.bt(df, PERIODS[0][1], PERIODS[0][2], **kw)
        # cumulative P/L per strategy, mapped onto the M1 clock (no lookahead)
        if len(tr):
            pl = tr.copy()
            pl["exit_time"] = pd.to_datetime(pl["exit_time"])
            pl = pl.sort_values("exit_time")
            cum = pl.groupby("exit_time")["pnl"].sum().cumsum()
            m1_times = pd.to_datetime(frame_m1["time"])
            aligned = pd.merge_asof(pd.DataFrame({"time": m1_times}).sort_values("time"),
                                    pd.DataFrame({"exit_time": cum.index, "cum": cum.values})
                                      .sort_values("exit_time"),
                                    left_on="time", right_on="exit_time", direction="backward")
            aligned["cum"] = aligned["cum"].ffill().fillna(0.0)
            curve = aligned["cum"].to_numpy(float)
        else:
            curve = np.zeros(len(frame_m1), dtype=float)
        out[key] = dict(name=name, tf=tf, trades=tr, curve=curve, stats=st, cadence=TF_MIN[tf])
    return out


def window_stats(trades, t0, t1, curve=None, m1_times=None):
    """Stats for one strategy (or the combined book) inside a window."""
    t0 = pd.to_datetime(t0)
    t1 = pd.to_datetime(t1)
    tr = trades
    if len(tr):
        et = pd.to_datetime(tr["exit_time"])
        sub = tr[(et >= t0) & (et <= t1)].copy()
    else:
        sub = tr
    n = len(sub)
    if n == 0:
        return dict(n_trades=0, net_pnl=0.0, profit_factor=0.0, win_rate=0.0,
                    max_dd_usd=0.0, max_dd_pct=0.0, expectancy=0.0)
    wins, losses = sub[sub.pnl > 0], sub[sub.pnl <= 0]
    gl = -losses.pnl.sum()
    net = sub.pnl.sum()
    dd_usd = dd_pct = 0.0
    if curve is not None and m1_times is not None:
        mask = (m1_times >= t0) & (m1_times <= t1)
        c = curve[mask]
        if len(c):
            eq = BALANCE0 + c
            peak = np.maximum.accumulate(eq)
            dd = eq - peak
            dd_usd = float(dd.min())
            dd_pct = float((dd / peak * 100).min())
    return dict(n_trades=n, net_pnl=round(float(net), 2),
                profit_factor=round(wins.pnl.sum() / gl, 2) if gl > 0 else float("inf"),
                win_rate=round(len(wins) / n * 100, 1),
                max_dd_usd=round(dd_usd, 2), max_dd_pct=round(dd_pct, 2),
                expectancy=round(float(sub.pnl.mean()), 3))


def main():
    global frame_m1
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    frame_m1 = m1
    frames = {"M1": m1}
    for tf in ("M5", "M15"):
        frames[tf] = SMC.resample_ohlc(m1, TF_MIN[tf])
    m1_times = pd.to_datetime(m1["time"]).to_numpy()

    specs = [
        dict(key="S7", name="S7 order block retest", tf="M1", kind="ob"),
        dict(key="S1", name="S1 swing BOS/CHoCH flip", tf="M5", kind="swing_flip"),
        dict(key="S4", name="S4 internal structure flip", tf="M5", kind="internal_flip"),
        dict(key="S6", name="S6 pullback zone entry", tf="M15", kind="zone_pullback"),
        dict(key="EMA", name="EMA 9/12 reverse (reference)", tf="M1", kind="ema"),
    ]
    print(f"data: {len(m1):,} M1 bars 2022 | 0.01 lot per strategy | ${COST:.2f}/trade\n")
    book = strategy_trades(m1, frames, specs)

    # ---------------- individual strategies ----------------
    print("=" * 104)
    print("1) EACH STRATEGY ALONE (0.01 lot, $0.20/trade, 2022)")
    print("=" * 104)
    print(f"{'strategy':32s}{'TF':>4s}{'year P/L':>11s}{'trd':>6s}{'win%':>7s}{'PF':>6s}"
          f"{'DD $':>9s}{'H1':>9s}{'H2':>9s}")
    ind = {}
    for s in specs:
        k = s["key"]
        st = window_stats(book[k]["trades"], *PERIODS[0][1:], book[k]["curve"], m1_times)
        h1 = window_stats(book[k]["trades"], *PERIODS[1][1:])
        h2 = window_stats(book[k]["trades"], *PERIODS[2][1:])
        ind[k] = (st, h1, h2)
        print(f"{book[k]['name']:32s}{book[k]['tf']:>4s}{st['net_pnl']:>11.2f}{st['n_trades']:>6d}"
              f"{st['win_rate']:>6.1f}%{st['profit_factor']:>6}{st['max_dd_usd']:>9.2f}"
              f"{h1['net_pnl']:>9.2f}{h2['net_pnl']:>9.2f}")

    # ---------------- combinations ----------------
    combos = [
        ("S7 alone", ["S7"]),
        ("S1 alone", ["S1"]),
        ("S4 alone", ["S4"]),
        ("S6 alone", ["S6"]),
        ("EMA alone (ref)", ["EMA"]),
        ("S7+S1", ["S7", "S1"]),
        ("S7+S1+S4", ["S7", "S1", "S4"]),
        ("S7+S1+S4+S6 (4 strategies)", ["S7", "S1", "S4", "S6"]),
        ("ALL 5 incl. EMA", ["S7", "S1", "S4", "S6", "EMA"]),
    ]
    print()
    print("=" * 104)
    print("2) COMBINATIONS — one account, each strategy keeps its own signals")
    print("=" * 104)
    print(f"{'combination':30s}{'year P/L':>10s}{'trd':>6s}{'win%':>7s}{'PF':>6s}"
          f"{'DD $':>9s}{'DD%':>7s}{'H1':>9s}{'H2':>9s}{'max':>5s}{'avg':>6s}")
    combo_res = {}
    for label, keys in combos:
        trades = pd.concat([book[k]["trades"] for k in keys if len(book[k]["trades"])],
                           ignore_index=True)
        curve = sum(book[k]["curve"] for k in keys)
        st = window_stats(trades, *PERIODS[0][1:], curve, m1_times)
        h1 = window_stats(trades, *PERIODS[1][1:], curve, m1_times)
        h2 = window_stats(trades, *PERIODS[2][1:], curve, m1_times)
        # concurrent positions (M1 bars) using only the keys in this combo
        occ = np.zeros(len(m1), dtype=int)
        for k in keys:
            occ += exposure(book[k]["trades"], m1_times)
        combo_res[label] = dict(st=st, h1=h1, h2=h2, curve=curve, trades=trades,
                                max_pos=int(occ.max()), avg_pos=float(occ.mean()))
        print(f"{label:30s}{st['net_pnl']:>10.2f}{st['n_trades']:>6d}{st['win_rate']:>6.1f}%"
              f"{st['profit_factor']:>6}{st['max_dd_usd']:>9.2f}{st['max_dd_pct']:>6.2f}%"
              f"{h1['net_pnl']:>9.2f}{h2['net_pnl']:>9.2f}{occ.max():>5d}{occ.mean():>6.2f}")

    best = max(combo_res, key=lambda k: combo_res[k]["st"]["net_pnl"])
    print(f"\n>>> best combination by 2022 P/L: {best} "
          f"(${combo_res[best]['st']['net_pnl']:.2f}, PF {combo_res[best]['st']['profit_factor']})")
    main_lbl = "S7+S1+S4+S6 (4 strategies)"
    mr = combo_res[main_lbl]
    print(f"    multi-signal (4 strategies): ${mr['st']['net_pnl']:.2f} | trades "
          f"{mr['st']['n_trades']} | PF {mr['st']['profit_factor']} | DD ${mr['st']['max_dd_usd']} "
          f"({mr['st']['max_dd_pct']}%) | H1 ${mr['h1']['net_pnl']} / H2 ${mr['h2']['net_pnl']} "
          f"| max {mr['max_pos']} positions at once (avg {mr['avg_pos']:.2f}))")

    # ---------------- monthly for the multi-signal book ----------------
    months = pd.date_range("2022-01-01", "2022-12-01", freq="MS")
    print("\n3) MONTH BY MONTH — multi-signal book (4 strategies) vs each strategy")
    hdr = f"{'month':9s}" + "".join(f"{n:>12s}" for n in ["S7", "S1", "S4", "S6", "BOOK"])
    print(hdr)
    monthly = {k: [] for k in ["S7", "S1", "S4", "S6", "BOOK"]}
    for m0 in months:
        m1t = m0 + pd.offsets.MonthEnd(0) + pd.Timedelta(hours=23, minutes=59, seconds=59)
        for k in ["S7", "S1", "S4", "S6"]:
            monthly[k].append(window_stats(book[k]["trades"], m0, m1t)["net_pnl"])
        monthly["BOOK"].append(window_stats(mr["trades"], m0, m1t)["net_pnl"])
    for i, m0 in enumerate(months):
        print(f"{m0.strftime('%b %Y'):9s}" + "".join(f"{monthly[k][i]:>12.2f}"
                                                    for k in ["S7", "S1", "S4", "S6", "BOOK"]))
    print(f"{'TOTAL':9s}" + "".join(f"{sum(monthly[k]):>12.2f}"
                                    for k in ["S7", "S1", "S4", "S6", "BOOK"]))
    pos_months = sum(1 for v in monthly["BOOK"] if v > 0)
    print(f"profitable months for the book: {pos_months}/12")

    # ---------------- correlation between strategies ----------------
    daily = {}
    for k in ["S7", "S1", "S4", "S6"]:
        tr = book[k]["trades"]
        if not len(tr):
            continue
        d = pd.to_datetime(tr["exit_time"]).dt.floor("D")
        daily[k] = tr.groupby(d)["pnl"].sum()
    ddf = pd.DataFrame(daily).fillna(0.0)
    print("\n4) DAILY P/L CORRELATION (lower = better diversification)")
    print(ddf.corr().round(2).to_string())

    # ---------------- charts ----------------
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={"height_ratios": [2, 1.3, 1]})
    colors = {"S7": "#1f77b4", "S1": "#2ca02c", "S4": "#d62728", "S6": "#ff7f0e",
              "EMA": "#888888"}
    for k in ["S7", "S1", "S4", "S6", "EMA"]:
        st = ind[k][0]
        axes[0].plot(m1_times, BALANCE0 + book[k]["curve"], color=colors[k], lw=1.3,
                     label=f"{book[k]['name']} ({book[k]['tf']}): {st['net_pnl']:+.2f} "
                           f"({st['n_trades']} trd, PF {st['profit_factor']})")
    axes[0].axhline(BALANCE0, color="k", ls=":", lw=1)
    axes[0].set_ylabel("Equity ($)")
    axes[0].set_title("XAUUSD 2022 — each strategy traded separately in the same account "
                      "(0.01 lot each, $0.20/trade)", fontsize=12)
    axes[0].legend(fontsize=8.5, loc="upper left")
    axes[0].grid(alpha=0.3)

    axes[1].plot(m1_times, BALANCE0 + mr["curve"], color="#111111", lw=1.6,
                 label=f"MULTI-SIGNAL book (S7+S1+S4+S6): {mr['st']['net_pnl']:+.2f} "
                       f"({mr['st']['n_trades']} trades, PF {mr['st']['profit_factor']})")
    axes[1].axhline(BALANCE0, color="k", ls=":", lw=1)
    axes[1].set_ylabel("Equity ($)")
    axes[1].legend(fontsize=9)
    axes[1].grid(alpha=0.3)

    x = np.arange(len(months))
    width = 0.16
    for j, k in enumerate(["S7", "S1", "S4", "S6", "BOOK"]):
        c = "#111111" if k == "BOOK" else colors[k]
        axes[2].bar(x + (j - 2) * width, monthly[k], width, color=c, label=k)
    axes[2].axhline(0, color="k", lw=1)
    axes[2].set_ylabel("Monthly P/L ($)")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels([m.strftime("%b") for m in months])
    axes[2].legend(fontsize=9, ncol=5)
    axes[2].grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig("results/multi_signal.png", dpi=120)
    plt.close(fig)
    print("\nSaved results/multi_signal.png")

    # ---------------- report ----------------
    lines = ["# Multi-signal system — every strategy keeps its own signals", "",
             "All strategies run inside one account: each opens its own 0.01-lot position "
             "on its own timeframe, with its own trade log and $0.20 round-trip cost. The "
             "account equity is the sum of the strategies' cumulative P/L, so several "
             "positions can be open at the same time.",
             "",
             "Data: data/xauusd_m1_2022.csv (354,628 real M1 bars, 2022).", "",
             "## 1. Each strategy alone (2022)", "",
             "| strategy | TF | year P/L | trades | win% | PF | max DD $ | H1 | H2 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in specs:
        k = s["key"]
        st, h1, h2 = ind[k]
        lines.append(f"| {book[k]['name']} | {book[k]['tf']} | ${st['net_pnl']:,.2f} | "
                     f"{st['n_trades']} | {st['win_rate']}% | {st['profit_factor']} | "
                     f"${st['max_dd_usd']:,.2f} | ${h1['net_pnl']:,.2f} | ${h2['net_pnl']:,.2f} |")
    lines += ["", "## 2. Combinations (one account)", "",
              "| combination | year P/L | trades | win% | PF | max DD $ | max DD % | H1 | H2 | max pos | avg pos |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, _ in combos:
        c = combo_res[label]
        lines.append(f"| {label} | ${c['st']['net_pnl']:,.2f} | {c['st']['n_trades']} | "
                     f"{c['st']['win_rate']}% | {c['st']['profit_factor']} | "
                     f"${c['st']['max_dd_usd']:,.2f} | {c['st']['max_dd_pct']}% | "
                     f"${c['h1']['net_pnl']:,.2f} | ${c['h2']['net_pnl']:,.2f} | {c['max_pos']} "
                     f"| {c['avg_pos']:.2f} |")
    lines += ["", "## 3. Month by month (multi-signal book)", "",
              "| month | " + " | ".join(["S7", "S1", "S4", "S6", "BOOK"]) + " |",
              "|---" * 6 + "|"]
    for i, m0 in enumerate(months):
        lines.append(f"| {m0.strftime('%b %Y')} | "
                     + " | ".join(f"${monthly[k][i]:,.2f}" for k in ["S7", "S1", "S4", "S6", "BOOK"])
                     + " |")
    lines.append("| **TOTAL** | " + " | ".join(f"**${sum(monthly[k]):,.2f}**"
                                               for k in ["S7", "S1", "S4", "S6", "BOOK"]) + " |")
    lines += [f"", f"Profitable months for the book: **{pos_months}/12**.", "",
              "## 4. Daily P/L correlation", "",
              "```", ddf.corr().round(2).to_string(), "```",
              "", "Chart: results/multi_signal.png"]
    with open("results/multi_signal_report.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("Saved results/multi_signal_report.md")
    return combo_res, ind, monthly, pos_months


def exposure(trades, m1_times):
    """1 on every M1 bar where this strategy had a position open."""
    occ = np.zeros(len(m1_times), dtype=int)
    if not len(trades):
        return occ
    ent = pd.to_datetime(trades["entry_time"]).to_numpy()
    ext = pd.to_datetime(trades["exit_time"]).to_numpy()
    for a, b in zip(ent, ext):
        i0 = np.searchsorted(m1_times, a, side="left")
        i1 = np.searchsorted(m1_times, b, side="left")
        if i1 > i0:
            occ[i0:i1] += 1
    return occ


if __name__ == "__main__":
    main()
