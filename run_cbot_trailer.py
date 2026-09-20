"""Faithful port of the pasted cTrader cBot "Trande Hunter".

What the cBot does
  OnBarClosed:
    - EMA 6/9 crossover on the 1-minute chart
    - the 5-minute EMA 9/12 gives the trend direction (last closed bar)
    - entry: bullCross + htfBullish (buy) / bearCross + htfBearish (sell)
    - exit: the raw opposite 1m crossover, whatever the 5m trend says
    - one position at a time (Positions.Find by label)
  OnTick (trailing stop, in USD of price):
    - activates when the profit distance reaches TrailTrigger (default $2.00)
    - stop = price - TrailDist (default $1.50), never worse than
      entry + (TrailTrigger - TrailDist)  -> locks at least +$0.50
    - and never better than entry + MaxTrailCap (default $2.00)
    - only ratchets: ModifyPosition is called when the new stop is better

Modelling notes
  - Only M1 OHLC is available (no ticks), so the intrabar order of the high and the
    low is unknown. Both orderings are reported:
        conservative = adverse extreme first (low before high for a buy)
        optimistic   = favourable extreme first (high before low for a buy)
    The truth lies between the two.
  - Stops are filled at the stop price, or at the bar open when the bar gaps through.
  - Reverse-cross exits fill at the next bar's open (same convention as every other
    script in this repo).
  - 0.01 lot = 1 oz (1 contract, point value 1), $0.20 per round trip.

Windows: 2023-08 (the worst month), the four full years 2022-2025, and the real
September 2026 window (Exness MT5 feed).

Usage: python3 run_cbot_trailer.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_trade_forensics import build, load_year, load_recent, OZ, COST, BAL0

TRIGGER, DIST, CAP = 2.0, 1.5, 2.0        # the cBot's defaults, in USD of price


def simulate_cbot(d, t0=None, t1=None, trigger=TRIGGER, dist=DIST, cap=CAP,
                  trail_on=True, path="conservative"):
    """Port of the cBot. Returns a list of trade dicts."""
    o, h, l, c, t = d["open"], d["high"], d["low"], d["close"], d["time"]
    bull, bear, hb, hs = d["bull"], d["bear"], d["htf_bull"], d["htf_bear"]
    n = len(o)
    win = np.ones(n, bool)
    if t0 is not None:
        win &= t >= np.datetime64(pd.to_datetime(t0))
    if t1 is not None:
        win &= t <= np.datetime64(pd.to_datetime(t1))

    trades = []
    pos, entry, entry_i, sig_i = 0, np.nan, None, None
    stop = np.nan

    def trail_update(i, px):
        """the OnTick block, using px as the best price seen in the bar"""
        nonlocal stop
        if not trail_on or pos == 0 or np.isnan(px):
            return
        if pos == 1:
            profit = px - entry
            if profit >= trigger:
                ideal = min(max(px - dist, entry + (trigger - dist)), entry + cap)
                if np.isnan(stop) or ideal > stop:
                    stop = ideal
        else:
            profit = entry - px
            if profit >= trigger:
                ideal = max(min(px + dist, entry - (trigger - dist)), entry - cap)
                if np.isnan(stop) or ideal < stop:
                    stop = ideal

    for i in range(1, n):
        j = i - 1
        # ---------- intrabar trailing stop on bar i ----------
        if pos != 0 and trail_on:
            if pos == 1 and o[i] <= stop and not np.isnan(stop):
                trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                   entry_time=pd.Timestamp(t[entry_i]),
                                   exit_time=pd.Timestamp(t[i]), entry=float(entry),
                                   exit=float(o[i]), pnl=float((o[i] - entry) * OZ - COST),
                                   why="trail gap"))
                pos, stop = 0, np.nan
            elif pos == -1 and o[i] >= stop and not np.isnan(stop):
                trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                   entry_time=pd.Timestamp(t[entry_i]),
                                   exit_time=pd.Timestamp(t[i]), entry=float(entry),
                                   exit=float(o[i]), pnl=float((entry - o[i]) * OZ - COST),
                                   why="trail gap"))
                pos, stop = 0, np.nan
            elif path == "conservative":
                hit = (pos == 1 and not np.isnan(stop) and l[i] <= stop) or \
                      (pos == -1 and not np.isnan(stop) and h[i] >= stop)
                if hit:
                    px = stop
                    trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                       entry_time=pd.Timestamp(t[entry_i]),
                                       exit_time=pd.Timestamp(t[i]), entry=float(entry),
                                       exit=float(px),
                                       pnl=float((px - entry) * pos * OZ - COST),
                                       why="trail"))
                    pos, stop = 0, np.nan
                else:
                    trail_update(i, h[i] if pos == 1 else l[i])
            else:  # optimistic: the favourable extreme happens first
                trail_update(i, h[i] if pos == 1 else l[i])
                hit = (pos == 1 and not np.isnan(stop) and l[i] <= stop) or \
                      (pos == -1 and not np.isnan(stop) and h[i] >= stop)
                if hit:
                    px = stop
                    trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                       entry_time=pd.Timestamp(t[entry_i]),
                                       exit_time=pd.Timestamp(t[i]), entry=float(entry),
                                       exit=float(px),
                                       pnl=float((px - entry) * pos * OZ - COST),
                                       why="trail"))
                    pos, stop = 0, np.nan
        # ---------- reverse cross exit (OnBarClosed of bar j -> fill at open of bar i)
        if pos != 0 and ((pos == 1 and bear[j]) or (pos == -1 and bull[j])):
            px = o[i]
            trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                               entry_time=pd.Timestamp(t[entry_i]),
                               exit_time=pd.Timestamp(t[i]), entry=float(entry),
                               exit=float(px), pnl=float((px - entry) * pos * OZ - COST),
                               why="cross"))
            pos, stop = 0, np.nan
        # ---------- entries ----------
        if pos == 0:
            if bull[j] and hb[j] and win[j]:
                pos, entry, entry_i, sig_i, stop = 1, o[i], i, j, np.nan
            elif bear[j] and hs[j] and win[j]:
                pos, entry, entry_i, sig_i, stop = -1, o[i], i, j, np.nan
            if pos != 0 and trail_on:          # ticks start right after the fill
                trail_update(i, h[i] if pos == 1 else l[i])
    if pos != 0:
        px = c[n - 1]
        trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=n - 1,
                           entry_time=pd.Timestamp(t[entry_i]),
                           exit_time=pd.Timestamp(t[n - 1]), entry=float(entry),
                           exit=float(px), pnl=float((px - entry) * pos * OZ - COST),
                           why="open at end"))
    return trades


def stats(trades):
    if not trades:
        return dict(n=0, net=0.0, wr=0.0, pf=0.0, dd=0.0, avg=0.0, hold=np.nan,
                    worst=0.0, best=0.0, gross=0.0)
    p = np.array([t["pnl"] for t in trades])
    eq = BAL0 + np.cumsum(p)
    w, ls = p[p > 0], p[p <= 0]
    hold = np.mean([(t["exit_time"] - t["entry_time"]).total_seconds() / 60 for t in trades])
    return dict(n=len(p), net=round(float(p.sum()), 2),
                wr=round(len(w) / len(p) * 100, 1),
                pf=round(float(w.sum() / -ls.sum()), 2) if ls.sum() < 0 else float("inf"),
                dd=round(float((eq - np.maximum.accumulate(eq)).min()), 2),
                avg=round(float(p.mean()), 3), hold=hold,
                worst=round(float(p.min()), 2), best=round(float(p.max()), 2),
                gross=round(float(p.sum() + COST * len(p)), 2))


HDR = (f"{'variant':44s}{'trades':>8s}{'net $':>11s}{'win%':>7s}{'PF':>7s}"
       f"{'maxDD $':>11s}{'avg hold':>9s}{'worst $':>9s}")


def pr(label, trades, width=44):
    s = stats(trades)
    print(f"{label:{width}s}{s['n']:>8d}{s['net']:>11.2f}{s['wr']:>6.1f}%{s['pf']:>7.2f}"
          f"{s['dd']:>11.2f}{s['hold']:>9.0f}{s['worst']:>9.2f}")
    return s


def main():
    print("loading 2022-2025 ...", flush=True)
    data = {y: build(load_year(y)) for y in (2022, 2023, 2024, 2025)}
    d26 = build(load_recent())

    # ---------------- worst month ----------------
    print("\n" + "=" * 122)
    print("AUGUST 2023 (the worst month) — cBot with and without the trailing stop")
    print("=" * 122)
    print(HDR)
    pr("no trail (reverse cross only)",
       simulate_cbot(data[2023], "2023-08-01", "2023-08-31 23:59", trail_on=False))
    pr("trail ON (defaults), conservative path",
       simulate_cbot(data[2023], "2023-08-01", "2023-08-31 23:59", path="conservative"))
    pr("trail ON (defaults), optimistic path",
       simulate_cbot(data[2023], "2023-08-01", "2023-08-31 23:59", path="optimistic"))

    # ---------------- four full years ----------------
    print("\n" + "=" * 122)
    print("FULL YEARS 2022-2025 — cBot variants (0.01 lot, $0.20/trade)")
    print("=" * 122)
    variants = [
        ("no trail (cross exit only)", dict(trail_on=False)),
        ("trail 2.0 / 1.5 / cap 2.0 (cBot defaults)", dict()),
        ("trail 2.0 / 1.5 / cap 2.0 (optimistic)", dict(path="optimistic")),
        ("trail 1.0 / 0.5 / cap 1.0", dict(trigger=1.0, dist=0.5, cap=1.0)),
        ("trail 1.0 / 1.0 / cap 1.0", dict(trigger=1.0, dist=1.0, cap=1.0)),
        ("trail 2.0 / 1.0 / cap 2.0", dict(trigger=2.0, dist=1.0, cap=2.0)),
        ("trail 3.0 / 1.5 / cap 3.0", dict(trigger=3.0, dist=1.5, cap=3.0)),
        ("trail 5.0 / 2.0 / cap 5.0", dict(trigger=5.0, dist=2.0, cap=5.0)),
        ("trail 10.0 / 3.0 / cap 10.0", dict(trigger=10.0, dist=3.0, cap=10.0)),
    ]
    print(f"{'variant':44s}" + "".join(f"{str(y):>11s}" for y in (2022, 2023, 2024, 2025))
          + f"{'total':>12s}{'trades':>8s}{'win%':>7s}{'maxDD':>11s}")
    yearly = {}
    for label, kw in variants:
        vals, tot_n, all_tr = [], 0, []
        for y in (2022, 2023, 2024, 2025):
            tr = simulate_cbot(data[y], **kw)
            s = stats(tr)
            vals.append(s["net"]); tot_n += s["n"]; all_tr += tr
        st = stats(all_tr)
        yearly[label] = (vals, tot_n, st, all_tr)
        print(f"{label:44s}" + "".join(f"{v:>11.2f}" for v in vals)
              + f"{sum(vals):>12.2f}{tot_n:>8d}{st['wr']:>6.1f}%{st['dd']:>11.2f}")

    # ---------------- what the trail does ----------------
    print("\n" + "=" * 122)
    print("WHAT THE TRAILING STOP ACTUALLY DOES — 2022-2025, cBot defaults")
    print("=" * 122)
    base_tr = yearly["no trail (cross exit only)"][3]
    tr_on = yearly["trail 2.0 / 1.5 / cap 2.0 (cBot defaults)"][3]
    b = pd.DataFrame(base_tr); ton = pd.DataFrame(tr_on)
    print(f"{'':28s}{'no trail':>14s}{'trail ON':>14s}")
    for lbl, key in [("closed trades", "n"), ("win rate %", "wr"), ("net $", "net"),
                     ("average win $", None), ("average loss $", None),
                     ("biggest win $", None), ("worst trade $", None),
                     ("average hold (min)", None)]:
        if key:
            sb, st_ = stats(base_tr), stats(tr_on)
            print(f"{lbl:28s}{sb[key]:>14,.2f}{st_[key]:>14,.2f}")
        else:
            wb, lb = b[b.pnl > 0].pnl, b[b.pnl <= 0].pnl
            wo, lo = ton[ton.pnl > 0].pnl, ton[ton.pnl <= 0].pnl
            x = {"average win $": (wb.mean(), wo.mean()),
                 "average loss $": (lb.mean(), lo.mean()),
                 "biggest win $": (b.pnl.max(), ton.pnl.max()),
                 "worst trade $": (b.pnl.min(), ton.pnl.min()),
                 "average hold (min)": ((b.exit_time - b.entry_time).dt.total_seconds().mean() / 60,
                                        (ton.exit_time - ton.entry_time).dt.total_seconds().mean() / 60)}[lbl]
            print(f"{lbl:28s}{x[0]:>14,.2f}{x[1]:>14,.2f}")
    print(f"\nexit mix with the trail ON: " + ", ".join(
        f"{k} {v:,}" for k, v in ton.why.value_counts().items()))
    trail_trades = ton[ton.why.isin(["trail", "trail gap"])]
    print(f"trades the trailing stop closed: {len(trail_trades):,} "
          f"({len(trail_trades) / len(ton) * 100:.1f}%) | their average P/L "
          f"${trail_trades.pnl.mean():+.2f} | total ${trail_trades.pnl.sum():,.0f}")
    capped = trail_trades[(trail_trades.pnl > 1.7) & (trail_trades.pnl < 1.9)]
    print(f"of those, {len(capped):,} exited at the +${CAP:.2f} cap "
          f"(+${CAP - COST:.2f} after the ${COST:.2f} cost)")
    print(f"trail exits in profit: {(trail_trades.pnl > 0).mean() * 100:.1f}% | "
          f"median ${trail_trades.pnl.median():+.2f} | min ${trail_trades.pnl.min():.2f}")
    bdf = pd.DataFrame(base_tr)
    mm = bdf.merge(trail_trades[["entry_time", "pnl"]], on="entry_time",
                   suffixes=("_cross", "_trail"))
    diff = mm.pnl_trail.sum() - mm.pnl_cross.sum()
    print(f"the same {len(mm):,} entries closed by the cross instead: "
          f"${mm.pnl_cross.sum():,.0f} vs trail ${mm.pnl_trail.sum():,.0f} -> the trail "
          f"{'gave up' if diff < 0 else 'added'} ${abs(diff):,.0f}")
    print(f"  improved {int((mm.pnl_trail > mm.pnl_cross).sum()):,} of them, worsened "
          f"{int((mm.pnl_trail < mm.pnl_cross).sum()):,}")
    # how much is left on the table: same trades under the cross-exit rule
    print(f"\nbiggest winners: no trail ${b.pnl.max():.2f} vs trail ${ton.pnl.max():.2f} "
          f"(the cap + MaxTrailCap = +${CAP:.2f} minus costs)")

    # ---------------- recent real window ----------------
    print("\n" + "=" * 122)
    print("SEPTEMBER 2026 (real Exness MT5, 9-18 Sep) — sanity check")
    print("=" * 122)
    print(HDR)
    for label, kw in [("no trail", dict(trail_on=False)),
                      ("trail defaults (conservative)", dict()),
                      ("trail defaults (optimistic)", dict(path="optimistic"))]:
        pr("cBot " + label, simulate_cbot(d26, **kw))

    # ---------------- chart ----------------
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [1.35, 1]})
    for label, col in [("no trail (cross exit only)", "#888888"),
                       ("trail 2.0 / 1.5 / cap 2.0 (cBot defaults)", "#1f77b4"),
                       ("trail 2.0 / 1.5 / cap 2.0 (optimistic)", "#9467bd"),
                       ("trail 10.0 / 3.0 / cap 10.0", "#2ca02c")]:
        vals, tot_n, st, all_tr = yearly[label]
        dfx = pd.DataFrame(all_tr)
        axes[0].plot(pd.to_datetime(dfx.exit_time), BAL0 + np.cumsum(dfx.pnl.values),
                     lw=1.2, color=col, label=f"{label}: {sum(vals):+,.0f}")
    axes[0].axhline(BAL0, color="k", ls=":", lw=1)
    axes[0].set_ylabel("Equity ($)")
    axes[0].set_title("cTrader 'Trande Hunter' cBot on real XAUUSD M1, 2022-2025 "
                      "(0.01 lot, $0.20/trade)")
    axes[0].legend(fontsize=8.5)
    axes[0].grid(alpha=0.3)

    labels = [v[0] for v in variants]
    vals = [sum(yearly[l][0]) for l in labels]
    axes[1].barh(range(len(labels)), vals,
                 color=["#089981" if v > 0 else "#f23645" for v in vals])
    axes[1].set_yticks(range(len(labels)))
    axes[1].set_yticklabels(labels, fontsize=8)
    axes[1].invert_yaxis()
    axes[1].axvline(0, color="k", lw=1)
    axes[1].set_xlabel("4-year net P/L ($)")
    axes[1].set_title("Trailing-stop parameter sensitivity")
    axes[1].grid(alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig("results/cbot_trailer.png", dpi=120)
    print("\nSaved results/cbot_trailer.png")

    # ---------------- report ----------------
    s0 = stats(base_tr); s1 = stats(tr_on)
    wb, lb = b[b.pnl > 0].pnl, b[b.pnl <= 0].pnl
    wo, lo = ton[ton.pnl > 0].pnl, ton[ton.pnl <= 0].pnl
    L = ["# cTrader cBot 'Trande Hunter' — faithful port and test", "",
         "The cBot: EMA 6/9 crossover on M1 + 5m EMA 9/12 trend, entry on the cross in the",
         "trend direction, exit on the raw opposite 1m crossover, plus a trailing stop that",
         "activates at +$2.00, trails $1.50 behind, locks at least +$0.50 and never more than",
         "+$2.00 (MaxTrailCap). 0.01 lot, $0.20 per round trip, real XAUUSD M1.", "",
         "Only M1 OHLC exists (no ticks), so the intrabar order of the high and the low is",
         "unknown; both orderings are reported: **conservative** (the adverse extreme is hit",
         "first) and **optimistic** (the favourable extreme comes first). The truth is between",
         "the two, and the difference is small.", "",
         "## Four full years 2022-2025", "",
         "| variant | 2022 | 2023 | 2024 | 2025 | total | trades | win% | maxDD $ |",
         "|---|---|---|---|---|---|---|---|---|"]
    for label, _ in variants:
        v, n, st, _ = yearly[label]
        L.append(f"| {label} | " + " | ".join(f"${x:,.0f}" for x in v) +
                 f" | **${sum(v):,.0f}** | {n:,} | {st['wr']}% | ${st['dd']:,.0f} |")
    L += ["", "## What the trailing stop actually does (2022-2025)", "",
          "| | no trail | trail ON (defaults) |", "|---|---|---|",
          f"| trades | {s0['n']:,} | {s1['n']:,} |",
          f"| win rate | {s0['wr']}% | {s1['wr']}% |",
          f"| net | ${s0['net']:,.2f} | ${s1['net']:,.2f} |",
          f"| gross before spread | ${s0['gross']:,.2f} | ${s1['gross']:,.2f} |",
          f"| average win | ${wb.mean():.2f} | ${wo.mean():.2f} |",
          f"| average loss | ${lb.mean():.2f} | ${lo.mean():.2f} |",
          f"| biggest win | ${b.pnl.max():.2f} | ${ton.pnl.max():.2f} |",
          f"| worst trade | ${b.pnl.min():.2f} | ${ton.pnl.min():.2f} |",
          f"| max drawdown | ${s0['dd']:,.0f} | ${s1['dd']:,.0f} |", "",
          f"With the trail ON, **{len(trail_trades):,} of {len(ton):,} trades "
          f"({len(trail_trades) / len(ton) * 100:.1f}%)** were closed by the trailing stop: "
          f"{(trail_trades.pnl > 0).mean() * 100:.1f}% of them in profit, median "
          f"${trail_trades.pnl.median():+.2f}, and {len(capped):,} exited at the "
          f"+${CAP:.2f} cap (+${CAP - COST:.2f} net). Exit mix: " +
          ", ".join(f"{k} {v:,}" for k, v in ton.why.value_counts().items()) + ".", "",
          f"The same {len(mm):,} entries closed by the cross instead would have produced "
          f"${mm.pnl_cross.sum():,.0f} versus the trail's ${mm.pnl_trail.sum():,.0f} - the "
          f"trailing stop {'gave up' if mm.pnl_trail.sum() < mm.pnl_cross.sum() else 'added'} "
          f"${abs(mm.pnl_trail.sum() - mm.pnl_cross.sum()):,.0f}. It improved "
          f"{int((mm.pnl_trail > mm.pnl_cross).sum()):,} trades and worsened "
          f"{int((mm.pnl_trail < mm.pnl_cross).sum()):,}: a reshuffle, not an edge.", "",
          "## Worst month (August 2023)", "",
          "| variant | trades | net $ | win% |", "|---|---|---|---|",
          f"| no trail | {stats(simulate_cbot(data[2023], '2023-08-01', '2023-08-31 23:59', trail_on=False))['n']:,} | "
          f"${stats(simulate_cbot(data[2023], '2023-08-01', '2023-08-31 23:59', trail_on=False))['net']:,.2f} | "
          f"{stats(simulate_cbot(data[2023], '2023-08-01', '2023-08-31 23:59', trail_on=False))['wr']}% |",
          f"| trail ON (conservative) | {stats(simulate_cbot(data[2023], '2023-08-01', '2023-08-31 23:59'))['n']:,} | "
          f"${stats(simulate_cbot(data[2023], '2023-08-01', '2023-08-31 23:59'))['net']:,.2f} | "
          f"{stats(simulate_cbot(data[2023], '2023-08-01', '2023-08-31 23:59'))['wr']}% |",
          f"| trail ON (optimistic) | "
          f"{stats(simulate_cbot(data[2023], '2023-08-01', '2023-08-31 23:59', path='optimistic'))['n']:,} | "
          f"${stats(simulate_cbot(data[2023], '2023-08-01', '2023-08-31 23:59', path='optimistic'))['net']:,.2f} | "
          f"{stats(simulate_cbot(data[2023], '2023-08-01', '2023-08-31 23:59', path='optimistic'))['wr']}% |", "",
          "## September 2026 (real Exness MT5, 9-18 Sep)", "",
          "| variant | trades | net $ | win% |", "|---|---|---|---|",
          f"| no trail | {stats(simulate_cbot(d26, trail_on=False))['n']} | "
          f"${stats(simulate_cbot(d26, trail_on=False))['net']:,.2f} | "
          f"{stats(simulate_cbot(d26, trail_on=False))['wr']}% |",
          f"| trail ON | {stats(simulate_cbot(d26))['n']} | "
          f"${stats(simulate_cbot(d26))['net']:,.2f} | {stats(simulate_cbot(d26))['wr']}% |", "",
          "Charts: results/cbot_trailer.png"]
    with open("results/cbot_trailer_report.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("Saved results/cbot_trailer_report.md")
    return yearly, b, ton


if __name__ == "__main__":
    main()
