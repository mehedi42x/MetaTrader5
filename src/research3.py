"""
research3.py
============
Stage-3: test structurally different hypotheses, with honest train/test split.

Stage 2 killed the plain breakout: inside every sane bucket the net edge was
<= 0. The one "positive" cell (low-vol / WIDE-spread, net +$0.262) is almost
certainly an artefact -- wide spreads occur at the 21:00-22:00 UTC rollover,
where the mid jumps because market makers pull quotes, not because gold moved.
Hypothesis H0 below tests exactly that before anything is built on it.

The remaining hypotheses are structural rather than "past return sign":

  H1  Session range breakout. Gold's Asian session (00:00-06:00 UTC) is quiet
      and range-bound; London (07:00+) supplies real volume. Breaking the
      Asian range at the London open is a classic, economically motivated
      setup -- and it trades at 07:00-12:00, exactly the cheapest spread
      hours found in stage 1.

  H2  Hour-of-day directional drift, fitted on 2024 and tested on 2026.

  H3  Overnight gap continuation / reversal.

Everything reports TRAIN (2024) and TEST (2026) separately. A result that
only exists in train is noise, and is reported as such.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

COMM = 0.07
SLIP = 0.01


def load_grid(path: str):
    d = np.load(path)
    bid = d["bid"].astype(np.float64)
    ask = d["ask"].astype(np.float64)
    t = d["t"]
    df = pd.DataFrame({"t": t, "bid": bid, "ask": ask})
    df["mid"] = 0.5 * (bid + ask)
    df["spread"] = ask - bid
    dt = pd.to_datetime(t, unit="s")
    df["dt"] = dt
    df["date"] = dt.normalize()
    df["hour"] = dt.hour
    df["dow"] = dt.dayofweek
    return df


# --------------------------------------------------------------------------- #
def h0_rollover_artifact(df: pd.DataFrame):
    print("\n" + "=" * 78)
    print("H0  Is the 'wide spread' edge just the rollover artefact?")
    print("=" * 78)
    wide = df["spread"] > df["spread"].quantile(0.90)
    byhour = df[wide].groupby("hour").size()
    tot = df.groupby("hour").size()
    frac = (byhour / tot * 100).fillna(0)
    print("  share of each hour that is in the widest 10% of spreads:")
    for h in range(24):
        bar = "#" * int(frac.get(h, 0) / 2)
        print(f"    {h:02d}h {frac.get(h,0):5.1f}%  {bar}")
    top = frac.sort_values(ascending=False).head(4)
    print(f"\n  --> concentrated in hours {list(top.index)}")
    print("  Those are rollover / illiquid hours. Mid-price 'moves' there are")
    print("  quote withdrawal, not tradable movement. EXCLUDED from now on.")


# --------------------------------------------------------------------------- #
def h1_session_breakout(df: pd.DataFrame):
    print("\n" + "=" * 78)
    print("H1  ASIAN RANGE BREAKOUT -> LONDON  (train 2024 / test 2026)")
    print("=" * 78)

    rows = []
    for date, day in df.groupby("date"):
        asia = day[(day["hour"] >= 0) & (day["hour"] < 6)]
        lon = day[(day["hour"] >= 7) & (day["hour"] < 16)]
        if len(asia) < 3000 or len(lon) < 3000:
            continue
        hi, lo = asia["mid"].max(), asia["mid"].min()
        rng = hi - lo
        if rng <= 0:
            continue

        m = lon["mid"].to_numpy()
        sp = lon["spread"].to_numpy()
        tt = lon["t"].to_numpy()

        up = np.argmax(m > hi) if (m > hi).any() else -1
        dn = np.argmax(m < lo) if (m < lo).any() else -1
        if up < 0 and dn < 0:
            continue
        if up >= 0 and (dn < 0 or up < dn):
            i, side = up, 1
        else:
            i, side = dn, -1

        entry = m[i]
        ent_sp = sp[i]
        # exit at 16:00 UTC (end of the London window)
        exit_px = m[-1]
        gross = (exit_px - entry) * side
        # also record the best excursion for target design
        fwd = (m[i:] - entry) * side
        rows.append({
            "date": date, "range": rng, "side": side, "entry": entry,
            "gross": gross, "spread": ent_sp,
            "mfe": fwd.max(), "mae": fwd.min(),
            "hold_h": (tt[-1] - tt[i]) / 3600,
            "year": date.year,
        })

    r = pd.DataFrame(rows)
    if r.empty:
        print("  no valid days")
        return None
    r["cost"] = r["spread"] + SLIP + COMM
    r["net"] = r["gross"] - r["cost"]

    print(f"  days with a breakout: {len(r)}")
    print(f"  median Asian range: ${r['range'].median():.2f}   "
          f"median cost ${r['cost'].median():.3f}")

    for label, sub in (("ALL", r), ("TRAIN 2024", r[r.year == 2024]),
                       ("TEST 2026", r[r.year == 2026])):
        if len(sub) < 5:
            continue
        w = sub[sub.net > 0]["net"].sum()
        l = abs(sub[sub.net <= 0]["net"].sum())
        pf = w / l if l else np.inf
        print(f"\n  {label}: n={len(sub)}")
        print(f"    mean gross ${sub['gross'].mean():+.3f}  "
              f"mean NET ${sub['net'].mean():+.3f}  "
              f"win {100*(sub['net']>0).mean():.1f}%  PF {pf:.2f}")
        print(f"    mean MFE ${sub['mfe'].mean():.2f}  "
              f"mean MAE ${sub['mae'].mean():.2f}")
    return r


def h1_with_targets(r: pd.DataFrame):
    """Does a sensible stop/target beat holding to the close?"""
    if r is None or r.empty:
        return
    print("\n" + "=" * 78)
    print("H1b  Same setup, but with a target/stop as a multiple of the range")
    print("=" * 78)
    print(f"  {'tp_k':>5} {'sl_k':>5} {'n':>5} {'meanNET':>9} {'win%':>7} {'PF':>6}"
          f"   {'TEST net':>9} {'TESTpf':>7}")
    best = []
    for tp_k in (0.5, 0.75, 1.0, 1.5):
        for sl_k in (0.4, 0.6, 0.8):
            pnl, yrs = [], []
            for _, row in r.iterrows():
                tp = tp_k * row["range"]
                sl = sl_k * row["range"]
                if row["mae"] <= -sl and row["mfe"] >= tp:
                    g = -sl          # conservative: assume stop hit first
                elif row["mfe"] >= tp:
                    g = tp
                elif row["mae"] <= -sl:
                    g = -sl
                else:
                    g = row["gross"]
                pnl.append(g - row["cost"])
                yrs.append(row["year"])
            pnl = np.array(pnl)
            yrs = np.array(yrs)
            w = pnl[pnl > 0].sum()
            l = abs(pnl[pnl <= 0].sum())
            pf = w / l if l else np.inf
            te = pnl[yrs == 2026]
            tw = te[te > 0].sum()
            tl = abs(te[te <= 0].sum())
            tpf = tw / tl if tl else np.inf
            best.append((pnl.mean(), tp_k, sl_k, pf, tpf, len(pnl)))
            print(f"  {tp_k:>5} {sl_k:>5} {len(pnl):>5} {pnl.mean():>9.3f} "
                  f"{100*(pnl>0).mean():>6.1f}% {pf:>6.2f}   "
                  f"{te.mean() if len(te) else float('nan'):>9.3f} {tpf:>7.2f}")
    best.sort(reverse=True)
    print("\n  BEST by mean net:")
    for b in best[:3]:
        print(f"    net ${b[0]:+.3f}  tp_k={b[1]} sl_k={b[2]}  "
              f"PF(all)={b[3]:.2f} PF(test2026)={b[4]:.2f}")


# --------------------------------------------------------------------------- #
def h2_hour_drift(df: pd.DataFrame):
    print("\n" + "=" * 78)
    print("H2  HOUR-OF-DAY DRIFT  (fit 2024, verify 2026)")
    print("=" * 78)
    d = df[(df.hour < 20)].copy()
    d["h_ret"] = d.groupby([d.date, d.hour])["mid"].transform("last") - \
        d.groupby([d.date, d.hour])["mid"].transform("first")
    hr = d.groupby([d.date, d.hour]).agg(ret=("h_ret", "first")).reset_index()
    hr["year"] = pd.to_datetime(hr["date"]).dt.year
    tr = hr[hr.year == 2024].groupby("hour")["ret"].agg(["mean", "count"])
    te = hr[hr.year == 2026].groupby("hour")["ret"].agg(["mean", "count"])
    print(f"  {'hour':>5} {'2024 mean':>11} {'n':>5} {'2026 mean':>11} {'n':>5} {'agree':>7}")
    agree = 0
    tot = 0
    for h in sorted(set(tr.index) & set(te.index)):
        a, b = tr.loc[h, "mean"], te.loc[h, "mean"]
        ok = np.sign(a) == np.sign(b)
        agree += ok
        tot += 1
        print(f"  {h:>5} {a:>11.3f} {int(tr.loc[h,'count']):>5} "
              f"{b:>11.3f} {int(te.loc[h,'count']):>5} {'YES' if ok else 'no':>7}")
    print(f"\n  sign agreement train->test: {agree}/{tot} "
          f"({100*agree/max(tot,1):.0f}%)  [50% = coin flip]")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grid.npz"
    df = load_grid(path)
    print(f"grid {len(df):,} rows  {df.dt.iloc[0]} -> {df.dt.iloc[-1]}")
    h0_rollover_artifact(df)
    r = h1_session_breakout(df)
    h1_with_targets(r)
    h2_hour_drift(df)


if __name__ == "__main__":
    main()
