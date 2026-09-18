"""Backtest of trading systems built ONLY on the LuxAlgo SMC logic (src/smc.py).

Ported logic (see src/smc.py): swing structure BOS/CHoCH (size 50), internal
structure (size 5), premium/discount equilibrium, fair value gaps, order blocks.

Systems tested (all signals on closed bars -> traded at the next bar open):
  S1  Swing bias flip          : BOS*and*CHoCH both reverse the position
  S2  CHoCH only               : reversal trades only, opposite CHoCH closes
  S3  BOS entry / CHoCH exit   : wait for confirmation (BOS) after a CHoCH
  S4  Internal bias flip       : same as S1 on the internal (size 5) structure
  S5  Swing bias + zone gate   : longs only in discount, shorts only in premium
  S6  CHoCH + zone gate        : S2 with the premium/discount filter

Sizing/costs follow the user's latest settings: 0.01 lot (1 oz), spread 20 points
= $0.20/oz -> $0.20 per round trip, leverage 1:1000.

Usage:  python3 run_smc_backtest.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from src.smc import compute_structure, premium_discount, fair_value_gaps, BULLISH, BEARISH
from src.backtest import compute_stats

DATA = "data/xauusd_m1_slice.csv"
BALANCE0 = 10_000.0
FIXED_LOT = 0.01
OZ = FIXED_LOT * 100.0
SPREAD = 0.20
COST = SPREAD * OZ                # $0.20 per round trip
SWING_SIZE = 50                   # LuxAlgo default "Swings" length
INTERNAL_SIZE = 5                 # LuxAlgo internal structure size
PERIODS = [
    ("Feb-2022 (last 30 days)", "2022-02-02 16:59", "2022-03-04 23:59"),
    ("Jan-2022 (validation)", "2022-01-01", "2022-01-31 23:59"),
]
TFS = [1, 5, 15]


def resample_ohlc(m1, minutes):
    if minutes == 1:
        return m1.copy()
    g = (m1.set_index("time").resample(f"{minutes}min")
         .agg(open=("open", "first"), high=("high", "max"),
              low=("low", "min"), close=("close", "last"), n=("close", "size")))
    return g[g.n > 0].drop(columns="n").reset_index()


# ------------------------------------------------------------------ engine --
def bt(df, t0, t1, long_entry, short_entry, long_exit=None, short_exit=None,
       reverse=True, balance0=BALANCE0):
    """One position at a time. Signals come from the PREVIOUS bar's close."""
    o = df["open"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    t = pd.to_datetime(df["time"]).to_numpy()
    start = np.searchsorted(t, np.datetime64(pd.to_datetime(t0)))
    le = np.asarray(long_entry, dtype=bool)
    se = np.asarray(short_entry, dtype=bool)
    lx = np.asarray(long_exit, dtype=bool) if long_exit is not None else None
    sx = np.asarray(short_exit, dtype=bool) if short_exit is not None else None

    bal = balance0
    trades, eq_ts, eq_val = [], [], []
    pos = None

    def close(price, when, idx, reason):
        nonlocal bal, pos
        pnl = (price - pos["entry"]) * pos["dir"] * OZ - COST
        bal += pnl
        trades.append(dict(entry_time=pos["t"], exit_time=when,
                           direction="LONG" if pos["dir"] == 1 else "SHORT",
                           entry=round(pos["entry"], 2), exit=round(price, 2),
                           sl=float("nan"), tp=float("nan"), lot=FIXED_LOT,
                           pnl=round(pnl, 2), r_multiple=0.0,
                           bars_held=int(idx - pos["idx"]), exit_reason=reason))
        pos = None

    for i in range(1, len(df)):
        if i >= start:
            j = i - 1                       # signal bar = previous close
            if pos is not None and pos["dir"] == 1:
                if (sx is not None and sx[j]) or (reverse and se[j]):
                    close(o[i], t[i], i, "SIGNAL")
                if pos is None and reverse and se[j]:
                    pos = dict(dir=-1, entry=o[i], t=t[i], idx=i)
            elif pos is not None and pos["dir"] == -1:
                if (lx is not None and lx[j]) or (reverse and le[j]):
                    close(o[i], t[i], i, "SIGNAL")
                if pos is None and reverse and le[j]:
                    pos = dict(dir=1, entry=o[i], t=t[i], idx=i)
            if pos is None:
                if le[j]:
                    pos = dict(dir=1, entry=o[i], t=t[i], idx=i)
                elif se[j]:
                    pos = dict(dir=-1, entry=o[i], t=t[i], idx=i)
        eq_ts.append(t[i])
        eq_val.append(bal)

    if pos is not None:
        close(float(c[-1]), t[-1], len(df) - 1, "END")

    tr = pd.DataFrame(trades)
    eq = pd.DataFrame({"time": pd.to_datetime(eq_ts), "equity": eq_val})
    eq = eq[eq.time >= pd.to_datetime(t0)].reset_index(drop=True)
    st = compute_stats(tr, eq, balance0) if len(tr) else dict(
        n_trades=0, net_pnl=0.0, return_pct=0.0, profit_factor=0.0, win_rate=0.0,
        max_dd_usd=0.0, max_dd_pct=0.0, expectancy=0.0)
    st["costs"] = round(st.get("n_trades", 0) * COST, 2)
    return tr, eq, st


def build_signals(df, st, internal, zone, fvg=None):
    """Returns the systems as dict name -> kwargs for bt()."""
    ev = st["event"]
    tag = st["tag"]
    bull_break = ev == 1
    bear_break = ev == -1
    bull_choch = bull_break & (tag == "CHoCH")
    bear_choch = bear_break & (tag == "CHoCH")
    bull_bos = bull_break & (tag == "BOS")
    bear_bos = bear_break & (tag == "BOS")
    iev = internal["event"]
    bull_int = iev == 1
    bear_int = iev == -1
    close = df["close"].to_numpy(dtype=float)
    disc = close < zone["equilibrium"]
    prem = close > zone["equilibrium"]

    return {
        "S1 swing bias flip": dict(long_entry=bull_break, short_entry=bear_break),
        "S2 CHoCH only": dict(long_entry=bull_choch, short_entry=bear_choch),
        "S3 BOS entry / CHoCH exit": dict(long_entry=bull_bos, short_entry=bear_bos,
                                          long_exit=bear_break, short_exit=bull_break,
                                          reverse=False),
        "S5 internal CHoCH only": dict(long_entry=(iev == 1) & (internal["tag"] == "CHoCH"),
                                       short_entry=(iev == -1) & (internal["tag"] == "CHoCH")),
        "S6 pullback zone entry": dict(long_entry=bull_break & (close < zone["equilibrium"] * 1.02),
                                       short_entry=bear_break & (close > zone["equilibrium"] * 0.98)),
    }


def bt_ob_retest(df, t0, t1, structure, obs, balance0=BALANCE0):
    """S7: SMC order-block retest entries.

    After a bullish structure break its order block is stored; when price later
    trades back into that block (low <= OB top) we buy with a limit fill. The
    trade is closed when (a) the structure flips against it, or (b) price closes
    beyond the far side of the block (block failed -> stop).
    """
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    t = pd.to_datetime(df["time"]).to_numpy()
    start = np.searchsorted(t, np.datetime64(pd.to_datetime(t0)))

    # latest bullish / bearish block available at each bar
    ob_bull = np.full(len(df), np.nan)
    ob_bear = np.full(len(df), np.nan)
    ob_bull_bot = np.full(len(df), np.nan)
    ob_bear_top = np.full(len(df), np.nan)
    cur_b = cur_s = None
    by_index = {}
    for ob in obs:
        by_index.setdefault(ob["index"], []).append(ob)
    for i in range(len(df)):
        for ob in by_index.get(i, []):
            if ob["bias"] == 1:
                cur_b = ob
            else:
                cur_s = ob
        if cur_b is not None:
            ob_bull[i], ob_bull_bot[i] = cur_b["top"], cur_b["bottom"]
        if cur_s is not None:
            ob_bear[i], ob_bear_top[i] = cur_s["bottom"], cur_s["top"]

    ev = structure["event"]
    bal = balance0
    trades, eq_ts, eq_val = [], [], []
    pos = None
    pending_bull = pending_bear = False

    def close(price, when, idx, reason):
        nonlocal bal, pos
        pnl = (price - pos["entry"]) * pos["dir"] * OZ - COST
        bal += pnl
        trades.append(dict(entry_time=pos["t"], exit_time=when,
                           direction="LONG" if pos["dir"] == 1 else "SHORT",
                           entry=round(pos["entry"], 2), exit=round(price, 2),
                           sl=float("nan"), tp=float("nan"), lot=FIXED_LOT,
                           pnl=round(pnl, 2), r_multiple=0.0,
                           bars_held=int(idx - pos["idx"]), exit_reason=reason))
        pos = None

    for i in range(1, len(df)):
        if i >= start:
            # exits first (signal from the previous bar's close)
            if pos is not None and pos["dir"] == 1:
                if ev[i - 1] == -1:
                    close(o[i], t[i], i, "FLIP")
                elif not np.isnan(ob_bull_bot[i - 1]) and c[i - 1] < ob_bull_bot[i - 1] and pos["idx"] < i - 1:
                    close(o[i], t[i], i, "OB_FAIL")
            elif pos is not None and pos["dir"] == -1:
                if ev[i - 1] == 1:
                    close(o[i], t[i], i, "FLIP")
                elif not np.isnan(ob_bear_top[i - 1]) and c[i - 1] > ob_bear_top[i - 1] and pos["idx"] < i - 1:
                    close(o[i], t[i], i, "OB_FAIL")
            # entries: pending limit order at the latest valid block (stays alive
            # until the block fails or the structure flips)
            if pos is None:
                if pending_bull and not np.isnan(ob_bull[i - 1]):
                    if l[i] <= ob_bull[i - 1]:
                        pos = dict(dir=1, entry=min(o[i], ob_bull[i - 1]), t=t[i], idx=i)
                        pending_bull = False
                    elif c[i - 1] < ob_bull_bot[i - 1]:
                        pending_bull = False
                elif pending_bear and not np.isnan(ob_bear[i - 1]):
                    if h[i] >= ob_bear[i - 1]:
                        pos = dict(dir=-1, entry=max(o[i], ob_bear[i - 1]), t=t[i], idx=i)
                        pending_bear = False
                    elif c[i - 1] > ob_bear_top[i - 1]:
                        pending_bear = False
                if pos is None:                       # new break arms a new order
                    if ev[i - 1] == 1:
                        pending_bull, pending_bear = True, False
                    elif ev[i - 1] == -1:
                        pending_bear, pending_bull = True, False
        eq_ts.append(t[i])
        eq_val.append(bal)

    if pos is not None:
        close(float(c[-1]), t[-1], len(df) - 1, "END")
    tr = pd.DataFrame(trades)
    eq = pd.DataFrame({"time": pd.to_datetime(eq_ts), "equity": eq_val})
    eq = eq[eq.time >= pd.to_datetime(t0)].reset_index(drop=True)
    st = compute_stats(tr, eq, balance0) if len(tr) else dict(
        n_trades=0, net_pnl=0.0, return_pct=0.0, profit_factor=0.0, win_rate=0.0,
        max_dd_usd=0.0, max_dd_pct=0.0, expectancy=0.0)
    st["costs"] = round(st.get("n_trades", 0) * COST, 2)
    return tr, eq, st


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    print(f"M1 source bars: {len(m1)} | 0.01 lot = {OZ:.0f} oz | ${COST:.2f} per trade\n")

    results, curves, structures = {}, {}, {}
    for tf in TFS:
        df = resample_ohlc(m1, tf)
        swing = compute_structure(df, SWING_SIZE)
        internal = compute_structure(df, INTERNAL_SIZE, swing=swing)
        zone = premium_discount(df, swing)
        fvg = fair_value_gaps(df)
        structures[tf] = (df, swing, internal, zone, fvg)

        n_bos = int(((swing["tag"] == "BOS") & (swing["event"] != 0)).sum())
        n_choch = int(((swing["tag"] == "CHoCH") & (swing["event"] != 0)).sum())
        print(f"M{tf}: {len(df)} bars | swing breaks {n_bos + n_choch} "
              f"(BOS {n_bos}, CHoCH {n_choch}) | internal breaks "
              f"{int((internal['event'] != 0).sum())} | FVGs "
              f"{int(fvg['bullish'].sum()) + int(fvg['bearish'].sum())}")

        from src.smc import order_blocks
        obs = order_blocks(df, swing)
        systems = build_signals(df, swing, internal, zone, fvg)
        systems["S4 internal bias flip"] = dict(
            long_entry=internal["event"] == 1, short_entry=internal["event"] == -1)

        for label, t0, t1 in PERIODS:
            for name, kw in systems.items():
                tr, eq, s = bt(df, t0, t1, **kw)
                results[(tf, name, label)] = (s, tr)
                if label == PERIODS[0][0] and name not in curves:
                    curves[name] = {}
                if label == PERIODS[0][0]:
                    curves[name][tf] = eq
            tr, eq, s = bt_ob_retest(df, t0, t1, swing, obs)
            results[(tf, "S7 order block retest", label)] = (s, tr)
            if label == PERIODS[0][0]:
                curves.setdefault("S7 order block retest", {})[tf] = eq
    print()

    # ---------------- tables ----------------
    for label, _, _ in PERIODS:
        print("=" * 110)
        print(f"{label} — SMC systems, 0.01 lot, spread 20 pts (${COST:.2f}/trade)")
        print("=" * 110)
        hdr = f"{'system':28s}" + "".join(f"{'M' + str(tf) + ' P/L':>12s}{'n':>6s}{'PF':>6s}"
                                          for tf in TFS)
        print(hdr)
        names = list(build_signals(structures[1][0], structures[1][1],
                                   structures[1][2], structures[1][3]).keys())
        names.insert(3, "S4 internal bias flip")
        names.append("S7 order block retest")
        for name in names:
            row = f"{name:28s}"
            for tf in TFS:
                s = results[(tf, name, label)][0]
                row += f"{s['net_pnl']:>12.2f}{s['n_trades']:>6d}{s['profit_factor']:>6}"
            print(row)
        print()

    all_names = ["S1 swing bias flip", "S2 CHoCH only", "S3 BOS entry / CHoCH exit",
                 "S4 internal bias flip", "S5 internal CHoCH only",
                 "S6 pullback zone entry", "S7 order block retest"]
    print("Trade quality (M1, both months together):")
    print(f"{'system':28s} {'trades':>7s} {'win%':>6s} {'avg win':>8s} {'avg loss':>9s} "
          f"{'avg hold':>10s} {'exp/trade':>10s}")
    for name in all_names:
        trs = [results[(1, name, lbl)][1] for lbl in (PERIODS[0][0], PERIODS[1][0])]
        tr = pd.concat([t for t in trs if len(t)], ignore_index=True)
        if not len(tr):
            continue
        wins = tr[tr.pnl > 0]
        losses = tr[tr.pnl <= 0]
        hold = (pd.to_datetime(tr.exit_time) - pd.to_datetime(tr.entry_time)).mean()
        print(f"{name:28s} {len(tr):>7d} {len(wins) / len(tr) * 100:>5.1f}% "
              f"{wins.pnl.mean() if len(wins) else 0:>8.2f} "
              f"{losses.pnl.mean() if len(losses) else 0:>9.2f} {str(hold)[:10]:>10s} "
              f"{tr.pnl.mean():>10.2f}")
    print()

    print("2-month totals (Jan + Feb), per system:")
    for tf in TFS:
        print(f"  M{tf}: " + " | ".join(
            f"{n.split()[0]} {results[(tf, n, PERIODS[0][0])][0]['net_pnl'] + results[(tf, n, PERIODS[1][0])][0]['net_pnl']:+.2f}"
            for n in all_names))

    # best
    best = max(results.items(), key=lambda kv: kv[1][0]["net_pnl"] + results.get(
        (kv[0][0], kv[0][1], PERIODS[1][0]), (dict(net_pnl=0), None))[0]["net_pnl"])
    (tf, name, label), _ = best
    tot = results[(tf, name, label)][0]["net_pnl"] + results[(tf, name, PERIODS[1][0])][0]["net_pnl"]
    print(f"\n>>> best 2-month combo: M{tf} / {name} -> ${tot:.2f}")

    # ---------------- structure chart (visual check of the port) ----------------
    df15, swing15, internal15, zone15, _ = structures[15]
    window = (df15.time >= "2022-02-15") & (df15.time <= "2022-03-01")
    w = df15[window].reset_index()
    idx0 = df15.index[window][0]
    fig, ax = plt.subplots(figsize=(14, 6.5))
    x = np.arange(len(w))
    for k in range(len(w)):
        i = idx0 + k
        col = "#089981" if swing15["bias"][i] == BULLISH else "#F23645"
        ax.plot([x[k], x[k]], [w.high[k], w.low[k]], color=col, lw=0.6)
        ax.plot([x[k], x[k]], [w.open[k], w.close[k]], color=col, lw=2.0)
        if not np.isnan(swing15["pivot_high"][i]):
            ax.plot(x[k], swing15["pivot_high"][i], marker="v", color="#F23645", ms=5)
        if not np.isnan(swing15["pivot_low"][i]):
            ax.plot(x[k], swing15["pivot_low"][i], marker="^", color="#089981", ms=5)
        if swing15["event"][i] != 0:
            ax.annotate(swing15["tag"][i], (x[k], w.high[k] if swing15["event"][i] == 1 else w.low[k]),
                        textcoords="offset points",
                        xytext=(0, 10 if swing15["event"][i] == 1 else -14),
                        ha="center", fontsize=7,
                        color="#089981" if swing15["event"][i] == 1 else "#F23645")
    ax.plot(x, zone15["equilibrium"][idx0:idx0 + len(w)], color="#878b94", ls="--", lw=1,
            label="equilibrium (50%)")
    ax.set_title("LuxAlgo SMC port on XAUUSD M15 — swing structure: pivots, BOS/CHoCH, "
                 "equilibrium (15-28 Feb 2022)")
    ax.set_ylabel("Price")
    ax.grid(alpha=0.25)
    step = max(1, len(w) // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels([t.strftime("%d-%b %H:%M") for t in w.time[::step]], rotation=30, ha="right")
    fig.tight_layout()
    fig.savefig("results/smc_structure.png", dpi=120)
    plt.close(fig)

    # ---------------- equity chart ----------------
    show = ["S1 swing bias flip", "S2 CHoCH only", "S4 internal bias flip",
            "S7 order block retest", "S5 internal CHoCH only"]
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    colors = ["#1f77b4", "#2ca02c", "#7f7f7f", "#ff7f0e", "#d62728"]
    for ax, (label, t0, t1) in zip(axes, PERIODS):
        for name, c in zip(show, colors):
            eq = curves[name][1]
            s = results[(1, name, label)][0]
            ax.plot(pd.to_datetime(eq["time"]), eq["equity"], color=c, lw=1.5,
                    label=f"{name}: {s['return_pct']:+.2f}% ({s['n_trades']} trd, PF {s['profit_factor']})")
        ax.axhline(BALANCE0, color="k", ls=":", lw=1)
        ax.set_title(f"SMC systems on M1 — {label}", fontsize=11)
        ax.set_ylabel("Equity ($)")
        ax.legend(fontsize=7.5, loc="lower left")
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    fig.suptitle("LuxAlgo Smart Money Concepts systems — XAUUSD M1, 0.01 lot, "
                 "$0.20/trade, spread 20 pts", fontsize=12)
    fig.tight_layout()
    fig.savefig("results/smc_equity.png", dpi=120)
    print("Saved results/smc_structure.png and results/smc_equity.png")

    # ---------------- report ----------------
    lines = ["# XAUUSD — LuxAlgo Smart Money Concepts (SMC) backtest", "",
             "Ported from the Pine v5 indicator “Smart Money Concepts [LuxAlgo]” "
             "(CC BY-NC-SA 4.0): swing structure (size 50), internal structure (size 5), "
             "BOS/CHoCH, premium/discount equilibrium, FVG, order blocks — all on closed "
             "bars, entry at the next bar open.", "",
             f"Sizing: 0.01 lot (1 oz), cost ${COST:.2f}/trade (spread 20 pts), leverage 1:1000.",
             "", "## Results per system (0.01 lot)", ""]
    for tf in TFS:
        lines += [f"### M{tf}", "",
                  "| system | Feb P/L | Feb trd | Feb PF | Jan P/L | Jan trd | Jan PF |",
                  "|---|---|---|---|---|---|---|"]
        for name in all_names:
            f = results[(tf, name, PERIODS[0][0])][0]
            j = results[(tf, name, PERIODS[1][0])][0]
            lines.append(f"| {name} | ${f['net_pnl']:.2f} | {f['n_trades']} | {f['profit_factor']} "
                         f"| ${j['net_pnl']:.2f} | {j['n_trades']} | {j['profit_factor']} |")
        lines.append("")
    with open("results/smc_report.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
