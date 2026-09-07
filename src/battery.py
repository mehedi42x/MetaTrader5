"""
battery.py -- test ~30 distinct strategy families on real XAUUSD ticks.

THE BRIEF
---------
"81,000 trades chai, win rate beshi chai, profit choto thakleo somossa nai."

High frequency + high win rate + small profit per trade. That combination
is achievable in principle -- market makers live on it -- but it collides
with one number: the round-trip cost is about $0.41 per trade. At 81,000
trades that is $33,000 of cost. So a small profit only works if the profit
per trade is larger than $0.41, or if the cost itself is reduced.

That gives two genuinely different research directions, and this script
tests both rather than assuming the answer:

  AGGRESSIVE (cross the spread, pay ~$0.41)
      Needs an edge > $0.41/trade. Strategies 1-20 below.

  PASSIVE (place limit orders, EARN the spread instead of paying it)
      A resting buy limit at the bid that gets filled costs nothing in
      spread -- it collects it. Cost drops from -$0.41 to about +$0.33
      minus commission. This is how real high-frequency, high-win-rate,
      small-profit systems actually work, and it is the only structure
      that fits the brief. Strategies 21-30.

Every strategy is evaluated the same way: signal -> forward return in the
signal direction -> subtract the real cost measured at that tick. Nothing
is tuned on the result; this is a scan for where an edge might exist.
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
    t = d["t"]
    mid = 0.5 * (bid + ask)
    return t, bid, ask, mid, ask - bid


def fwd(mid, t, h):
    """Forward move h seconds ahead; NaN where a data gap intervenes."""
    n = len(mid)
    out = np.full(n, np.nan)
    out[:n - h] = mid[h:] - mid[:n - h]
    bad = np.full(n, True)
    bad[:n - h] = (t[h:] - t[:n - h]) <= h * 1.5
    out[~bad] = np.nan
    return out


def rollmean(x, w):
    c = np.cumsum(np.insert(x, 0, 0.0))
    out = np.full(len(x), np.nan)
    out[w:] = (c[w + 1:] - c[1:-w]) / w
    return out


def rollstd(x, w):
    m = rollmean(x, w)
    m2 = rollmean(x * x, w)
    return np.sqrt(np.maximum(m2 - m * m, 0))


def rollmax(x, w):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(x), np.nan)
    if len(x) > w:
        out[w - 1:] = sliding_window_view(x, w).max(axis=1)
    return out


def rollmin(x, w):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(x), np.nan)
    if len(x) > w:
        out[w - 1:] = sliding_window_view(x, w).min(axis=1)
    return out


# --------------------------------------------------------------------------- #
RESULTS = []


def report(name, sig, f, cost, note=""):
    """sig: -1/0/+1 array. f: forward move. cost: per-trade cost array."""
    m = (sig != 0) & np.isfinite(f) & np.isfinite(cost)
    n = int(m.sum())
    if n < 500:
        RESULTS.append((name, n, np.nan, np.nan, np.nan, np.nan, "too few"))
        print(f"  {name:<44} n={n:>9,}  -- too few signals")
        return
    gross = f[m] * sig[m]
    net = gross - cost[m]
    win = 100 * (net > 0).mean()
    w = net[net > 0].sum()
    l = abs(net[net <= 0].sum())
    pf = w / l if l else np.inf
    RESULTS.append((name, n, gross.mean(), net.mean(), win, pf, note))
    flag = "  <== POSITIVE" if net.mean() > 0 else ""
    print(f"  {name:<44} n={n:>9,} gross={gross.mean():>+8.4f} "
          f"net={net.mean():>+8.4f} win={win:>5.1f}% PF={pf:>5.2f}{flag}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grid.npz"
    t, bid, ask, mid, spread = load(path)
    n = len(mid)
    print(f"grid {n:,} one-second bars, mean spread ${spread.mean():.3f}")

    hour = ((t // 3600) % 24).astype(int)
    liquid = (hour >= 6) & (hour < 20)          # avoid rollover hours

    ret1 = np.diff(mid, prepend=mid[0])
    absret = np.abs(ret1)

    # cost models
    cost_aggr = spread + SLIP + COMM            # cross the spread
    cost_pass = -spread + COMM                  # earn the spread (limit order)

    f60 = fwd(mid, t, 60)
    f300 = fwd(mid, t, 300)
    f900 = fwd(mid, t, 900)
    f1800 = fwd(mid, t, 1800)
    f3600 = fwd(mid, t, 3600)

    print("\n" + "=" * 100)
    print("PART 1 -- AGGRESSIVE ENTRIES (cross the spread, cost ~$0.41)")
    print("=" * 100)

    # 1-3: momentum at several horizons
    for w, f, lbl in ((60, f60, "1m"), (300, f300, "5m"), (900, f900, "15m")):
        past = mid - np.roll(mid, w)
        past[:w] = np.nan
        sig = np.sign(past) * liquid
        report(f"{len(RESULTS)+1:>2}. Momentum {lbl} -> {lbl}", sig, f, cost_aggr)

    # 4-6: mean reversion
    for w, f, lbl in ((60, f60, "1m"), (300, f300, "5m"), (900, f900, "15m")):
        past = mid - np.roll(mid, w)
        past[:w] = np.nan
        sig = -np.sign(past) * liquid
        report(f"{len(RESULTS)+1:>2}. MeanRevert {lbl} -> {lbl}", sig, f, cost_aggr)

    # 7: z-score reversion
    m300 = rollmean(mid, 300)
    s300 = rollstd(mid, 300)
    z = (mid - m300) / np.where(s300 > 0, s300, np.nan)
    sig = np.where(z > 2, -1, np.where(z < -2, 1, 0)) * liquid
    report(f"{len(RESULTS)+1:>2}. Z-score>2 revert 5m -> 5m", sig, f300, cost_aggr)

    # 8: z-score momentum
    sig = np.where(z > 2, 1, np.where(z < -2, -1, 0)) * liquid
    report(f"{len(RESULTS)+1:>2}. Z-score>2 momentum 5m -> 15m", sig, f900, cost_aggr)

    # 9-10: channel breakout
    for w, f, lbl in ((900, f900, "15m"), (1800, f1800, "30m")):
        hi, lo = rollmax(mid, w), rollmin(mid, w)
        sig = np.where(mid >= hi, 1, np.where(mid <= lo, -1, 0)) * liquid
        report(f"{len(RESULTS)+1:>2}. Channel breakout {lbl} -> 1h", sig, f3600, cost_aggr)

    # 11: channel fade
    hi, lo = rollmax(mid, 900), rollmin(mid, 900)
    sig = np.where(mid >= hi, -1, np.where(mid <= lo, 1, 0)) * liquid
    report(f"{len(RESULTS)+1:>2}. Channel fade 15m -> 15m", sig, f900, cost_aggr)

    # 12: volatility-breakout
    vol = rollmean(absret, 900)
    past = mid - np.roll(mid, 300); past[:300] = np.nan
    sig = np.where(np.abs(past) > 3 * vol * np.sqrt(300),
                   np.sign(past), 0) * liquid
    report(f"{len(RESULTS)+1:>2}. Vol-scaled breakout 5m -> 1h", sig, f3600, cost_aggr)

    # 13: acceleration
    p1 = mid - np.roll(mid, 300); p1[:300] = np.nan
    p2 = np.roll(mid, 300) - np.roll(mid, 600); p2[:600] = np.nan
    sig = np.where((np.sign(p1) == np.sign(p2)) & (np.abs(p1) > np.abs(p2)),
                   np.sign(p1), 0) * liquid
    report(f"{len(RESULTS)+1:>2}. Acceleration 5m -> 30m", sig, f1800, cost_aggr)

    # 14: exhaustion (decelerating move -> fade)
    sig = np.where((np.sign(p1) == np.sign(p2)) & (np.abs(p1) < np.abs(p2) * 0.5),
                   -np.sign(p1), 0) * liquid
    report(f"{len(RESULTS)+1:>2}. Exhaustion fade 5m -> 30m", sig, f1800, cost_aggr)

    # 15: spread-compression (tight spread = confident MMs)
    sp_med = rollmean(spread, 3600)
    tight = spread < sp_med * 0.7
    past = mid - np.roll(mid, 300); past[:300] = np.nan
    sig = np.where(tight, np.sign(past), 0) * liquid
    report(f"{len(RESULTS)+1:>2}. Tight-spread momentum -> 30m", sig, f1800, cost_aggr)

    # 16: vol-regime conditional momentum
    volq = rollmean(absret, 3600)
    hv = volq > np.nanpercentile(volq, 70)
    sig = np.where(hv, np.sign(past), 0) * liquid
    report(f"{len(RESULTS)+1:>2}. High-vol momentum 5m -> 1h", sig, f3600, cost_aggr)

    # 17: low-vol momentum
    lv = volq < np.nanpercentile(volq, 30)
    sig = np.where(lv, np.sign(past), 0) * liquid
    report(f"{len(RESULTS)+1:>2}. Low-vol momentum 5m -> 1h", sig, f3600, cost_aggr)

    # 18: time-of-day (London open momentum)
    lon = (hour == 7) | (hour == 8)
    sig = np.where(lon, np.sign(past), 0)
    report(f"{len(RESULTS)+1:>2}. London-open momentum -> 1h", sig, f3600, cost_aggr)

    # 19: NY open
    ny = (hour == 13) | (hour == 14)
    sig = np.where(ny, np.sign(past), 0)
    report(f"{len(RESULTS)+1:>2}. NY-open momentum -> 1h", sig, f3600, cost_aggr)

    # 20: tick-imbalance (uptick vs downtick ratio)
    upt = rollmean((ret1 > 0).astype(float), 300)
    sig = np.where(upt > 0.55, 1, np.where(upt < 0.45, -1, 0)) * liquid
    report(f"{len(RESULTS)+1:>2}. Tick imbalance 5m -> 15m", sig, f900, cost_aggr)

    print("\n" + "=" * 100)
    print("PART 2 -- PASSIVE ENTRIES (limit orders: EARN the spread)")
    print("=" * 100)
    print("  Cost model: -spread + commission. A filled buy limit at the bid")
    print("  collects the spread rather than paying it. Mean cost here is")
    print(f"  ${np.nanmean(cost_pass):.3f} vs ${np.nanmean(cost_aggr):.3f} aggressive.")
    print()

    # 21-24: passive mean reversion at several horizons
    for w, f, lbl in ((30, fwd(mid, t, 30), "30s"), (60, f60, "1m"),
                      (300, f300, "5m"), (900, f900, "15m")):
        past = mid - np.roll(mid, w); past[:w] = np.nan
        sig = -np.sign(past) * liquid
        report(f"{len(RESULTS)+1:>2}. PASSIVE revert {lbl} -> {lbl}", sig, f, cost_pass)

    # 25: passive z-score reversion
    sig = np.where(z > 1.5, -1, np.where(z < -1.5, 1, 0)) * liquid
    report(f"{len(RESULTS)+1:>2}. PASSIVE z>1.5 revert -> 5m", sig, f300, cost_pass)

    # 26: passive flat-market scalp (low vol = safe to quote)
    sig = np.where(lv & liquid, -np.sign(np.where(np.isnan(p1), 0, p1)), 0)
    report(f"{len(RESULTS)+1:>2}. PASSIVE low-vol revert -> 5m", sig, f300, cost_pass)

    # 27: passive tight-spread quote
    sig = np.where(tight & liquid, -np.sign(np.where(np.isnan(p1), 0, p1)), 0)
    report(f"{len(RESULTS)+1:>2}. PASSIVE tight-spread revert -> 5m", sig, f300, cost_pass)

    # 28: passive, hold very short (30s)
    f30 = fwd(mid, t, 30)
    sig = np.where(lv & liquid, -np.sign(np.where(np.isnan(p1), 0, p1)), 0)
    report(f"{len(RESULTS)+1:>2}. PASSIVE low-vol revert -> 30s", sig, f30, cost_pass)

    # 29: passive channel fade
    sig = np.where(mid >= hi, -1, np.where(mid <= lo, 1, 0)) * liquid
    report(f"{len(RESULTS)+1:>2}. PASSIVE channel fade 15m -> 5m", sig, f300, cost_pass)

    # 30: passive pure market-making (quote both sides, flat signal)
    #     approximated: every liquid second, revert the last 60s move
    past60 = mid - np.roll(mid, 60); past60[:60] = np.nan
    sig = -np.sign(past60) * liquid
    report(f"{len(RESULTS)+1:>2}. PASSIVE market-make -> 30s", sig, f30, cost_pass)

    # ---------------------------------------------------------------- #
    print("\n" + "=" * 100)
    print("RANKING BY NET EDGE PER TRADE")
    print("=" * 100)
    ok = [r for r in RESULTS if np.isfinite(r[3])]
    ok.sort(key=lambda r: -r[3])
    print(f"  {'#':>3} {'strategy':<44} {'n':>10} {'net$':>9} {'win%':>7} {'PF':>6}")
    for i, r in enumerate(ok, 1):
        print(f"  {i:>3} {r[0]:<44} {r[1]:>10,} {r[3]:>+9.4f} "
              f"{r[4]:>6.1f}% {r[5]:>6.2f}")

    pos = [r for r in ok if r[3] > 0]
    print(f"\n  strategies with a positive net edge: {len(pos)} / {len(ok)}")
    for r in pos:
        ann = r[3] * r[1]
        print(f"    {r[0]}: ${r[3]:+.4f}/trade x {r[1]:,} = ${ann:,.0f}")


if __name__ == "__main__":
    main()
