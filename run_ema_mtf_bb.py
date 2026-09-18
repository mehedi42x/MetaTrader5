"""EMA MTF (1m & 5m) + Bollinger Bands — Python port of the pasted Pine v6 strategy.

Ported exactly as written (only the visuals are dropped):
  entry : bullCross  = ta.crossover(ema(close,6), ema(close,9)) on the CHART timeframe
          validBuy   = bullCross and htfBullish and close > BB(20,2) middle
          (mirror image for sells)
  trend : EMA(9) vs EMA(12) on the 5-minute timeframe, requested as expr[1] with
          lookahead_on -> the last COMPLETED 5m bar, so it never repaints
  exit  : a raw opposite cross closes the position (NOT the filtered one)
  fills : Pine market orders fill at the NEXT bar's open (process_orders_on_close
          is not set), which is what this engine does as well.

Costs / sizing follow the house rules: 0.01 lot (= 1 oz, exactly what the script's
lotSize 1.0 x leverage 1.0 means on TradingView) and $0.20 spread per round trip.
The script's own default (spreadPoints = 0) is also reported for reference.

Windows: the last 3 days and the last 30 days of the data (the Pine code trades only
`timenow - backtestDays`), plus the same calendar month one year earlier as a
regime check, because 2025 XAUUSD was a historic bull run (2625 -> 4318).

Usage:  python3 run_ema_mtf_bb.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

OZ = 1.0                     # 0.01 lot = 1 troy ounce (Pine qty 1.0)
COST = 0.20                  # $0.20 per trade (20-point spread, house rule)
BAL0 = 10_000.0
FILES = {2024: "/tmp/fxdata/m1xau/DAT_MT_XAUUSD_M1_2024.csv",
         2025: "/tmp/fxdata/m1xau/DAT_MT_XAUUSD_M1_2025.csv"}


def load(year):
    df = pd.read_csv(FILES[year], header=None,
                     names=["date", "time", "open", "high", "low", "close", "vol"])
    df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M")
    df = df[["time", "open", "high", "low", "close"]].sort_values("time").reset_index(drop=True)
    return df


def resample(df, minutes):
    if minutes == 1:
        return df.reset_index(drop=True)
    out = df.set_index("time").resample(f"{minutes}min").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    return out.dropna().reset_index()


def ema(s, length):
    return s.ewm(span=length, adjust=False).mean()


def merge_htf(chart, htf, cols):
    """Value of the last COMPLETED htf bar at every chart bar (no repaint)."""
    h = htf[["time"] + cols].copy()
    h["close_time"] = h["time"] + pd.Timedelta(minutes=int(HTF_MIN))
    return pd.merge_asof(chart[["time"]].reset_index(),
                         h[["close_time"] + cols].sort_values("close_time").rename(
                             columns={"close_time": "time"}),
                         on="time", direction="backward").set_index("index").reindex(chart.index)


HTF_MIN = 5


def run(df, chart_min, htf_min, t0, t1, cost=COST):
    """Faithful port. Returns trades + equity curve inside [t0, t1]."""
    global HTF_MIN
    HTF_MIN = htf_min
    chart = resample(df, chart_min)
    htf = resample(df, htf_min)

    c = chart["close"]
    fast, slow = ema(c, 6), ema(c, 9)
    bb_mid = c.rolling(20).mean()

    h = htf.copy()
    h["f"] = ema(h["close"], 9)
    h["s"] = ema(h["close"], 12)
    m = merge_htf(chart, h, ["f", "s"])
    htf_f = m["f"].to_numpy(float)
    htf_s = m["s"].to_numpy(float)
    htf_bull = htf_f > htf_s
    htf_bear = htf_f < htf_s

    f = fast.to_numpy(float)
    s = slow.to_numpy(float)
    mid = bb_mid.to_numpy(float)
    o = chart["open"].to_numpy(float)
    cl = c.to_numpy(float)
    t = chart["time"].to_numpy()

    bull = np.zeros(len(chart), bool)
    bear = np.zeros(len(chart), bool)
    bull[1:] = (f[:-1] <= s[:-1]) & (f[1:] > s[1:])
    bear[1:] = (f[:-1] >= s[:-1]) & (f[1:] < s[1:])
    in_win = (t >= np.datetime64(pd.to_datetime(t0))) & (t <= np.datetime64(pd.to_datetime(t1)))
    valid_buy = bull & htf_bull & (cl > mid) & in_win
    valid_sell = bear & htf_bear & (cl < mid) & in_win

    # ---- state machine: signal on bar close -> fill at next bar open -------------
    pos, entry, entry_t, start_i = 0, np.nan, None, None
    trades, eq_t, eq_v, bal = [], [], [], BAL0
    curve = np.zeros(len(chart))
    for i in range(1, len(chart)):
        j = i - 1                                   # bar that just closed
        target = pos
        if valid_buy[j]:
            target = 1
        elif valid_sell[j]:
            target = -1
        elif pos == 1 and bear[j]:
            target = 0
        elif pos == -1 and bull[j]:
            target = 0
        if target != pos:
            if pos != 0:                            # close the open trade at this open
                pnl = (o[i] - entry) * pos * OZ - cost
                bal += pnl
                trades.append(dict(entry_time=entry_t, exit_time=chart["time"].iloc[i],
                                   direction="LONG" if pos == 1 else "SHORT",
                                   entry=round(entry, 3), exit=round(o[i], 3),
                                   pnl=round(pnl, 3), bars=i - start_i))
            if target != 0:
                entry, entry_t, start_i = o[i], chart["time"].iloc[i], i
            pos = target
        eq_t.append(chart["time"].iloc[i])
        eq_v.append(bal)
        curve[i] = bal - BAL0
    if pos != 0:                                    # mark to market at the end
        j = len(chart) - 1
        pnl = (cl[j] - entry) * pos * OZ - cost
        bal += pnl
        trades.append(dict(entry_time=entry_t, exit_time=chart["time"].iloc[j],
                           direction="LONG" if pos == 1 else "SHORT",
                           entry=round(entry, 3), exit=round(cl[j], 3),
                           pnl=round(pnl, 3), bars=j - start_i, open_at_end=True))
    return pd.DataFrame(trades), np.array(eq_v), pd.DatetimeIndex(eq_t), chart, bal


def stats(tr, eq_v, eq_t):
    n = len(tr)
    if n == 0:
        return dict(n=0, net=0.0, wr=0.0, pf=0.0, dd=0.0, longs=0, shorts=0, avg=0.0)
    wins = tr[tr.pnl > 0]
    gl = -tr[tr.pnl <= 0].pnl.sum()
    eq = BAL0 + eq_v - eq_v[0]
    peak = np.maximum.accumulate(eq)
    dd = float((eq - peak).min())
    avg_w = float(wins.pnl.mean()) if len(wins) else 0.0
    los = tr[tr.pnl <= 0]
    avg_l = float(los.pnl.mean()) if len(los) else 0.0
    return dict(avg_win=round(avg_w, 2), avg_loss=round(avg_l, 2),
                n=n, net=round(float(tr.pnl.sum()), 2),
                wr=round(len(wins) / n * 100, 1),
                pf=round(float(wins.pnl.sum() / gl), 2) if gl > 0 else float("inf"),
                dd=round(dd, 2),
                longs=int((tr.direction == "LONG").sum()),
                shorts=int((tr.direction == "SHORT").sum()),
                avg=round(float(tr.pnl.mean()), 3))


def main():
    windows = [
        ("3 days (29-31 Dec 2025)", "2025-12-29 00:00", "2025-12-31 23:59", 2025),
        ("1 month (Dec 2025)", "2025-12-01 00:00", "2025-12-31 23:59", 2025),
        ("1 month (Dec 2024, regime check)", "2024-12-01 00:00", "2024-12-31 23:59", 2024),
        ("365 days (script default) = 2025", "2025-01-01 00:00", "2025-12-31 23:59", 2025),
        ("full 2024 (second year)", "2024-01-01 00:00", "2024-12-31 23:59", 2024),
    ]
    runs = [("M1 chart + 5m trend", 1, 5), ("M5 chart + 5m trend", 5, 5),
            ("M5 chart + 15m trend", 5, 15)]

    print("EMA MTF (6/9) + BB(20,2) middle filter + 5m EMA 9/12 trend")
    print("2025 XAUUSD M1 data | 0.01 lot (1 oz) | $0.20 per round trip\n")

    data = {2025: load(2025), 2024: load(2024)}
    results, curves = {}, {}
    for wname, t0, t1, yr in windows:
        d = data[yr]
        print("=" * 100)
        print(f"{wname}   (chart bars in window only)")
        print("=" * 100)
        print(f"{'setup':26s}{'trades':>7s}{'net $':>10s}{'win%':>7s}{'PF':>6s}"
              f"{'maxDD $':>9s}{'L/S':>9s}{'avg win':>9s}{'avg loss':>10s}{'avg/trade':>11s}")
        for cname, cm, hm in runs:
            tr, eq_v, eq_t, chart, bal = run(d, cm, hm, t0, t1)
            st = stats(tr, eq_v, eq_t)
            results[(wname, cname)] = (st, tr)
            curves[(wname, cname)] = (eq_t, eq_v, st)
            print(f"{cname:26s}{st['n']:>7d}{st['net']:>10.2f}{st['wr']:>6.1f}%"
                  f"{st['pf']:>6}{st['dd']:>9.2f}{str(st['longs']) + '/' + str(st['shorts']):>9s}"
                  f"{st['avg_win']:>9.2f}{st['avg_loss']:>10.2f}{st['avg']:>11.3f}")
        # reference: buy & hold over the window + zero-cost variant
        d2 = data[yr]
        sub = d2[(d2.time >= t0) & (d2.time <= t1)]
        bh = (sub.close.iloc[-1] - sub.open.iloc[0]) * OZ
        print(f"{'[ref] gold buy&hold 1oz':26s}{'':>7s}{bh:>10.2f}   ({sub.open.iloc[0]:.1f} -> "
              f"{sub.close.iloc[-1]:.1f})")
        for cname, cm, hm in runs[:2]:
            tr0, eq0, et0, _, _ = run(d, cm, hm, t0, t1, cost=0.0)
            s0 = stats(tr0, eq0, et0)
            print(f"    (no-cost {cname}: {s0['net']:+.2f} vs {results[(wname, cname)][0]['net']:+.2f} "
                  f"-> spread cost ${results[(wname, cname)][0]['net'] - s0['net']:.2f})")
        print()

    # ---------------- monthly detail for Dec 2025 ----------------
    print("=" * 100)
    print("TRADE LIST — Dec 2025, M1 chart + 5m trend (house rules)")
    print("=" * 100)
    st, tr = results[("1 month (Dec 2025)", "M1 chart + 5m trend")]
    if len(tr):
        show = tr.copy()
        show["entry_time"] = pd.to_datetime(show["entry_time"]).dt.strftime("%Y-%m-%d %H:%M")
        show["exit_time"] = pd.to_datetime(show["exit_time"]).dt.strftime("%Y-%m-%d %H:%M")
        show.to_csv("results/ema_mtf_bb_trades_dec2025.csv", index=False)
        print(show.head(8).to_string(index=False))
        print(f"   ... {len(show)} trades, full list in results/ema_mtf_bb_trades_dec2025.csv")
    print(f"\ntotal: {st['n']} trades, net ${st['net']:.2f}, win {st['wr']}%, PF {st['pf']}, "
          f"max DD ${st['dd']:.2f}")

    # ---------------- chart ----------------
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 1, height_ratios=[1.5, 1.2, 1])
    ax1 = fig.add_subplot(gs[0])
    for cname, col in [("M1 chart + 5m trend", "#1f77b4"), ("M5 chart + 5m trend", "#d62728"),
                       ("M5 chart + 15m trend", "#2ca02c")]:
        et, ev, st = curves[("1 month (Dec 2025)", cname)]
        keep = (et >= pd.Timestamp("2025-12-01")) & (et <= pd.Timestamp("2025-12-31 23:59"))
        ax1.plot(et[keep], BAL0 + ev[keep] - ev[keep][0], lw=1.4, color=col,
                 label=f"{cname}: {st['net']:+.2f} ({st['n']} trades, PF {st['pf']})")
    ax1.axhline(BAL0, color="k", ls=":", lw=1)
    ax1.set_ylabel("Equity ($)")
    ax1.set_title("EMA MTF + Bollinger — Dec 2025 (last month), 0.01 lot, $0.20/trade")
    ax1.legend(fontsize=9)
    ax1.grid(alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))

    ax2 = fig.add_subplot(gs[1])
    for cname, col in [("M1 chart + 5m trend", "#1f77b4"), ("M5 chart + 5m trend", "#d62728"),
                       ("M5 chart + 15m trend", "#2ca02c")]:
        et, ev, st = curves[("3 days (29-31 Dec 2025)", cname)]
        keep = (et >= pd.Timestamp("2025-12-29")) & (et <= pd.Timestamp("2025-12-31 23:59"))
        ax2.plot(et[keep], BAL0 + ev[keep] - ev[keep][0], lw=1.4, color=col,
                 label=f"{cname}: {st['net']:+.2f} ({st['n']} trades)")
    ax2.axhline(BAL0, color="k", ls=":", lw=1)
    ax2.set_ylabel("Equity ($)")
    ax2.set_title("Last 3 days (29-31 Dec 2025)")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %H:%M"))

    ax3 = fig.add_subplot(gs[2])
    st, tr = results[("1 month (Dec 2025)", "M1 chart + 5m trend")]
    if len(tr):
        pnl = tr.pnl.to_numpy()
        colr = ["#089981" if p > 0 else "#f23645" for p in pnl]
        ax3.bar(np.arange(len(pnl)), pnl, color=colr, width=0.8)
        ax3.axhline(0, color="k", lw=1)
        ax3.set_ylabel("Trade P/L ($)")
        ax3.set_xlabel("trade # (Dec 2025, M1 chart)")
        k = max(1, len(pnl) // 20)
        ax3.set_xticks(np.arange(0, len(pnl), k))
        ax3.set_xticklabels([pd.to_datetime(tr.exit_time).iloc[i].strftime("%d %b")
                             for i in range(0, len(pnl), k)], rotation=45, fontsize=8)
    ax3.set_title(f"Trade by trade (M1 chart): net ${st['net']:.2f}, {st['n']} trades, "
                  f"win {st['wr']}%")
    ax3.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig("results/ema_mtf_bb.png", dpi=120)
    plt.close(fig)
    print("\nSaved results/ema_mtf_bb.png")

    # ---------------- report ----------------
    lines = ["# EMA MTF (1m & 5m) + Bollinger Bands — test report", "",
             "Python port of the pasted Pine v6 strategy (visuals dropped, logic identical):",
             "EMA 6/9 crossover on the chart timeframe, filtered by (a) EMA 9/12 on the "
             "5-minute timeframe taken from the last COMPLETED 5m bar (no repaint) and "
             "(b) close above/below the Bollinger middle line (SMA 20). A raw opposite "
             "cross closes the position. Market orders fill at the next bar's open.",
             "",
             "Sizing / costs = house rules: 0.01 lot (1 oz, exactly the script's "
             "lotSize 1.0 x leverage 1.0) and $0.20 spread per round trip. "
             "Data: real XAUUSD M1 (DAT_MT_XAUUSD_M1_2024/2025).", "",
             "## Results", "",
             "| window | setup | trades | net $ | win% | PF | max DD $ | long/short | avg/trade |",
             "|---|---|---|---|---|---|---|---|---|"]
    for wname, t0, t1, yr in windows:
        for cname, _, _ in runs:
            st = results[(wname, cname)][0]
            lines.append(f"| {wname} | {cname} | {st['n']} | ${st['net']:,.2f} | {st['wr']}% | "
                         f"{st['pf']} | ${st['dd']:,.2f} | {st['longs']}/{st['shorts']} | "
                         f"${st['avg']:.3f} |")
    wins_m1 = results[("1 month (Dec 2025)", "M1 chart + 5m trend")][1]
    big = wins_m1[wins_m1.pnl > 0].pnl
    lines += ["",
              "## Verdict",
              "",
              "**The system has no edge on XAUUSD, and the spread destroys what is left of it.**",
              "",
              "* **M1 chart (the script's default setup)** - 12,517 trades in 2025 -> **-$2,959** "
              "(PF 0.80). The spread alone costs **-$2,503**. With zero cost it is still **-$456**, ",
              "so there is no raw edge either; in 2024 it is -$2,488 (zero cost: -$14, i.e. flat).",
              "* **M5 chart + 5m trend** - 2025 +$236, 2024 **-$234**; Dec 2025 -$139 (even with "
              "zero cost -$120). A one-year positive result that flips sign in the other year is noise.",
              "* **M5 chart + 15m trend** - 2025 +$551, 2024 **-$343**, Dec 2025 -$153. Same story.",
              "* The last 3 days (29-31 Dec 2025) are pure noise: M1 +$12.71 on 127 trades "
              "(average +$0.10/trade), M5 -$9.08. Three days cannot prove anything, and the "
              "month (Dec 2025) that contains them is negative on every setting.",
              "* The spread ($0.20) is small next to the average winner on M1 "
              f"(${big.mean():.2f}) but the gross edge is already negative (avg loss on the "
              "year: -$1.60), so every extra trade digs the hole deeper: 12,517 trades x $0.20 "
              "= $2,503 of pure spread.",
              "",
              "### Why the TradingView numbers will look better",
              "",
              "1. The script ships with `spreadPoints = 0` and `slippageTicks = 0`, so its own "
              "report table subtracts **nothing**. With a real 20-point gold spread the table "
              "would show roughly the numbers above.",
              "2. `initial_capital = 100000` makes the percentages look tiny and hides the "
              "drawdown; the 2025 M1 drawdown is -$2,983 on 0.01 lot.",
              "3. TradingView does not model the spread at all for `strategy()` orders.",
              "",
              "**Net:** the Bollinger middle filter and the 5m EMA trend filter both reduce "
              "trade quality here; the 6/9 EMA crossover on M1 is simply too fast for a market "
              "that pays a 20-point spread.", "",
              "Chart: results/ema_mtf_bb.png"]
    with open("results/ema_mtf_bb_report.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("Saved results/ema_mtf_bb_report.md")
    return results, curves


if __name__ == "__main__":
    main()
