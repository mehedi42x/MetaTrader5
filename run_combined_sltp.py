"""S7 + S1 — what changing SL / TP does (so the TradingView defaults are tested).

S7 (chart TF = M1): order-block retest. Entry = limit at the block's near side after
a structure break; exits = structure flip, or the block failing.
S1 (M5): swing structure flip, always in market (opposite break reverses).

This script adds optional hard SL/TP to both legs and measures each variant on the
2022 data, so the Pine script's default settings are the tested ones and the user can
see the cost of using tight stops/targets.

Usage:  python3 run_combined_sltp.py
"""
import numpy as np
import pandas as pd

import run_smc_backtest as SMC
from src.smc import compute_structure, order_blocks
from src.indicators import atr_wilder

OZ = SMC.OZ
COST = SMC.COST
BAL0 = 10_000.0
DATA = "data/xauusd_m1_2022.csv"
T0, T1 = "2022-01-01", "2022-12-31 23:59"
SWING = 50


# ----------------------------------------------------------------- S7 engine --
def bt_s7(df, structure, obs, atr, sl_mode="close", sl_mult=2.0,
          tp_mode="none", tp_mult=2.0, balance0=BAL0):
    """S7 with optional hard stop / target.

    sl_mode: 'close' (faithful OB-fail exit at next open) | 'wick' (stop at block far
             side, filled intrabar) | 'atr' (hard stop at entry -/+ sl_mult*ATR)
    tp_mode: 'none' | 'r' (tp_mult x the block width) | 'atr' (tp_mult x ATR)
    """
    o = df["open"].to_numpy(float); c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
    t = pd.to_datetime(df["time"]).to_numpy()
    ev = structure["event"]

    ob_bull = np.full(len(df), np.nan); ob_bull_bot = np.full(len(df), np.nan)
    ob_bear = np.full(len(df), np.nan); ob_bear_top = np.full(len(df), np.nan)
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

    bal = balance0
    trades, eq_val = [], []
    pos = None
    pend_bull = pend_bear = False

    def cl(price, when, idx, reason):
        nonlocal bal, pos
        pnl = (price - pos["entry"]) * pos["dir"] * OZ - COST
        bal += pnl
        trades.append(dict(entry_time=pos["t"], exit_time=when,
                           direction="LONG" if pos["dir"] == 1 else "SHORT",
                           entry=round(pos["entry"], 2), exit=round(price, 2),
                           pnl=round(pnl, 2), exit_reason=reason,
                           bars_held=int(idx - pos["idx"])))
        pos = None

    for i in range(1, len(df)):
        # ---- exits signalled by the previous close, filled at this open
        if pos is not None and pos["dir"] == 1:
            if ev[i - 1] == -1:
                cl(o[i], t[i], i, "FLIP")
            elif (sl_mode == "close" and not np.isnan(ob_bull_bot[i - 1])
                  and c[i - 1] < ob_bull_bot[i - 1] and pos["idx"] < i - 1):
                cl(o[i], t[i], i, "OB_FAIL")
        elif pos is not None and pos["dir"] == -1:
            if ev[i - 1] == 1:
                cl(o[i], t[i], i, "FLIP")
            elif (sl_mode == "close" and not np.isnan(ob_bear_top[i - 1])
                  and c[i - 1] > ob_bear_top[i - 1] and pos["idx"] < i - 1):
                cl(o[i], t[i], i, "OB_FAIL")

        # ---- entries (pending limit at the latest block)
        if pos is None:
            if pend_bull and not np.isnan(ob_bull[i - 1]):
                if l[i] <= ob_bull[i - 1]:
                    entry = min(o[i], ob_bull[i - 1])
                    d = 1
                    slv = ob_bull_bot[i - 1]
                    if sl_mode == "atr":
                        slv = entry - sl_mult * atr[i - 1]
                    tpv = np.nan
                    if tp_mode == "r" and not np.isnan(slv):
                        tpv = entry + tp_mult * (entry - slv)
                    elif tp_mode == "atr":
                        tpv = entry + tp_mult * atr[i - 1]
                    pos = dict(dir=1, entry=entry, t=t[i], idx=i, sl=slv, tp=tpv)
                    pend_bull = False
                elif c[i - 1] < ob_bull_bot[i - 1]:
                    pend_bull = False
            elif pend_bear and not np.isnan(ob_bear[i - 1]):
                if h[i] >= ob_bear[i - 1]:
                    entry = max(o[i], ob_bear[i - 1])
                    slv = ob_bear_top[i - 1]
                    if sl_mode == "atr":
                        slv = entry + sl_mult * atr[i - 1]
                    tpv = np.nan
                    if tp_mode == "r" and not np.isnan(slv):
                        tpv = entry - tp_mult * (slv - entry)
                    elif tp_mode == "atr":
                        tpv = entry - tp_mult * atr[i - 1]
                    pos = dict(dir=-1, entry=entry, t=t[i], idx=i, sl=slv, tp=tpv)
                    pend_bear = False
                elif c[i - 1] > ob_bear_top[i - 1]:
                    pend_bear = False
            if pos is None:
                if ev[i - 1] == 1:
                    pend_bull, pend_bear = True, False
                elif ev[i - 1] == -1:
                    pend_bear, pend_bull = True, False

        # ---- hard stop / target inside this bar (entry bar excluded: the limit fill
        #      and the bar's extreme are ambiguous to order)
        if pos is not None and pos["idx"] < i:
            if pos["dir"] == 1:
                if sl_mode in ("wick", "atr") and not np.isnan(pos["sl"]) and l[i] <= pos["sl"]:
                    cl(min(o[i], pos["sl"]), t[i], i, "SL")
                elif not np.isnan(pos["tp"]) and h[i] >= pos["tp"]:
                    cl(max(o[i], pos["tp"]), t[i], i, "TP")
            else:
                if sl_mode in ("wick", "atr") and not np.isnan(pos["sl"]) and h[i] >= pos["sl"]:
                    cl(max(o[i], pos["sl"]), t[i], i, "SL")
                elif not np.isnan(pos["tp"]) and l[i] <= pos["tp"]:
                    cl(min(o[i], pos["tp"]), t[i], i, "TP")
        eq_val.append(bal)

    if pos is not None:
        cl(c[-1], t[-1], len(df) - 1, "END")
    return _stats(trades, eq_val, balance0)


# ----------------------------------------------------------------- S1 engine --
def bt_s1(df, structure, atr, sl_mode="none", sl_mult=2.0,
          tp_mode="none", tp_mult=4.0, balance0=BAL0):
    """S1 swing-flip, optionally with an ATR stop / target."""
    o = df["open"].to_numpy(float); c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
    t = pd.to_datetime(df["time"]).to_numpy()
    le = structure["event"] == 1
    se = structure["event"] == -1
    bal = balance0
    trades, eq_val = [], []
    pos = None

    def cl(price, when, idx, reason):
        nonlocal bal, pos
        pnl = (price - pos["entry"]) * pos["dir"] * OZ - COST
        bal += pnl
        trades.append(dict(entry_time=pos["t"], exit_time=when,
                           direction="LONG" if pos["dir"] == 1 else "SHORT",
                           entry=round(pos["entry"], 2), exit=round(price, 2),
                           pnl=round(pnl, 2), exit_reason=reason,
                           bars_held=int(idx - pos["idx"])))
        pos = None

    for i in range(1, len(df)):
        j = i - 1
        if pos is not None:
            if pos["dir"] == 1 and se[j]:
                cl(o[i], t[i], i, "FLIP")
            elif pos["dir"] == -1 and le[j]:
                cl(o[i], t[i], i, "FLIP")
        if pos is None and (le[j] or se[j]):
            d = 1 if le[j] else -1
            entry = o[i]
            av = atr[j]
            slv = entry - d * sl_mult * av if sl_mode == "atr" else np.nan
            tpv = np.nan
            if tp_mode == "atr":
                tpv = entry + d * tp_mult * av
            elif tp_mode == "r" and not np.isnan(slv):
                tpv = entry + d * tp_mult * abs(entry - slv)
            pos = dict(dir=d, entry=entry, t=t[i], idx=i, sl=slv, tp=tpv)
        if pos is not None:
            if pos["dir"] == 1:
                if not np.isnan(pos["sl"]) and l[i] <= pos["sl"]:
                    cl(min(o[i], pos["sl"]), t[i], i, "SL")
                elif not np.isnan(pos["tp"]) and h[i] >= pos["tp"]:
                    cl(max(o[i], pos["tp"]), t[i], i, "TP")
            else:
                if not np.isnan(pos["sl"]) and h[i] >= pos["sl"]:
                    cl(max(o[i], pos["sl"]), t[i], i, "SL")
                elif not np.isnan(pos["tp"]) and l[i] <= pos["tp"]:
                    cl(min(o[i], pos["tp"]), t[i], i, "TP")
        eq_val.append(bal)

    if pos is not None:
        cl(c[-1], t[-1], len(df) - 1, "END")
    return _stats(trades, eq_val, balance0)


def _stats(trades, eq_val, balance0):
    eq = balance0 + np.array(eq_val)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    tr = pd.DataFrame(trades)
    if len(tr) == 0:
        return dict(n=0, net=0.0, pf=0.0, win=0.0, dd=0.0, reasons={}, trades=tr)
    wins = tr[tr.pnl > 0]
    losses = tr[tr.pnl <= 0]
    gl = -losses.pnl.sum()
    return dict(n=len(tr), net=round(float(tr.pnl.sum()), 2),
                pf=round(float(wins.pnl.sum() / gl), 2) if gl > 0 else float("inf"),
                win=round(len(wins) / len(tr) * 100, 1),
                dd=round(float(dd.min()), 2),
                reasons=tr.exit_reason.value_counts().to_dict(), trades=tr)


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    df5 = SMC.resample_ohlc(m1, 5)
    print(f"M1 bars {len(m1):,} | M5 bars {len(df5):,} | 0.01 lot | ${COST:.2f}/trade\n")

    st1 = compute_structure(m1, SWING)
    obs = order_blocks(m1, st1)
    atr1 = atr_wilder(m1["high"], m1["low"], m1["close"], 14).to_numpy()
    st5 = compute_structure(df5, SWING)
    atr5 = atr_wilder(df5["high"], df5["low"], df5["close"], 14).to_numpy()

    s7_variants = {
        "faithful: OB-fail close, no TP": dict(sl_mode="close", tp_mode="none"),
        "wick stop at block far side": dict(sl_mode="wick", tp_mode="none"),
        "OB-fail close + 2R target": dict(sl_mode="close", tp_mode="r", tp_mult=2.0),
        "wick stop + 2R target": dict(sl_mode="wick", tp_mode="r", tp_mult=2.0),
        "ATR 2.0 stop + ATR 4.0 TP": dict(sl_mode="atr", sl_mult=2.0, tp_mode="atr", tp_mult=4.0),
        "ATR 2.0 stop only": dict(sl_mode="atr", sl_mult=2.0, tp_mode="none"),
    }
    s1_variants = {
        "faithful: flip only, no SL/TP": dict(sl_mode="none", tp_mode="none"),
        "ATR 2.0 stop only": dict(sl_mode="atr", sl_mult=2.0, tp_mode="none"),
        "ATR 2.0 stop + ATR 4.0 TP": dict(sl_mode="atr", sl_mult=2.0, tp_mode="atr", tp_mult=4.0),
        "no stop + ATR 4.0 TP": dict(sl_mode="none", tp_mode="atr", tp_mult=4.0),
        "ATR 3.0 stop + 3R target": dict(sl_mode="atr", sl_mult=3.0, tp_mode="r", tp_mult=3.0),
    }

    print("=" * 96)
    print("S7 alone (M1) — 2022")
    print("=" * 96)
    s7 = {}
    print(f"{'variant':34s}{'net $':>10s}{'trd':>7s}{'win%':>7s}{'PF':>6s}{'maxDD $':>10s}  exits")
    for name, kw in s7_variants.items():
        r = bt_s7(m1, st1, obs, atr1, **kw)
        s7[name] = r
        print(f"{name:34s}{r['net']:>10.2f}{r['n']:>7d}{r['win']:>6.1f}%{r['pf']:>6}{r['dd']:>10.2f}  {r['reasons']}")

    print()
    print("=" * 96)
    print("S1 alone (M5) — 2022")
    print("=" * 96)
    s1 = {}
    print(f"{'variant':34s}{'net $':>10s}{'trd':>7s}{'win%':>7s}{'PF':>6s}{'maxDD $':>10s}  exits")
    for name, kw in s1_variants.items():
        r = bt_s1(df5, st5, atr5, **kw)
        s1[name] = r
        print(f"{name:34s}{r['net']:>10.2f}{r['n']:>7d}{r['win']:>6.1f}%{r['pf']:>6}{r['dd']:>10.2f}  {r['reasons']}")

    # ---------------- combined book (S7 + S1, one account) ----------------
    combos = [
        ("faithful (both legs unchanged)", "faithful: OB-fail close, no TP",
         "faithful: flip only, no SL/TP"),
        ("S7 wick stop + S1 faithful", "wick stop at block far side",
         "faithful: flip only, no SL/TP"),
        ("S7 faithful + S1 ATR 2/4", "faithful: OB-fail close, no TP",
         "ATR 2.0 stop + ATR 4.0 TP"),
        ("S7 ATR 2/4 + S1 ATR 2/4", "ATR 2.0 stop + ATR 4.0 TP",
         "ATR 2.0 stop + ATR 4.0 TP"),
        ("S7 wick+2R + S1 ATR 2/4", "wick stop + 2R target",
         "ATR 2.0 stop + ATR 4.0 TP"),
    ]
    print()
    print("=" * 96)
    print("COMBINED BOOK — S7 (M1) + S1 (M5) in one account")
    print("=" * 96)
    print(f"{'configuration':38s}{'net $':>10s}{'trd':>7s}{'win%':>7s}{'PF':>6s}{'maxDD $':>10s}")
    rows = []
    for label, k7, k1 in combos:
        a, b = s7[k7], s1[k1]
        n = a["n"] + b["n"]
        net = round(a["net"] + b["net"], 2)
        # combined equity: recompute properly
        tr7 = a["trades"]
        tr1 = b["trades"]
        allt = pd.concat([tr7, tr1], ignore_index=True).sort_values("exit_time").reset_index(drop=True)
        eq = BAL0 + allt.pnl.cumsum().to_numpy()
        dd = float((eq - np.maximum.accumulate(eq)).min())
        gl = -allt[allt.pnl <= 0].pnl.sum()
        pf = round(float(allt[allt.pnl > 0].pnl.sum() / gl), 2) if gl > 0 else float("inf")
        win = round(float((allt.pnl > 0).mean() * 100), 1)
        rows.append((label, net, n, win, pf, round(dd, 2)))
        print(f"{label:38s}{net:>10.2f}{n:>7d}{win:>6.1f}%{pf:>6}{dd:>10.2f}")

    lines = ["# S7 + S1 — SL/TP variant test (2022, 0.01 lot, $0.20/trade)", "",
             "Purpose: the TradingView script must offer SL and TP signals, so every "
             "variant was measured first. Half the stop/target settings destroy the edge; "
             "the defaults in the Pine script are the ones shown here as faithful.", "",
             "## S7 alone (M1)", "",
             "| variant | net $ | trades | win% | PF | max DD $ | exits |",
             "|---|---|---|---|---|---|---|"]
    for name, r in s7.items():
        lines.append(f"| {name} | {r['net']:,.2f} | {r['n']} | {r['win']}% | {r['pf']} | "
                     f"{r['dd']:,.2f} | {r['reasons']} |")
    lines += ["", "## S1 alone (M5)", "",
              "| variant | net $ | trades | win% | PF | max DD $ | exits |",
              "|---|---|---|---|---|---|---|"]
    for name, r in s1.items():
        lines.append(f"| {name} | {r['net']:,.2f} | {r['n']} | {r['win']}% | {r['pf']} | "
                     f"{r['dd']:,.2f} | {r['reasons']} |")
    lines += ["", "## Combined book (one account)", "",
              "| configuration | net $ | trades | win% | PF | max DD $ |",
              "|---|---|---|---|---|---|"]
    for label, net, n, win, pf, dd in rows:
        lines.append(f"| {label} | {net:,.2f} | {n} | {win}% | {pf} | {dd:,.2f} |")
    with open("results/combined_sltp_report.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\nSaved results/combined_sltp_report.md")


if __name__ == "__main__":
    main()
