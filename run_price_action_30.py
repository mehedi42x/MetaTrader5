"""Faithful port of the pasted Pine v6 script
"30 Price Action Systems | Independent Paper Simulator".

Mechanics reproduced bar for bar:
  - signals are evaluated on the CONFIRMED bar; a flat system queues a setup
  - the setup fills at the NEXT bar's open (+ adverse slip)
  - initial SL = signal bar's low - buffer (long) / high + buffer (short)
  - setup is skipped when the open is already beyond the SL, or when the
    entry-to-SL distance is below minRiskTicks
  - TP = fill +- risk * rr
  - exit order inside a bar: SL gap -> TP gap -> SL (BOTH TOUCHED if the TP was
    also touched) -> TP -> TIME (maxHold bars)
  - 30 systems run independently, one position each, and may overlap
Costs (house rules): 1 contract = 1 oz (0.01 lot), $0.10 slip each side = $0.20 per
round trip, commission 0.

Windows: full years 2022-2025 (real XAUUSD M1) + the real September 2026 window.

Usage: python3 run_price_action_30.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_trade_forensics import load_year, load_recent

TICK = 0.01          # syminfo.mintick for XAUUSD
PV = 1.0             # point value per contract = 1 oz
QTY = 1.0            # 1 contract = 0.01 lot = 1 oz
SLIP_TICKS = 10      # each side -> $0.20 per round trip (house rule)
BUFFER_TICKS = 2
MIN_RISK_TICKS = 5
TOL_TICKS = 10
MAX_HOLD = 40
RR = 2.0
START_BAR = 60       # script: bar_index >= 60

NAMES = ["Engulfing", "Pin bar", "Inside breakout", "Outside reversal",
         "3-bar reversal", "3-candle momentum", "Breakout 5", "Breakout 20",
         "Breakout 50", "Failed break 5", "Failed break 20", "Candle sweep",
         "Double reversal", "Triple reversal", "Triangle", "Stepped trend",
         "Flag", "Pennant", "Double inside", "Fakey", "Harami",
         "Piercing / cloud", "Tweezer", "Full body", "Range rejection", "NR4",
         "NR7", "Gap continuation", "Compression", "Break and retest"]


# ─────────────────────────── signals (vectorised) ───────────────────────────
def rolling_extreme(s, w, kind, shift=1):
    r = s.rolling(w).max() if kind == "max" else s.rolling(w).min()
    return r.shift(shift).to_numpy()


def signals(df):
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float);  c = df["close"].to_numpy(float)
    S = pd.Series
    os_, hs, ls, cs = S(o), S(h), S(l), S(c)

    rng = np.maximum(h - l, TICK)
    rngs = S(rng)
    body = np.abs(c - o)
    safe_body = np.maximum(body, TICK)
    up_w = h - np.maximum(o, c)
    lo_w = np.minimum(o, c) - l
    bull = c > o
    bear = c < o
    tol = TOL_TICKS * TICK
    mid1 = ((os_ + cs) / 2.0).shift(1).to_numpy()

    hi5 = rolling_extreme(hs, 5, "max");   lo5 = rolling_extreme(ls, 5, "min")
    hi20 = rolling_extreme(hs, 20, "max"); lo20 = rolling_extreme(ls, 20, "min")
    hi50 = rolling_extreme(hs, 50, "max"); lo50 = rolling_extreme(ls, 50, "min")
    nr4 = rolling_extreme(rngs, 4, "min"); nr7 = rolling_extreme(rngs, 7, "min")

    def sh(a, k):
        return S(a).shift(k).to_numpy()

    h1, h2, h3, l1, l2, l3 = sh(h, 1), sh(h, 2), sh(h, 3), sh(l, 1), sh(l, 2), sh(l, 3)
    o1, c1, o2, c2, o3, c3 = sh(o, 1), sh(c, 1), sh(o, 2), sh(c, 2), sh(o, 3), sh(c, 3)
    c4, o4, rng3, rng4 = sh(c, 4), sh(o, 4), sh(rng, 3), sh(rng, 4)
    body3, body1, body2 = sh(body, 3), sh(body, 1), sh(body, 2)
    rng1 = sh(rng, 1)

    inside1 = (h1 < h2) & (l1 > l2)
    inside2 = (h2 < h3) & (l2 > l3)
    imp_up3 = (c3 > o3) & (body3 >= rng3 * 0.65)
    imp_dn3 = (c3 < o3) & (body3 >= rng3 * 0.65)
    imp_up4 = (c4 > o4) & (sh(body, 4) >= rng4 * 0.65)
    imp_dn4 = (c4 < o4) & (sh(body, 4) >= rng4 * 0.65)
    squeeze = (h1 < h2) & (h2 < h3) & (l1 > l2) & (l2 > l3)

    B, Sg = [], []
    B.append(bull & (c1 < o1) & (o <= c1) & (c > o1))                        # S01
    Sg.append(bear & (c1 > o1) & (o >= c1) & (c < o1))
    B.append(bull & (lo_w >= safe_body * 2.0) & (up_w <= safe_body) &
             (c >= l + rng * 0.70))                                          # S02
    Sg.append(bear & (up_w >= safe_body * 2.0) & (lo_w <= safe_body) &
              (c <= l + rng * 0.30))
    B.append(inside1 & (c > h2))                                             # S03
    Sg.append(inside1 & (c < l2))
    B.append((h > h1) & (l < l1) & bull & (c > h1))                          # S04
    Sg.append((h > h1) & (l < l1) & bear & (c < l1))
    B.append((c2 < o2) & (l1 < l2) & (body1 < body2) & bull & (c > h1) &
             (c > mid1))                                                     # S05
    Sg.append((c2 > o2) & (h1 > h2) & (body1 < body2) & bear & (c < l1) &
              (c < mid1))
    B.append(bull & (c1 > o1) & (c2 > o2) & (c > c1) & (c1 > c2) &
             (l > l1) & (l1 > l2))                                           # S06
    Sg.append(bear & (c1 < o1) & (c2 < o2) & (c < c1) & (c1 < c2) &
              (h < h1) & (h1 < h2))
    B.append((c > hi5) & bull)                                               # S07
    Sg.append((c < lo5) & bear)
    B.append((c > hi20) & bull)                                              # S08
    Sg.append((c < lo20) & bear)
    B.append((c > hi50) & bull)                                              # S09
    Sg.append((c < lo50) & bear)
    B.append((l < lo5) & (c > lo5) & bull)                                   # S10
    Sg.append((h > hi5) & (c < hi5) & bear)
    B.append((l < lo20) & (c > lo20) & bull)                                 # S11
    Sg.append((h > hi20) & (c < hi20) & bear)
    B.append((l < l1) & (c > l1) & (c > mid1) & bull)                        # S12
    Sg.append((h > h1) & (c < h1) & (c < mid1) & bear)
    B.append((np.abs(l - l2) <= tol) & (l1 > np.maximum(l, l2)) &
             (c > h1) & bull)                                                # S13
    Sg.append((np.abs(h - h2) <= tol) & (h1 < np.minimum(h, h2)) &
              (c < l1) & bear)
    B.append((np.abs(l - l2) <= tol) & (np.abs(l2 - sh(l, 4)) <= tol) &
             (l1 > np.maximum(l, l2)) & (l3 > np.maximum(l2, sh(l, 4))) &
             (c > np.maximum(h1, h3)) & bull)                                # S14
    Sg.append((np.abs(h - h2) <= tol) & (np.abs(h2 - sh(h, 4)) <= tol) &
              (h1 < np.minimum(h, h2)) & (h3 < np.minimum(h2, sh(h, 4))) &
              (c < np.minimum(l1, l3)) & bear)
    B.append((np.abs(h1 - h3) <= tol) & (l1 > l3) & (c > np.maximum(h1, h3)))  # S15
    Sg.append((np.abs(l1 - l3) <= tol) & (h1 < h3) & (c < np.minimum(l1, l3)))
    B.append((h1 > h3) & (h3 > sh(h, 5)) & (l1 > l3) & (l3 > sh(l, 5)) &
             (c > h1))                                                       # S16
    Sg.append((l1 < l3) & (l3 < sh(l, 5)) & (h1 < h3) & (h3 < sh(h, 5)) &
              (c < l1))
    B.append(imp_up3 & (c2 < c3) & (c1 < c2) & (l2 > l3) & (l1 > l3) &
             (h2 <= h3) & (h1 <= h3) & (c > np.maximum(h1, h2)))             # S17
    Sg.append(imp_dn3 & (c2 > c3) & (c1 > c2) & (h2 < h3) & (h1 < h3) &
              (l2 >= l3) & (l1 >= l3) & (c < np.minimum(l1, l2)))
    B.append(imp_up4 & squeeze & (h3 <= sh(h, 4)) & (l3 >= sh(l, 4)) &
             (c > h1))                                                       # S18
    Sg.append(imp_dn4 & squeeze & (h3 <= sh(h, 4)) & (l3 >= sh(l, 4)) &
              (c < l1))
    B.append(inside1 & inside2 & (c > h3))                                   # S19
    Sg.append(inside1 & inside2 & (c < l3))
    B.append(inside1 & (l < l2) & (c > h2) & bull)                           # S20
    Sg.append(inside1 & (h > h2) & (c < l2) & bear)
    B.append((c2 < o2) & (c1 > o1) & (o1 > c2) & (c1 < o2) & (c > h1))       # S21
    Sg.append((c2 > o2) & (c1 < o1) & (o1 < c2) & (c1 > o2) & (c < l1))
    B.append((c1 < o1) & bull & (o <= c1) & (c > mid1) & (c < o1))           # S22
    Sg.append((c1 > o1) & bear & (o >= c1) & (c < mid1) & (c > o1))
    B.append((np.abs(l - l1) <= tol) & (c1 < o1) & bull & (c > mid1))        # S23
    Sg.append((np.abs(h - h1) <= tol) & (c1 > o1) & bear & (c < mid1))
    B.append(bull & (body >= rng * 0.85) & (c > h1))                         # S24
    Sg.append(bear & (body >= rng * 0.85) & (c < l1))
    B.append((l <= lo20) & (lo_w >= safe_body * 2.0) &
             (c >= l + rng * 0.75) & bull)                                   # S25
    Sg.append((h >= hi20) & (up_w >= safe_body * 2.0) &
              (c <= l + rng * 0.25) & bear)
    B.append((rng1 <= nr4) & (c > h1) & bull)                                # S26
    Sg.append((rng1 <= nr4) & (c < l1) & bear)
    B.append((rng1 <= nr7) & (c > h1) & bull)                                # S27
    Sg.append((rng1 <= nr7) & (c < l1) & bear)
    B.append((o > h1) & bull & (l >= h1))                                    # S28
    Sg.append((o < l1) & bear & (h <= l1))
    B.append(squeeze & (c > h3))                                             # S29
    Sg.append(squeeze & (c < l3))
    retest_hi = rolling_extreme(hs, 5, "max", shift=2)                       # S30
    retest_lo = rolling_extreme(ls, 5, "min", shift=2)
    B.append((c1 > retest_hi) & (l <= retest_hi) & (c > retest_hi) & bull)
    Sg.append((c1 < retest_lo) & (h >= retest_lo) & (c < retest_lo) & bear)

    buy = np.array([np.nan_to_num(x, nan=False).astype(bool) for x in B])
    sell = np.array([np.nan_to_num(x, nan=False).astype(bool) for x in Sg])
    return buy, sell


# ─────────────────────────── the paper simulator ───────────────────────────
def run_system(o, h, l, c, buy, sell, rr=RR, max_hold=MAX_HOLD, slip_ticks=SLIP_TICKS,
               buffer_ticks=BUFFER_TICKS, min_risk_ticks=MIN_RISK_TICKS):
    n = len(o)
    slip = slip_ticks * TICK
    buffer = buffer_ticks * TICK
    min_risk = min_risk_ticks * TICK
    sig_idx = np.flatnonzero(buy | sell)
    sig_idx = sig_idx[sig_idx >= START_BAR]

    trades = []
    skips = 0
    open_pos = 0
    entry = sl = tp = np.nan
    entry_bar = 0
    exit_bar = -1

    for j in sig_idx:
        if open_pos != 0 and entry_bar <= j < exit_bar:
            continue                      # in a position at this bar: no new setup
        # ---- a flat system queues the setup on this signal bar ----
        L, S = buy[j], sell[j]
        d = 1 if (L and not S) else (-1 if (S and not L) else 0)
        if d == 0:
            continue
        psl = l[j] - buffer if d == 1 else h[j] + buffer
        m = j + 1
        if m >= n:
            break
        fill = o[m] + d * slip
        risk = d * (fill - psl)
        open_safe = (o[m] > psl) if d == 1 else (o[m] < psl)
        if not open_safe or risk < min_risk:
            skips += 1
            continue
        tgt = fill + d * risk * rr
        # ---- forward scan for the exit (same bar included) ----
        end = min(n, m + max_hold) if max_hold > 0 else n
        oo, hh, ll, cc = o[m:end], h[m:end], l[m:end], c[m:end]
        if d == 1:
            gap_sl, gap_tp = oo <= psl, oo >= tgt
            hit_sl, hit_tp = ll <= psl, hh >= tgt
        else:
            gap_sl, gap_tp = oo >= psl, oo <= tgt
            hit_sl, hit_tp = hh >= psl, ll <= tgt
        touch = gap_sl | gap_tp | hit_sl | hit_tp
        k = -1
        if touch.any():
            k = int(np.argmax(touch))
            if gap_sl[k]:
                raw, why = oo[k], "SL GAP"
            elif gap_tp[k]:
                raw, why = oo[k], "TP GAP"
            elif hit_sl[k]:
                raw = psl
                why = "SL: BOTH TOUCHED" if (hit_tp[k] or gap_tp[k]) else "SL"
            else:
                raw, why = tgt, "TP"
        elif max_hold > 0 and end - m >= max_hold:
            k = max_hold - 1
            raw, why = cc[k], "TIME"
        if k < 0:
            break                          # still open at the end of the data
        exit_fill = raw - d * slip
        gross = d * (exit_fill - fill) * QTY * PV
        pnl = gross
        b = m + k
        trades.append(dict(dir=d, sig_bar=j, entry_bar=m, exit_bar=b,
                           entry=float(fill), exit=float(exit_fill), sl=float(psl),
                           tp=float(tgt), risk=float(risk), pnl=float(pnl), why=why,
                           bars=int(k + 1), time=pd.Timestamp(df_time[b])))
        open_pos = d
        entry_bar = m
        exit_bar = b
    return trades, skips


def stat(trades):
    if not trades:
        return dict(n=0, net=0.0, wr=0.0, pf=0.0, dd=0.0, avg=0.0, bars=0.0,
                    worst=0.0, best=0.0, gross=0.0)
    p = np.array([t["pnl"] for t in trades])
    w, ls = p[p > 0], p[p <= 0]
    return dict(n=len(p), net=round(float(p.sum()), 2),
                wr=round(len(w) / len(p) * 100, 1),
                pf=round(float(w.sum() / -ls.sum()), 2) if ls.sum() < 0 else float("inf"),
                dd=round(float((np.cumsum(p) - np.maximum.accumulate(np.cumsum(p))).min()), 2),
                avg=round(float(p.mean()), 3),
                bars=round(float(np.mean([t["bars"] for t in trades])), 1),
                worst=round(float(p.min()), 2), best=round(float(p.max()), 2),
                gross=round(float(p.sum() + 0.20 * len(p)), 2))


df_time = None


def prep(df):
    global df_time
    df_time = df["time"].to_numpy()
    buy, sell = signals(df)
    return (df["open"].to_numpy(float), df["high"].to_numpy(float),
            df["low"].to_numpy(float), df["close"].to_numpy(float), buy, sell)


def run_all(years=(2022, 2023, 2024, 2025), **kw):
    res = {}
    for y in years:
        df = load_year(y)
        o, h, l, c, buy, sell = prep(df)
        for s in range(30):
            tr, sk = run_system(o, h, l, c, buy[s], sell[s], **kw)
            res.setdefault(s, []).append(stat(tr))
            res[s][-1]["skips"] = sk
    return res


def main():
    years = (2022, 2023, 2024, 2025)
    print("loading and running 30 systems over 2022-2025 (this takes a few minutes) ...",
          flush=True)
    res = run_all(years)

    # ---------- per-system summary ----------
    rows = []
    for s in range(30):
        per = res[s]
        n = sum(p["n"] for p in per)
        net = sum(p["net"] for p in per)
        wins = sum(p["n"] * p["wr"] / 100 for p in per)
        pf_num = sum(p["n"] * p["wr"] / 100 * (p["net"] / max(p["n"], 1) + 0) for p in per)
        gross = sum(p["gross"] for p in per)
        dd = min(p["dd"] for p in per)
        bars = np.mean([p["bars"] for p in per if p["n"]])
        skips = sum(p["skips"] for p in per)
        pos_years = sum(1 for p in per if p["net"] > 0)
        rows.append(dict(id=f"S{s + 1:02d}", name=NAMES[s], trades=n,
                         win=round(wins / n * 100, 1) if n else 0.0,
                         net=round(net, 2), gross=round(gross, 2), dd=round(dd, 2),
                         avg=round(net / n, 3) if n else 0.0,
                         bars=round(bars, 1) if n else 0.0, skips=skips,
                         pos_years=pos_years,
                         y2022=per[0]["net"], y2023=per[1]["net"],
                         y2024=per[2]["net"], y2025=per[3]["net"]))
    df = pd.DataFrame(rows)
    df["score"] = df["net"]
    print("\n" + "=" * 128)
    print("30 PRICE ACTION SYSTEMS — 2022-2025, real XAUUSD M1, 0.01 lot, $0.20/trade "
          "(RR 2.0, maxHold 40 bars)")
    print("=" * 128)
    hdr = (f"{'ID':4s}{'system':20s}{'closed':>8s}{'win%':>7s}{'net $':>11s}{'gross $':>11s}"
           f"{'PF*':>6s}{'maxDD $':>10s}{'avg/trd':>9s}{'bars':>6s}{'+yrs':>6s}"
           f"{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}")
    print(hdr)
    for _, r in df.iterrows():
        print(f"{r['id']:4s}{r['name']:20s}{r['trades']:>8d}{r['win']:>6.1f}%{r['net']:>11.2f}"
              f"{r['gross']:>11.2f}{'':>6s}{r['dd']:>10.2f}{r['avg']:>9.3f}{r['bars']:>6.0f}"
              f"{r['pos_years']:>4d}/4{r['y2022']:>10.2f}{r['y2023']:>10.2f}"
              f"{r['y2024']:>10.2f}{r['y2025']:>10.2f}")
    tot_n, tot_net = int(df.trades.sum()), float(df.net.sum())
    tot_wins = float((df.trades * df.win / 100).sum())
    tot_gross = float(df.gross.sum())
    print("-" * 128)
    print(f"{'SUM':4s}{'30 independent systems':20s}{tot_n:>8d}{tot_wins / tot_n * 100:>6.1f}%"
          f"{tot_net:>11.2f}{tot_gross:>11.2f}{'':>6s}{'':>10s}{tot_net / tot_n:>9.3f}")
    print(f"\ntotal spread paid over the 4 years: ${0.20 * tot_n:,.2f} | "
          f"gross P/L before spread: ${tot_gross:,.2f}")
    print(f"profitable systems: {int((df.net > 0).sum())}/30 | "
          f"positive in all four years: {int((df.pos_years == 4).sum())}/30")
    print(f"best: {df.loc[df.net.idxmax(), 'id']} {df.loc[df.net.idxmax(), 'name']} "
          f"${df.net.max():,.2f} | worst: {df.loc[df.net.idxmin(), 'id']} "
          f"{df.loc[df.net.idxmin(), 'name']} ${df.net.min():,.2f}")

    # ---------- settings sensitivity on the aggregate ----------
    print("\n" + "=" * 128)
    print("SETTINGS SENSITIVITY (all 30 systems summed)")
    print("=" * 128)
    variants = [("base: RR 2.0, maxHold 40, $0.20 cost", dict()),
                ("zero cost (slip 0)", dict(slip_ticks=0)),
                ("RR 1.0", dict(rr=1.0)),
                ("RR 3.0", dict(rr=3.0)),
                ("maxHold disabled", dict(max_hold=0)),
                ("maxHold 10 bars", dict(max_hold=10)),
                ("maxHold 80 bars", dict(max_hold=80)),
                ("stop buffer 0 ticks", dict(buffer_ticks=0)),
                ("min risk 1 tick", dict(min_risk_ticks=1)),
                ("$0.40 cost (slip 20/side)", dict(slip_ticks=20))]
    sens = []
    for label, kw in variants:
        r = run_all(years, **kw) if kw else res
        n = sum(p["n"] for s in r for p in r[s])
        net = sum(p["net"] for s in r for p in r[s])
        wins = sum(p["n"] * p["wr"] / 100 for s in r for p in r[s])
        pos = sum(1 for s in r if sum(p["net"] for p in r[s]) > 0)
        sens.append((label, n, wins / n * 100 if n else 0, net, pos))
        print(f"{label:38s}{n:>9d}{wins / n * 100:>8.1f}%{net:>13.2f}{pos:>8d}/30")
        if kw:
            print(f"{'':38s}(gross before spread: ${net + 0.20 * n:>10.2f})")

    # ---------- recent real window ----------
    print("\n" + "=" * 128)
    print("SEPTEMBER 2026 (real Exness MT5, 9-18 Sep) — sanity check")
    print("=" * 128)
    dfr = load_recent()
    o, h, l, c, buy, sell = prep(dfr)
    rec = []
    for s in range(30):
        tr, sk = run_system(o, h, l, c, buy[s], sell[s])
        st = stat(tr)
        rec.append((NAMES[s], st))
    rn = sum(x[1]["n"] for x in rec)
    rw = sum(x[1]["n"] * x[1]["wr"] / 100 for x in rec)
    rnet = sum(x[1]["net"] for x in rec)
    print(f"{'all 30 systems':38s}{rn:>9d}{rw / rn * 100:>8.1f}%{rnet:>13.2f}")
    for nm, st in sorted(rec, key=lambda x: -x[1]["net"])[:5]:
        print(f"  {nm:36s}{st['n']:>6d}{st['wr']:>8.1f}%{st['net']:>13.2f}")
    print("  ...")
    for nm, st in sorted(rec, key=lambda x: x[1]["net"])[:3]:
        print(f"  {nm:36s}{st['n']:>6d}{st['wr']:>8.1f}%{st['net']:>13.2f}")

    # ---------- detail on the interesting ones ----------
    print("\n" + "=" * 128)
    print("EXIT REASON BREAKDOWN — 2022-2025, the 5 systems with the smallest losses")
    print("=" * 128)
    best5 = list(df.sort_values("net", ascending=False).head(5)["id"])
    idxs = [int(x[1:]) - 1 for x in best5]
    for s in idxs:
        all_tr = []
        for y in years:
            d = load_year(y)
            o, h, l, c, buy, sell = prep(d)
            tr, sk = run_system(o, h, l, c, buy[s], sell[s])
            all_tr += tr
        t = pd.DataFrame(all_tr)
        vc = t.why.value_counts()
        print(f"\n{NAMES[s]} (${df[df.id == f'S{s + 1:02d}'].net.iloc[0]:,.2f}) — "
              f"{len(t)} trades | TP {int(vc.get('TP', 0))} | SL {int(vc.get('SL', 0))} | "
              f"BOTH {int(vc.get('SL: BOTH TOUCHED', 0))} | TIME {int(vc.get('TIME', 0))} | "
              f"gaps {int(vc.get('SL GAP', 0) + vc.get('TP GAP', 0))}")

    # ---------- chart ----------
    fig = plt.figure(figsize=(15, 11))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.15], hspace=0.32, wspace=0.22)
    ax0 = fig.add_subplot(gs[0, :])
    order = df.sort_values("net")
    ax0.barh(range(30), order.net, color=["#089981" if v > 0 else "#f23645" for v in order.net])
    ax0.set_yticks(range(30))
    ax0.set_yticklabels([f"{r.id} {r.name}" for _, r in order.iterrows()], fontsize=7.5)
    ax0.axvline(0, color="k", lw=1)
    ax0.set_xlabel("4-year net P/L ($)")
    ax0.set_title("30 price-action systems, 2022-2025 — net P/L (0.01 lot, $0.20/trade)")
    ax0.grid(alpha=0.3, axis="x")

    ax1 = fig.add_subplot(gs[1, 0])
    for s in idxs[:3]:
        xs, ys, run = [], [], 0.0
        for y in years:
            d = load_year(y)
            o, h, l, c, buy, sell = prep(d)
            tr, sk = run_system(o, h, l, c, buy[s], sell[s])
            xs += [pd.Timestamp(t["time"]) for t in tr]
            ys += list(run + np.cumsum([t["pnl"] for t in tr]))
            run += sum(t["pnl"] for t in tr)
        ax1.plot(xs, ys, lw=1.2, label=f"{NAMES[s]} ({run:+,.0f})")
    ax1.axhline(0, color="k", ls=":", lw=1)
    ax1.set_title("Best systems — equity curve (4 years)")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)
    ax1.tick_params(axis="x", labelsize=8)

    ax2 = fig.add_subplot(gs[1, 1])
    ax2.scatter(df.win, df.net, s=28, c=["#089981" if v > 0 else "#f23645" for v in df.net])
    for _, r in df.iterrows():
        ax2.annotate(r.id, (r.win, r.net), fontsize=6.5, xytext=(2, 2), textcoords="offset points")
    ax2.axhline(0, color="k", ls=":", lw=1)
    ax2.set_xlabel("win rate (%)")
    ax2.set_ylabel("4-year net P/L ($)")
    ax2.set_title("Win rate vs net result")
    ax2.grid(alpha=0.3)

    fig.savefig("results/price_action_30.png", dpi=120, bbox_inches="tight")
    print("\nSaved results/price_action_30.png")

    df.to_csv("results/price_action_30_summary.csv", index=False)
    print("Saved results/price_action_30_summary.csv")

    # ---------- report ----------
    L = ["# 30 Price Action Systems — Independent Paper Simulator (faithful port)", "",
         "Pasted Pine v6 script tested on real XAUUSD M1 data. Mechanics reproduced exactly:",
         "signal on the confirmed bar -> setup queued -> fill at the NEXT bar's open with adverse",
         "slip -> SL = signal bar extreme +- 2 ticks, TP = 2R, maxHold 40 bars, exit order",
         "SL-gap / TP-gap / SL (BOTH TOUCHED) / TP / TIME, one position per system, 30 systems",
         "independent and allowed to overlap.", "",
         "House rules: 0.01 lot (1 oz, qty 1 contract x point value 1), $0.10 slip each side =",
         "**$0.20 per round trip**, commission 0. Windows: full years 2022-2025 plus the real",
         "September 2026 window as a sanity check.", "",
         f"## Aggregate 2022-2025", "",
         f"| | value |", "|---|---|",
         f"| closed trades (30 systems) | {tot_n:,} |",
         f"| win rate | {tot_wins / tot_n * 100:.1f}% |",
         f"| net P/L | **${tot_net:,.2f}** |",
         f"| gross P/L before spread | ${tot_gross:,.2f} |",
         f"| spread paid | ${0.20 * tot_n:,.2f} |",
         f"| profitable systems | {int((df.net > 0).sum())}/30 |",
         f"| positive in all four years | {int((df.pos_years == 4).sum())}/30 |", "",
         "## Per system (net $ by year)", "",
         "| ID | system | trades | win% | 2022 | 2023 | 2024 | 2025 | **total** | gross | "
         "worst DD | avg/trade |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.sort_values("net", ascending=False).iterrows():
        L.append(f"| {r.id} | {r['name']} | {r.trades:,} | {r.win}% | {r.y2022:,.0f} | "
                 f"{r.y2023:,.0f} | {r.y2024:,.0f} | {r.y2025:,.0f} | **{r.net:,.0f}** | "
                 f"{r.gross:,.0f} | {r.dd:,.0f} | {r.avg:+.3f} |")
    L += ["", "## Settings sensitivity (all 30 summed)", "",
          "| variant | trades | win% | net $ | gross $ | profitable systems |",
          "|---|---|---|---|---|---|"]
    for label, n, wr, net, pos in sens:
        L.append(f"| {label} | {n:,} | {wr:.1f}% | {net:,.2f} | {net + 0.20 * n:,.2f} | {pos}/30 |")
    L += ["", f"## September 2026 (real Exness MT5, 9-18 Sep)", "",
          f"All 30 systems: {rn} closed trades, win rate {rw / rn * 100:.1f}%, net ${rnet:,.2f}.",
          "Best three: " + ", ".join(f"{nm} ${st['net']:,.2f}" for nm, st in
                                     sorted(rec, key=lambda x: -x[1]["net"])[:3]) + ".", "",
          "Charts: results/price_action_30.png | table: results/price_action_30_summary.csv"]
    with open("results/price_action_30_report.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("Saved results/price_action_30_report.md")


if __name__ == "__main__":
    main()
