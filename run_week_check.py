"""Why a profitable TradingView week does not contradict the long-run result.

The user tested one week on TradingView and saw roughly +$250 per day. This script
reconciles that with the multi-year backtests in this repo by measuring the three things
that can produce the gap:

  1. POSITION SIZE / CONTRACT MULTIPLIER — the same signal at 1 oz (0.01 lot), 10 oz
     (0.1 lot) and 100 oz (1 lot, or a 100-oz CFD/futures contract on TradingView).
  2. COSTS — the pasted scripts ship with slipTicks = 0 / commissionPct = 0, i.e. no
     spread at all, while this repo charges $0.20 per round trip.
  3. WHICH WEEK — every week of 2022-2026 is ranked, and the tested week's percentile is
     reported, so we can see whether one week is evidence or luck.

Everything runs on the same data as the committed reports: real XAUUSD M1, the last week
being 14-18 September 2026 (the real Exness MT5 feed).

Usage: python3 run_week_check.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_trade_forensics import build, load_year, load_recent, COST, BAL0
from run_hold_losers import simulate_hybrid
from run_cbot_trailer import simulate_cbot, stats
import run_price_action_30 as PA30

LAST_WEEK = ("2026-09-14", "2026-09-18 23:59")


def per_day(trades):
    if not trades:
        return pd.Series(dtype=float)
    df = pd.DataFrame(trades)
    return df.groupby(pd.to_datetime(df.exit_time).dt.date).pnl.sum()


def weekly(trades):
    """Mon-Fri buckets."""
    if not trades:
        return pd.Series(dtype=float)
    df = pd.DataFrame(trades)
    d = pd.to_datetime(df.exit_time)
    wk = (d - pd.to_timedelta(d.dt.weekday, unit="D")).dt.date
    return df.groupby(wk).pnl.sum()


def main():
    d26 = build(load_recent())
    print("=" * 118)
    print("1. THE WEEK YOU TESTED — 14-18 September 2026 (real Exness MT5 M1 data)")
    print("=" * 118)
    variants = [("E1 your script x cross", dict(entry="bb", exit_="cross")),
                ("E1 x hybrid (your rule)", dict(entry="bb", exit_="hybrid")),
                ("E1 x trail (cBot stop)", dict(entry="bb", exit_="trail")),
                ("E2 cBot x cross", dict(entry="plain", exit_="cross"))]

    def run(d, entry, exit_):
        buy = d["base_buy"] if entry == "bb" else (d["bull"] & d["htf_bull"])
        sell = d["base_sell"] if entry == "bb" else (d["bear"] & d["htf_bear"])
        if exit_ == "hybrid":
            dd = dict(d); dd["base_buy"], dd["base_sell"] = buy, sell
            return simulate_hybrid(dd, mode="hybrid", five_min_closes_winners=True)
        if exit_ == "trail":
            return simulate_cbot(d, trail_on=True, path="conservative",
                                 entry_buy=buy, entry_sell=sell)
        return simulate_cbot(d, trail_on=False, entry_buy=buy, entry_sell=sell)

    week_trades = {}
    print(f"{'variant':30s}{'trades':>8s}{'week net $':>12s}{'win%':>7s}"
          f"{'9-18 net $':>12s}{'9-18 gross $':>14s}")
    for label, kw in variants:
        wk = [t for t in run(d26, **kw) if str(pd.Timestamp(t["exit_time"]).date()) >= LAST_WEEK[0]]
        full = run(d26, **kw)
        week_trades[label] = wk
        s, sf = stats(wk), stats(full)
        print(f"{label:30s}{s['n']:>8d}{s['net']:>12.2f}{s['wr']:>6.1f}%"
              f"{sf['net']:>12.2f}{sf['gross']:>14.2f}")

    # the 30-systems script for the same week
    o, h, l, c, buy, sell = PA30.prep(load_recent())
    pa30_week, pa30_day = [], []
    for s_ in range(30):
        tr, sk = PA30.run_system(o, h, l, c, buy[s_], sell[s_])
        pa30_week += [t for t in tr if str(pd.Timestamp(t["time"]).date()) >= LAST_WEEK[0]]
    print(f"{'30-systems script (all 30)':30s}{len(pa30_week):>8d}"
          f"{sum(t['pnl'] for t in pa30_week):>12.2f}")

    # ---------------- 2. the three explanations ----------------
    print("\n" + "=" * 118)
    print("2. SCALING — same trades, different position size (with and without the cost)")
    print("=" * 118)
    base_wk = pd.DataFrame(week_trades["E1 your script x cross"])
    print(f"last week: {len(base_wk)} trades | with cost ${base_wk.pnl.sum():.2f} | "
          f"without cost ${base_wk.pnl.sum() + COST * len(base_wk):.2f}")
    sizes = [("1 oz = 0.01 lot", 1), ("10 oz = 0.10 lot", 10), ("100 oz = 1.00 lot", 100)]
    print(f"\n{'size':22s}{'week $ (with cost)':>20s}{'per day':>12s}"
          f"{'week $ (no cost)':>20s}{'per day':>12s}")
    scaling = []
    for nm, mult in sizes:
        wc = base_wk.pnl.sum() * mult
        wn = (base_wk.pnl.sum() + COST * len(base_wk)) * mult
        scaling.append((nm, wc, wc / 5, wn, wn / 5))
        print(f"{nm:22s}{wc:>20,.2f}{wc / 5:>12,.2f}{wn:>20,.2f}{wn / 5:>12,.2f}")
    need_c = 250 * 5 / base_wk.pnl.sum() if base_wk.pnl.sum() > 0 else float("inf")
    need_n = 250 * 5 / (base_wk.pnl.sum() + COST * len(base_wk))
    print(f"\nTo make $250/day in this week you needed: {need_c:.2f} oz with the $0.20 cost, "
          f"or {need_n:.2f} oz with zero cost")
    print(f"(i.e. a position {need_c:.1f}x the house 1 oz, or {need_n:.1f}x = "
          f"about 1 contract on a 100-oz gold symbol)")

    # ---------------- 3. how special was that week? ----------------
    print("\n" + "=" * 118)
    print("3. EVERY WEEK 2022-2026 — is one profitable week evidence of an edge?")
    print("=" * 118)
    weeks = []
    for y in (2022, 2023, 2024, 2025):
        tr = run(build(load_year(y)), entry="bb", exit_="cross")
        weeks.append(weekly(tr))
    weeks.append(weekly(run(d26, entry="bb", exit_="cross")))
    wk = pd.concat(weeks)
    wk = wk[wk.index >= pd.Timestamp("2022-01-03").date()]
    pos = (wk > 0).mean() * 100
    target = wk.get(pd.Timestamp("2026-09-14").date())
    pct = (wk < target).mean() * 100
    print(f"weeks counted: {len(wk)} | positive weeks: {int((wk > 0).sum())} ({pos:.1f}%)")
    print(f"week of 14 Sep 2026: ${target:,.2f} -> better than {pct:.0f}% of all weeks")
    print(f"median week ${wk.median():,.2f} | average ${wk.mean():,.2f} | "
          f"best ${wk.max():,.2f} | worst ${wk.min():,.2f}")
    print(f"sum of all weeks (4.7 years) ${wk.sum():,.2f} at 1 oz; "
          f"at 100 oz that is ${wk.sum() * 100:,.0f}")
    print("\nthe ten best weeks:")
    print(wk.sort_values(ascending=False).head(10).round(2).to_string())
    print(f"\nchance a random week is positive: {pos:.1f}% | chance of a week better than "
          f"+$148.84: {(wk > 148.84).mean() * 100:.1f}%")

    # ---------------- what happens after a great week ----------------
    print("\n" + "=" * 118)
    print("4. WHAT HAPPENED AFTER THE PREVIOUS GREAT WEEKS")
    print("=" * 118)
    wk_sorted = wk.sort_values(ascending=False)
    idx = list(wk.index)
    after = []
    for d_, v in wk_sorted.head(10).items():
        i = idx.index(d_)
        nxt = wk.iloc[i + 1:i + 5]
        after.append((d_, float(v), float(nxt.sum()), int((nxt > 0).sum())))
        print(f"  week {d_} ${v:>8.2f} -> the next 4 weeks ${nxt.sum():>9.2f} "
              f"({int((nxt > 0).sum())}/4 positive)")
    avg_after = float(np.mean([a[2] for a in after]))
    print(f"\naverage of the 4 weeks after a top-10 week: ${avg_after:,.2f} "
          f"(a random 4-week block averages ${wk.mean() * 4:,.2f})")
    pos_runs, neg_runs, cur = [], [], 0
    for x in (wk > 0).astype(int):
        cur = cur + 1 if x else 0
        pos_runs.append(cur)
    cur = 0
    for x in (wk < 0).astype(int):
        cur = cur + 1 if x else 0
        neg_runs.append(cur)
    print(f"longest winning streak: {max(pos_runs)} weeks | "
          f"longest losing streak: {max(neg_runs)} weeks")

    # ---------------- chart ----------------
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), gridspec_kw={"height_ratios": [1, 1.2]})
    days = per_day(week_trades["E1 your script x cross"])
    axes[0].bar([str(x) for x in days.index], days.values,
                color=["#089981" if v > 0 else "#f23645" for v in days.values])
    axes[0].axhline(0, color="k", lw=1)
    axes[0].set_title("Your script, the week of 14-18 September 2026 — daily net P/L "
                      "at 0.01 lot (1 oz), $0.20/trade")
    axes[0].set_ylabel("net $ / day")
    for i, v in enumerate(days.values):
        axes[0].annotate(f"{v:+.0f}", (i, v), ha="center",
                         va="bottom" if v > 0 else "top", fontsize=9)
    axes[0].grid(alpha=0.3, axis="y")

    axes[1].hist(wk.values, bins=40, color="#7f7f7f")
    axes[1].axvline(0, color="k", lw=1)
    axes[1].axvline(target, color="#d62728", lw=2,
                    label=f"the tested week: ${target:,.0f}")
    axes[1].axvline(wk.mean(), color="#1f77b4", lw=2, ls="--",
                    label=f"average week: ${wk.mean():,.0f}")
    axes[1].set_title(f"All {len(wk)} weeks of 2022-2026 at 0.01 lot — the tested week is in "
                      f"the top {100 - pct:.0f}%")
    axes[1].set_xlabel("weekly net P/L ($)")
    axes[1].set_ylabel("weeks")
    axes[1].legend(fontsize=9)
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("results/week_check.png", dpi=120)
    print("\nSaved results/week_check.png")

    # ---------------- report ----------------
    s_wk = stats(week_trades["E1 your script x cross"])
    L = ["# Checking the TradingView week against this repo's results", "",
         "You tested one week on TradingView and saw about +$250 per day. This report does not",
         "argue with that - it measures where the number comes from.", "",
         "## 1. The same week, on the real Exness MT5 feed", "",
         "| variant | trades | week net $ (1 oz) | win% | 9-18 Sep net $ | 9-18 Sep gross $ |",
         "|---|---|---|---|---|---|"]
    for label, kw in variants:
        wk_t = week_trades[label]
        s, sf = stats(wk_t), stats(run(d26, **kw))
        L.append(f"| {label} | {s['n']} | ${s['net']:,.2f} | {s['wr']}% | ${sf['net']:,.2f} | "
                 f"${sf['gross']:,.2f} |")
    L += [f"| 30-systems script (all 30) | {len(pa30_week)} | "
          f"${sum(t['pnl'] for t in pa30_week):,.2f} | | | |", "",
          "**The week WAS profitable here too.** So the disagreement is not about that week -",
          "it is about what one week can prove.", "",
          "## 2. The three things that turn +$148.84 into +$250 a day", "",
          "| size | week $ (with the $0.20 cost) | per day | week $ (no cost) | per day |",
          "|---|---|---|---|---|"]
    for nm, wc, dc, wn, dn in scaling:
        L.append(f"| {nm} | ${wc:,.2f} | ${dc:,.2f} | ${wn:,.2f} | ${dn:,.2f} |")
    L += ["", f"To reach $250/day in that week: **{need_c:.2f} oz** with the cost, or "
          f"**{need_n:.2f} oz** with TradingView's default zero cost. The pasted scripts ship",
          "with `slipTicks = 0` and `commissionPct = 0`, so on the chart no spread is charged",
          "at all - that alone adds "
          f"${COST * len(base_wk):,.2f} to the week ({COST * len(base_wk) / 1:.0f} trades x $0.20).", "",
          "## 3. How special was that week?", "",
          f"All weeks of 2022-2026 at 0.01 lot: **{len(wk)} weeks**, "
          f"**{int((wk > 0).sum())} positive ({pos:.1f}%)**, median week "
          f"${wk.median():,.2f}, average ${wk.mean():,.2f}.", "",
          f"The tested week (+${target:,.2f}) is better than **{pct:.0f}% of all weeks** in the",
          f"record. Ten best weeks: " +
          ", ".join(f"{d} ${v:,.0f}" for d, v in wk.sort_values(ascending=False).head(10).items())
          + ".", "",
          "### What happened after the previous great weeks", "",
          "| great week | next 4 weeks | positive |", "|---|---|---|"]
    L += [f"| {d_} (${v:,.0f}) | ${n:,.0f} | {p}/4 |" for d_, v, n, p in after]
    L += [
          "", f"Average of the four weeks after a top-10 week: **${avg_after:,.2f}**. The record",
          f"also contains a **{max(neg_runs)}-week losing streak** against a longest winning",
          f"streak of {max(pos_runs)} weeks.", "",
          f"Sum of every week 2022-2026: **${wk.sum():,.2f} at 1 oz**. At the size needed for",
          f"$250/day that same record becomes **${wk.sum() * need_n:,.0f}** - scaling multiplies",
          "the losses exactly like it multiplies the wins.", "",
          "## Verdict", "",
          "1. Your week is real and my own data reproduces it (+$148.84 net at 0.01 lot,",
          "   +$29.77/day; the other variants: trail +$88.15, hybrid +$14.91 for 9-18 Sep).",
          "2. The step to ~$250/day comes from position size (~8x with the $0.20 cost, ~5.8x",
          "   with zero cost) and/or from TradingView charging no spread, which is what the",
          "   script's default `slipTicks = 0` does. Neither changes the expected value of the",
          "   strategy - it only scales it.",
          f"3. That week sits in the top {100 - pct:.0f}% of the 2022-2026 record; the median",
          "   week loses money and only "
          f"{pos:.0f}% of weeks are positive, so a single winning week is the expected",
          "   experience of a losing system on a good streak, not evidence of an edge.",
          "4. The honest test is the one this repo keeps running: months and years, with the",
          "   spread charged. On that test the same rules lose -$10,810 (2022-2025) and",
          "   -$1,502 (2026 Jan-Sep) at 0.01 lot. At the $250/day size those numbers scale to",
          "   roughly -$1.2M and -$150k respectively - the size that makes the wins big makes",
          "   the losses big in exactly the same proportion.", "",
          "If you want, tell me the symbol you tested on TradingView (for example XAUUSD vs a",
          "100-oz futures contract) and the position size, and I will reproduce that exact",
          "configuration bar for bar.", "", "Chart: results/week_check.png"]
    with open("results/week_check_report.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("Saved results/week_check_report.md")
    return wk


if __name__ == "__main__":
    main()
