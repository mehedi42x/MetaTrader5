"""
research2.py
============
Stage-2 edge discovery: can CONDITIONING rescue the breakout signal?

Stage 1 (research.py) established three facts on the real data:

  * Breakout (look 900s / hold 3600s) has the strongest raw directional
    signal: gross +$0.252 per trade -- but average cost is $0.524, so it
    loses unconditionally.
  * Spread is extremely predictable: autocorrelation +0.97 at 60s, and the
    median spread ranges from $0.330 (hours 07-12 UTC) to $0.90 (hour 21).
  * Volatility clusters strongly: realised-vol autocorrelation +0.61 at 5min,
    still +0.50 an hour out.

So the question is not "is there a signal" (there is, +$0.252) but
"can we take that signal ONLY when the cost is low and the expected move
is large?" Cheap spread cuts the cost; high volatility raises the payoff.

This script measures the breakout edge inside each (volatility, spread)
bucket, then checks whether the surviving combination is stable across time.
No strategy is written until the numbers justify one.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

COMM = 0.07      # $/oz round turn at 0.01 lot ($7 per 1.0 lot)
SLIP = 0.01      # $/oz assumed adverse slippage per round trip


def load_grid(path: str) -> dict:
    d = np.load(path)
    bid = d["bid"].astype(np.float64)
    ask = d["ask"].astype(np.float64)
    return {"t": d["t"], "bid": bid, "ask": ask,
            "mid": 0.5 * (bid + ask), "spread": ask - bid}


def build_features(g: dict, look: int, hold: int, vol_win: int = 900):
    """Breakout signal plus the conditioning variables, on the 1s grid."""
    mid, sp, t = g["mid"], g["spread"], g["t"]
    n = len(mid)

    # contiguity: only use windows with no data gap (weekends / missing months)
    contiguous = (t[look:n - hold] - t[:n - hold - look]) <= look * 1.5
    fwd_ok = (t[look + hold:] - t[look:n - hold]) <= hold * 1.5

    past = mid[look:n - hold] - mid[:n - hold - look]
    fwd = mid[look + hold:] - mid[look:n - hold]
    spr = sp[look:n - hold]

    # realised volatility over the trailing vol_win seconds (sum |1s returns|)
    ar = np.abs(np.diff(mid, prepend=mid[0]))
    cs = np.cumsum(ar)
    rv = np.empty(n)
    rv[vol_win:] = cs[vol_win:] - cs[:-vol_win]
    rv[:vol_win] = np.nan
    rv = rv[look:n - hold]

    hours = pd.to_datetime(t[look:n - hold], unit="s").hour.to_numpy()

    ok = contiguous & fwd_ok & np.isfinite(rv)
    return {"past": past[ok], "fwd": fwd[ok], "spread": spr[ok],
            "rv": rv[ok], "hour": hours[ok], "t": t[look:n - hold][ok]}


def bucket_study(f: dict, look: int, hold: int):
    print("\n" + "=" * 78)
    print(f"BREAKOUT look={look}s hold={hold}s -- edge by VOLATILITY x SPREAD bucket")
    print("=" * 78)

    past, fwd, spr, rv = f["past"], f["fwd"], f["spread"], f["rv"]
    sig = np.sign(past)
    # only act on a decisive move
    thr = np.percentile(np.abs(past), 80)
    base = np.abs(past) >= thr

    vq = np.percentile(rv[base], [33, 66])
    sq = np.percentile(spr[base], [33, 66])
    print(f"  entry filter: |past move| >= ${thr:.3f} (top 20%)")
    print(f"  vol terciles:    {vq.round(3)}")
    print(f"  spread terciles: {sq.round(3)}")
    print(f"\n  {'vol':>8} {'spread':>10} {'n':>9} {'gross':>9} {'cost':>8} "
          f"{'NET':>9} {'win%':>7}")

    best = []
    for vi, vname in enumerate(["low", "mid", "HIGH"]):
        for si, sname in enumerate(["CHEAP", "mid", "wide"]):
            vlo = -np.inf if vi == 0 else vq[vi - 1]
            vhi = np.inf if vi == 2 else vq[vi]
            slo = -np.inf if si == 0 else sq[si - 1]
            shi = np.inf if si == 2 else sq[si]
            m = base & (rv >= vlo) & (rv < vhi) & (spr >= slo) & (spr < shi)
            if m.sum() < 2000:
                continue
            gross = fwd[m] * sig[m]
            cost = spr[m] + SLIP + COMM
            net = gross - cost
            best.append((net.mean(), vname, sname, m.sum(),
                         gross.mean(), cost.mean(), 100 * (net > 0).mean()))
            mark = "  <== POSITIVE" if net.mean() > 0 else ""
            print(f"  {vname:>8} {sname:>10} {m.sum():>9,} {gross.mean():>9.3f} "
                  f"{cost.mean():>8.3f} {net.mean():>9.3f} "
                  f"{100*(net>0).mean():>6.1f}%{mark}")
    best.sort(reverse=True)
    return best


def horizon_sweep(g: dict):
    """Find the (look, hold) that maximises edge in the best bucket."""
    print("\n" + "=" * 78)
    print("HORIZON SWEEP inside HIGH-vol / CHEAP-spread bucket")
    print("=" * 78)
    print(f"  {'look':>7} {'hold':>7} {'n':>9} {'gross':>9} {'cost':>8} "
          f"{'NET':>9} {'win%':>7} {'PF':>6}")
    rows = []
    for look in (600, 900, 1800):
        for hold in (1800, 3600, 7200, 14400):
            f = build_features(g, look, hold)
            past, fwd, spr, rv = f["past"], f["fwd"], f["spread"], f["rv"]
            sig = np.sign(past)
            thr = np.percentile(np.abs(past), 80)
            base = np.abs(past) >= thr
            vhi = np.percentile(rv[base], 66)
            slo = np.percentile(spr[base], 33)
            m = base & (rv >= vhi) & (spr <= slo)
            if m.sum() < 2000:
                continue
            gross = fwd[m] * sig[m]
            cost = spr[m] + SLIP + COMM
            net = gross - cost
            w = net[net > 0].sum()
            l = abs(net[net <= 0].sum())
            pf = w / l if l else np.inf
            rows.append((net.mean(), look, hold, m.sum(), gross.mean(),
                         cost.mean(), 100 * (net > 0).mean(), pf))
            print(f"  {look:>6}s {hold:>6}s {m.sum():>9,} {gross.mean():>9.3f} "
                  f"{cost.mean():>8.3f} {net.mean():>9.3f} "
                  f"{100*(net>0).mean():>6.1f}% {pf:>6.2f}")
    rows.sort(reverse=True)
    print("\n  BEST:")
    for r in rows[:4]:
        print(f"    net ${r[0]:+.3f} look={r[1]}s hold={r[2]}s "
              f"n={r[3]:,} PF={r[7]:.2f}")
    return rows


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grid.npz"
    g = load_grid(path)
    print(f"grid: {len(g['t']):,} points")
    f = build_features(g, 900, 3600)
    print(f"usable samples after gap filtering: {len(f['past']):,}")
    bucket_study(f, 900, 3600)
    horizon_sweep(g)


if __name__ == "__main__":
    main()
