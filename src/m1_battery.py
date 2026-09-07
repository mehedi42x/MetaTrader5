"""
m1_battery.py -- vectorised strategy scan over 8.7 years of M1 bars.

WHY A SECOND BATTERY
--------------------
The M1 run of ARB delivered a genuinely important negative result: across
2018-2026 the three-session breakout returns PF 1.00 -- no edge at all.
It is profitable only in 2025-2026 and loses in 2018-2019, 2021 and 2023.
That means the original 76-trade tick backtest (PF 1.57) was measuring a
favourable 83-day window, not a durable effect. The long history did what
short history could not: it exposed the strategy as regime-dependent.

So the search restarts, with the advantages the new data brings:
  * 3,022,190 bars over 2,692 trading days
  * nine calendar years, covering bull, bear and chop regimes
  * enough trades that per-year profit factors are meaningful

Everything here is vectorised over the whole array rather than looping
per day, so a few dozen variants run in seconds instead of minutes.

The bar for accepting a strategy is deliberately strict: it must be
profitable in the 2018-2022 training era AND hold up in 2023-2024 AND
in the 2025-2026 holdout. A strategy that only works in the recent bull
market is exactly what just failed, and will not be counted as a success
a second time.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd


COMM = 0.07
SLIP = 0.02      # both sides


def prep(path):
    df = pd.read_pickle(path) if path.endswith(".pkl") else pd.read_parquet(path)
    df = df.reset_index(drop=True)
    return df


def fwd_ret(close, k):
    n = len(close)
    f = np.full(n, np.nan)
    f[:n - k] = close[k:] - close[:n - k]
    return f


def roll(a, w, fn):
    s = pd.Series(a)
    return getattr(s.rolling(w, min_periods=w), fn)().to_numpy()


RESULTS = []


def ev(name, sig, f, cost, year, gap_ok):
    m = (sig != 0) & np.isfinite(f) & gap_ok
    n = int(m.sum())
    if n < 300:
        print(f"  {name:<46} n={n:>8,}  too few")
        return
    net = f[m] * sig[m] - cost[m]
    y = year[m]

    def pf(x):
        w = x[x > 0].sum()
        l = abs(x[x <= 0].sum())
        return (w / l) if l else np.inf

    tr = net[np.isin(y, range(2018, 2023))]
    va = net[np.isin(y, (2023, 2024))]
    ho = net[np.isin(y, (2025, 2026))]
    if min(len(tr), len(va), len(ho)) < 50:
        print(f"  {name:<46} n={n:>8,}  thin era coverage")
        return
    row = (name, n, net.mean(), pf(net), 100 * (net > 0).mean(),
           pf(tr), pf(va), pf(ho))
    RESULTS.append(row)
    allpos = pf(tr) > 1 and pf(va) > 1 and pf(ho) > 1
    flag = "  <== ALL ERAS POSITIVE" if allpos else ""
    print(f"  {name:<46} n={n:>8,} net={net.mean():>+7.3f} "
          f"PF={pf(net):>5.2f} win={100*(net>0).mean():>5.1f}% | "
          f"tr{pf(tr):>5.2f} va{pf(va):>5.2f} ho{pf(ho):>5.2f}{flag}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/m1.pkl"
    df = prep(path)
    n = len(df)
    print(f"{n:,} M1 bars, {df['date'].nunique():,} days, "
          f"{df['year'].min()}-{df['year'].max()}")

    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    hour = df["hour"].to_numpy()
    year = df["year"].to_numpy()
    spread = df["spread"].to_numpy(float)
    tmin = df["dt"].astype("int64").to_numpy() // 60_000_000_000

    liquid = (hour >= 6) & (hour < 20)
    cost = spread + SLIP + COMM

    ret1 = np.diff(c, prepend=c[0])
    absret = np.abs(ret1)

    print(f"mean bar move ${absret.mean():.3f}  mean cost ${cost.mean():.3f}  "
          f"ratio {absret.mean()/cost.mean():.2f}x")

    # forward returns with gap protection
    fwds, gaps = {}, {}
    for k in (5, 15, 30, 60, 120, 240, 480):
        fwds[k] = fwd_ret(c, k)
        g = np.full(n, False)
        g[:n - k] = (tmin[k:] - tmin[:n - k]) <= k * 2
        gaps[k] = g

    print("\n" + "=" * 112)
    print("M1 STRATEGY SCAN -- must be positive in ALL THREE eras to count")
    print("=" * 112)

    # ---- momentum / reversion at several horizons -------------------- #
    for w in (15, 60, 240):
        past = c - np.roll(c, w); past[:w] = np.nan
        for k in (30, 120, 480):
            ev(f"Momentum {w}m -> {k}m", np.sign(np.nan_to_num(past)) * liquid,
               fwds[k], cost, year, gaps[k])
            ev(f"Revert   {w}m -> {k}m", -np.sign(np.nan_to_num(past)) * liquid,
               fwds[k], cost, year, gaps[k])

    # ---- z-score --------------------------------------------------- #
    for w in (60, 240):
        m = roll(c, w, "mean")
        s = roll(c, w, "std")
        z = (c - m) / np.where(s > 0, s, np.nan)
        for th in (1.5, 2.5):
            ev(f"Z{th} revert {w}m -> 60m",
               np.where(z > th, -1, np.where(z < -th, 1, 0)) * liquid,
               fwds[60], cost, year, gaps[60])
            ev(f"Z{th} moment {w}m -> 240m",
               np.where(z > th, 1, np.where(z < -th, -1, 0)) * liquid,
               fwds[240], cost, year, gaps[240])

    # ---- channel breakout / fade ------------------------------------ #
    for w in (60, 240, 480):
        hh = roll(h, w, "max")
        ll = roll(l, w, "min")
        brk = np.where(c > hh - 1e-9, 1, np.where(c < ll + 1e-9, -1, 0)) * liquid
        ev(f"Channel breakout {w}m -> 240m", brk, fwds[240], cost, year, gaps[240])
        ev(f"Channel fade     {w}m -> 60m", -brk, fwds[60], cost, year, gaps[60])

    # ---- volatility-conditioned momentum ---------------------------- #
    vol = roll(absret, 240, "mean")
    vq = pd.Series(vol).rolling(2400, min_periods=480).rank(pct=True).to_numpy()
    past60 = c - np.roll(c, 60); past60[:60] = np.nan
    s60 = np.sign(np.nan_to_num(past60))
    for lo_, hi_, lbl in ((0.0, 0.3, "lowvol"), (0.3, 0.7, "midvol"),
                          (0.7, 1.01, "highvol")):
        m = (vq >= lo_) & (vq < hi_) & liquid
        ev(f"{lbl} momentum 60m -> 240m", s60 * m, fwds[240], cost, year, gaps[240])
        ev(f"{lbl} revert   60m -> 60m", -s60 * m, fwds[60], cost, year, gaps[60])

    # ---- range-expansion -------------------------------------------- #
    rng = roll(h, 60, "max") - roll(l, 60, "min")
    rng_prev = np.roll(rng, 60)
    expand = rng > rng_prev * 1.5
    ev("Range expansion -> 240m", s60 * expand * liquid,
       fwds[240], cost, year, gaps[240])
    ev("Range contraction -> 240m", s60 * (~expand) * liquid,
       fwds[240], cost, year, gaps[240])

    # ---- gap / overnight -------------------------------------------- #
    dnum = df["date"].astype("int64").to_numpy()
    newday = np.concatenate([[False], np.diff(dnum) != 0])
    prev_close = np.roll(c, 1)
    gap = np.where(newday, c - prev_close, 0.0)
    gsig = np.sign(gap)
    ev("Gap continuation -> 240m", gsig, fwds[240], cost, year, gaps[240])
    ev("Gap fade -> 240m", -gsig, fwds[240], cost, year, gaps[240])

    # ---- day-of-week ------------------------------------------------ #
    dow = df["dow"].to_numpy()
    for d, nm in ((0, "Mon"), (2, "Wed"), (4, "Fri")):
        ev(f"{nm} momentum 60m -> 240m", s60 * (dow == d) * liquid,
           fwds[240], cost, year, gaps[240])

    # ---- hour-of-day trend ------------------------------------------ #
    for hh_ in (7, 13):
        ev(f"Hour {hh_:02d} momentum -> 240m", s60 * (hour == hh_),
           fwds[240], cost, year, gaps[240])

    # ---- long-horizon trend (the one thing cost can't kill) --------- #
    for w in (480, 1440, 2880):
        past = c - np.roll(c, w); past[:w] = np.nan
        for k in (240, 480):
            ev(f"LongTrend {w}m -> {k}m", np.sign(np.nan_to_num(past)) * liquid,
               fwds[k], cost, year, gaps[k])

    # ---------------------------------------------------------------- #
    print("\n" + "=" * 112)
    print("STRATEGIES POSITIVE IN ALL THREE ERAS")
    print("=" * 112)
    good = [r for r in RESULTS if r[5] > 1 and r[6] > 1 and r[7] > 1]
    if not good:
        print("  NONE.")
    else:
        good.sort(key=lambda r: -min(r[5], r[6], r[7]))
        print(f"  {'strategy':<46} {'n':>8} {'net$':>8} {'PF':>6} "
              f"{'train':>6} {'valid':>6} {'hold':>6}")
        for r in good:
            print(f"  {r[0]:<46} {r[1]:>8,} {r[2]:>+8.3f} {r[3]:>6.2f} "
                  f"{r[5]:>6.2f} {r[6]:>6.2f} {r[7]:>6.2f}")

    print("\n  ranked by overall PF:")
    RESULTS.sort(key=lambda r: -r[3])
    for r in RESULTS[:12]:
        print(f"    {r[0]:<46} PF={r[3]:>5.2f} net=${r[2]:>+7.3f} n={r[1]:>8,}")


if __name__ == "__main__":
    main()
