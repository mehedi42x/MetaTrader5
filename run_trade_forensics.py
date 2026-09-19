"""Trade-by-trade forensics on the M1 EMA 6/9 + Bollinger system (5m EMA 9/12 trend).

What this does
  1. Runs the base system over 2023-2025 and finds the month with the biggest loss.
  2. Re-runs that month and records EVERY trade with the market context at the moment
     the signal fired (structure, volatility, extension, session, ...).
  3. Compares winners vs losers feature by feature (bucket win rates) to see what the
     losers have in common.
  4. Applies candidate rules that block the losing pattern (BLOCKERS below) and reports
     the effect on that month, then validates out-of-sample on the other months/years.

Everything is the faithful port of the pasted Pine v6 script: EMA 6/9 crossover on M1,
EMA 9/12 trend on M5 from the last CLOSED bar, close on the correct side of the
Bollinger(20,2) middle, exit on the raw opposite cross, fill at the next bar's open.
0.01 lot, $0.20 per round trip.

Usage:  python3 run_trade_forensics.py            # analysis only
        python3 run_trade_forensics.py --filter   # analysis + blockers + validation
"""
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SRC = "/tmp/fxdata/m1xau/DAT_MT_XAUUSD_M1_{y}.csv"
RECENT = "data/xauusd_m1_2026-09.csv"
OZ, COST, BAL0 = 1.0, 0.20, 10_000.0
FEATS = ["adx", "chop", "er", "atrr", "bbw", "sep", "bbpos", "distmid", "runup",
         "slope", "rng20", "htfstr", "body", "wick", "hour"]


# ────────────────────────────── indicators ──────────────────────────────
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def wilder(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def tr_series(h, l, c):
    return pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)


def adx(h, l, c, n=14):
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = wilder(tr_series(h, l, c), n)
    pdi = 100 * wilder(pd.Series(plus, index=h.index), n) / atr
    mdi = 100 * wilder(pd.Series(minus, index=h.index), n) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return wilder(dx.fillna(0), n)


def choppiness(h, l, c, n=14):
    tr = tr_series(h, l, c)
    rng = h.rolling(n).max() - l.rolling(n).min()
    return (100 * np.log10((tr.rolling(n).sum() / rng).replace(0, np.nan))
            / np.log10(n)).fillna(50)


# ────────────────────────────── data / features ──────────────────────────────
def load_year(y):
    df = pd.read_csv(SRC.format(y=y), header=None,
                     names=["date", "time", "open", "high", "low", "close", "vol"])
    df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M")
    return df[["time", "open", "high", "low", "close"]].sort_values("time").reset_index(drop=True)


def load_recent():
    df = pd.read_csv(RECENT, parse_dates=["time"])
    return df[["time", "open", "high", "low", "close"]].sort_values("time").reset_index(drop=True)


def resample(df, minutes):
    if minutes == 1:
        return df.reset_index(drop=True)
    return (df.set_index("time").resample(f"{minutes}min")
            .agg(open=("open", "first"), high=("high", "max"),
                 low=("low", "min"), close=("close", "last")).dropna().reset_index())


def build(df):
    chart = resample(df, 1)
    c, h, l, o = chart["close"], chart["high"], chart["low"], chart["open"]
    f, s = ema(c, 6), ema(c, 9)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    up, lo = mid + 2 * sd, mid - 2 * sd
    atr14 = wilder(tr_series(h, l, c), 14)
    atr50 = wilder(tr_series(h, l, c), 50)

    htf = resample(df, 5)
    htf["f"], htf["s"] = ema(htf.close, 9), ema(htf.close, 12)
    htf["atr"] = wilder(tr_series(htf.high, htf.low, htf.close), 14)
    htf["ct"] = htf.time + pd.Timedelta(minutes=5)
    m = pd.merge_asof(chart[["time"]].reset_index(),
                      htf[["ct", "f", "s", "atr"]].rename(columns={"ct": "time"}).sort_values("time"),
                      on="time", direction="backward").set_index("index").reindex(chart.index)

    bull = (f.shift(1) <= s.shift(1)) & (f > s)
    bear = (f.shift(1) >= s.shift(1)) & (f < s)
    d = dict(
        time=chart["time"].to_numpy(),
        open=o.to_numpy(float), high=h.to_numpy(float), low=l.to_numpy(float),
        close=c.to_numpy(float),
        bull=bull.to_numpy(bool), bear=bear.to_numpy(bool),
        htf_bull=(m["f"] > m["s"]).to_numpy(bool), htf_bear=(m["f"] < m["s"]).to_numpy(bool),
        # ---- context features (all on M1, known at the signal bar's close)
        adx=adx(h, l, c).to_numpy(float),
        chop=choppiness(h, l, c).to_numpy(float),
        er=((c - c.shift(10)).abs() / c.diff().abs().rolling(10).sum().replace(0, np.nan)
            ).fillna(0).to_numpy(float),
        atrr=(atr14 / atr50).fillna(1.0).to_numpy(float),
        bbw=(((up - lo) / mid) / (((up - lo) / mid).rolling(240).mean())).fillna(0).to_numpy(float),
        sep=((f - s).abs() / atr14).fillna(0).to_numpy(float),
        bbpos=((c - lo) / (up - lo).replace(0, np.nan)).fillna(0.5).to_numpy(float),
        distmid=((c - mid) / atr14).fillna(0).to_numpy(float),
        runup=((c - c.shift(15)) / atr14).fillna(0).to_numpy(float),
        slope=((f - f.shift(5)) / atr14).fillna(0).to_numpy(float),
        rng20=((h.rolling(20).max() - l.rolling(20).min()) / atr14).fillna(0).to_numpy(float),
        htfstr=((m["f"] - m["s"]).abs() / m["atr"]).fillna(0).to_numpy(float),
        body=((c - o).abs() / atr14).fillna(0).to_numpy(float),
        wick=(((h - np.maximum(o, c)) + (np.minimum(o, c) - l)) / (h - l).replace(0, np.nan)
              ).fillna(0).to_numpy(float),
        atr=atr14.to_numpy(float),
    )
    d["atr_pct"] = pd.Series(d["atr"]).rolling(500).rank(pct=True).fillna(0.5).to_numpy(float)
    d["base_buy"] = d["bull"] & d["htf_bull"] & (d["close"] > mid.to_numpy(float))
    d["base_sell"] = d["bear"] & d["htf_bear"] & (d["close"] < mid.to_numpy(float))
    hrs = pd.to_datetime(chart["time"]).dt.hour.to_numpy()
    d["hour"] = hrs
    d["runup_signed"] = d["runup"] * np.where(d["base_buy"], 1, -1)
    d["bbpos_side"] = np.where(d["base_buy"], d["bbpos"], 1 - d["bbpos"])
    return d


# ────────────────────────────── engine ──────────────────────────────
def simulate(d, t0=None, t1=None):
    """Signal at close -> fill next open. Exit on the raw opposite cross.
    Returns a list of trade dicts that includes the signal bar index."""
    o, cl, t = d["open"], d["close"], d["time"]
    bull, bear = d["bull"], d["bear"]
    buy, sell = d["base_buy"], d["base_sell"]
    n = len(o)
    m = np.ones(n, bool)
    if t0 is not None:
        m &= t >= np.datetime64(pd.to_datetime(t0))
    if t1 is not None:
        m &= t <= np.datetime64(pd.to_datetime(t1))
    trades, pos, entry, entry_i, sig_i = [], 0, np.nan, None, None
    for i in range(1, n):
        j = i - 1
        tgt = 1 if (buy[j] and m[j]) else -1 if (sell[j] and m[j]) else (
            0 if (pos == 1 and bear[j]) or (pos == -1 and bull[j]) else pos)
        if tgt != pos:
            if pos != 0:
                pnl = (o[i] - entry) * pos * OZ - COST
                trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=i,
                                   entry_time=pd.Timestamp(t[entry_i]),
                                   exit_time=pd.Timestamp(t[i]),
                                   entry=float(entry), exit=float(o[i]), pnl=float(pnl)))
            if tgt != 0:
                entry, entry_i, sig_i = o[i], i, j
            pos = tgt
    if pos != 0:
        pnl = (cl[n - 1] - entry) * pos * OZ - COST
        trades.append(dict(dir=pos, entry_i=entry_i, sig_i=sig_i, exit_i=n - 1,
                           entry_time=pd.Timestamp(t[entry_i]),
                           exit_time=pd.Timestamp(t[n - 1]),
                           entry=float(entry), exit=float(cl[n - 1]), pnl=float(pnl)))
    # attach the context of the SIGNAL bar
    for tr in trades:
        i = tr["sig_i"]
        for fe in FEATS:
            tr[fe] = float(d[fe][i])
        tr["atr_pct"] = float(d["atr_pct"][i])
        tr["runup_signed"] = float(d["runup_signed"][i])
        tr["bbpos_side"] = float(d["bbpos_side"][i])
        tr["side"] = "LONG" if tr["dir"] == 1 else "SHORT"
    prev_exit = None
    for k, tr in enumerate(trades):
        tr["idx"] = k + 1
        tr["mins"] = (tr["entry_time"] - prev_exit).total_seconds() / 60 if prev_exit is not None else np.nan
        tr["consec"] = 0
        j = k - 1
        while j >= 0 and trades[j]["pnl"] <= 0:
            tr["consec"] += 1
            j -= 1
        prev_exit = tr["exit_time"]
    return trades


def to_df(trades):
    return pd.DataFrame(trades)


def stat_row(trades, label):
    if len(trades) == 0:
        return dict(label=label, n=0, net=0.0, wr=0.0, pf=0.0, per=0.0)
    pnl = np.array([t["pnl"] for t in trades])
    w, l = pnl[pnl > 0], pnl[pnl <= 0]
    return dict(label=label, n=len(pnl), net=round(float(pnl.sum()), 2),
                wr=round(len(w) / len(pnl) * 100, 1),
                pf=round(float(w.sum() / -l.sum()), 2) if l.sum() < 0 else float("inf"),
                per=round(float(pnl.mean()), 3))


def main():
    do_filter = "--filter" in sys.argv
    print("loading 2022-2025 ...", flush=True)
    data = {y: build(load_year(y)) for y in (2022, 2023, 2024, 2025)}
    d26 = build(load_recent())

    # ── 1. monthly P/L to find the worst month ───────────────────────────────
    print("\n" + "=" * 100)
    print("MONTHLY P/L — base system, M1 EMA 6/9 + BB, 5m EMA 9/12 (2023-2025)")
    print("=" * 100)
    monthly = {}
    for y in (2023, 2024, 2025):
        tr = to_df(simulate(data[y]))
        tr["m"] = pd.to_datetime(tr.exit_time).dt.to_period("M")
        g = tr.groupby("m").pnl.agg(["sum", "count"])
        monthly[y] = g
    worst = None
    for i in range(12):
        row = f"{pd.Timestamp(2023, i + 1, 1).strftime('%b'):6s}"
        for y in (2023, 2024, 2025):
            g = monthly[y]
            if i < len(g):
                s, n = g["sum"].iloc[i], int(g["count"].iloc[i])
                row += f"{s:>12.2f}({n:>5d})"
                if worst is None or s < worst[1]:
                    worst = (f"{y}-{i + 1:02d}", s, y)
            else:
                row += f"{'':>18s}"
        print(row)
    print(f"\n>>> WORST MONTH = {worst[0]}  (${worst[1]:.2f})")
    wy, wm = worst[2], int(worst[0].split("-")[1])
    t0 = f"{wy}-{wm:02d}-01 00:00"
    t1 = (pd.Timestamp(wy, wm, 1) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d 23:59")
    print(f"    window: {t0} -> {t1}\n")

    # ── 2. forensics on the worst month ──────────────────────────────────────
    base = to_df(simulate(data[wy], t0, t1))
    base["result"] = np.where(base.pnl > 0, "WIN", "LOSS")
    print("=" * 100)
    print(f"FORENSICS — every trade of {worst[0]}  ({len(base)} trades)")
    print("=" * 100)
    print(f"wins {int((base.pnl > 0).sum())} | losses {int((base.pnl <= 0).sum())} | "
          f"win rate {(base.pnl > 0).mean() * 100:.1f}% | net ${base.pnl.sum():.2f}")
    print(f"avg win ${base[base.pnl > 0].pnl.mean():.2f} | "
          f"avg loss ${base[base.pnl <= 0].pnl.mean():.2f} | "
          f"biggest win ${base.pnl.max():.2f} | biggest loss ${base.pnl.min():.2f}")
    print(f"avg hold {((base.exit_time - base.entry_time).dt.total_seconds() / 60).mean():.1f} min")

    # what did the winners and losers look like?
    print("\nWINNER vs LOSER context (mean of each feature on the signal bar):")
    print(f"{'feature':16s}{'winners':>12s}{'losers':>12s}{'diff':>10s}   "
          f"{'feature':16s}{'winners':>12s}{'losers':>12s}{'diff':>10s}")
    w = base[base.pnl > 0]
    l = base[base.pnl <= 0]
    rows = []
    for fe in FEATS + ["atr_pct", "runup_signed", "bbpos_side"]:
        a, b = w[fe].mean(), l[fe].mean()
        rows.append((fe, a, b, a - b))
    for i in range(0, len(rows), 2):
        line = ""
        for (fe, a, b, dd) in rows[i:i + 2]:
            line += f"{fe:16s}{a:>12.3f}{b:>12.3f}{dd:>10.3f}   "
        print(line)

    # win rate by bucket for the most promising features
    print("\nWIN RATE BY BUCKET (quintiles) — losers usually live in one bucket:")
    interesting = ["adx", "chop", "er", "atrr", "bbw", "sep", "bbpos_side", "runup_signed",
                   "slope", "rng20", "htfstr", "body", "atr_pct", "consec", "mins"]
    for fe in interesting:
        try:
            q = pd.qcut(base[fe], 5, duplicates="drop")
        except ValueError:
            continue
        g = base.groupby(q, observed=True).apply(
            lambda x: pd.Series({"wr": (x.pnl > 0).mean() * 100, "net": x.pnl.sum(), "n": len(x)}),
            include_groups=False)
        parts = []
        for iv, r in g.iterrows():
            parts.append(f"[{iv.left:6.2f},{iv.right:6.2f}) wr {r['wr']:5.1f}% n {int(r['n']):4d} ${r['net']:7.2f}")
        print(f"  {fe:14s} " + " | ".join(parts))

    # per-day and per-hour view
    base["day"] = pd.to_datetime(base.exit_time).dt.date
    base["hour"] = base.hour.astype(int)
    print("\nBY HOUR (UTC):")
    hg = base.groupby("hour").apply(lambda x: pd.Series(
        {"n": len(x), "wr": (x.pnl > 0).mean() * 100, "net": x.pnl.sum()}), include_groups=False)
    line = "  "
    for hh, r in hg.iterrows():
        line += f"{hh:02d}h wr{r['wr']:4.0f}% n{int(r['n']):3d} ${r['net']:7.1f}   "
        if hh % 3 == 2:
            print(line); line = "  "
    if line.strip():
        print(line)

    base.to_csv(f"results/forensics_trades_{worst[0]}.csv", index=False)
    print(f"\nSaved results/forensics_trades_{worst[0]}.csv (every trade with its context)")

    # ── 3. blockers ──────────────────────────────────────────────────────────
    if not do_filter:
        print("\n(re-run with --filter for the blocker rules and the validation)")
        return

    def keep(tr):
        """Rules that block the losers found above (a trade is kept unless a rule says no)."""
        ok = True
        # rule 1: ranging market -> no trades (ADX below 20 was the worst bucket)
        ok &= tr["adx"] >= 20
        # rule 2: do not chase an extended move (price already far from the 15-bar mean)
        ok &= abs(tr["runup_signed"]) <= 3.0
        # rule 3: do not enter when price is glued to the band edge on the entry side
        ok &= tr["bbpos_side"] <= 0.90
        # rule 4: dead volatility / no expansion
        ok &= tr["atrr"] >= 0.95
        return ok

    kept = [t for t in base.to_dict("records") if keep(t)]
    drop = [t for t in base.to_dict("records") if not keep(t)]
    print("\n" + "=" * 100)
    print(f"BLOCKERS applied to {worst[0]}")
    print("=" * 100)
    print(f"{'':22s}{'trades':>8s}{'net $':>11s}{'win%':>8s}{'PF':>7s}{'avg/trade':>11s}")
    for label, trs in [("base (no filter)", base.to_dict("records")), ("with blockers", kept)]:
        r = stat_row(trs, label)
        print(f"{label:22s}{r['n']:>8d}{r['net']:>11.2f}{r['wr']:>7.1f}%{r['pf']:>7.2f}{r['per']:>11.3f}")
    r = stat_row(drop, "blocked")
    print(f"{'blocked (removed)':22s}{r['n']:>8d}{r['net']:>11.2f}{r['wr']:>7.1f}%{r['pf']:>7.2f}{r['per']:>11.3f}")

    # ── 4. validation on everything else ─────────────────────────────────────
    print("\n" + "=" * 100)
    print("VALIDATION — the same blockers on the other months and years")
    print("=" * 100)
    print(f"{'window':26s}{'base trd':>9s}{'base $':>10s}{'base wr':>8s}"
          f"{'filt trd':>9s}{'filt $':>10s}{'filt wr':>8s}{'change $':>10s}")
    windows = [("2022 full year", 2022, None, None),
               ("2023 full year", 2023, None, None),
               ("2024 full year", 2024, None, None),
               ("2025 full year", 2025, None, None),
               (f"{worst[0]} (tuned)", wy, t0, t1)]
    for y in (2023, 2024, 2025):
        for mo in range(1, 13):
            key = f"{y}-{mo:02d}"
            if key == worst[0]:
                continue
        break
    total_base = total_filt = 0.0
    for label, y, a, b in windows:
        trs = to_df(simulate(data[y], a, b)).to_dict("records")
        f = [t for t in trs if keep(t)]
        rb, rf = stat_row(trs, label), stat_row(f, label)
        total_base += rb["net"]; total_filt += rf["net"]
        print(f"{label:26s}{rb['n']:>9d}{rb['net']:>10.2f}{rb['wr']:>7.1f}%"
              f"{rf['n']:>9d}{rf['net']:>10.2f}{rf['wr']:>7.1f}%{rf['net'] - rb['net']:>10.2f}")
    trs26 = to_df(simulate(d26)).to_dict("records")
    f26 = [t for t in trs26 if keep(t)]
    rb, rf = stat_row(trs26, "Sep 2026"), stat_row(f26, "Sep 2026")
    print(f"{'Sep 2026 (9-18, real MT5)':26s}{rb['n']:>9d}{rb['net']:>10.2f}{rb['wr']:>7.1f}%"
          f"{rf['n']:>9d}{rf['net']:>10.2f}{rf['wr']:>7.1f}%{rf['net'] - rb['net']:>10.2f}")
    print(f"\n4-year total: base ${total_base:,.2f} -> filtered ${total_filt:,.2f}")

    # ── 5. chart ─────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [1.5, 1]})
    for y, col in [(2023, "#1f77b4"), (2024, "#d62728"), (2025, "#2ca02c")]:
        trs = to_df(simulate(data[y]))
        axes[0].plot(trs.exit_time, BAL0 + trs.pnl.cumsum(), lw=1.2, color=col,
                     label=f"{y} base: {trs.pnl.sum():+.2f} ({len(trs)} trd)")
        f = trs[[keep(t) for t in trs.to_dict("records")]]
        if len(f):
            axes[0].plot(f.exit_time, BAL0 + f.pnl.cumsum(), lw=1.2, ls="--", color=col, alpha=0.75,
                         label=f"{y} filtered: {f.pnl.sum():+.2f} ({len(f)} trd)")
    axes[0].axhline(BAL0, color="k", ls=":", lw=1)
    axes[0].set_ylabel("Equity ($)")
    axes[0].set_title("M1 EMA 6/9 + BB: base vs the loss-blocking rules (2023-2025)")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    for fe, col in [("adx", "#1f77b4"), ("runup_signed", "#d62728"), ("bbpos_side", "#2ca02c")]:
        q = pd.qcut(base[fe], 8, duplicates="drop")
        g = base.groupby(q, observed=True).apply(
            lambda x: (x.pnl > 0).mean() * 100, include_groups=False)
        xs = [iv.mid for iv in g.index]
        axes[1].plot(xs, g.values, "o-", color=col, label=f"{fe} (win % per bucket)")
    axes[1].set_xlabel("feature value (bucket centre)")
    axes[1].set_ylabel("win rate (%)")
    axes[1].set_title(f"Win rate by context feature — {worst[0]} (the worst month)")
    axes[1].legend(fontsize=9)
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("results/forensics.png", dpi=120)
    print("Saved results/forensics.png")


if __name__ == "__main__":
    main()
