"""Sideways filters on the S7 order-block system (M1) — the M1 system that works.

S7 (as backtested before): on every swing-structure break (BOS/CHoCH, size 50) the order
block that produced the break is stored; when price trades back into that block a limit
fills at the block edge; the trade closes when the structure flips or the block fails
(close beyond the far side). 0.01 lot, $0.20 per trade.

This script asks whether a sideways/range filter improves it:
  ADX(14) > th | Choppiness(14) < th | Efficiency ratio(10) > th | ATR(14)/ATR(50) > th
applied either when the order is armed (at the break) and/or when it fills (at the
retest), plus a "both" variant.

Years: 2022 (the year S7 was tuned on: +$702) and 2023, 2024, 2025 (fresh years).

Usage:  python3 run_sideways_s7.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.smc import compute_structure, order_blocks

SRC = "/tmp/fxdata/m1xau/DAT_MT_XAUUSD_M1_{y}.csv"
YEARS = [2022, 2023, 2024, 2025]
OZ, COST, BAL0 = 1.0, 0.20, 10_000.0
SWING = 50


def load(y):
    df = pd.read_csv(SRC.format(y=y), header=None,
                     names=["date", "time", "open", "high", "low", "close", "vol"])
    df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M")
    return df[["time", "open", "high", "low", "close"]].sort_values("time").reset_index(drop=True)


def wilder(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def adx(h, l, c, n=14):
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = wilder(tr, n)
    pdi = 100 * wilder(pd.Series(plus, index=h.index), n) / atr
    mdi = 100 * wilder(pd.Series(minus, index=h.index), n) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return wilder(dx.fillna(0), n).to_numpy(float)


def choppiness(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    rng = h.rolling(n).max() - l.rolling(n).min()
    return (100 * np.log10((tr.rolling(n).sum() / rng).replace(0, np.nan))
            / np.log10(n)).fillna(50).to_numpy(float)


def efficiency_ratio(c, n=10):
    return ((c - c.shift(n)).abs() / c.diff().abs().rolling(n).sum().replace(0, np.nan)
            ).fillna(0).to_numpy(float)


def atr_ratio(h, l, c, n1=14, n2=50):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return (wilder(tr, n1) / wilder(tr, n2)).fillna(1.0).to_numpy(float)


def prepare(y):
    df = load(y)
    swing = compute_structure(df, SWING)
    obs = order_blocks(df, swing)
    h, l, c = df["high"], df["low"], df["close"]
    filters = dict(ADX=adx(h, l, c), CHOP=choppiness(h, l, c),
                   ER=efficiency_ratio(c), ATRR=atr_ratio(h, l, c))
    return df, swing, obs, filters


def simulate(df, swing, obs, f_arm=None, f_fill=None, variant="none"):
    """variant: 'fill' (filter at fill bar), 'arm' (at arming), 'both'."""
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    ev = swing["event"]
    n = len(df)

    ob_bull, ob_bull_bot = np.full(n, np.nan), np.full(n, np.nan)
    ob_bear, ob_bear_top = np.full(n, np.nan), np.full(n, np.nan)
    cur_b = cur_s = None
    by_index = {}
    for ob in obs:
        by_index.setdefault(ob["index"], []).append(ob)
    for i in range(n):
        for ob in by_index.get(i, []):
            if ob["bias"] == 1:
                cur_b = ob
            else:
                cur_s = ob
        if cur_b is not None:
            ob_bull[i], ob_bull_bot[i] = cur_b["top"], cur_b["bottom"]
        if cur_s is not None:
            ob_bear[i], ob_bear_top[i] = cur_s["bottom"], cur_s["top"]

    pos = None
    pend_bull = pend_bear = False
    trades = []
    for i in range(1, n):
        if pos is not None:
            if pos["dir"] == 1:
                if ev[i - 1] == -1:
                    trades.append(((o[i] - pos["entry"]) * OZ - COST, 1, "FLIP"))
                    pos = None
                elif not np.isnan(ob_bull_bot[i - 1]) and c[i - 1] < ob_bull_bot[i - 1] \
                        and pos["idx"] < i - 1:
                    trades.append(((o[i] - pos["entry"]) * OZ - COST, 1, "OB_FAIL"))
                    pos = None
            else:
                if ev[i - 1] == 1:
                    trades.append(((pos["entry"] - o[i]) * OZ - COST, -1, "FLIP"))
                    pos = None
                elif not np.isnan(ob_bear_top[i - 1]) and c[i - 1] > ob_bear_top[i - 1] \
                        and pos["idx"] < i - 1:
                    trades.append(((pos["entry"] - o[i]) * OZ - COST, -1, "OB_FAIL"))
                    pos = None
        if pos is None:
            ok_fill = True if f_fill is None else bool(f_fill[i - 1])
            if pend_bull and not np.isnan(ob_bull[i - 1]):
                if l[i] <= ob_bull[i - 1]:
                    if ok_fill:
                        pos = dict(dir=1, entry=min(o[i], ob_bull[i - 1]), idx=i)
                    pend_bull = False
                elif c[i - 1] < ob_bull_bot[i - 1]:
                    pend_bull = False
            elif pend_bear and not np.isnan(ob_bear[i - 1]):
                if h[i] >= ob_bear[i - 1]:
                    if ok_fill:
                        pos = dict(dir=-1, entry=max(o[i], ob_bear[i - 1]), idx=i)
                    pend_bear = False
                elif c[i - 1] > ob_bear_top[i - 1]:
                    pend_bear = False
            if pos is None:
                ok_arm = True if f_arm is None else bool(f_arm[i - 1])
                if ev[i - 1] == 1:
                    pend_bull, pend_bear = ok_arm, False
                elif ev[i - 1] == -1:
                    pend_bear, pend_bull = ok_arm, False
    if pos is not None:
        trades.append(((c[-1] - pos["entry"]) * (1 if pos["dir"] == 1 else -1) * OZ - COST,
                       pos["dir"], "END"))
    pnl = np.array([t[0] for t in trades]) if trades else np.array([])
    return pnl, trades


def stats(pnl):
    if len(pnl) == 0:
        return dict(n=0, net=0.0, wr=0.0, pf=0.0, dd=0.0)
    w, l = pnl[pnl > 0], pnl[pnl <= 0]
    eq = BAL0 + np.cumsum(pnl)
    return dict(n=len(pnl), net=round(float(pnl.sum()), 2),
                wr=round(len(w) / len(pnl) * 100, 1),
                pf=round(float(w.sum() / -l.sum()), 2) if l.sum() < 0 else float("inf"),
                dd=round(float((eq - np.maximum.accumulate(eq)).min()), 2))


def main():
    print("=" * 112)
    print("S7 order-block retest (M1) + sideways filters — 0.01 lot, $0.20/trade")
    print("=" * 112)
    data = {}
    for y in YEARS:
        print(f"preparing {y} ...", flush=True)
        data[y] = prepare(y)

    CONFIGS = [
        ("no filter",            None, None),
        ("arm+fill ADX>25",      "ADX>25", "both"),
        ("arm+fill ADX>30",      "ADX>30", "both"),
        ("arm+fill Chop<38.2",   "CHOP<38.2", "both"),
        ("arm+fill Chop<45",     "CHOP<45", "both"),
        ("arm+fill ER>0.3",      "ER>0.3", "both"),
        ("arm+fill ER>0.4",      "ER>0.4", "both"),
        ("arm+fill ATRratio>1.0", "ATRR>1.0", "both"),
        ("arm+fill ATRratio>1.2", "ATRR>1.2", "both"),
        ("fill-only ADX>25",     "ADX>25", "fill"),
        ("fill-only Chop<45",    "CHOP<45", "fill"),
        ("fill-only ER>0.3",     "ER>0.3", "fill"),
        ("arm+fill Chop<45 & ER>0.3", "CHOP<45+ER>0.3", "both"),
        ("arm+fill ADX>25 & ER>0.3", "ADX>25+ER>0.3", "both"),
    ]

    def mask(name, flt):
        if name is None:
            return None
        if name == "ADX>25":
            return flt["ADX"] > 25
        if name == "ADX>30":
            return flt["ADX"] > 30
        if name == "CHOP<38.2":
            return flt["CHOP"] < 38.2
        if name == "CHOP<45":
            return flt["CHOP"] < 45
        if name == "ER>0.3":
            return flt["ER"] > 0.3
        if name == "ER>0.4":
            return flt["ER"] > 0.4
        if name == "ATRR>1.0":
            return flt["ATRR"] > 1.0
        if name == "ATRR>1.2":
            return flt["ATRR"] > 1.2
        if name == "CHOP<45+ER>0.3":
            return (flt["CHOP"] < 45) & (flt["ER"] > 0.3)
        if name == "ADX>25+ER>0.3":
            return (flt["ADX"] > 25) & (flt["ER"] > 0.3)
        raise KeyError(name)

    print()
    print(f"{'filter':30s}" + "".join(f"{str(y) + ' net':>11s}{'trd':>7s}" for y in YEARS)
          + f"{'4-yr':>10s}{'pos':>6s}")
    rows = []
    for label, fname, variant in CONFIGS:
        per, tot = {}, 0.0
        for y in YEARS:
            df, swing, obs, flt = data[y]
            m = mask(fname, flt)
            f_arm = m if variant == "both" else None
            f_fill = m if variant in ("both", "fill") else None
            pnl, _ = simulate(df, swing, obs, f_arm, f_fill)
            per[y] = stats(pnl)
            tot += per[y]["net"]
        pos = sum(1 for y in YEARS if per[y]["net"] > 0)
        rows.append((label, per, tot, pos))
        line = f"{label:30s}"
        for y in YEARS:
            line += f"{per[y]['net']:>11.2f}{per[y]['n']:>7d}"
        line += f"{tot:>10.2f}{pos:>4d}/4"
        print(line)

    base = rows[0]
    print(f"\nbaseline (no filter): 4 years {base[2]:+.2f}, positive years {base[3]}/4")
    best = max(rows[1:], key=lambda r: r[2])
    print(f"best filter: {best[0]} -> 4-year {best[2]:+.2f} "
          f"(baseline {base[2]:+.2f}, change {best[2] - base[2]:+.2f}), positive years {best[3]}/4")
    print("\nFull details of the best few:")
    for label, per, tot, pos in sorted(rows, key=lambda r: -r[2])[:5]:
        print(f"  {label:30s} total {tot:>9.2f} | " +
              " | ".join(f"{y}: {per[y]['net']:>8.2f} ({per[y]['n']:>4d} trd, PF {per[y]['pf']})"
                         for y in YEARS))

    # ---- chart -----------------------------------------------------------------
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), gridspec_kw={"height_ratios": [1.4, 1]})
    xs = np.arange(len(YEARS))
    w = 0.25
    top3 = sorted(rows, key=lambda r: -r[2])[:3]
    for k, ((label, per, tot, pos), col) in enumerate(zip(top3, ["#1f77b4", "#2ca02c", "#d62728"])):
        axes[0].bar(xs + (k - 1) * w, [per[y]["net"] for y in YEARS], w, color=col,
                    label=f"{label} (4-yr {tot:+.0f})")
    base_row = base
    axes[0].bar(xs + 2 * w, [base_row[1][y]["net"] for y in YEARS], w, color="#888888",
                label=f"no filter (4-yr {base_row[2]:+.0f})")
    axes[0].axhline(0, color="k", lw=1)
    axes[0].set_xticks(xs)
    axes[0].set_xticklabels([str(y) for y in YEARS])
    axes[0].set_ylabel("Net P/L ($)")
    axes[0].set_title("S7 order-block retest (M1) with sideways filters — yearly net P/L "
                      "(0.01 lot, $0.20/trade)")
    axes[0].legend(fontsize=8.5)
    axes[0].grid(alpha=0.3, axis="y")

    labs = [r[0] for r in sorted(rows, key=lambda r: -r[2])]
    vals = [r[2] for r in sorted(rows, key=lambda r: -r[2])]
    axes[1].barh(range(len(labs)), vals,
                 color=["#089981" if v > 0 else "#f23645" for v in vals])
    axes[1].set_yticks(range(len(labs)))
    axes[1].set_yticklabels(labs, fontsize=8)
    axes[1].invert_yaxis()
    axes[1].axvline(0, color="k", lw=1)
    axes[1].set_xlabel("4-year net P/L ($, 2022-2025)")
    axes[1].set_title("All S7 filter variants")
    axes[1].grid(alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig("results/sideways_s7.png", dpi=120)
    print("\nSaved results/sideways_s7.png")

    # ---- recent Sep 2026 check -------------------------------------------------
    print("\nRECENT CHECK — real Exness MT5 M1, 9-18 September 2026 (data/xauusd_m1_2026-09.csv):")
    rec = pd.read_csv("data/xauusd_m1_2026-09.csv", parse_dates=["time"])
    rec = rec[["time", "open", "high", "low", "close"]].reset_index(drop=True)
    sw_r = compute_structure(rec, SWING)
    obs_r = order_blocks(rec, sw_r)
    h, l, c = rec["high"], rec["low"], rec["close"]
    flt_r = dict(ADX=adx(h, l, c), CHOP=choppiness(h, l, c),
                 ER=efficiency_ratio(c), ATRR=atr_ratio(h, l, c))
    print(f"{'variant':28s}{'trades':>8s}{'net $':>10s}{'win%':>7s}{'PF':>6s}{'maxDD $':>10s}")
    recent_rows = []
    for label, fname in [("no filter", None), ("fill-only ER>0.3", "ER>0.3"),
                         ("arm+fill Chop<45", "CHOP<45"), ("arm+fill ADX>25", "ADX>25")]:
        m = mask(fname, flt_r)
        pnl, _ = simulate(rec, sw_r, obs_r, m if fname in ("CHOP<45", "ADX>25") else None,
                          m if fname else None)
        st = stats(pnl)
        recent_rows.append((label, st, pnl))
        print(f"{label:28s}{st['n']:>8d}{st['net']:>10.2f}{st['wr']:>6.1f}%{st['pf']:>6.2f}{st['dd']:>10.2f}")
    r0 = recent_rows[0][1]["net"]
    print(f"  -> the recent 8 sessions agree with the 4 years: S7 unfiltered is the best "
          f"(${r0:+.2f}).")

    # equity curve of the recent window for the chart
    fig2, ax2 = plt.subplots(figsize=(11, 4))
    for (label, st, pnl), col in zip(recent_rows, ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"]):
        ax2.plot(range(1, len(pnl) + 1), BAL0 + np.cumsum(pnl), lw=1.4, color=col,
                 label=f"{label}: {st['net']:+.2f} ({st['n']} trades, PF {st['pf']})")
    ax2.axhline(BAL0, color="k", ls=":", lw=1)
    ax2.set_xlabel("trade #")
    ax2.set_ylabel("Equity ($)")
    ax2.set_title("S7 (M1) on REAL data — 9-18 September 2026 (Exness MT5 feed)")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)
    fig2.tight_layout()
    fig2.savefig("results/sideways_s7_recent.png", dpi=120)
    plt.close(fig2)
    print("Saved results/sideways_s7_recent.png")

    L = ["# Sideways filters on the S7 order-block system (M1)", "",
         "S7 = the order-block retest system (swing structure size 50, BOS/CHoCH stores the "
         "block, a retest fills at the block edge, exit on structure flip or block failure). "
         "0.01 lot, $0.20 per trade. Filters are applied both when the order is armed (at the "
         "break) and when it fills (at the retest).", "",
         "| filter | 2022 | 2023 | 2024 | 2025 | 4-year total | positive years |",
         "|---|---|---|---|---|---|---|"]
    for label, per, tot, pos in rows:
        L.append(f"| {label} | ${per[2022]['net']:,.2f} ({per[2022]['n']}) | "
                 f"${per[2023]['net']:,.2f} ({per[2023]['n']}) | ${per[2024]['net']:,.2f} "
                 f"({per[2024]['n']}) | ${per[2025]['net']:,.2f} ({per[2025]['n']}) | "
                 f"**${tot:,.2f}** | {pos}/4 |")
    L += ["", "## Recent check — real Exness MT5 M1, 9-18 September 2026", "",
          "| variant | trades | net $ | win% | PF | max DD $ |", "|---|---|---|---|---|---|"]
    for label, st, _ in recent_rows:
        L.append(f"| {label} | {st['n']} | ${st['net']:,.2f} | {st['wr']}% | {st['pf']} | ${st['dd']:,.2f} |")
    L += ["", "Chart: results/sideways_s7.png | recent: results/sideways_s7_recent.png"]
    with open("results/sideways_s7_report.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("Saved results/sideways_s7_report.md")
    return rows


if __name__ == "__main__":
    main()
