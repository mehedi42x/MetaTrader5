"""
research4.py
============
Stage-4: make H1 (Asian-range -> London breakout) rigorous.

Stage 3 found the edge but measured it sloppily, in two ways that both
flatter the result and must be fixed before anything is trusted:

  1. DOLLAR BIAS. In 2026 gold trades near $4,084; in 2024 near $2,045.
     A $10 win in 2026 is the same *trade* as a $5 win in 2024. Reporting
     raw dollars makes the out-of-sample period look twice as good as it
     is. Everything here is therefore also reported in R-multiples
     (R = the Asian range), which is scale-free.

  2. TP/SL ORDERING. Stage 3 only knew the max favourable and max adverse
     excursion, not which came first, so it pessimistically assumed the
     stop always hit first. That is wrong in both directions. This version
     walks the actual second-by-second path and fills whichever level the
     price reaches first -- the real answer.

It then tests whether simple, non-curve-fitted filters improve the edge,
and reports train (2024) and test (2026) separately for every variant.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

COMM = 0.07
SLIP = 0.01

ASIA_START, ASIA_END = 0, 6      # UTC
LON_START, LON_END = 7, 16       # UTC entry window / forced exit


def load_grid(path: str):
    d = np.load(path)
    bid = d["bid"].astype(np.float64)
    ask = d["ask"].astype(np.float64)
    t = d["t"]
    dt = pd.to_datetime(t, unit="s")
    return pd.DataFrame({
        "t": t, "mid": 0.5 * (bid + ask), "spread": ask - bid,
        "date": dt.normalize(), "hour": dt.hour, "dt": dt,
    })


def simulate(df: pd.DataFrame, tp_k: float, sl_k: float,
             max_entry_hour: int = 15, range_filter=None):
    """Path-accurate simulation. Returns one row per traded day."""
    out = []
    for date, day in df.groupby("date", sort=True):
        asia = day[(day.hour >= ASIA_START) & (day.hour < ASIA_END)]
        lon = day[(day.hour >= LON_START) & (day.hour < LON_END)]
        if len(asia) < 3000 or len(lon) < 3000:
            continue
        hi, lo = asia["mid"].max(), asia["mid"].min()
        rng = hi - lo
        if rng <= 0:
            continue
        # scale-free range filter: range as a fraction of price
        rng_pct = rng / asia["mid"].mean() * 100
        if range_filter and not (range_filter[0] <= rng_pct <= range_filter[1]):
            continue

        m = lon["mid"].to_numpy()
        sp = lon["spread"].to_numpy()
        hr = lon["hour"].to_numpy()

        above = m > hi
        below = m < lo
        iu = int(np.argmax(above)) if above.any() else 10**9
        idn = int(np.argmax(below)) if below.any() else 10**9
        i = min(iu, idn)
        if i >= len(m) or hr[i] > max_entry_hour:
            continue
        side = 1 if iu < idn else -1

        entry = m[i]
        cost = sp[i] + SLIP + COMM
        tp = tp_k * rng
        sl = sl_k * rng

        # walk the path forward; first level touched wins
        fwd = (m[i:] - entry) * side
        hit_tp = np.argmax(fwd >= tp) if (fwd >= tp).any() else 10**9
        hit_sl = np.argmax(fwd <= -sl) if (fwd <= -sl).any() else 10**9
        if hit_tp < hit_sl:
            gross, exit_reason = tp, "tp"
        elif hit_sl < hit_tp:
            gross, exit_reason = -sl, "sl"
        else:
            gross, exit_reason = fwd[-1], "time"

        out.append({
            "date": date, "year": date.year, "side": side, "range": rng,
            "rng_pct": rng_pct, "entry_hour": int(hr[i]), "price": entry,
            "gross": gross, "cost": cost, "net": gross - cost,
            "R": (gross - cost) / rng, "exit": exit_reason,
        })
    return pd.DataFrame(out)


def stats(r: pd.DataFrame, label: str):
    if len(r) < 3:
        return None
    w = r[r.net > 0]["net"].sum()
    l = abs(r[r.net <= 0]["net"].sum())
    pf = w / l if l else np.inf
    return {
        "label": label, "n": len(r), "net": r["net"].mean(),
        "R": r["R"].mean(), "win": 100 * (r.net > 0).mean(), "pf": pf,
        "total": r["net"].sum(),
    }


def show(r: pd.DataFrame, title: str):
    print(f"\n  {title}")
    print(f"    {'period':<12} {'n':>4} {'meanNET':>9} {'meanR':>8} "
          f"{'win%':>7} {'PF':>6} {'total$':>9}")
    for lbl, sub in (("ALL", r), ("TRAIN 2024", r[r.year == 2024]),
                     ("TEST 2026", r[r.year == 2026])):
        s = stats(sub, lbl)
        if s:
            print(f"    {s['label']:<12} {s['n']:>4} {s['net']:>9.3f} "
                  f"{s['R']:>8.3f} {s['win']:>6.1f}% {s['pf']:>6.2f} "
                  f"{s['total']:>9.2f}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grid.npz"
    df = load_grid(path)
    print(f"grid {len(df):,} rows")

    print("\n" + "=" * 78)
    print("A. PATH-ACCURATE TP/SL GRID  (R-multiples: scale-free across eras)")
    print("=" * 78)
    print(f"  {'tp_k':>5} {'sl_k':>5} {'n':>4} | {'ALL R':>7} {'ALL PF':>7} | "
          f"{'TR R':>7} {'TR PF':>7} | {'TE R':>7} {'TE PF':>7}")
    grid = []
    for tp_k in (0.75, 1.0, 1.25, 1.5, 2.0):
        for sl_k in (0.5, 0.75, 1.0):
            r = simulate(df, tp_k, sl_k)
            a = stats(r, "a")
            tr = stats(r[r.year == 2024], "t")
            te = stats(r[r.year == 2026], "e")
            if not (a and tr and te):
                continue
            grid.append((tr["pf"], te["pf"], a["pf"], tp_k, sl_k, a["R"]))
            print(f"  {tp_k:>5} {sl_k:>5} {a['n']:>4} | {a['R']:>7.3f} "
                  f"{a['pf']:>7.2f} | {tr['R']:>7.3f} {tr['pf']:>7.2f} | "
                  f"{te['R']:>7.3f} {te['pf']:>7.2f}")

    # pick on TRAIN only -- never on test
    grid.sort(reverse=True)
    best_tr_pf, best_te_pf, best_a_pf, tp_k, sl_k, _ = grid[0]
    print(f"\n  Selected on TRAIN only: tp_k={tp_k} sl_k={sl_k} "
          f"(train PF {best_tr_pf:.2f}) -> test PF {best_te_pf:.2f}")

    print("\n" + "=" * 78)
    print("B. FILTERS  (each applied to the train-selected tp/sl)")
    print("=" * 78)
    base = simulate(df, tp_k, sl_k)
    show(base, "no filter")

    for lo, hi, name in ((0.0, 0.35, "quiet Asia (range < 0.35% of price)"),
                         (0.0, 0.50, "range < 0.50%"),
                         (0.20, 0.60, "range 0.20-0.60%"),
                         (0.35, 9.9, "wide Asia (range > 0.35%)")):
        r = simulate(df, tp_k, sl_k, range_filter=(lo, hi))
        if len(r) >= 10:
            show(r, name)

    for meh in (10, 12, 14):
        r = simulate(df, tp_k, sl_k, max_entry_hour=meh)
        show(r, f"entry only before {meh:02d}:00 UTC")

    print("\n" + "=" * 78)
    print("C. EXIT REASON MIX (base config)")
    print("=" * 78)
    print(base.groupby(["year", "exit"]).size().to_string())
    print("\n  by side:")
    print(base.groupby(["year", "side"])["net"].agg(["count", "mean"]).to_string())


if __name__ == "__main__":
    main()
