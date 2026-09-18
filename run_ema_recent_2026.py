"""EMA 6/9 + Bollinger on M1  with the EMA 9/12 trend on M5 — REAL recent data.

Data: data/xauusd_m1_2026-09.csv
      9,744 real XAUUSD M1 bars from an Exness MT5 feed (XAUUSDm), 2026-09-09 19:08
      -> 2026-09-18 20:54 UTC, reconstructed from the public mirror
      github.com/lbronight/xau-live-mirror (its commit history holds the live bars).
      Only the 1-hour daily break (20:58-21:59) and the weekend are missing, plus a
      couple of stray single minutes.

Windows reported:
      last 3 sessions : 16, 17, 18 September 2026 (Wed, Thu, Fri)
      last 5 sessions : 14-18 September 2026 (Mon-Fri)
      (19 September 2026 is a Saturday -> no data exists yet; the sandbox date is
       2026-09-18 21:xx UTC, i.e. just after the Friday close.)

Rules (exactly the pasted Pine script):
      entry : bullCross EMA(6)/EMA(9) on M1, EMA(9) > EMA(12) on M5 (last CLOSED bar),
              close above the Bollinger(20,2) middle  ->  BUY  (mirror for SELL)
      exit  : raw opposite EMA cross on M1
      fill  : next M1 bar's open
House rules: 0.01 lot (1 oz), $0.20 spread per round trip. The feed's own live spread
was 26 points ($0.26) at the time of the download, so a $0.26 variant is shown too.

Usage:  python3 run_ema_recent_2026.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

DATA = "data/xauusd_m1_2026-09.csv"
OZ, BAL0 = 1.0, 10_000.0
W3 = ("2026-09-16", "2026-09-18 23:59")        # last 3 sessions
W5 = ("2026-09-14", "2026-09-18 23:59")        # last 5 sessions


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def resample(df, minutes):
    if minutes == 1:
        return df.reset_index(drop=True)
    out = (df.set_index("time").resample(f"{minutes}min")
           .agg(open=("open", "first"), high=("high", "max"),
                low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
           .dropna().reset_index())
    return out


def run(df, chart_min, htf_min, cost):
    """Faithful port: signal at close -> fill next bar's open."""
    chart = resample(df, chart_min)
    htf = resample(df, htf_min)
    c = chart["close"]
    f, s = ema(c, 6).to_numpy(float), ema(c, 9).to_numpy(float)
    mid = c.rolling(20).mean().to_numpy(float)

    h = htf.copy()
    h["f"], h["s"] = ema(h.close, 9), ema(h.close, 12)
    h["ct"] = h.time + pd.Timedelta(minutes=htf_min)
    m = pd.merge_asof(chart[["time"]].reset_index(),
                      h[["ct", "f", "s"]].rename(columns={"ct": "time"}).sort_values("time"),
                      on="time", direction="backward").set_index("index").reindex(chart.index)
    hf, hs = m["f"].to_numpy(float), m["s"].to_numpy(float)

    bull = np.zeros(len(chart), bool); bear = np.zeros(len(chart), bool)
    bull[1:] = (f[:-1] <= s[:-1]) & (f[1:] > s[1:])
    bear[1:] = (f[:-1] >= s[:-1]) & (f[1:] < s[1:])
    buy = bull & (hf > hs) & (c.to_numpy(float) > mid)
    sell = bear & (hf < hs) & (c.to_numpy(float) < mid)

    o = chart.open.to_numpy(float); cl = c.to_numpy(float)
    trades, pos, entry, entry_t = [], 0, np.nan, None
    for i in range(1, len(chart)):
        j = i - 1
        tgt = 1 if buy[j] else -1 if sell[j] else (0 if (pos == 1 and bear[j]) or (pos == -1 and bull[j]) else pos)
        if tgt != pos:
            if pos != 0:
                trades.append(dict(entry_time=entry_t, exit_time=chart.time.iloc[i],
                                   side="LONG" if pos == 1 else "SHORT",
                                   entry=round(entry, 2), exit=round(o[i], 2),
                                   pnl=round((o[i] - entry) * pos * OZ - cost, 2),
                                   minutes=int((chart.time.iloc[i] - entry_t).total_seconds() // 60)))
            if tgt != 0:
                entry, entry_t = o[i], chart.time.iloc[i]
            pos = tgt
    if pos != 0:                       # mark to market at the last bar
        trades.append(dict(entry_time=entry_t, exit_time=chart.time.iloc[-1],
                           side="LONG" if pos == 1 else "SHORT", entry=round(entry, 2),
                           exit=round(cl[-1], 2),
                           pnl=round((cl[-1] - entry) * pos * OZ - cost, 2),
                           minutes=int((chart.time.iloc[-1] - entry_t).total_seconds() // 60),
                           open_at_end=True))
    tr = pd.DataFrame(trades)
    if len(tr):
        tr["exit_time"] = pd.to_datetime(tr["exit_time"])
    return tr, chart


def block(tr, t0, t1, label, chart, cost):
    if len(tr) == 0:
        print(f"{label:22s}  no trades"); return None
    w = tr[(tr.exit_time >= t0) & (tr.exit_time <= t1)].copy()
    if len(w) == 0:
        print(f"{label:22s}  no trades"); return None
    wins, losses = w[w.pnl > 0], w[w.pnl <= 0]
    pf = wins.pnl.sum() / -losses.pnl.sum() if len(losses) else float("inf")
    eq = BAL0 + w.pnl.cumsum()
    dd = float((eq - np.maximum.accumulate(eq)).min())
    print(f"{label:22s}{len(w):>6d}{w.pnl.sum():>11.2f}{len(wins) / len(w) * 100:>7.1f}%"
          f"{pf:>6.2f}{dd:>10.2f}{w.pnl.mean():>11.3f}"
          f"{wins.pnl.mean() if len(wins) else 0:>10.2f}{losses.pnl.mean() if len(losses) else 0:>11.2f}")
    return dict(n=len(w), net=round(w.pnl.sum(), 2), wr=round(len(wins) / len(w) * 100, 1),
                pf=round(pf, 2), dd=round(dd, 2), avg=round(w.pnl.mean(), 3), trades=w)


def main():
    df = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    span = f"{df.time.min():%d %b %H:%M} -> {df.time.max():%d %b %H:%M}"
    print("=" * 104)
    print(f"REAL XAUUSD M1 — {len(df):,} bars, {span} UTC (Exness MT5 feed, Sept 2026)")
    print("EMA 6/9 + BB(20,2) on M1 | EMA 9/12 trend on M5 | 0.01 lot | $0.20 per trade")
    print("=" * 104)
    print(f"{'window':22s}{'trades':>6s}{'net $':>11s}{'win%':>7s}{'PF':>6s}{'maxDD $':>10s}"
          f"{'avg/trade':>11s}{'avg win':>10s}{'avg loss':>11s}")

    out = {}
    for cname, cm, hm in [("M1 chart + M5 trend", 1, 5), ("M5 chart + M5 trend", 5, 5)]:
        tr, chart = run(df, cm, hm, 0.20)
        out[cname] = (tr, chart)
        for lab, (t0, t1) in [("last 3 sessions", W3), ("last 5 sessions", W5)]:
            name = f"{cname[:11]} {lab}"
            r = block(tr, t0, t1, name, chart, 0.20)
            if r:
                out[(cname, lab)] = r
        print()

    # extra references on the main setup
    tr1, ch1 = out["M1 chart + M5 trend"]
    for extra_cost, nm in [(0.0, "[ref] M1+5m no cost"), (0.26, "[ref] M1+5m $0.26 spread")]:
        tr2, _ = run(df, 1, 5, extra_cost)
        block(tr2, *W5, nm, ch1, extra_cost)

    # day by day for the main setup, last 5 sessions
    w = tr1[(tr1.exit_time >= W5[0]) & (tr1.exit_time <= W5[1])].copy()
    w["day"] = w.exit_time.dt.date
    print("\nDay by day — M1 chart + M5 trend ($0.20/trade):")
    print(f"{'day':14s}{'trades':>7s}{'net $':>10s}{'win%':>7s}{'cum $':>10s}")
    cum = 0.0
    for day, g in w.groupby("day"):
        cum += g.pnl.sum()
        print(f"{pd.Timestamp(day).strftime('%a %d %b'):14s}{len(g):>7d}{g.pnl.sum():>10.2f}"
              f"{(g.pnl > 0).sum() / len(g) * 100:>6.1f}%{cum:>10.2f}")

    # trade list
    print(f"\nAll {len(w)} trades (M1 chart + M5 trend, 14-18 Sep 2026):")
    show = w.copy()
    show["entry_time"] = show.entry_time.dt.strftime("%d %b %H:%M")
    show["exit_time"] = show.exit_time.dt.strftime("%d %b %H:%M")
    print(show[["entry_time", "exit_time", "side", "entry", "exit", "pnl", "minutes"]].to_string(index=False))

    # ---- chart -----------------------------------------------------------------
    fig, ax = plt.subplots(2, 1, figsize=(13, 7.5), gridspec_kw={"height_ratios": [1.5, 1]})
    ax[0].plot(w.exit_time, BAL0 + w.pnl.cumsum(), "o-", color="#1f77b4", lw=1.6, ms=3,
               label=f"M1 chart + M5 trend: {w.pnl.sum():+.2f} ({len(w)} trades)")
    for cname, col in [("M5 chart + M5 trend", "#d62728")]:
        tr2 = out[cname][0]
        w2 = tr2[(tr2.exit_time >= W5[0]) & (tr2.exit_time <= W5[1])]
        ax[0].plot(w2.exit_time, BAL0 + w2.pnl.cumsum(), "o-", color=col, lw=1.4, ms=3,
                   label=f"{cname}: {w2.pnl.sum():+.2f} ({len(w2)} trades)")
    ax[0].axhline(BAL0, color="k", ls=":", lw=1)
    ax[0].set_ylabel("Equity ($)")
    ax[0].set_title("REAL XAUUSD M1, 14-18 September 2026 (Exness MT5 feed) — EMA 6/9 + BB on M1, "
                    "EMA 9/12 on M5, 0.01 lot, $0.20/trade")
    ax[0].legend(fontsize=9)
    ax[0].grid(alpha=0.3)
    ax[0].xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    ax[1].bar(w.exit_time, w.pnl, color=["#089981" if p > 0 else "#f23645" for p in w.pnl], width=0.004)
    ax[1].axhline(0, color="k", lw=1)
    ax[1].set_ylabel("Trade P/L ($)")
    ax[1].grid(alpha=0.3)
    ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    fig.tight_layout()
    fig.savefig("results/ema_recent_2026.png", dpi=120)
    print("\nSaved results/ema_recent_2026.png")

    # ---- report ----------------------------------------------------------------
    r3 = out.get(("M1 chart + M5 trend", "last 3 sessions"))
    r5 = out.get(("M1 chart + M5 trend", "last 5 sessions"))
    r53 = out.get(("M5 chart + M5 trend", "last 5 sessions"))
    lines = ["# EMA 6/9 + Bollinger (M1) with EMA 9/12 trend (M5) — REAL recent data", "",
             f"Data: `data/xauusd_m1_2026-09.csv` — {len(df):,} real XAUUSD M1 bars from an "
             f"Exness MT5 feed ({span} UTC), reconstructed from the public mirror "
             "github.com/lbronight/xau-live-mirror. Only the daily 1-hour break and the "
             "weekend are missing (plus a few stray minutes).", "",
             "19 September 2026 is a Saturday — no bars exist. Data was downloaded right "
             "after the Friday close (sandbox clock: 2026-09-18 21:xx UTC).", "",
             "| window | trades | net $ | win% | PF | max DD $ | avg/trade |",
             "|---|---|---|---|---|---|---|"]
    for lab, r in [("Last 3 sessions (16-18 Sep)", r3), ("Last 5 sessions (14-18 Sep)", r5),
                   ("Last 5 sessions, M5 chart (14-18 Sep)", r53)]:
        if r:
            lines.append(f"| {lab} | {r['n']} | ${r['net']:,.2f} | {r['wr']}% | {r['pf']} | "
                         f"${r['dd']:,.2f} | ${r['avg']:+.3f} |")
    lines += ["", "| day | trades | net $ | win% |", "|---|---|---|---|"]
    for day, g in w.groupby("day"):
        lines.append(f"| {pd.Timestamp(day).strftime('%a %d %b %Y')} | {len(g)} | ${g.pnl.sum():,.2f} | "
                     f"{(g.pnl > 0).sum() / len(g) * 100:.1f}% |")
    lines += ["", "Chart: results/ema_recent_2026.png"]
    with open("results/ema_recent_2026_report.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("Saved results/ema_recent_2026_report.md")


if __name__ == "__main__":
    main()
