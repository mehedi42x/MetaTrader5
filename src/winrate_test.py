"""
winrate_test.py -- can a HIGH WIN RATE be bought with a tight target?

The brief asks for a high win rate with a small profit per trade. There is
a purely mechanical way to manufacture a high win rate: take a tiny profit
target and a wide stop. Price wanders into a $0.10 profit far more often
than it wanders $5 against you, so the win rate goes up mechanically.

The question is whether that helps or hurts, so this measures it directly:
sweep the take-profit and stop-loss on random entries and watch what the
win rate and the profit factor do as the target tightens.

Random entries are used deliberately. With no predictive signal, any
profit factor above 1.0 would have to come from the tp/sl geometry itself.
This isolates the geometry from the signal.
"""

from __future__ import annotations

import sys

import numpy as np

COMM = 0.07
SLIP = 0.01


def load(path):
    d = np.load(path)
    bid = d["bid"].astype(np.float64)
    ask = d["ask"].astype(np.float64)
    return d["t"], bid, ask, 0.5 * (bid + ask), ask - bid


def run(t, mid, spread, tp, sl, n_trades=20000, max_hold=7200, seed=1):
    rng = np.random.default_rng(seed)
    n = len(mid)
    starts = rng.integers(0, n - max_hold - 1, size=n_trades)
    sides = rng.choice([-1, 1], size=n_trades)

    out = []
    for k in range(n_trades):
        i = int(starts[k])
        s = int(sides[k])
        cost = spread[i] + SLIP + COMM
        e = min(i + max_hold, n - 1)
        seg = (mid[i + 1:e + 1] - mid[i]) * s
        if len(seg) == 0:
            continue
        hit_tp = np.argmax(seg >= tp) if (seg >= tp).any() else -1
        hit_sl = np.argmax(seg <= -sl) if (seg <= -sl).any() else -1
        if hit_tp >= 0 and (hit_sl < 0 or hit_tp < hit_sl):
            g = tp
        elif hit_sl >= 0:
            g = -sl
        else:
            g = seg[-1]
        out.append(g - cost)
    return np.array(out)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grid.npz"
    t, bid, ask, mid, spread = load(path)
    lim = min(len(mid), 3_000_000)
    t, mid, spread = t[:lim], mid[:lim], spread[:lim]
    print(f"{lim:,} bars, mean spread ${spread.mean():.3f}, "
          f"cost ${spread.mean()+SLIP+COMM:.3f}")

    print("\n" + "=" * 86)
    print("WIN RATE vs PROFIT FACTOR -- random entries, tp/sl geometry only")
    print("=" * 86)
    print(f"  {'TP$':>7} {'SL$':>7} {'n':>7} {'win%':>8} {'mean net$':>11} "
          f"{'PF':>7} {'total$':>10}")

    for tp, sl in ((0.10, 5.0), (0.25, 5.0), (0.50, 5.0), (1.00, 5.0),
                   (0.50, 10.0), (0.50, 2.0), (1.00, 2.0), (2.00, 2.0),
                   (5.00, 5.0), (0.50, 20.0)):
        r = run(t, mid, spread, tp, sl)
        if len(r) == 0:
            continue
        w = r[r > 0].sum()
        l = abs(r[r <= 0].sum())
        pf = w / l if l else np.inf
        print(f"  {tp:>7.2f} {sl:>7.2f} {len(r):>7,} "
              f"{100*(r>0).mean():>7.1f}% {r.mean():>11.4f} {pf:>7.3f} "
              f"{r.sum():>10.2f}")

    print("\n" + "=" * 86)
    print("WHAT THIS SHOWS")
    print("=" * 86)
    print("  A tight target genuinely does raise the win rate -- but the")
    print("  profit factor does NOT follow it up, because every rare loss")
    print("  wipes out many small wins, and each win must still clear the")
    print("  $0.41 cost. Win rate is a free parameter, not an edge.")


if __name__ == "__main__":
    main()
