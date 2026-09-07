"""
diagnose_zone.py
================
The zone sweep lost money in every configuration, and -- importantly --
it lost money BEFORE costs were even applied. That is a different and
more serious failure than the usual "spread ate the edge", so it needs
explaining rather than just reporting.

Two candidate causes:

  A. The EXIT rule is backwards. "Close when price sits in a zone and
     tries to reverse" fires almost immediately after entry, because a
     freshly entered position is by definition sitting in a new zone and
     ticking around in it. That would cut every winner short after a few
     cents while the hard stop lets every loser run the full $1.50 --
     a guaranteed loser regardless of signal quality.

  B. The ENTRY signal has no edge. Price leaving a congested zone may
     simply not predict direction.

This script separates the two. It re-runs the entry signal but replaces
the exit with a set of fixed horizons. If the entry has an edge, some
horizon will show positive gross. If nothing is positive, the signal
itself is empty and no exit rule can save it.
"""

from __future__ import annotations

import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zone_strategy import ZoneConfig, ZoneStrategy       # noqa: E402
from arb_strategy import stream_ticks                    # noqa: E402


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/REAL_XAUUSD.csv"

    print("loading ticks ...")
    ticks = []
    for i, x in enumerate(stream_ticks(path)):
        if i >= 3_000_000:
            break
        ticks.append(x)
    print(f"  {len(ticks):,} ticks")

    ts = np.array([t[0].timestamp() for t in ticks])
    bid = np.array([t[1] for t in ticks])
    ask = np.array([t[2] for t in ticks])
    mid = 0.5 * (bid + ask)

    # ---- run the strategy just to harvest its ENTRY timestamps -------- #
    cfg = ZoneConfig(zone_w=0.25, min_touch=5, break_zones=2)
    s = ZoneStrategy(cfg)
    entries = []
    orig_close = s._close

    for i, (dt, b, a) in enumerate(ticks):
        was = s.pos
        s.on_tick(dt, b, a)
        if was == 0 and s.pos != 0:
            entries.append((i, s.pos))
    print(f"  entry signals harvested: {len(entries):,}")

    print("\n" + "=" * 78)
    print("A. EXIT-RULE DIAGNOSIS -- how fast does the zone exit fire?")
    print("=" * 78)
    s2 = ZoneStrategy(ZoneConfig(zone_w=0.25, min_touch=5, break_zones=2))
    last = None
    for dt, b, a in ticks:
        s2.on_tick(dt, b, a)
        last = (dt, b, a)
    s2.finalize(*last)
    if s2.trades:
        durs = np.array([t.duration_s for t in s2.trades])
        reasons = Counter(t.exit_reason for t in s2.trades)
        print(f"  trades: {len(s2.trades):,}")
        print(f"  exit reasons: {dict(reasons)}")
        print(f"  duration: median {np.median(durs):.1f}s  "
              f"mean {durs.mean():.1f}s  p90 {np.percentile(durs,90):.1f}s")
        for r in reasons:
            sub = [t for t in s2.trades if t.exit_reason == r]
            g = np.mean([t.gross for t in sub])
            print(f"    {r:<14} n={len(sub):>6,}  mean gross ${g:+.4f}  "
                  f"mean dur {np.mean([t.duration_s for t in sub]):>7.1f}s")

    print("\n" + "=" * 78)
    print("B. ENTRY-SIGNAL DIAGNOSIS -- fixed horizons instead of the zone exit")
    print("=" * 78)
    print("  If the entry has ANY edge, some horizon shows positive gross.")
    print(f"\n  {'horizon':>9} {'n':>8} {'mean gross$':>13} {'win%':>7} "
          f"{'vs cost$0.41':>14}")

    idx = np.array([e[0] for e in entries])
    side = np.array([e[1] for e in entries])

    for hz in (10, 30, 60, 120, 300, 600, 1800):
        moves = []
        for k, i in enumerate(idx):
            tgt = ts[i] + hz
            j = np.searchsorted(ts, tgt)
            if j >= len(ts) or ts[j] - ts[i] > hz * 3:
                continue
            moves.append((mid[j] - mid[i]) * side[k])
        if not moves:
            continue
        m = np.array(moves)
        print(f"  {hz:>8}s {len(m):>8,} {m.mean():>13.4f} "
              f"{100*(m>0).mean():>6.1f}% {m.mean()-0.41:>14.4f}")

    print("\n" + "=" * 78)
    print("C. CONTROL -- what does a RANDOM entry look like at the same times?")
    print("=" * 78)
    rng = np.random.default_rng(0)
    rside = rng.choice([-1, 1], size=len(idx))
    for hz in (60, 300):
        moves = []
        for k, i in enumerate(idx):
            j = np.searchsorted(ts, ts[i] + hz)
            if j >= len(ts):
                continue
            moves.append((mid[j] - mid[i]) * rside[k])
        m = np.array(moves)
        print(f"  random {hz}s: mean ${m.mean():+.4f}  win {100*(m>0).mean():.1f}%")

    print("\n  If the zone entry is no better than random, the signal is empty.")


if __name__ == "__main__":
    main()
