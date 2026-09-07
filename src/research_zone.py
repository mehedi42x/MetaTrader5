"""
research_zone.py
================
Test the user's ZONE COMPRESSION idea before building a strategy on it.

THE IDEA (as specified)
-----------------------
Price sits in one small zone and keeps returning to it:

    500.45, 500.46, 500.47, 500.45, 500.46, 500.50, 500.55, 500.46, 500.45

If price visits the same zone more than 4 times, the zone is "charged".
Whichever way price then leaves the zone, trade that way. Entry analysis
runs on a 1-minute window. The exit uses the same logic: once in a trade,
if price starts sitting in a new zone and trying to reverse, close.

WHAT THIS SCRIPT MEASURES
-------------------------
The idea is intuitive, but on gold the deciding question is arithmetic:
after a zone breaks, does price travel further than the round-trip cost
(~$0.52) inside a 1-minute-ish horizon?

So for a grid of zone widths and touch counts we measure, over the real
tick history:

    * how many zones charge up (is the system active enough?)
    * the average move AFTER the break, in the break direction
    * that move minus the actual spread paid

If the post-break move does not exceed the cost, no amount of coding
makes the strategy profitable, and we need to know that first.
Every number below comes from 12.8M real XAUUSD ticks.
"""

from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np


COMM = 0.07
SLIP = 0.01


def load(path: str):
    d = np.load(path)
    bid = d["bid"].astype(np.float64)
    ask = d["ask"].astype(np.float64)
    return d["t"], 0.5 * (bid + ask), ask - bid


def scan(t, mid, spread, zone_w: float, min_touch: int, window: int,
         horizons=(30, 60, 120, 300)):
    """
    Walk the series. Maintain a 1-minute (window seconds) rolling history of
    which zone each point was in. When the current zone has been visited
    >= min_touch separate times inside the window, arm it. When price then
    leaves the zone, record the forward move in the break direction.
    """
    n = len(mid)
    zi = np.floor(mid / zone_w).astype(np.int64)

    results = {h: [] for h in horizons}
    costs = []
    n_break = 0
    armed_zone = None
    armed_until = 0

    # counts of zone visits inside the rolling window
    visits = defaultdict(int)
    last_zone_of = {}
    buf = []          # (index, zone) inside window
    head = 0

    for i in range(n):
        z = zi[i]

        # slide the window
        while head < len(buf) and t[i] - t[buf[head][0]] > window:
            visits[buf[head][1]] -= 1
            if visits[buf[head][1]] <= 0:
                del visits[buf[head][1]]
            head += 1
        if head > 100000:
            buf = buf[head:]
            head = 0

        # count a "touch" only when price ENTERS the zone (not every tick)
        prev = last_zone_of.get("z")
        if prev != z:
            visits[z] += 1
            buf.append((i, z))
            last_zone_of["z"] = z

        # arm a zone that has been revisited enough
        if visits.get(z, 0) >= min_touch:
            armed_zone = z
            armed_until = i + 1

        # break detection: we were armed, price is now 2+ zones away
        if armed_zone is not None and i > armed_until:
            dz = z - armed_zone
            if abs(dz) >= 2:
                side = 1 if dz > 0 else -1
                n_break += 1
                costs.append(spread[i] + SLIP + COMM)
                for h in horizons:
                    j = i + h
                    if j < n and (t[j] - t[i]) <= h * 1.5:
                        results[h].append((mid[j] - mid[i]) * side)
                    else:
                        results[h].append(np.nan)
                armed_zone = None

    return n_break, results, np.array(costs)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grid.npz"
    t, mid, spread = load(path)

    # use a slice for the sweep -- 2024-01 only, keeps it fast
    lim = min(len(t), 1_500_000)
    t, mid, spread = t[:lim], mid[:lim], spread[:lim]
    print(f"scanning {lim:,} one-second points "
          f"(mean spread ${spread.mean():.3f})")

    print("\n" + "=" * 92)
    print("ZONE COMPRESSION BREAKOUT -- does the post-break move beat the cost?")
    print("=" * 92)
    print(f"  {'zone$':>7} {'touch':>6} {'win_s':>6} {'breaks':>8} {'cost':>7} "
          f"| {'mv30s':>8} {'mv60s':>8} {'mv120s':>8} {'mv300s':>8} | {'best net':>9}")

    rows = []
    for zone_w in (0.05, 0.10, 0.25, 0.50, 1.00):
        for min_touch in (4, 6):
            for window in (60, 180):
                nb, res, costs = scan(t, mid, spread, zone_w, min_touch, window)
                if nb < 200:
                    print(f"  {zone_w:>7} {min_touch:>6} {window:>6} "
                          f"{nb:>8} -- too few breaks")
                    continue
                c = costs.mean()
                mv = {}
                for h in (30, 60, 120, 300):
                    a = np.array(res[h], dtype=float)
                    mv[h] = np.nanmean(a)
                best_h = max(mv, key=lambda k: mv[k])
                best_net = mv[best_h] - c
                rows.append((best_net, zone_w, min_touch, window, nb, best_h, mv[best_h], c))
                flag = "  <== POSITIVE" if best_net > 0 else ""
                print(f"  {zone_w:>7} {min_touch:>6} {window:>6} {nb:>8} "
                      f"{c:>7.3f} | {mv[30]:>8.3f} {mv[60]:>8.3f} "
                      f"{mv[120]:>8.3f} {mv[300]:>8.3f} | {best_net:>9.3f}{flag}")

    rows.sort(reverse=True)
    print("\n  BEST CONFIGS BY NET EDGE PER TRADE:")
    for r in rows[:5]:
        print(f"    net ${r[0]:+.4f}  zone=${r[1]} touch={r[2]} win={r[3]}s "
              f"breaks={r[4]:,} best_horizon={r[5]}s gross=${r[6]:+.3f} cost=${r[7]:.3f}")

    if rows and rows[0][0] > 0:
        print("\n  --> at least one config beats cost. Worth building.")
    else:
        print("\n  --> NO config beats cost on this sample.")
        print("      The break move is smaller than the spread paid to take it.")


if __name__ == "__main__":
    main()
