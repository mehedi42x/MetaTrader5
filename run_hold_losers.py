"""Hybrid exit rule: M1 reverse cross closes only WINNING trades; losing trades are held
until the 5-minute EMA 9/12 trend reverses.

The rule (as asked):
  - a trade that is in PROFIT is closed by the M1 EMA 6/9 reverse cross
  - a trade that is in LOSS is NOT closed by that cross - it is held
  - losing trades close only when the 5m EMA 9/12 trend flips against the position
Variants tested around it so we can see whether holding losers helps or hurts:
  - does the 5m flip also close profitable trades?          (yes / no)
  - is there a hard stop far away as a disaster brake?      (none / 2.5 ATR / 4 ATR)
  - with and without the entry blockers from run_loss_blocker.py
Everything else is the usual port of the pasted script: EMA 6/9 crossover on M1 +
Bollinger(20,2) middle filter + 5m EMA 9/12 trend, fill at the next bar's open,
0.01 lot, $0.20 per round trip.

Windows: the worst month (2023-08), the four full years 2022-2025, and the real
September 2026 window (Exness MT5 feed).

Usage:  python3 run_hold_losers.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_trade_forensics import build, load_year, load_recent, OZ, COST, BAL0
from run_loss_blocker import mask_from_rules

BAD_MONTH = ("2023-08-01 00:00", "2023-08-31 23:59")
BLOCK_RULES = [("hour", "range", (9, 13)), ("sep", "range", (0.03, 0.08)), ("htfstr", "<=", 0.20)]


def simulate_hybrid(d, t0=None, t1=None, ok_mask=None,
                    five_min_closes_winners=True, hard_stop_atr=None, min_hold=0,
                    mode="hybrid"):
    """mode:
         'base'   : the original rule - M1 reverse cross closes everything
         'hybrid' : M1 reverse cross closes only trades in profit (+ optional 5m flip rule)
    """
    o, h, l, c, t = d["open"], d["high"], d["low"], d["close"], d["time"]
    atr = d["atr"]
    bull, bear = d["bull"], d["bear"]
    htf_bull, htf_bear = d["htf_bull"], d["htf_bear"]
    buy, sell = d["base_buy"], d["base_sell"]
    n = len(o)
    win = np.ones(n, bool)
    if t0 is not None:
        win &= t >= np.datetime64(pd.to_datetime(t0))
    if t1 is not None:
        win &= t <= np.datetime64(pd.to_datetime(t1))
    if ok_mask is not None:
        win = win & ok_mask

    trades = []
    pos, entry, entry_i, sig_i = 0, np.nan, None, None
    for i in range(1, n):
        j = i - 1
        # ---------- exits (decided by what was known at the close of bar j) ----------
        if pos != 0 and i > entry_i:
            in_profit = ((c[j] - entry) * pos * OZ - COST) > 0
            htf_flip = (pos == 1 and htf_bear[j]) or (pos == -1 and htf_bull[j])
            m1_cross = (pos == 1 and bear[j]) or (pos == -1 and bull[j])
            held_long_enough = (i - entry_i) >= min_hold
            do_close = False
            kind = ""
            if mode == "base":
                if m1_cross and held_long_enough:
                    do_close, kind = True, "M1 cross"
            else:
                # the 5m trend flip: closes the losers (and optionally the winners too)
                if htf_flip and (five_min_closes_winners or not in_profit) and held_long_enough:
                    do_close, kind = True, "5m flip"
                elif m1_cross and in_profit and held_long_enough:
                    do_close, kind = True, "M1 cross (in profit)"
            if do_close:
                px = o[i]
                trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                   entry_time=pd.Timestamp(t[entry_i]),
                                   exit_time=pd.Timestamp(t[i]), entry=float(entry),
                                   exit=float(px), pnl=float((px - entry) * pos * OZ - COST),
                                   exit_kind=kind, in_profit_at_signal=bool(in_profit)))
                pos = 0
        # ---------- hard stop (disaster brake), intrabar ----------
        if pos != 0 and hard_stop_atr is not None:
            stop = entry - pos * hard_stop_atr * atr[sig_i]
            hit = (l[i] <= stop) if pos == 1 else (h[i] >= stop)
            if hit:
                px = stop
                trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                   entry_time=pd.Timestamp(t[entry_i]),
                                   exit_time=pd.Timestamp(t[i]), entry=float(entry),
                                   exit=float(px), pnl=float((px - entry) * pos * OZ - COST),
                                   exit_kind="hard stop", in_profit_at_signal=None))
                pos = 0
        # ---------- entries ----------
        if pos == 0:
            if buy[j] and win[j]:
                pos, entry, entry_i, sig_i = 1, o[i], i, j
            elif sell[j] and win[j]:
                pos, entry, entry_i, sig_i = -1, o[i], i, j
    if pos != 0:
        px = c[n - 1]
        trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=n - 1,
                           entry_time=pd.Timestamp(t[entry_i]), exit_time=pd.Timestamp(t[n - 1]),
                           entry=float(entry), exit=float(px),
                           pnl=float((px - entry) * pos * OZ - COST),
                           exit_kind="open at end", in_profit_at_signal=None))
    return trades


def stats(trades):
    if not trades:
        return dict(n=0, net=0.0, wr=0.0, pf=0.0, dd=0.0, avg=0.0, hold=np.nan,
                    worst=0.0, best=0.0, gross=0.0)
    pnl = np.array([t["pnl"] for t in trades])
    eq = BAL0 + np.cumsum(pnl)
    hold = np.mean([(t["exit_time"] - t["entry_time"]).total_seconds() / 60 for t in trades])
    w, ls = pnl[pnl > 0], pnl[pnl <= 0]
    return dict(n=len(pnl), net=round(float(pnl.sum()), 2), wr=round(len(w) / len(pnl) * 100, 1),
                pf=round(float(w.sum() / -ls.sum()), 2) if ls.sum() < 0 else float("inf"),
                dd=round(float((eq - np.maximum.accumulate(eq)).min()), 2),
                avg=round(float(pnl.mean()), 3),
                hold=hold, worst=round(float(pnl.min()), 2), best=round(float(pnl.max()), 2),
                gross=round(float(pnl.sum() + COST * len(pnl)), 2))


def pr(label, trades, width=46):
    s = stats(trades)
    print(f"{label:{width}s}{s['n']:>7d}{s['net']:>11.2f}{s['wr']:>7.1f}%{s['pf']:>7.2f}"
          f"{s['dd']:>10.2f}{s['hold']:>9.0f}{s['worst']:>9.2f}")
    return s


HDR = (f"{'variant':46s}{'trades':>7s}{'net $':>11s}{'win%':>7s}{'PF':>7s}"
       f"{'maxDD $':>10s}{'avg hold':>9s}{'worst $':>9s}")


def main():
    print("loading 2022-2025 ...", flush=True)
    data = {y: build(load_year(y)) for y in (2022, 2023, 2024, 2025)}
    d26 = build(load_recent())

    # ---------- 1. the worst month ----------
    print("\n" + "=" * 118)
    print("AUGUST 2023 (the worst month) — the new exit rule vs the original")
    print("=" * 118)
    print(HDR)
    pr("original: M1 cross closes everything",
       simulate_hybrid(data[2023], *BAD_MONTH, mode="base"))
    pr("hybrid: M1 cross (profit only) + 5m flip closes all",
       simulate_hybrid(data[2023], *BAD_MONTH, mode="hybrid", five_min_closes_winners=True))
    pr("hybrid: M1 cross (profit only) + 5m flip closes losers",
       simulate_hybrid(data[2023], *BAD_MONTH, mode="hybrid", five_min_closes_winners=False))
    pr("hybrid + hard stop 2.5 ATR",
       simulate_hybrid(data[2023], *BAD_MONTH, mode="hybrid", hard_stop_atr=2.5))
    pr("hybrid + hard stop 4 ATR",
       simulate_hybrid(data[2023], *BAD_MONTH, mode="hybrid", hard_stop_atr=4.0))

    # ---------- 2. four full years ----------
    print("\n" + "=" * 118)
    print("FULL YEARS 2022-2025 — every variant (no entry blockers)")
    print("=" * 118)
    variants = [
        ("base (original exit)", dict(mode="base")),
        ("hybrid: 5m flip closes all", dict(mode="hybrid", five_min_closes_winners=True)),
        ("hybrid: 5m flip closes losers", dict(mode="hybrid", five_min_closes_winners=False)),
        ("hybrid + hard stop 2.5 ATR", dict(mode="hybrid", hard_stop_atr=2.5)),
        ("hybrid + hard stop 4 ATR", dict(mode="hybrid", hard_stop_atr=4.0)),
        ("hybrid + min hold 5 bars", dict(mode="hybrid", min_hold=5)),
    ]
    print(f"{'variant':34s}" + "".join(f"{str(y):>11s}" for y in (2022, 2023, 2024, 2025))
          + f"{'total':>12s}{'trades':>8s}{'win%':>7s}{'maxDD':>10s}")
    yearly = {}
    for label, kw in variants:
        vals, tot_n, all_tr = [], 0, []
        for y in (2022, 2023, 2024, 2025):
            tr = simulate_hybrid(data[y], **kw)
            s = stats(tr)
            vals.append(s["net"]); tot_n += s["n"]; all_tr += tr
        st = stats(all_tr)
        yearly[label] = vals
        print(f"{label:34s}" + "".join(f"{v:>11.2f}" for v in vals)
              + f"{sum(vals):>12.2f}{tot_n:>8d}{st['wr']:>6.1f}%{st['dd']:>10.2f}")

    # ---------- 3. with the entry blockers too ----------
    print("\n" + "=" * 118)
    print("FULL YEARS with the entry blockers ON (09-13 UTC + EMA separation window)")
    print("=" * 118)
    print(f"{'variant':34s}" + "".join(f"{str(y):>11s}" for y in (2022, 2023, 2024, 2025))
          + f"{'total':>12s}{'trades':>8s}{'win%':>7s}{'maxDD':>10s}")
    yearly_blocked = {}
    for label, kw in variants:
        vals, tot_n, all_tr = [], 0, []
        for y in (2022, 2023, 2024, 2025):
            m = mask_from_rules(data[y], BLOCK_RULES)
            tr = simulate_hybrid(data[y], ok_mask=m, **kw)
            s = stats(tr)
            vals.append(s["net"]); tot_n += s["n"]; all_tr += tr
        st = stats(all_tr)
        yearly_blocked[label] = vals
        print(f"{label:34s}" + "".join(f"{v:>11.2f}" for v in vals)
              + f"{sum(vals):>12.2f}{tot_n:>8d}{st['wr']:>6.1f}%{st['dd']:>10.2f}")

    # ---------- 4. recent real data ----------
    print("\n" + "=" * 118)
    print("SEPTEMBER 2026 (real Exness MT5, 9-18 Sep) — sanity check")
    print("=" * 118)
    print(HDR)
    for label, kw in variants[:5]:
        m = mask_from_rules(d26, BLOCK_RULES)
        pr(label + " [blocked]", simulate_hybrid(d26, ok_mask=m, **kw))

    # ---------- 5. detail of what holding does ----------
    print("\n" + "=" * 118)
    print("WHAT HOLDING LOSERS DOES — 2022-2025, hybrid rule")
    print("=" * 118)
    all_tr = []
    for y in (2022, 2023, 2024, 2025):
        all_tr += simulate_hybrid(data[y], mode="hybrid")
    df = pd.DataFrame(all_tr)
    df["hold"] = (df.exit_time - df.entry_time).dt.total_seconds() / 60
    print(f"trades {len(df)} | closed by: ")
    print(df.exit_kind.value_counts().to_string())
    print(f"\nheld-over trades (M1 cross was ignored while in loss): "
          f"{int((df.exit_kind == '5m flip').sum())} closed by the 5m flip, "
          f"{int((df.exit_kind == 'open at end').sum())} still open at the end")
    print(f"average hold of trades closed by the 5m flip: "
          f"{df[df.exit_kind == '5m flip'].hold.mean():.0f} min "
          f"(median {df[df.exit_kind == '5m flip'].hold.median():.0f})")
    print(f"worst single trade ${df.pnl.min():.2f} | best ${df.pnl.max():.2f}")
    print(f"longest hold: {df.hold.max():.0f} min ({df.hold.max() / 60:.1f} hours)")

    # win rate of trades whose M1 cross was ignored (in loss at the cross, then held)
    ignored = df[df.exit_kind == "5m flip"]
    print(f"\ntrades closed by the 5m flip: {len(ignored)}, win rate "
          f"{(ignored.pnl > 0).mean() * 100:.1f}%, net ${ignored.pnl.sum():.2f}")

    # ---------- chart ----------
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [1.4, 1]})
    for label, col, ls in [("base (original exit)", "#888888", "-"),
                           ("hybrid: 5m flip closes all", "#1f77b4", "-"),
                           ("hybrid: 5m flip closes losers", "#2ca02c", "--"),
                           ("hybrid + hard stop 2.5 ATR", "#d62728", "-")]:
        kw = dict(variants[[v[0] for v in variants].index(label)][1])
        xs, ys, run = [], [], BAL0
        for y in (2022, 2023, 2024, 2025):
            tr = pd.DataFrame(simulate_hybrid(data[y], **kw))
            if len(tr) == 0:
                continue
            xs.extend(pd.to_datetime(tr.exit_time))
            ys.extend(run + np.cumsum(tr.pnl.values))
            run += tr.pnl.sum()
        axes[0].plot(xs, ys, lw=1.3, color=col, ls=ls,
                     label=f"{label}: total {run - BAL0:+.2f}")
    axes[0].axhline(BAL0, color="k", ls=":", lw=1)
    axes[0].set_ylabel("Equity ($)")
    axes[0].set_title("Holding losers until the 5m trend flips — 2022-2025 (0.01 lot, $0.20/trade)")
    axes[0].legend(fontsize=9)
    axes[0].grid(alpha=0.3)

    labels = [v[0] for v in variants]
    vals = [sum(yearly[l]) for l in labels]
    axes[1].barh(range(len(labels)), vals, color=["#089981" if v > 0 else "#f23645" for v in vals])
    axes[1].set_yticks(range(len(labels)))
    axes[1].set_yticklabels(labels, fontsize=8)
    axes[1].invert_yaxis()
    axes[1].axvline(0, color="k", lw=1)
    axes[1].set_xlabel("4-year net P/L ($)")
    axes[1].set_title("Exit variants over four years (no entry blockers)")
    axes[1].grid(alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig("results/hold_losers.png", dpi=120)
    print("\nSaved results/hold_losers.png")

    # ---------- report ----------
    L = ["# Hybrid exit: M1 cross closes only winners, losers are held for the 5m flip", "",
         "Rule as asked: a trade in PROFIT is closed by the M1 EMA 6/9 reverse cross; a trade "
         "in LOSS is not closed by that cross and is held until the 5m EMA 9/12 trend flips "
         "against the position. 0.01 lot, $0.20/trade.", "",
         "## Worst month (August 2023)", "",
         "| variant | trades | net $ | win% | PF | maxDD $ | avg hold (min) | worst trade $ |",
         "|---|---|---|---|---|---|---|---|"]
    month_rows = [("original", simulate_hybrid(data[2023], *BAD_MONTH, mode="base")),
                  ("hybrid (5m flip closes all)",
                   simulate_hybrid(data[2023], *BAD_MONTH, mode="hybrid")),
                  ("hybrid (5m flip closes losers only)",
                   simulate_hybrid(data[2023], *BAD_MONTH, mode="hybrid",
                                   five_min_closes_winners=False)),
                  ("hybrid + hard stop 2.5 ATR",
                   simulate_hybrid(data[2023], *BAD_MONTH, mode="hybrid", hard_stop_atr=2.5))]
    for label, trs in month_rows:
        s = stats(trs)
        L.append(f"| {label} | {s['n']} | ${s['net']:,.2f} | {s['wr']}% | {s['pf']} | "
                 f"${s['dd']:,.2f} | {s['hold']:.0f} | ${s['worst']:,.2f} |")
    L += ["", "## Four full years 2022-2025", "",
          "| variant | 2022 | 2023 | 2024 | 2025 | total | trades | win% | maxDD $ |",
          "|---|---|---|---|---|---|---|---|---|"]
    for label, _ in variants:
        v = yearly[label]
        trs = []
        for y in (2022, 2023, 2024, 2025):
            trs += simulate_hybrid(data[y], **dict(variants[[x[0] for x in variants].index(label)][1]))
        st = stats(trs)
        L.append(f"| {label} | " + " | ".join(f"${x:,.0f}" for x in v) +
                 f" | **${sum(v):,.0f}** | {st['n']} | {st['wr']}% | ${st['dd']:,.0f} |")
    L += ["", "With the entry blockers (09-13 UTC + EMA separation window) on:", "",
          "| variant | 2022 | 2023 | 2024 | 2025 | total |", "|---|---|---|---|---|---|"]
    for label, _ in variants:
        v = yearly_blocked[label]
        L.append(f"| {label} | " + " | ".join(f"${x:,.0f}" for x in v) + f" | **${sum(v):,.0f}** |")
    L += ["", "Charts: results/hold_losers.png", "",
          "Trades closed by the 5m flip: " +
          f"{(df.exit_kind == '5m flip').sum()} of {len(df)} over four years; "
          f"their win rate {(df[df.exit_kind == '5m flip'].pnl > 0).mean() * 100:.1f}%; "
          f"worst single trade ${df.pnl.min():,.2f}; longest hold {df.hold.max() / 60:.1f} hours."]
    with open("results/hold_losers_report.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("Saved results/hold_losers_report.md")
    return yearly, yearly_blocked, df


if __name__ == "__main__":
    main()
