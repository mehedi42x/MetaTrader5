"""
research.py
===========
Edge discovery on REAL XAUUSD tick data.

The previous strategy failed because it bet on ~5-second momentum, where the
average move ($0.22) is smaller than the round-trip cost ($0.53). Before
writing another strategy I measure, on the real data, WHERE a tradable edge
actually exists — if anywhere.

This script answers four questions:

  Q1  At what holding horizon does the move/cost ratio become favourable?
  Q2  Is the spread predictable? (trade only when costs are cheap)
  Q3  Does volatility cluster? (a genuine, well-known effect)
  Q4  Is there a *conditional* directional edge that survives costs?

Everything is measured out-of-sample-honest: no parameter is fitted here,
these are raw population statistics of the data.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mt5_loader import load_ticks  # noqa: E402


def resample_seconds(t: pd.DataFrame, step: float = 1.0) -> dict:
    """Build a uniform time grid (last quote at each step). Tick data is
    irregular; a uniform grid makes horizon maths honest."""
    ts = t["ts"].to_numpy()
    bid = t["bid"].to_numpy()
    ask = t["ask"].to_numpy()
    t0, t1 = ts[0], ts[-1]
    grid = np.arange(t0, t1, step)
    idx = np.searchsorted(ts, grid, side="right") - 1
    idx = np.clip(idx, 0, len(ts) - 1)
    return {
        "t": grid,
        "bid": bid[idx],
        "ask": ask[idx],
        "mid": 0.5 * (bid[idx] + ask[idx]),
        "spread": ask[idx] - bid[idx],
        "gap": grid - ts[idx],          # staleness of the quote
    }


def q1_horizon(g: dict, cost: float):
    print("\n" + "=" * 72)
    print("Q1  MOVE vs COST BY HORIZON  (can any horizon pay for the trade?)")
    print("=" * 72)
    mid = g["mid"]
    print(f"  round-trip cost = ${cost:.3f}")
    print(f"  {'horizon':>10} {'mean|move|':>12} {'p60':>9} {'p75':>9} {'ratio':>8}")
    for sec in (10, 30, 60, 180, 300, 900, 1800, 3600, 7200):
        n = int(sec)
        if n >= len(mid):
            continue
        mv = np.abs(mid[n:] - mid[:-n])
        r = mv.mean() / cost
        flag = "  <-- viable" if r >= 2.5 else ""
        print(f"  {sec:>8}s {mv.mean():>12.3f} {np.percentile(mv,60):>9.3f} "
              f"{np.percentile(mv,75):>9.3f} {r:>7.2f}x{flag}")


def q2_spread(g: dict):
    print("\n" + "=" * 72)
    print("Q2  IS THE SPREAD PREDICTABLE?  (only trade when it is cheap)")
    print("=" * 72)
    sp = g["spread"]
    t = g["t"]
    hours = pd.to_datetime(t, unit="s").hour
    print(f"  overall: mean ${sp.mean():.3f}  median ${np.median(sp):.3f}")
    print(f"  {'hour':>5} {'mean spread':>13} {'median':>9} {'n':>10}")
    best = []
    for h in range(24):
        m = hours == h
        if m.sum() < 500:
            continue
        best.append((np.median(sp[m]), h, sp[m].mean(), m.sum()))
        print(f"  {h:>5} {sp[m].mean():>13.3f} {np.median(sp[m]):>9.3f} {m.sum():>10,}")
    best.sort()
    cheap = sorted(h for _, h, _, _ in best[:8])
    print(f"\n  --> 8 cheapest hours (UTC): {cheap}")
    # persistence: does a cheap spread now mean a cheap spread soon?
    for lag in (60, 300):
        if lag < len(sp):
            c = np.corrcoef(sp[:-lag], sp[lag:])[0, 1]
            print(f"  spread autocorrelation at {lag}s: {c:+.3f}")
    return cheap


def q3_vol(g: dict):
    print("\n" + "=" * 72)
    print("Q3  DOES VOLATILITY CLUSTER?  (predictable size, if not direction)")
    print("=" * 72)
    mid = g["mid"]
    r = np.diff(mid)
    W = 300
    if len(r) < 4 * W:
        return
    # realised vol over rolling 5-minute windows, sampled every 5 minutes
    n = len(r) // W
    rv = np.array([np.abs(r[i * W:(i + 1) * W]).sum() for i in range(n)])
    for lag in (1, 2, 3, 6, 12):
        if lag < n:
            c = np.corrcoef(rv[:-lag], rv[lag:])[0, 1]
            print(f"  realised-vol autocorr at lag {lag*5:>3}min: {c:+.3f}")
    print("  -> if positive, current volatility predicts near-future volatility.")
    print("     That lets us size targets to conditions instead of guessing.")


def q4_conditional(g: dict, cost: float):
    print("\n" + "=" * 72)
    print("Q4  CONDITIONAL DIRECTIONAL EDGE  (net of cost, on a 1s grid)")
    print("=" * 72)
    mid = g["mid"]
    sp = g["spread"]
    n = len(mid)
    print(f"  cost ${cost:.3f}. Testing breakout & fade over many horizons.")
    print(f"  {'look':>6} {'hold':>6} {'mode':>9} {'n':>9} {'gross':>9} {'net':>9} {'win%':>7}")

    results = []
    for look in (60, 300, 900):
        for hold in (300, 900, 1800, 3600):
            if look + hold >= n:
                continue
            past = mid[look:n - hold] - mid[:n - hold - look]
            fwd = mid[look + hold:] - mid[look:n - hold]
            spr = sp[look:n - hold]
            # only consider moves that are large relative to the local spread
            thr = np.percentile(np.abs(past), 80)
            sel = np.abs(past) >= thr
            if sel.sum() < 500:
                continue
            for mode, sgn in (("breakout", 1), ("fade", -1)):
                d = np.sign(past[sel]) * sgn
                gross = fwd[sel] * d
                net = gross - (spr[sel] + 0.01 + 0.07)
                results.append((net.mean(), look, hold, mode, sel.sum(),
                                gross.mean(), 100 * (net > 0).mean()))
                print(f"  {look:>5}s {hold:>5}s {mode:>9} {sel.sum():>9,} "
                      f"{gross.mean():>9.3f} {net.mean():>9.3f} "
                      f"{100*(net>0).mean():>6.1f}%")
    results.sort(reverse=True)
    print("\n  BEST configurations by net expectancy:")
    for r in results[:5]:
        print(f"    net ${r[0]:+.3f}  look={r[1]}s hold={r[2]}s {r[3]} "
              f"(n={r[4]:,}, gross ${r[5]:+.3f}, win {r[6]:.1f}%)")
    return results


def load_grid(path: str) -> dict:
    d = np.load(path)
    bid = d["bid"].astype(np.float64)
    ask = d["ask"].astype(np.float64)
    return {"t": d["t"], "bid": bid, "ask": ask,
            "mid": 0.5 * (bid + ask), "spread": ask - bid, "gap": d["gap"]}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grid.npz"
    g = load_grid(path) if path.endswith(".npz") else \
        resample_seconds(load_ticks(path, verbose=True), 1.0)
    cost = float(np.mean(g["spread"])) + 0.01 + 0.07
    print(f"\n1-second grid: {len(g['t']):,} points")

    q1_horizon(g, cost)
    q2_spread(g)
    q3_vol(g)
    q4_conditional(g, cost)


if __name__ == "__main__":
    main()
