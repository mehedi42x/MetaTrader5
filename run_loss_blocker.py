"""Loss-blocker system for the M1 EMA 6/9 + Bollinger system — built on the worst month.

Stage 1 (entry filter): a greedy search over interpretable context rules picks the small
set that best blocks losing trades in the worst month found by run_trade_forensics.py
(2023-08). Then that exact rule set is validated on 40+ other months (2022, 2023-2025,
and the real September 2026 window) — those months were NOT used for tuning.

Stage 2 (exit fix): the forensics showed the average loss is barely bigger than the
spread, so the exit (raw opposite EMA cross) is cutting trades before they can pay for
the cost. Several exit schemes are compared on the same data:
   cross              exit on the opposite cross (the original script)
   cross+minhold      the same, but not before N bars have passed
   sl/tp              ATR-based stop/target, plus the cross exit
   trail              ATR trailing stop, plus the cross exit
   tp/sl only         pure ATR bracket, no cross exit

Usage:  python3 run_loss_blocker.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_trade_forensics import (build, load_year, load_recent, simulate, to_df,
                                 stat_row, OZ, COST, BAL0)

BAD_MONTH = ("2023-08-01 00:00", "2023-08-31 23:59")
TUNED_TAG = "2023-08"


# ─────────────────────────── rule engine ───────────────────────────
def mask_from_rules(d, rules):
    ok = np.ones(len(d["close"]), bool)
    for fe, op, th in rules:
        v = d[fe]
        if op == ">=":
            ok &= v >= th
        elif op == "<=":
            ok &= v <= th
        elif op == "abs<=":
            ok &= np.abs(v) <= th
        elif op == "range":
            lo, hi = th
            ok &= (v >= lo) & (v <= hi)
        else:
            raise ValueError(op)
    return ok


CANDIDATES = [
    ("adx", ">=", 16.0), ("adx", ">=", 20.0), ("adx", ">=", 24.0),
    ("atrr", ">=", 0.95), ("atrr", ">=", 1.00), ("atrr", ">=", 1.05),
    ("atr_pct", ">=", 0.40), ("atr_pct", ">=", 0.60),
    ("bbpos_side", "<=", 0.85), ("bbpos_side", "<=", 0.75),
    ("sep", "range", (0.03, 0.08)),
    ("hour", "range", (7, 14)), ("hour", "range", (9, 13)),
    ("slope", ">=", -0.10),
    ("body", "<=", 1.20),
    ("runup_signed", "abs<=", 2.5),
    ("er", ">=", 0.05),
    ("rng20", "<=", 5.0),
    ("htfstr", "<=", 0.20), ("htfstr", "<=", 0.10),
    ("chop", "<=", 55.0),
    ("wick", "<=", 0.45),
]


def rules_label(rules):
    out = []
    for fe, op, th in rules:
        if op == "range":
            out.append(f"{fe} {th[0]:g}-{th[1]:g}")
        elif op == "abs<=":
            out.append(f"|{fe}|<={th:g}")
        else:
            out.append(f"{fe}{op}{th:g}")
    return " & ".join(out) if out else "(no filter)"


def greedy_select(base_df, d, max_rules=4, min_trades=80):
    """Forward selection maximising in-sample net P/L (tuned on the worst month only)."""
    chosen, remaining = [], list(CANDIDATES)
    best_net = float(base_df.pnl.sum())
    best_rules = []
    print(f"\nGREEDY RULE SEARCH (in-sample = {TUNED_TAG}, objective = net P/L, "
          f"min {min_trades} trades)")
    print(f"{'step':5s}{'rule added':26s}{'trades':>8s}{'net $':>10s}{'win%':>8s}{'action':>10s}")
    print(f"{0:<5d}{'(base)':26s}{len(base_df):>8d}{base_df.pnl.sum():>10.2f}"
          f"{(base_df.pnl > 0).mean() * 100:>7.1f}%")
    for step in range(max_rules):
        best_cand, best_net_c, best_wr = None, best_net, 0.0
        for cand in remaining:
            rs = chosen + [cand]
            m = mask_from_rules(d, rs)
            sel = base_df[[bool(m[int(s)]) for s in base_df.sig_i]]
            if len(sel) < min_trades:
                continue
            net = float(sel.pnl.sum())
            if net > best_net_c + 1e-9:
                best_cand, best_net_c, best_wr = cand, net, float((sel.pnl > 0).mean() * 100)
        if best_cand is None:
            print(f"{step + 1:<5d}{'-':26s}{'':>8s}{'':>10s}{'':>8s}{'stop (no gain)':>10s}")
            break
        chosen.append(best_cand)
        remaining.remove(best_cand)
        m = mask_from_rules(d, chosen)
        sel = base_df[[bool(m[int(s)]) for s in base_df.sig_i]]
        net = float(sel.pnl.sum())
        print(f"{step + 1:<5d}{rules_label([best_cand]):26s}{len(sel):>8d}{net:>10.2f}"
              f"{(sel.pnl > 0).mean() * 100:>7.1f}%{'added':>10s}")
        best_net = net
        best_rules = list(chosen)
    print(f"\nSELECTED RULES: {rules_label(best_rules)}")
    return best_rules


# ─────────────────────────── engine with exit variants ───────────────────────────
def simulate_exit(d, exit_mode, t0=None, t1=None, ok_mask=None,
                  sl_atr=1.0, tp_atr=2.0, trail_atr=1.0, min_hold=10):
    o, h, l, c, t = d["open"], d["high"], d["low"], d["close"], d["time"]
    atr = d["atr"]
    bull, bear = d["bull"], d["bear"]
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
    trail = np.nan
    for i in range(1, n):
        j = i - 1
        # ---- 1. intrabar stop / target while in a position
        if pos != 0 and exit_mode in ("sl/tp", "trail", "tp/sl only"):
            stop = tp = np.nan
            if exit_mode in ("sl/tp", "tp/sl only"):
                stop = entry - pos * sl_atr * atr[sig_i]
                tp = entry + pos * tp_atr * atr[sig_i]
            if exit_mode == "trail":
                trail = (max(trail, h[i]) if pos == 1 else min(trail, l[i])) if not np.isnan(trail) \
                    else (entry + pos * trail_atr * atr[sig_i] if pos == 1
                          else entry - pos * trail_atr * atr[sig_i])
                stop = trail + pos * -trail_atr * atr[sig_i]
            hit_stop = pos == 1 and l[i] <= stop if not np.isnan(stop) else False
            hit_tp = pos == 1 and h[i] >= tp if not np.isnan(tp) else False
            if pos == -1:
                hit_stop = h[i] >= stop if not np.isnan(stop) else False
                hit_tp = l[i] <= tp if not np.isnan(tp) else False
            if hit_stop:                       # stop checked first (conservative)
                px = stop
                trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                   entry_time=pd.Timestamp(t[entry_i]),
                                   exit_time=pd.Timestamp(t[i]), entry=float(entry),
                                   exit=float(px), pnl=float((px - entry) * pos * OZ - COST),
                                   exit_kind="SL"))
                pos = 0; continue
            if hit_tp:
                px = tp
                trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                   entry_time=pd.Timestamp(t[entry_i]),
                                   exit_time=pd.Timestamp(t[i]), entry=float(entry),
                                   exit=float(px), pnl=float((px - entry) * pos * OZ - COST),
                                   exit_kind="TP"))
                pos = 0; continue
        # ---- 2. cross exit decided by the previous close
        if pos != 0 and exit_mode != "tp/sl only":
            opp = (pos == 1 and bear[j]) or (pos == -1 and bull[j])
            if opp and (exit_mode != "cross+minhold" or (i - entry_i) >= min_hold):
                px = o[i]
                trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                   entry_time=pd.Timestamp(t[entry_i]),
                                   exit_time=pd.Timestamp(t[i]), entry=float(entry),
                                   exit=float(px), pnl=float((px - entry) * pos * OZ - COST),
                                   exit_kind="CROSS"))
                pos = 0
        # ---- 3. entries
        if pos == 0:
            if buy[j] and win[j]:
                pos, entry, entry_i, sig_i = 1, o[i], i, j
                trail = np.nan
            elif sell[j] and win[j]:
                pos, entry, entry_i, sig_i = -1, o[i], i, j
                trail = np.nan
    if pos != 0:
        px = c[n - 1]
        trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=n - 1,
                           entry_time=pd.Timestamp(t[entry_i]), exit_time=pd.Timestamp(t[n - 1]),
                           entry=float(entry), exit=float(px),
                           pnl=float((px - entry) * pos * OZ - COST), exit_kind="END"))
    for tr in trades:
        i = tr["sig_i"]
        for fe in ("adx", "chop", "er", "atrr", "bbw", "sep", "bbpos_side", "runup_signed",
                   "slope", "rng20", "htfstr", "body", "atr_pct", "hour"):
            tr[fe] = float(d[fe][i])
    return trades


def pr(label, trades, width=34):
    r = stat_row(trades, label)
    print(f"{label:{width}s}{r['n']:>8d}{r['net']:>11.2f}{r['wr']:>7.1f}%{r['pf']:>7.2f}{r['per']:>11.3f}")
    return r


def main():
    print("loading 2022-2025 ...", flush=True)
    data = {y: build(load_year(y)) for y in (2022, 2023, 2024, 2025)}
    d26 = build(load_recent())

    # ---------------- stage 1: entry blockers ----------------
    base = to_df(simulate(data[2023], *BAD_MONTH))
    rules = greedy_select(base, data[2023])
    mask = mask_from_rules(data[2023], rules)

    print("\n" + "=" * 100)
    print(f"STAGE 1 — entry blockers on {TUNED_TAG} (in-sample)")
    print("=" * 100)
    print(f"{'variant':34s}{'trades':>8s}{'net $':>11s}{'win%':>8s}{'PF':>7s}{'avg/trade':>11s}")
    all_recs = base.to_dict("records")
    kept = [t for t in all_recs if mask[int(t["sig_i"])]]
    blocked = [t for t in all_recs if not mask[int(t["sig_i"])]]
    pr("base (every signal)", all_recs)
    pr("with entry blockers", kept)
    pr("blocked trades (what we skipped)", blocked)

    print("\n" + "=" * 100)
    print("VALIDATION — same rules, months NOT used for tuning")
    print("=" * 100)
    print(f"{'window':34s}{'trades':>8s}{'net $':>11s}{'win%':>8s}{'PF':>7s}{'avg/trade':>11s}")
    rows = []
    tot_b = tot_f = 0.0
    for y in (2022, 2023, 2024, 2025):
        m = mask_from_rules(data[y], rules)
        trs = simulate_exit(data[y], "cross", ok_mask=m)
        r = pr(f"{y} full year (blockers)", trs)
        rb = stat_row(simulate_exit(data[y], "cross"), f"{y}")
        tot_b += rb["net"]; tot_f += r["net"]
        rows.append((y, rb, r))
    m26 = mask_from_rules(d26, rules)
    r26 = pr("Sep 2026 (real MT5)", simulate_exit(d26, "cross", ok_mask=m26))
    rb26 = stat_row(simulate_exit(d26, "cross"), "Sep 2026")
    print(f"\n4-year total: base ${tot_b:,.2f} -> with entry blockers ${tot_f:,.2f} "
          f"(change {tot_f - tot_b:+,.2f})")

    # ---------------- stage 2: exit fix ----------------
    print("\n" + "=" * 100)
    print("STAGE 2 — the exit is what makes the losses: compare exit schemes")
    print("=" * 100)
    print(f"{'exit scheme':34s}{'trades':>8s}{'net $':>11s}{'win%':>8s}{'PF':>7s}{'avg/trade':>11s}")
    exits = [("cross (original)", dict(exit_mode="cross")),
             ("cross + min hold 10 bars", dict(exit_mode="cross+minhold", min_hold=10)),
             ("cross + min hold 20 bars", dict(exit_mode="cross+minhold", min_hold=20)),
             ("SL 1.0 / TP 2.0 ATR + cross", dict(exit_mode="sl/tp", sl_atr=1.0, tp_atr=2.0)),
             ("SL 1.5 / TP 3.0 ATR + cross", dict(exit_mode="sl/tp", sl_atr=1.5, tp_atr=3.0)),
             ("trail 1.0 ATR + cross", dict(exit_mode="trail", trail_atr=1.0)),
             ("trail 1.5 ATR + cross", dict(exit_mode="trail", trail_atr=1.5)),
             ("TP/SL 2/1 ATR only", dict(exit_mode="tp/sl only", sl_atr=1.0, tp_atr=2.0))]
    month_res = {}
    for label, kw in exits:
        trs = simulate_exit(data[2023], t0=BAD_MONTH[0], t1=BAD_MONTH[1], **kw)
        month_res[label] = pr(f"{label} [{TUNED_TAG}]", trs)
    best_exit = max(month_res, key=lambda k: month_res[k]["net"])
    print(f"\nbest exit scheme on the worst month: {best_exit} "
          f"({month_res[best_exit]['net']:+.2f})")

    print(f"\nThe same exit schemes over the full years (with the entry blockers ON):")
    print(f"{'exit scheme':34s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'total':>11s}")
    exit_totals = {}
    for label, kw in exits:
        vals = []
        for y in (2022, 2023, 2024, 2025):
            m = mask_from_rules(data[y], rules)
            trs = simulate_exit(data[y], ok_mask=m, **kw)
            vals.append(stat_row(trs, label)["net"])
        exit_totals[label] = vals
        print(f"{label:34s}" + "".join(f"{v:>10.2f}" for v in vals) + f"{sum(vals):>11.2f}")

    # best combination overall
    best_total = max(exit_totals, key=lambda k: sum(exit_totals[k]))
    print(f"\n>>> BEST COMBINATION (entry blockers + exit): {best_total} -> "
          f"${sum(exit_totals[best_total]):,.2f} over 4 years")

    # ---------------- chart ----------------
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.2, 1])
    ax = fig.add_subplot(gs[0, :])
    for y, col in [(2022, "#9467bd"), (2023, "#1f77b4"), (2024, "#d62728"), (2025, "#2ca02c")]:
        m = mask_from_rules(data[y], rules)
        trs = pd.DataFrame(simulate_exit(data[y], "cross"))
        f = trs[[bool(m[int(s)]) for s in trs.sig_i]]
        ax.plot(trs.exit_time, BAL0 + trs.pnl.cumsum(), lw=1.0, color=col, alpha=0.45,
                label=f"{y} base {trs.pnl.sum():+.0f}")
        ax.plot(f.exit_time, BAL0 + f.pnl.cumsum(), lw=1.5, color=col,
                label=f"{y} blocked {f.pnl.sum():+.0f}")
    ax.axhline(BAL0, color="k", ls=":", lw=1)
    ax.set_ylabel("Equity ($)")
    ax.set_title("Entry blockers (thin = base, thick = filtered) — 2022-2025")
    ax.legend(fontsize=7.5, ncol=4)
    ax.grid(alpha=0.3)

    ax2 = fig.add_subplot(gs[1, 0])
    labels = list(month_res.keys())
    vals = [month_res[k]["net"] for k in labels]
    ax2.barh(range(len(labels)), vals, color=["#089981" if v > 0 else "#f23645" for v in vals])
    ax2.set_yticks(range(len(labels)))
    ax2.set_yticklabels(labels, fontsize=8)
    ax2.invert_yaxis()
    ax2.axvline(0, color="k", lw=1)
    ax2.set_title(f"Exit schemes on {TUNED_TAG} ($)")
    ax2.grid(alpha=0.3, axis="x")

    ax3 = fig.add_subplot(gs[1, 1])
    for (fe, col) in [("adx", "#1f77b4"), ("atrr", "#2ca02c"), ("atr_pct", "#ff7f0e"),
                      ("bbpos_side", "#d62728")]:
        q = pd.qcut(base[fe].rank(method="first"), 6, duplicates="drop")
        g = base.groupby(q, observed=True).apply(
            lambda x: (x.pnl > 0).mean() * 100, include_groups=False)
        ax3.plot([iv.mid for iv in g.index], g.values, "o-", color=col, label=fe)
    ax3.axhline(38, color="k", ls="--", lw=1)
    ax3.text(0.02, 39, "38% = break-even at the 1.6 reward/risk seen", fontsize=7)
    ax3.set_title(f"Win rate by feature bucket ({TUNED_TAG})")
    ax3.set_ylabel("win rate (%)")
    ax3.legend(fontsize=8)
    ax3.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("results/loss_blocker.png", dpi=120)
    print("\nSaved results/loss_blocker.png")

    # ---------------- report ----------------
    L = ["# Loss-blocker system for the M1 EMA 6/9 + BB strategy", "",
         f"Tuned on the worst month in 2023-2025 = **{TUNED_TAG}** (-$361.81 with 1,200 trades, "
         "18.2% win rate). The rules below were selected on that month only, then validated on "
         "40 other months.", "",
         f"**Selected rules:** `{rules_label(rules)}`", "",
         "## Stage 1 — entry blockers (in-sample + validation)", "",
         "| window | base net $ | blocked net $ | change |",
         "|---|---|---|---|"]
    for y, rb, r in rows:
        L.append(f"| {y} | ${rb['net']:,.2f} | ${r['net']:,.2f} | {r['net'] - rb['net']:+,.2f} |")
    L += ["", "## Stage 2 — exit schemes", "",
          "| exit | 2022 | 2023 | 2024 | 2025 | total |", "|---|---|---|---|---|---|"]
    for label, _ in exits:
        v = exit_totals[label]
        L.append(f"| {label} | " + " | ".join(f"${x:,.0f}" for x in v) + f" | **${sum(v):,.0f}** |")
    L += ["", f"Best combination: **{best_total}** (${sum(exit_totals[best_total]):,.2f} over 4 years).",
          "", "Charts: results/loss_blocker.png | trades: results/forensics_trades_2023-08.csv"]
    with open("results/loss_blocker_report.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("Saved results/loss_blocker_report.md")


if __name__ == "__main__":
    main()
