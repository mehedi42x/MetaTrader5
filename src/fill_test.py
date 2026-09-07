"""
fill_test.py -- the decisive test of the passive (limit-order) results.

WHY THIS EXISTS
---------------
battery.py found 5 passive strategies with a positive net edge, one showing
94.1% win rate and PF 38. Those numbers assumed something that was never
checked: that a limit order always gets filled.

It does not, and the way it fails is not random. A resting BUY limit at the
bid only executes when someone sells into it -- that is, when price is
coming DOWN. So the fills you get are precisely the ones where the market
is already moving against you, while the orders that would have been
profitable simply never fill. This is ADVERSE SELECTION, and it is the
single reason most retail "market making" backtests are fiction.

The battery cost model (-spread + commission = -$0.374, i.e. a guaranteed
profit on every trade) therefore measured a fantasy. This script replaces
it with an honest simulation:

    * Place a buy limit at the bid (or sell limit at the ask).
    * Wait up to `timeout` seconds.
    * It fills ONLY if the market actually trades at or through the price.
    * If it never fills, there is no trade -- and crucially, we track how
      those unfilled cases would have performed, to measure exactly how
      much of the edge was selection bias.

If the edge survives realistic fills, it is real and we build it.
If it evaporates, the passive result was an illusion and we say so.
"""

from __future__ import annotations

import sys

import numpy as np

COMM = 0.07


def load(path):
    d = np.load(path)
    bid = d["bid"].astype(np.float64)
    ask = d["ask"].astype(np.float64)
    t = d["t"]
    return t, bid, ask, 0.5 * (bid + ask), ask - bid


def rollmean(x, w):
    c = np.cumsum(np.insert(x, 0, 0.0))
    out = np.full(len(x), np.nan)
    out[w:] = (c[w + 1:] - c[1:-w]) / w
    return out


def rollstd(x, w):
    m = rollmean(x, w)
    m2 = rollmean(x * x, w)
    return np.sqrt(np.maximum(m2 - m * m, 0))


def simulate_passive(t, bid, ask, mid, spread, sig_idx, sig_side,
                     timeout=60, hold=300, tp=None, sl=None,
                     max_trades=200_000):
    """
    Honest limit-order simulation.

    For each signal:
      side +1 -> place BUY limit at the current bid
      side -1 -> place SELL limit at the current ask
    Fill occurs at the first later second where the market reaches it:
      buy limit fills if ask <= limit  (someone sold down to us)
      sell limit fills if bid >= limit (someone bought up to us)
    After filling, exit at `hold` seconds, or tp/sl if given.
    Exit is PASSIVE too (limit at the favourable side) but we
    conservatively exit at the market to avoid double-counting the edge.
    """
    n = len(mid)
    filled, unfilled = [], []
    n_fill = n_nofill = 0

    for k in range(len(sig_idx)):
        if n_fill + n_nofill >= max_trades:
            break
        i = int(sig_idx[k])
        side = int(sig_side[k])
        limit = bid[i] if side > 0 else ask[i]

        # ---- wait for a fill -------------------------------------- #
        end = min(i + timeout, n - 1)
        j = -1
        for q in range(i + 1, end + 1):
            if t[q] - t[i] > timeout * 1.5:
                break
            if side > 0 and ask[q] <= limit:
                j = q
                break
            if side < 0 and bid[q] >= limit:
                j = q
                break

        if j < 0:
            # never filled -- record the counterfactual
            e = min(i + hold, n - 1)
            if t[e] - t[i] <= hold * 1.5:
                unfilled.append((mid[e] - mid[i]) * side)
            n_nofill += 1
            continue

        n_fill += 1
        entry = limit
        # ---- manage the position ---------------------------------- #
        e_end = min(j + hold, n - 1)
        exit_px = None
        for q in range(j + 1, e_end + 1):
            if t[q] - t[j] > hold * 1.5:
                e_end = q
                break
            px = bid[q] if side > 0 else ask[q]
            mv = (px - entry) * side
            if tp is not None and mv >= tp:
                exit_px = px
                break
            if sl is not None and mv <= -sl:
                exit_px = px
                break
        if exit_px is None:
            exit_px = bid[e_end] if side > 0 else ask[e_end]

        gross = (exit_px - entry) * side
        filled.append(gross - COMM)

    return np.array(filled), np.array(unfilled), n_fill, n_nofill


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grid.npz"
    t, bid, ask, mid, spread = load(path)
    # use a slice -- the fill loop is O(n * timeout)
    lim = min(len(mid), 2_000_000)
    t, bid, ask, mid, spread = t[:lim], bid[:lim], ask[:lim], mid[:lim], spread[:lim]
    print(f"{lim:,} one-second bars, mean spread ${spread.mean():.3f}")

    hour = ((t // 3600) % 24).astype(int)
    liquid = (hour >= 6) & (hour < 20)
    absret = np.abs(np.diff(mid, prepend=mid[0]))
    volq = rollmean(absret, 3600)
    lv = volq < np.nanpercentile(volq, 30)

    m300 = rollmean(mid, 300)
    s300 = rollstd(mid, 300)
    z = (mid - m300) / np.where(s300 > 0, s300, np.nan)

    p1 = mid - np.roll(mid, 300); p1[:300] = np.nan

    tests = [
        ("25. PASSIVE z>1.5 revert",
         np.where(z > 1.5, -1, np.where(z < -1.5, 1, 0)) * liquid, 300),
        ("26. PASSIVE low-vol revert 5m",
         np.where(lv & liquid, -np.sign(np.nan_to_num(p1)), 0), 300),
        ("28. PASSIVE low-vol revert 30s",
         np.where(lv & liquid, -np.sign(np.nan_to_num(p1)), 0), 30),
    ]

    print("\n" + "=" * 98)
    print("REALISTIC LIMIT-ORDER FILLS vs THE BATTERY'S ASSUMPTION")
    print("=" * 98)

    for name, sig, hold in tests:
        idx = np.flatnonzero(sig != 0)
        if len(idx) == 0:
            continue
        # thin the signals so we sample across the whole period
        step = max(1, len(idx) // 60_000)
        idx = idx[::step]
        side = sig[idx]

        f, u, nf, nn = simulate_passive(t, bid, ask, mid, spread,
                                        idx, side, timeout=60, hold=hold)
        if len(f) == 0:
            print(f"\n  {name}: no fills")
            continue

        fill_rate = 100 * nf / (nf + nn)
        w = f[f > 0].sum()
        l = abs(f[f <= 0].sum())
        pf = w / l if l else np.inf
        print(f"\n  {name}  (hold {hold}s)")
        print(f"    attempts {nf+nn:,}   FILL RATE {fill_rate:.1f}%   "
              f"fills {nf:,}")
        print(f"    FILLED   mean net ${f.mean():+.4f}  "
              f"win {100*(f>0).mean():.1f}%  PF {pf:.2f}")
        if len(u):
            print(f"    UNFILLED counterfactual mean ${u.mean():+.4f}  "
                  f"(these are the trades we never got)")
            print(f"    --> adverse selection cost: "
                  f"${u.mean() - f.mean():+.4f} per signal")

    print("\n" + "=" * 98)
    print("INTERPRETATION")
    print("=" * 98)
    print("  battery.py assumed a filled limit order earns the spread:")
    print("     cost = -spread + commission = -$0.374  (profit on every trade)")
    print("  The simulation above only counts orders the market actually")
    print("  reached. Compare 'FILLED mean net' against that -$0.374 fantasy.")


if __name__ == "__main__":
    main()
