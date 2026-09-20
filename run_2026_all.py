"""Backtest of the user's own rules on the 2026 data.

Which rules ("amar niyome"):
  ENTRY
    E1 "script (MTF + BB)"  = M1 EMA 6/9 crossover + 5m EMA 9/12 trend + close on the
                              correct side of the Bollinger(20,2) middle   (the pasted
                              Pine v6 "EMA MTF (1m & 5m) + Bollinger Bands" script)
    E2 "cBot (no BB)"       = M1 EMA 6/9 crossover + 5m EMA 9/12 trend   (the pasted
                              cTrader cBot "Trande Hunter")
  EXIT
    X1 "cross"              = the opposite M1 crossover (both original scripts)
    X2 "hybrid"             = the rule the user described: the M1 cross closes a trade
                              only when it is in profit; a losing trade is held until the
                              5m EMA 9/12 flips against the position
    X3 "trail 2.0/1.5/cap 2.0" = the cBot's trailing stop
  plus "blockers" (09-13 UTC + EMA-separation window) as a labelled extra, since it was
  built on request earlier.

2026 data available (all real, M1):
  segment A  2026-01-01 -> 2026-03-11   sherwynjoel/xauusd-historical-data parquet
  segment B  2026-03-12 -> 2026-09-08   getdata-finance/xauusd-1m-ohlcv-metals-historical-data
  segment C  2026-09-09 -> 2026-09-18   the real Exness MT5 mirror (already in data/)
Segments are never spliced: every variant is simulated inside a segment, so no trade
spans a source change, and the segment results are reported separately as well as summed.
Source validation: getdata vs the real MT5 mirror on 2,851 overlapping minutes -> median
difference -$0.05, mean absolute difference $0.13 (same market). The sherwyn feed differs
in LEVEL (day-to-day drift of tens of dollars, likely a futures-based continuous series)
but its intraday moves match the validated feed to $0.19 per bar, so segment A is
indicative and is flagged as such in the report.

Usage: python3 run_2026_all.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_trade_forensics import build, load_recent, BAL0, COST
from run_hold_losers import simulate_hybrid
from run_cbot_trailer import simulate_cbot, stats
from run_loss_blocker import mask_from_rules

SHERWYN = "/tmp/d2026/sherwyn/xauusd_m1_full.parquet"
GETDATA = "/tmp/d2026/getdata/XAUUSD_1m.csv"
BLOCK_RULES = [("hour", "range", (9, 13)), ("sep", "range", (0.03, 0.08)), ("htfstr", "<=", 0.20)]
HDR = (f"{'variant':40s}{'trades':>8s}{'net $':>11s}{'win%':>7s}{'PF':>7s}"
       f"{'maxDD $':>11s}{'avg hold':>9s}{'worst $':>9s}{'gross $':>11s}")


def prepare_sources():
    """Return the list of (label, window, df) segments, or raise with instructions."""
    segs = []
    if os.path.exists(SHERWYN):
        s = pd.read_parquet(SHERWYN, columns=["open", "high", "low", "close"])
        s.index = s.index.tz_convert("UTC").tz_localize(None)
        s = s.loc["2026-01-01":"2026-03-11 23:59"]
        segs.append(("A 01-01 -> 03-11 (sherwyn feed)", s.reset_index(names="time")))
    if os.path.exists(GETDATA):
        g = pd.read_csv(GETDATA, parse_dates=["datetime"]).set_index("datetime")
        g.index = g.index.tz_convert("UTC").tz_localize(None)
        g = g.loc["2026-03-12":"2026-09-08 23:59", ["open", "high", "low", "close"]]
        segs.append(("B 03-12 -> 09-08 (getdata feed)", g.reset_index(names="time")))
    r = load_recent().rename(columns={})
    segs.append(("C 09-09 -> 09-18 (real MT5)", r))
    if len(segs) < 3:
        print("WARNING: only", len(segs), "segments available - re-clone the 2026 sources:")
        print("  git clone --depth 1 https://github.com/sherwynjoel/xauusd-historical-data"
              " /tmp/d2026/sherwyn")
        print("  git clone --depth 1"
              " https://github.com/getdata-finance/xauusd-1m-ohlcv-metals-historical-data"
              " /tmp/d2026/getdata")
    return segs


VARIANTS = [
    ("E1 script (MTF+BB) x cross", dict(entry="bb", exit_="cross")),
    ("E2 cBot x cross", dict(entry="plain", exit_="cross")),
    ("E1 script x hybrid (your rule)", dict(entry="bb", exit_="hybrid")),
    ("E2 cBot x hybrid (your rule)", dict(entry="plain", exit_="hybrid")),
    ("E1 script x trail (cBot stop)", dict(entry="bb", exit_="trail")),
    ("E2 cBot x trail (cBot stop)", dict(entry="plain", exit_="trail")),
    ("E1 script x cross + blockers", dict(entry="bb", exit_="cross", blockers=True)),
    ("E1 script x hybrid + blockers", dict(entry="bb", exit_="hybrid", blockers=True)),
    ("E1 script x trail + blockers", dict(entry="bb", exit_="trail", blockers=True)),
]


def run_variant(d, entry, exit_, blockers=False):
    buy = d["base_buy"] if entry == "bb" else (d["bull"] & d["htf_bull"])
    sell = d["base_sell"] if entry == "bb" else (d["bear"] & d["htf_bear"])
    m = mask_from_rules(d, BLOCK_RULES) if blockers else None
    if blockers:                      # the blockers also gate the hybrid/trail runs
        buy = buy & m
        sell = sell & m
    dd = dict(d)
    dd["base_buy"], dd["base_sell"] = buy, sell
    if exit_ == "hybrid":
        return simulate_hybrid(dd, mode="hybrid", five_min_closes_winners=True)
    if exit_ == "trail":
        return simulate_cbot(dd, trail_on=True, path="conservative",
                             entry_buy=buy, entry_sell=sell)
    return simulate_cbot(dd, trail_on=False, entry_buy=buy, entry_sell=sell)


def pr(label, trades, width=40):
    s = stats(trades)
    print(f"{label:{width}s}{s['n']:>8d}{s['net']:>11.2f}{s['wr']:>6.1f}%{s['pf']:>7.2f}"
          f"{s['dd']:>11.2f}{s['hold']:>9.0f}{s['worst']:>9.2f}{s['gross']:>11.2f}")
    return s


def main():
    segs = prepare_sources()
    print("2026 segments:")
    for label, df in segs:
        print(f"  {label}: {len(df):,} bars | {df.time.iloc[0]} -> {df.time.iloc[-1]}")
    built = [(label, build(df)) for label, df in segs]

    # ---------------- per segment ----------------
    seg_stats = {}
    print("\n" + "=" * 128)
    print("PER SEGMENT — every rule of yours on the 2026 data")
    print("=" * 128)
    for label, d in built:
        print(f"\n--- {label} ---")
        print(HDR)
        for vlabel, kw in VARIANTS:
            tr = run_variant(d, **kw)
            seg_stats[(label, vlabel)] = (stats(tr), tr)
            pr(vlabel, tr)

    # ---------------- combined 2026 ----------------
    print("\n" + "=" * 128)
    print("COMBINED 2026 (segments simulated separately, no trade crosses a source change)")
    print("=" * 128)
    print(HDR)
    comb = {}
    for vlabel, kw in VARIANTS:
        all_tr = []
        for label, d in built:
            all_tr += run_variant(d, **kw)
        comb[vlabel] = all_tr
        pr(vlabel, all_tr)

    # ---------------- monthly ----------------
    print("\n" + "=" * 128)
    print("MONTHLY NET P/L — 2026")
    print("=" * 128)
    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
              "2026-07", "2026-08", "2026-09"]
    print(f"{'variant':40s}" + "".join(f"{m[5:]:>9s}" for m in months) + f"{'total':>11s}")
    monthly = {}
    for vlabel, trs in comb.items():
        dfx = pd.DataFrame(trs)
        dfx["m"] = pd.to_datetime(dfx.exit_time).dt.strftime("%Y-%m")
        row = [dfx[dfx.m == m].pnl.sum() for m in months]
        monthly[vlabel] = row
        print(f"{vlabel:40s}" + "".join(f"{v:>9.0f}" for v in row) + f"{sum(row):>11.0f}")

    # ---------------- comparison with previous years ----------------
    print("\n" + "=" * 128)
    print("HOW 2026 COMPARES (same rules, earlier years, from the committed reports)")
    print("=" * 128)
    print(f"{'variant':40s}{'2022-2025 (4y)':>18s}{'2026 (Jan-Sep)':>18s}")
    hist = {"E1 script (MTF+BB) x cross": -11810.52, "E2 cBot x cross": -11864.97,
            "E1 script x hybrid (your rule)": -5590.22, "E2 cBot x hybrid (your rule)": None,
            "E1 script x trail (cBot stop)": -11780.82, "E2 cBot x trail (cBot stop)": None,
            "E1 script x cross + blockers": -613.08}
    for vlabel in comb:
        h = hist.get(vlabel)
        print(f"{vlabel:40s}{('%.2f' % h) if h is not None else 'n/a':>18s}"
              f"{sum(monthly[vlabel]):>18.2f}")

    # ---------------- detail ----------------
    print("\n" + "=" * 128)
    print("DETAIL — 2026")
    print("=" * 128)
    base = pd.DataFrame(comb["E1 script (MTF+BB) x cross"])
    hyb = pd.DataFrame(comb["E1 script x hybrid (your rule)"])
    trl = pd.DataFrame(comb["E1 script x trail (cBot stop)"])
    print(f"E1 script: {len(base):,} trades, {base.pnl.sum():,.0f} $ | "
          f"avg hold {(base.exit_time - base.entry_time).dt.total_seconds().mean() / 60:.1f} min")
    for nm, dfx in [("hybrid", hyb), ("trail", trl)]:
        if "why" in dfx:
            print(f"{nm}: exit mix " + ", ".join(f"{k} {v:,}" for k, v in
                                                 dfx.why.value_counts().items()))
    hk = hyb["exit_kind"] if "exit_kind" in hyb else hyb["why"]
    held = hyb[hk == "5m flip"]
    print(f"\nhybrid: the held-over trades (closed by the 5m flip) = {len(held):,} of "
          f"{len(hyb):,}, win {(held.pnl > 0).mean() * 100:.1f}%, total ${held.pnl.sum():,.0f} | "
          f"closed in profit by the M1 cross: {int((hk == 'M1 cross (in profit)').sum()):,}")
    print(f"trail: trades closed by the stop = "
          f"{int(trl.why.isin(['trail', 'trail gap']).sum()):,}, "
          f"of which at the +$2 cap: "
          f"{int(((trl.pnl > 1.7) & (trl.pnl < 1.9)).sum()):,}")
    print(f"\nspread paid (E1 script, 2026): ${COST * len(base):,.2f} | "
          f"gross before spread ${base.pnl.sum() + COST * len(base):,.2f}")
    bm = base.groupby(base.pnl <= 0).pnl.agg(['count', 'mean'])
    print(f"losers {int(bm.loc[True, 'count']):,} | average loss "
          f"${bm.loc[True, 'mean']:.2f} | average win ${base[base.pnl > 0].pnl.mean():.2f}")

    # ---------------- chart ----------------
    fig, axes = plt.subplots(2, 1, figsize=(14, 9.5), gridspec_kw={"height_ratios": [1.3, 1]})
    colors = {"E1 script (MTF+BB) x cross": "#888888",
              "E1 script x hybrid (your rule)": "#2ca02c",
              "E1 script x trail (cBot stop)": "#1f77b4",
              "E1 script x cross + blockers": "#d62728"}
    for vlabel, col in colors.items():
        dfx = pd.DataFrame(comb[vlabel]).sort_values("exit_time")
        xs = pd.to_datetime(dfx.exit_time)
        axes[0].plot(xs, BAL0 + np.cumsum(dfx.pnl.values), lw=1.2, color=col,
                     label=f"{vlabel}: {dfx.pnl.sum():+,.0f}")
    axes[0].axhline(BAL0, color="k", ls=":", lw=1)
    axes[0].set_ylabel("Equity ($)")
    axes[0].set_title("Your rules on the 2026 data (Jan-Sep 18) — 0.01 lot, $0.20/trade")
    axes[0].legend(fontsize=8.5)
    axes[0].grid(alpha=0.3)

    x = np.arange(len(months))
    w = 0.26
    for k, (vlabel, col) in enumerate([("E1 script (MTF+BB) x cross", "#888888"),
                                       ("E1 script x hybrid (your rule)", "#2ca02c"),
                                       ("E1 script x trail (cBot stop)", "#1f77b4")]):
        axes[1].bar(x + (k - 1) * w, monthly[vlabel], width=w, color=col,
                    label=vlabel.replace("E1 script ", "").replace(" x ", " × "))
    axes[1].axhline(0, color="k", lw=1)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(months, rotation=0, fontsize=8)
    axes[1].set_ylabel("monthly net P/L ($)")
    axes[1].set_title("Month by month, 2026")
    axes[1].legend(fontsize=8.5)
    axes[1].grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig("results/backtest_2026.png", dpi=120)
    print("\nSaved results/backtest_2026.png")

    # ---------------- csv + report ----------------
    rows = []
    for vlabel, trs in comb.items():
        dfx = pd.DataFrame(trs)
        s = stats(trs)
        rows.append(dict(variant=vlabel, trades=s["n"], win_pct=s["wr"], net=s["net"],
                         gross=s["gross"], pf=s["pf"], max_dd=s["dd"],
                         avg_hold_min=round(s["hold"], 1), worst=s["worst"],
                         **{f"m{m[5:]}": round(v, 2) for m, v in zip(months, monthly[vlabel])}))
    pd.DataFrame(rows).to_csv("results/backtest_2026_summary.csv", index=False)
    print("Saved results/backtest_2026_summary.csv")

    L = ["# Your rules on the 2026 data — backtest report", "",
         "**Rules tested** (everything as you specified it):", "",
         "| | rule |", "|---|---|",
         "| entry E1 | M1 EMA 6/9 crossover + 5m EMA 9/12 trend + Bollinger(20,2) middle filter"
         " (the pasted Pine v6 script) |",
         "| entry E2 | M1 EMA 6/9 crossover + 5m EMA 9/12 trend (the pasted cTrader cBot) |",
         "| exit X1 | the opposite M1 crossover (both scripts) |",
         "| exit X2 | **your hybrid rule** - the M1 cross closes a trade only in profit; a losing"
         " trade is held until the 5m EMA 9/12 flips |",
         "| exit X3 | the cBot trailing stop: +$2.00 trigger, $1.50 distance, +$2.00 cap |",
         "| extra | the 09-13 UTC + EMA-separation blockers built on request earlier |", "",
         "0.01 lot (1 oz), **$0.20 per round trip**, real M1 data.", "",
         "## The 2026 data", "",
         "| segment | window | bars | source | validated against |", "|---|---|---|---|---|",
         f"| A | 2026-01-01 -> 03-11 | "
         f"{len(segs[0][1]) if len(segs) > 0 else 0:,} | sherwynjoel/xauusd-historical-data | "
         f"indirectly: intraday moves agree with segment B to $0.19/bar, LEVEL differs |",
         f"| B | 2026-03-12 -> 09-08 | {len(segs[1][1]) if len(segs) > 1 else 0:,} | "
         f"getdata-finance/xauusd-1m-ohlcv | the real MT5 mirror: median -$0.05, mean abs $0.13 |",
         f"| C | 2026-09-09 -> 09-18 | {len(segs[2][1]) if len(segs) > 2 else 0:,} | "
         f"real Exness MT5 mirror | it IS the reference |", "",
         "Segments are never spliced: each variant is simulated inside a segment so no trade",
         "spans a source change, and every trade is charged the full $0.20.", "",
         "## Combined 2026 (Jan 1 - Sep 18)", "",
         "| variant | trades | net $ | win% | PF | maxDD $ | avg hold (min) | gross $ |",
         "|---|---|---|---|---|---|---|---|"]
    for vlabel in comb:
        s = stats(comb[vlabel])
        L.append(f"| {vlabel} | {s['n']:,} | **${s['net']:,.2f}** | {s['wr']}% | {s['pf']} | "
                 f"${s['dd']:,.2f} | {s['hold']:.0f} | ${s['gross']:,.2f} |")
    L += ["", "## Month by month 2026 (net $)", "",
          "| variant | " + " | ".join(m[5:] for m in months) + " | total |",
          "|---" * (len(months) + 2) + "|"]
    for vlabel in comb:
        L.append(f"| {vlabel} | " + " | ".join(f"{v:,.0f}" for v in monthly[vlabel]) +
                 f" | **{sum(monthly[vlabel]):,.0f}** |")
    L += ["", "## How 2026 compares with 2022-2025", "",
          "| variant | 2022-2025 (4 years) | 2026 (Jan-Sep) |", "|---|---|---|"]
    for vlabel in comb:
        h = hist.get(vlabel)
        L.append(f"| {vlabel} | {'$%s' % format(h, ',.0f') if h is not None else 'n/a'} | "
                 f"${sum(monthly[vlabel]):,.0f} |")
    L += ["", "## Notes from the numbers", "",
          f"- E1 with the original exit: {len(base):,} trades in 2026, average hold "
          f"{(base.exit_time - base.entry_time).dt.total_seconds().mean() / 60:.1f} minutes, "
          f"average loss ${base[base.pnl <= 0].pnl.mean():.2f} against an average win "
          f"${base[base.pnl > 0].pnl.mean():.2f}.",
          f"- Spread paid over the nine months: ${COST * len(base):,.2f}; gross P/L "
          f"${base.pnl.sum() + COST * len(base):,.2f}.",
          f"- Your hybrid rule: {len(held):,} trades were held over (the M1 cross hit them "
          f"under water), winning {(held.pnl > 0).mean() * 100:.1f}% of the time for "
          f"${held.pnl.sum():,.0f}; the rest closed by the M1 cross in profit.",
          f"- The trailing stop closed {int(trl.why.isin(['trail', 'trail gap']).sum()):,} "
          f"trades, {int(((trl.pnl > 1.7) & (trl.pnl < 1.9)).sum()):,} of them pinned at the "
          f"+$2.00 cap.", "", "Charts: results/backtest_2026.png | "
          "table: results/backtest_2026_summary.csv"]
    with open("results/backtest_2026_report.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("Saved results/backtest_2026_report.md")
    return comb, monthly, seg_stats


if __name__ == "__main__":
    main()
