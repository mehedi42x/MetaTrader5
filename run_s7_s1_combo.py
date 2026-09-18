"""Combine S7 (order-block retest) with the S1 M5 swing trend as a filter.

Idea: only take an order-block retest when it agrees with the M5 swing structure
(S1). The M5 structure is mapped onto the M1 bars without lookahead (a bar's
direction is only known after that bar has closed).

Variants on the same full-year 2022 M1 data (0.01 lot, $0.20/trade):
  A S7 alone                     - baseline
  B S7 + M5 align at break       - M5 bias must agree with the break direction
  C S7 + M5 align at fill        - M5 bias re-checked when the limit fills
  D B S7 break + M5 align        - same as B but timed on M5 bars
  E S7 + M5 align, both TFs give an OB - block from the M1 50-swing structure, but the
                                   break must also be a M5 50-swing break
  F S7 + M15 align at fill
  G S1 M5 + M1 OB confluence     - enter only when an M1 order block sits inside the M5
                                   structure break direction
  H S7 + session/volatility tilt - OB retests only while the M5 bias is fresh
                                   (<= 50 M5 bars since the M5 structure flip)

Usage:  python3 run_s7_s1_combo.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import run_smc_backtest as SMC
from src.smc import compute_structure, order_blocks

DATA = "data/xauusd_m1_2022.csv"
BALANCE0 = 10_000.0
PERIODS = [
    ("Full year 2022", "2022-01-01", "2022-12-31"),
    ("H1 2022 (dev)", "2022-01-01", "2022-06-30 23:59"),
    ("H2 2022 (out-of-sample)", "2022-07-01", "2022-12-31"),
]


def map_bias_to_m1(m1, htf_df, htf_structure, minutes):
    """HTF swing bias (+1/-1) known at each M1 bar, no lookahead."""
    known_at = pd.to_datetime(htf_df["time"]) + pd.Timedelta(minutes=minutes)
    bias = pd.DataFrame({"known_at": known_at, "bias": htf_structure["bias"]}).sort_values("known_at")
    out = pd.merge_asof(pd.DataFrame({"time": pd.to_datetime(m1["time"])}).sort_values("time"),
                        bias, left_on="time", right_on="known_at", direction="backward")
    return out["bias"].fillna(0).to_numpy(dtype=int)


def map_break_flags_to_m1(m1, htf_df, htf_structure, minutes, direction):
    """+1 where an HTF break of `direction` became known, else 0 -> forward-fill state."""
    mask = htf_structure["event"] == direction
    known_at = (pd.to_datetime(htf_df.loc[mask, "time"]) + pd.Timedelta(minutes=minutes)).to_numpy()
    t = pd.to_datetime(m1["time"]).to_numpy()
    idx = np.searchsorted(t, known_at, side="left")
    flag = np.zeros(len(t), dtype=int)
    flag[idx[idx < len(t)]] = 1
    return flag


def bt_s7_filtered(df, t0, t1, swing, obs, ml_bias=None, ml_break_bull=None,
                   ml_break_bear=None, fill_check=None, fresh_limit=None,
                   balance0=BALANCE0):
    """bt_ob_retest with optional higher-timeframe agreement gates.

    ml_bias      : array aligned to df, HTF bias (+1/-1) known at that bar
    ml_break_*   : arrays, 1 on bars where an HTF break became known (state resets on flip)
    fill_check   : array, HTF bias re-checked at the moment the limit fills
    fresh_limit  : array of bar indices of HTF flips (bias allowed to be stale otherwise)
    """
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    t = pd.to_datetime(df["time"]).to_numpy()
    start = np.searchsorted(t, np.datetime64(pd.to_datetime(t0)))
    end = np.searchsorted(t, np.datetime64(pd.to_datetime(t1)), side="right")

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

    ev = swing["event"]
    bal = balance0
    trades, eq_ts, eq_val = [], [], []
    pos = None
    pending_bull = pending_bear = False
    # M5 break state: which side the last M5 break pointed to
    m5_state = None
    if ml_break_bull is not None:
        m5_state = np.zeros(len(df), dtype=int)
        state = 0
        for i in range(len(df)):
            if ml_break_bull[i]:
                state = 1
            elif ml_break_bear[i]:
                state = -1
            m5_state[i] = state

    n_blocked = 0

    def close(price, when, idx, reason):
        nonlocal bal, pos
        pnl = (price - pos["entry"]) * pos["dir"] * SMC.OZ - SMC.COST
        bal += pnl
        trades.append(dict(entry_time=pos["t"], exit_time=when,
                           direction="LONG" if pos["dir"] == 1 else "SHORT",
                           entry=round(pos["entry"], 2), exit=round(price, 2),
                           sl=float("nan"), tp=float("nan"), lot=SMC.FIXED_LOT,
                           pnl=round(pnl, 2), r_multiple=0.0,
                           bars_held=int(idx - pos["idx"]), exit_reason=reason))
        pos = None

    for i in range(1, min(len(df), end)):
        if i >= start:
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

            if pos is None:
                if pending_bull and not np.isnan(ob_bull[i - 1]):
                    if l[i] <= ob_bull[i - 1]:
                        ok = True
                        if fill_check is not None and fill_check[i - 1] != 1:
                            ok = False
                        if fresh_limit is not None and i - fresh_limit[0][i] > 50:
                            ok = False
                        if ok:
                            pos = dict(dir=1, entry=min(o[i], ob_bull[i - 1]), t=t[i], idx=i)
                            pending_bull = False
                        else:
                            n_blocked += 1
                            pending_bull = False
                    elif c[i - 1] < ob_bull_bot[i - 1]:
                        pending_bull = False
                elif pending_bear and not np.isnan(ob_bear[i - 1]):
                    if h[i] >= ob_bear[i - 1]:
                        ok = True
                        if fill_check is not None and fill_check[i - 1] != -1:
                            ok = False
                        if fresh_limit is not None and i - fresh_limit[1][i] > 50:
                            ok = False
                        if ok:
                            pos = dict(dir=-1, entry=max(o[i], ob_bear[i - 1]), t=t[i], idx=i)
                            pending_bear = False
                        else:
                            n_blocked += 1
                            pending_bear = False
                    elif c[i - 1] > ob_bear_top[i - 1]:
                        pending_bear = False
                if pos is None:
                    if ev[i - 1] == 1:
                        if ml_bias is not None and ml_bias[i - 1] != 1:
                            n_blocked += 1
                        elif m5_state is not None and m5_state[i - 1] != 1:
                            n_blocked += 1
                        else:
                            pending_bull, pending_bear = True, False
                    elif ev[i - 1] == -1:
                        if ml_bias is not None and ml_bias[i - 1] != -1:
                            n_blocked += 1
                        elif m5_state is not None and m5_state[i - 1] != -1:
                            n_blocked += 1
                        else:
                            pending_bear, pending_bull = True, False
        eq_ts.append(t[i])
        eq_val.append(bal)

    last = min(len(df), end) - 1
    if pos is not None:
        close(float(c[last]), t[last], last, "END")
    tr = pd.DataFrame(trades)
    eq = pd.DataFrame({"time": pd.to_datetime(eq_ts), "equity": eq_val})
    eq = eq[eq.time >= pd.to_datetime(t0)].reset_index(drop=True)
    st = SMC.compute_stats(tr, eq, balance0) if len(tr) else dict(
        n_trades=0, net_pnl=0.0, return_pct=0.0, profit_factor=0.0, win_rate=0.0,
        max_dd_usd=0.0, max_dd_pct=0.0, expectancy=0.0)
    st["costs"] = round(st.get("n_trades", 0) * SMC.COST, 2)
    st["blocked"] = n_blocked
    return tr, eq, st


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    print(f"{len(m1)} M1 bars ({m1.time.min().date()} -> {m1.time.max().date()}) | "
          f"0.01 lot | ${SMC.COST:.2f}/trade\n")

    m1_swing = compute_structure(m1, 50)
    m1_obs = order_blocks(m1, m1_swing)
    m5 = SMC.resample_ohlc(m1, 5)
    m5_swing = compute_structure(m5, 50)
    m15 = SMC.resample_ohlc(m1, 15)
    m15_swing = compute_structure(m15, 50)

    bias5 = map_bias_to_m1(m1, m5, m5_swing, 5)
    bias15 = map_bias_to_m1(m1, m15, m15_swing, 15)
    bull5 = map_break_flags_to_m1(m1, m5, m5_swing, 5, +1)
    bear5 = map_break_flags_to_m1(m1, m5, m5_swing, 5, -1)

    # bar index of the most recent M5 bias flip (for variant H)
    flips5 = np.where(np.diff(bias5, prepend=0) != 0)[0]
    last_flip_bull = np.zeros(len(m1), dtype=int)
    last_flip_bear = np.zeros(len(m1), dtype=int)
    cur_b = cur_s = -10 ** 9
    for i in range(len(m1)):
        if bias5[i] == 1 and (i == 0 or bias5[i - 1] != 1):
            cur_b = i
        elif bias5[i] == -1 and (i == 0 or bias5[i - 1] != -1):
            cur_s = i
        last_flip_bull[i] = cur_b
        last_flip_bear[i] = cur_s
    fresh = (last_flip_bull, last_flip_bear)

    # split the order blocks by the kind of break that created them
    ev = m1_swing["event"]
    def ob_break_tag(ob):
        seg = np.where(ev[ob["index"]:] != 0)[0]
        if len(seg) == 0:
            return None
        k = ob["index"] + seg[0]
        return m1_swing["tag"][k] if ev[k] == ob["bias"] else None
    tags = [ob_break_tag(o) for o in m1_obs]
    obs_choch = [o for o, t in zip(m1_obs, tags) if t == "CHoCH"]
    print(f"order blocks: {len(m1_obs)} total, {len(obs_choch)} created by a CHoCH")

    variants = {
        "A S7 alone (baseline)": (m1_obs, dict()),
        "B S7 + M5 align at break": (m1_obs, dict(ml_bias=bias5)),
        "C S7 + M5 align at fill": (m1_obs, dict(fill_check=bias5)),
        "D S7 + M5 break state": (m1_obs, dict(ml_break_bull=bull5, ml_break_bear=bear5)),
        "E S7 + M15 align at fill": (m1_obs, dict(fill_check=bias15)),
        "F S7 from CHoCH blocks only": (obs_choch, dict()),
        "G CHoCH blocks + M5 fill": (obs_choch, dict(fill_check=bias5)),
        "H S7 + fresh M5 bias (<=50 bars)": (m1_obs, dict(fill_check=bias5, fresh_limit=fresh)),
    }

    results, curves = {}, {}
    for label, t0, t1 in PERIODS:
        for name, (obs_used, kw) in variants.items():
            tr, eq, st = bt_s7_filtered(m1, t0, t1, m1_swing, obs_used, **kw)
            results[(name, label)] = (st, tr)
            if label == PERIODS[0][0]:
                curves[name] = eq
    print()

    print("=" * 112)
    print("S7 order-block retest + S1 (M5 swing trend) filters — 2022 full year, 0.01 lot")
    print("=" * 112)
    print(f"{'variant':34s} {'Year P/L':>10s} {'trd':>6s} {'win%':>6s} {'PF':>6s} "
          f"{'DD $':>9s} {'H1':>9s} {'H2':>9s} {'blocked':>8s}")
    for name in variants:
        st = results[(name, PERIODS[0][0])][0]
        h1 = results[(name, PERIODS[1][0])][0]["net_pnl"]
        h2 = results[(name, PERIODS[2][0])][0]["net_pnl"]
        print(f"{name:34s} {st['net_pnl']:>10.2f} {st['n_trades']:>6d} {st['win_rate']:>5.1f}% "
              f"{st['profit_factor']:>6} {st['max_dd_usd']:>9.2f} {h1:>9.2f} {h2:>9.2f} "
              f"{st['blocked']:>8d}")
    print()

    base_st = results[("A S7 alone (baseline)", PERIODS[0][0])][0]
    base = base_st["net_pnl"]
    best = max(variants, key=lambda n: results[(n, PERIODS[0][0])][0]["net_pnl"])
    best_pnl = results[(best, PERIODS[0][0])][0]["net_pnl"]
    print(f">>> baseline S7 = ${base:.2f} | best variant = {best} (${best_pnl:.2f}, "
          f"{'IMPROVED' if best_pnl > base else 'no improvement'} by ${best_pnl - base:.2f})")
    print("\nPer-trade quality (year):")
    for name in variants:
        st = results[(name, PERIODS[0][0])][0]
        if not st["n_trades"]:
            continue
        print(f"  {name:34s} exp/trade ${st['expectancy']:>6.3f} | PF {st['profit_factor']:>4} "
              f"| DD ${st['max_dd_usd']:>7.2f} | P/L per DD {st['net_pnl'] / abs(st['max_dd_usd'] or 1):>6.2f}")

    # monthly for baseline and the best (if different)
    months = pd.date_range("2022-01-01", "2022-12-01", freq="MS")
    show = ["A S7 alone (baseline)"]
    for cand in ("C S7 + M5 align at fill", best):
        if cand not in show:
            show.append(cand)
    print("\nMonth-by-month (baseline vs best):")
    header = "month    " + "".join(f"{n.split()[0] + ' ' + n.split()[1]:>16s}" for n in show)
    print(header)
    monthly = {}
    for n in show:
        vals = []
        _, kw = variants[n]
        for m0 in months:
            m1t = m0 + pd.offsets.MonthEnd(0)
            tr, eq, st = bt_s7_filtered(m1, m0, m1t, m1_swing, m1_obs, **kw)
            vals.append(st["net_pnl"])
        monthly[n] = vals
    for k, m0 in enumerate(months):
        print(f"{m0.strftime('%b %Y'):9s}" + "".join(f"{monthly[n][k]:>16.2f}" for n in show))
    print(f"{'TOTAL':9s}" + "".join(f"{sum(monthly[n]):>16.2f}" for n in show))

    # charts
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9),
                                   gridspec_kw={"height_ratios": [2.2, 1]})
    colors = ["#1f77b4", "#2ca02c", "#d62728", "#ff7f0e", "#9467bd", "#8c564b"]
    for name, c in zip(variants, colors):
        eq = curves[name]
        st = results[(name, PERIODS[0][0])][0]
        ax1.plot(pd.to_datetime(eq["time"]), eq["equity"], color=c, lw=1.4,
                 label=f"{name}: {st['return_pct']:+.2f}% ({st['n_trades']} trd, PF {st['profit_factor']})")
    ax1.axhline(BALANCE0, color="k", ls=":", lw=1)
    ax1.set_ylabel("Equity ($)")
    ax1.set_title("XAUUSD 2022 — S7 order-block retest with / without the M5 swing-trend filter "
                  "(0.01 lot, $0.20/trade)", fontsize=12)
    ax1.legend(fontsize=8.5, loc="upper left")
    ax1.grid(alpha=0.3)
    x = np.arange(len(months))
    width = 0.35
    for k, (name, c) in enumerate(zip(show, ["#1f77b4", "#2ca02c"])):
        ax2.bar(x + (k - 0.5) * width, monthly[name], width, color=c, label=name)
    ax2.axhline(0, color="k", lw=1)
    ax2.set_ylabel("Monthly P/L ($)")
    ax2.set_xticks(x)
    ax2.set_xticklabels([m.strftime("%b") for m in months])
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig("results/s7_s1_combo.png", dpi=120)
    plt.close(fig)
    print("\nSaved results/s7_s1_combo.png")

    # report
    lines = ["# S7 + S1 (M5 trend) combination test — XAUUSD 2022", "",
             "Data: data/xauusd_m1_2022.csv (354,628 M1 bars). 0.01 lot, spread 20 pts "
             "= $0.20 per round trip. M5 structure mapped to M1 with no lookahead "
             "(a 5-minute bar's bias is known only at its close).", "",
             "| variant | year P/L | trades | win% | PF | max DD $ | H1 | H2 | signals blocked |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name in variants:
        st = results[(name, PERIODS[0][0])][0]
        h1 = results[(name, PERIODS[1][0])][0]["net_pnl"]
        h2 = results[(name, PERIODS[2][0])][0]["net_pnl"]
        lines.append(f"| {name} | ${st['net_pnl']:,.2f} | {st['n_trades']} | {st['win_rate']}% "
                     f"| {st['profit_factor']} | ${st['max_dd_usd']:,.2f} | ${h1:,.2f} "
                     f"| ${h2:,.2f} | {st['blocked']} |")
    lines += ["", f"Baseline S7: ${base:,.2f}. Best variant: {best} -> ${best_pnl:,.2f} "
                  f"({best_pnl - base:+,.2f}).", "",
              "Chart: results/s7_s1_combo.png"]
    with open("results/s7_s1_report.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("Saved results/s7_s1_report.md")


if __name__ == "__main__":
    main()
