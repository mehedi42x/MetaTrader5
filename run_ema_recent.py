"""Recent-days report — EMA 6/9 + Bollinger on the M1 chart, EMA 9/12 trend from M5.

Only this configuration (the one asked for), only the last few days.
Data: real XAUUSD M1, file DAT_MT_XAUUSD_M1_2025.csv.
House rules: 0.01 lot (1 oz), $0.20 spread per round trip.

Entry : bullCross(ema6, ema9) on M1 and 5m EMA9 > EMA12 (last CLOSED 5m bar) and close > BB(20,2) middle
Exit  : raw opposite cross on M1
Fills : next M1 bar's open (same as the Pine script)
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

FILE = "/tmp/fxdata/m1xau/DAT_MT_XAUUSD_M1_2025.csv"
OZ, COST, BAL0 = 1.0, 0.20, 10_000.0
# the last 5 sessions that actually have data (27 Dec is a Saturday, 25 Dec is a holiday session)
WIN0, WIN1 = "2025-12-26 00:00", "2025-12-31 23:59"
SHOW0 = "2025-12-24 00:00"          # a bit of context in the daily table / chart


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def main():
    df = pd.read_csv(FILE, header=None,
                     names=["date", "time", "open", "high", "low", "close", "vol"])
    df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M")
    df = df[["time", "open", "high", "low", "close"]].sort_values("time").reset_index(drop=True)

    m1 = df[(df.time >= "2025-11-15")].reset_index(drop=True)     # warm-up before December
    m5 = (df[df.time >= "2025-11-01"].set_index("time")
          .resample("5min").agg(open=("open", "first"), high=("high", "max"),
                                low=("low", "min"), close=("close", "last")).dropna().reset_index())

    f, s = ema(m1.close, 6).to_numpy(float), ema(m1.close, 9).to_numpy(float)
    mid = m1.close.rolling(20).mean().to_numpy(float)
    o, c = m1.open.to_numpy(float), m1.close.to_numpy(float)
    t = m1.time.to_numpy()

    h = m5.copy()
    h["f"], h["s"] = ema(h.close, 9), ema(h.close, 12)
    h["ct"] = h.time + pd.Timedelta(minutes=5)
    m = pd.merge_asof(m1[["time"]].reset_index(),
                      h[["ct", "f", "s"]].rename(columns={"ct": "time"}).sort_values("time"),
                      on="time", direction="backward").set_index("index").reindex(m1.index)
    hf, hs = m["f"].to_numpy(float), m["s"].to_numpy(float)

    bull = np.zeros(len(m1), bool); bear = np.zeros(len(m1), bool)
    bull[1:] = (f[:-1] <= s[:-1]) & (f[1:] > s[1:])
    bear[1:] = (f[:-1] >= s[:-1]) & (f[1:] < s[1:])
    buy = bull & (hf > hs) & (c > mid)
    sell = bear & (hf < hs) & (c < mid)

    # ---- state machine: signal at close -> fill at next open --------------------
    trades, pos, entry, entry_t = [], 0, np.nan, None
    for i in range(1, len(m1)):
        j = i - 1
        tgt = 1 if buy[j] else -1 if sell[j] else (0 if (pos == 1 and bear[j]) or (pos == -1 and bull[j]) else pos)
        if tgt != pos:
            if pos != 0:
                trades.append(dict(entry_time=entry_t, exit_time=m1.time.iloc[i],
                                   side="LONG" if pos == 1 else "SHORT",
                                   entry=round(entry, 2), exit=round(o[i], 2),
                                   pnl=round((o[i] - entry) * pos * OZ - COST, 2),
                                   minutes=int((m1.time.iloc[i] - entry_t).total_seconds() // 60)))
            if tgt != 0:
                entry, entry_t = o[i], m1.time.iloc[i]
            pos = tgt
    tr = pd.DataFrame(trades)
    et = pd.to_datetime(tr.exit_time)
    win = tr[(et >= WIN0) & (et <= WIN1)].copy()

    pnl = win.pnl
    wins, losses = win[pnl > 0], win[pnl <= 0]
    pf = wins.pnl.sum() / -losses.pnl.sum() if len(losses) else float("inf")
    eq = BAL0 + pnl.cumsum()
    dd = float((eq - np.maximum.accumulate(eq)).min())

    print("=" * 78)
    print(f"EMA 6/9 + BB(20,2) on M1  |  EMA 9/12 trend on M5 (last closed bar)")
    print(f"LAST 5 SESSIONS: 26 Dec 2025 -> 31 Dec 2025   (0.01 lot, $0.20/trade)")
    print("=" * 78)
    print(f"trades        : {len(win)}   (long {int((win.side == 'LONG').sum())} / "
          f"short {int((win.side == 'SHORT').sum())})")
    print(f"net P/L       : ${pnl.sum():+.2f}      balance {BAL0:,.0f} -> {BAL0 + pnl.sum():,.2f}")
    print(f"win rate      : {len(wins) / len(win) * 100:.1f}%   ({len(wins)}W / {len(losses)}L)")
    print(f"profit factor : {pf:.2f}")
    print(f"avg win/loss  : ${wins.pnl.mean():+.2f} / ${losses.pnl.mean():+.2f}")
    print(f"avg per trade : ${pnl.mean():+.3f}")
    print(f"best / worst  : ${pnl.max():+.2f} / ${pnl.min():+.2f}")
    print(f"max drawdown  : ${dd:.2f}")
    print(f"avg hold      : {win.minutes.mean():.0f} min (median {win.minutes.median():.0f})")

    print("\nDay by day:")
    d = tr[(et >= SHOW0)].copy()
    d["day"] = pd.to_datetime(d.exit_time).dt.strftime("%a %d %b")
    d["din"] = pd.to_datetime(d.exit_time).dt.date
    print(f"{'day':12s}{'trades':>7s}{'net $':>10s}{'win%':>7s}{'cum $':>10s}")
    cum = 0.0
    for day, g in d.groupby("din"):
        cum += g.pnl.sum()
        w = (g.pnl > 0).sum()
        star = "  <-- in the 5-day window" if pd.Timestamp(day) >= pd.Timestamp("2025-12-26") else ""
        print(f"{pd.Timestamp(day).strftime('%a %d %b'):12s}{len(g):>7d}{g.pnl.sum():>10.2f}"
              f"{w / len(g) * 100:>6.1f}%{cum:>10.2f}{star}")

    print(f"\nAll {len(win)} trades in the window:")
    show = win.copy()
    show["entry_time"] = pd.to_datetime(show.entry_time).dt.strftime("%d %b %H:%M")
    show["exit_time"] = pd.to_datetime(show.exit_time).dt.strftime("%d %b %H:%M")
    print(show[["entry_time", "exit_time", "side", "entry", "exit", "pnl", "minutes"]]
          .to_string(index=False))

    # ---- chart -----------------------------------------------------------------
    fig, ax = plt.subplots(2, 1, figsize=(13, 7), gridspec_kw={"height_ratios": [1.4, 1]})
    w2 = tr[et >= SHOW0].copy()
    xt = pd.to_datetime(w2.exit_time)
    ax[0].plot(xt, BAL0 + w2.pnl.cumsum(), "o-", color="#1f77b4", lw=1.6, ms=3,
               label=f"equity, 26-31 Dec: {pnl.sum():+.2f} ({len(win)} trades)")
    ax[0].axhline(BAL0, color="k", ls=":", lw=1)
    ax[0].axvspan(pd.Timestamp("2025-12-26"), pd.Timestamp("2025-12-31 23:59"), color="orange", alpha=0.08)
    ax[0].set_ylabel("Equity ($)")
    ax[0].set_title("EMA 6/9 + BB on M1, EMA 9/12 trend on M5 — last 5 sessions (0.01 lot, $0.20/trade)")
    ax[0].legend(fontsize=9)
    ax[0].grid(alpha=0.3)
    ax[0].xaxis.set_major_formatter(mdates.DateFormatter("%d %b %H:%M"))
    ax[1].bar(xt, w2.pnl, color=["#089981" if p > 0 else "#f23645" for p in w2.pnl], width=0.01)
    ax[1].axhline(0, color="k", lw=1)
    ax[1].set_ylabel("Trade P/L ($)")
    ax[1].grid(alpha=0.3)
    ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b %H:%M"))
    fig.tight_layout()
    fig.savefig("results/ema_recent_5days.png", dpi=120)
    print("\nSaved results/ema_recent_5days.png")


if __name__ == "__main__":
    main()
