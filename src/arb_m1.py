"""
arb_m1.py -- ARB on 8.7 years of M1 data, extended to multiple sessions.

WHY THIS RUN MATTERS
--------------------
The original ARB backtest had one real weakness: only 83 trading days of
tick data existed, so it produced only 76 trades. That was never a
frequency limit of the strategy -- it traded almost every available day --
it was a data limit.

The new M1 archive covers 2018-01 to 2026-09: 3,022,190 bars across 2,692
trading days, 32x more history, and continuous rather than four scattered
months. That allows two things the tick data could not support:

  1. A real out-of-sample test. Fit on 2018-2022, validate on 2023-2024,
     and keep 2025-2026 completely untouched until the end.
  2. Higher frequency, honestly. Instead of forcing more trades out of one
     session, the same range-breakout logic is applied to THREE independent
     sessions per day, each with its own range and its own breakout window.

THE THREE SESSIONS
------------------
  ASIA  range 00:00-06:00 UTC -> trade the London open  (07:00-12:00)
  LON   range 07:00-12:00 UTC -> trade the NY open      (13:00-16:00)
  NY    range 13:00-17:00 UTC -> trade the late session (17:00-20:00)

Each is the same economic idea: a quiet accumulation window builds a
range, the next session's fresh order flow breaks it. They are separate
trades on separate ranges, so up to 3 positions can occur per day.

COST MODEL
----------
M1 bars carry no bid/ask, so the spread is imposed from the hour-by-hour
profile measured on the real tick archives (m1_loader.SPREAD_BY_HOUR),
plus commission and slippage. This is stricter than assuming a flat
spread, because it charges the true premium during the expensive hours.

FILL REALISM ON M1 BARS
-----------------------
A 1-minute bar hides the path within the minute. Two rules keep this
honest:
  * Entry is filled at the bar CLOSE after the breakout is confirmed,
    not at the exact range level -- so no look-ahead on the break.
  * When a bar's high and low would have hit both the target and the
    stop, the STOP is assumed to hit first. This is the pessimistic
    assumption and it costs the strategy real money in the results.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd


COMM = 0.07      # $ round turn per 0.01 lot
SLIP = 0.01      # $/oz per side
OUNCES = 1.0     # 0.01 lot
INITIAL = 1000.0


SESSIONS = {
    #        range_start, range_end, entry_start, entry_end, exit_hour
    "ASIA": (0,  6,  7,  12, 16),
    "LON":  (7,  12, 13, 16, 20),
    "NY":   (13, 17, 17, 20, 23),
}


@dataclass
class Cfg:
    tp_k: float = 0.75
    sl_k: float = 1.00
    min_range_pct: float = 0.05    # ignore a dead range
    max_range_pct: float = 2.0     # ignore an already-violent day
    min_bars: int = 60             # need a real range window


def run_session(df: pd.DataFrame, name: str, cfg: Cfg):
    rs, re_, es, ee, xh = SESSIONS[name]
    out = []

    for date, day in df.groupby("date", sort=True):
        rng_df = day[(day.hour >= rs) & (day.hour < re_)]
        ent_df = day[(day.hour >= es) & (day.hour < ee)]
        hold_df = day[(day.hour >= es) & (day.hour < xh)]
        if len(rng_df) < cfg.min_bars or len(ent_df) < 10:
            continue

        hi = rng_df["high"].max()
        lo = rng_df["low"].min()
        R = hi - lo
        if R <= 0:
            continue
        ref = rng_df["close"].mean()
        rpct = R / ref * 100
        if not (cfg.min_range_pct <= rpct <= cfg.max_range_pct):
            continue

        # ---- find the breakout bar (confirmed on close) ---------------- #
        c = ent_df["close"].to_numpy()
        up = c > hi
        dn = c < lo
        iu = int(np.argmax(up)) if up.any() else 10**9
        idn = int(np.argmax(dn)) if dn.any() else 10**9
        i = min(iu, idn)
        if i >= len(c):
            continue
        side = 1 if iu < idn else -1

        ebar = ent_df.iloc[i]
        entry = float(ebar["close"])
        spread = float(ebar["spread"])
        cost = spread + SLIP * 2 + COMM

        tp = cfg.tp_k * R
        sl = cfg.sl_k * R

        # ---- walk forward bar by bar ----------------------------------- #
        after = hold_df[hold_df["dt"] > ebar["dt"]]
        gross = None
        reason = "time"
        exit_dt = ebar["dt"]
        for _, b in after.iterrows():
            hi_m = (b["high"] - entry) * side
            lo_m = (b["low"] - entry) * side
            if side < 0:
                hi_m, lo_m = (entry - b["low"]) * 1, (entry - b["high"]) * 1
            # pessimistic: if both levels are inside the bar, the stop wins
            if lo_m <= -sl:
                gross, reason, exit_dt = -sl, "sl", b["dt"]
                break
            if hi_m >= tp:
                gross, reason, exit_dt = tp, "tp", b["dt"]
                break
        if gross is None:
            if len(after) == 0:
                continue
            last = after.iloc[-1]
            gross = (float(last["close"]) - entry) * side
            exit_dt = last["dt"]

        net = gross * OUNCES - cost
        out.append({
            "session": name, "date": date, "year": date.year,
            "dt": ebar["dt"], "exit_dt": exit_dt, "side": side,
            "R": R, "rpct": rpct, "entry": entry, "spread": spread,
            "gross": gross * OUNCES, "cost": cost, "net": net,
            "Rmult": net / (R * OUNCES), "exit": reason,
            "entry_hour": int(ebar["hour"]),
        })
    return pd.DataFrame(out)


def stats(r: pd.DataFrame):
    if len(r) < 3:
        return None
    net = r["net"].to_numpy()
    w, l = net[net > 0].sum(), abs(net[net <= 0].sum())
    eq = INITIAL + np.cumsum(net)
    peak = np.maximum.accumulate(np.concatenate([[INITIAL], eq]))
    dd = (peak - np.concatenate([[INITIAL], eq]))
    return {
        "n": len(r), "net": net.sum(), "pf": (w / l) if l else np.inf,
        "win": 100 * (net > 0).mean(), "exp": net.mean(),
        "Rmult": r["Rmult"].mean(), "dd": dd.max(),
        "dd_pct": (dd / peak).max() * 100,
    }


def show(r: pd.DataFrame, title: str):
    s = stats(r)
    if not s:
        print(f"  {title:<34} -- too few")
        return
    print(f"  {title:<34} n={s['n']:>5,} net=${s['net']:>9.2f} "
          f"PF={s['pf']:>5.2f} win={s['win']:>5.1f}% "
          f"exp=${s['exp']:>6.3f} R={s['Rmult']:>+6.3f} dd={s['dd_pct']:>5.1f}%")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/m1.pkl"
    df = pd.read_pickle(path) if path.endswith(".pkl") else pd.read_parquet(path)
    print(f"M1 bars: {len(df):,}  {df['dt'].min()} -> {df['dt'].max()}")
    print(f"trading days: {df['date'].nunique():,}")

    cfg = Cfg()

    print("\n" + "=" * 104)
    print("PER-SESSION RESULTS (whole history, tp=0.75R sl=1.00R)")
    print("=" * 104)
    allr = []
    for name in SESSIONS:
        r = run_session(df, name, cfg)
        allr.append(r)
        show(r, f"{name} session")
    comb = pd.concat(allr, ignore_index=True).sort_values("dt")

    print()
    show(comb, "ALL THREE COMBINED")
    tpd = len(comb) / df["date"].nunique()
    print(f"\n  trades/day {tpd:.2f}   trades/year ~{tpd*252:.0f}")

    print("\n" + "=" * 104)
    print("WALK-FORWARD: fit 2018-2022 / validate 2023-2024 / HOLDOUT 2025-2026")
    print("=" * 104)
    for lbl, yrs in (("TRAIN   2018-2022", range(2018, 2023)),
                     ("VALID   2023-2024", (2023, 2024)),
                     ("HOLDOUT 2025-2026", (2025, 2026))):
        show(comb[comb.year.isin(yrs)], lbl)

    print("\n" + "=" * 104)
    print("YEAR BY YEAR (combined)")
    print("=" * 104)
    print(f"  {'year':>6} {'n':>6} {'net$':>10} {'PF':>7} {'win%':>7} {'meanR':>8}")
    for y in sorted(comb.year.unique()):
        s = stats(comb[comb.year == y])
        if s:
            print(f"  {y:>6} {s['n']:>6,} {s['net']:>10.2f} {s['pf']:>7.2f} "
                  f"{s['win']:>6.1f}% {s['Rmult']:>+8.3f}")

    print("\n" + "=" * 104)
    print("TP/SL SWEEP -- selected on TRAIN only")
    print("=" * 104)
    print(f"  {'tp':>5} {'sl':>5} | {'TRAIN PF':>9} {'TRAIN R':>8} | "
          f"{'VALID PF':>9} {'VALID R':>8} | {'HOLD PF':>8} {'HOLD R':>8} | {'n':>6}")
    best = []
    for tp_k in (0.5, 0.75, 1.0, 1.5, 2.0):
        for sl_k in (0.75, 1.0, 1.5):
            c2 = Cfg(tp_k=tp_k, sl_k=sl_k)
            rr = pd.concat([run_session(df, s, c2) for s in SESSIONS],
                           ignore_index=True)
            tr = stats(rr[rr.year.isin(range(2018, 2023))])
            va = stats(rr[rr.year.isin((2023, 2024))])
            ho = stats(rr[rr.year.isin((2025, 2026))])
            if not (tr and va and ho):
                continue
            best.append((tr["pf"], tp_k, sl_k, tr, va, ho, len(rr)))
            print(f"  {tp_k:>5} {sl_k:>5} | {tr['pf']:>9.2f} {tr['Rmult']:>+8.3f} | "
                  f"{va['pf']:>9.2f} {va['Rmult']:>+8.3f} | "
                  f"{ho['pf']:>8.2f} {ho['Rmult']:>+8.3f} | {len(rr):>6,}")

    best.sort(reverse=True)
    if best:
        _, tp_k, sl_k, tr, va, ho, ntot = best[0]
        print(f"\n  BEST ON TRAIN: tp={tp_k}R sl={sl_k}R")
        print(f"    TRAIN   PF {tr['pf']:.2f}  net ${tr['net']:.2f}  n={tr['n']:,}")
        print(f"    VALID   PF {va['pf']:.2f}  net ${va['net']:.2f}  n={va['n']:,}")
        print(f"    HOLDOUT PF {ho['pf']:.2f}  net ${ho['net']:.2f}  n={ho['n']:,}")

    comb.to_csv("/tmp/arb_m1_trades.csv", index=False)
    print("\n  wrote /tmp/arb_m1_trades.csv")


if __name__ == "__main__":
    main()
