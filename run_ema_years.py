"""EMA MTF (1m & 5m) + Bollinger — full-year test on the older data (2023, 2024, 2025).

The strategy is the one the user pasted (Pine v6); this is the same faithful port as
run_ema_mtf_bb.py, run here over complete calendar years because the script's own
"Backtest Days" default is 365.

  entry : EMA 6/9 crossover on the M1 chart, EMA 9/12 trend on M5 taken from the last
          CLOSED 5m bar (expr[1] + lookahead_on -> no repaint), close above/below the
          Bollinger(20,2) middle line
  exit  : raw opposite EMA cross on M1 (the script does not filter the exit)
  fill  : next M1 bar's open (Pine market orders fill on the next bar)
House rules: 0.01 lot (1 oz) and $0.20 spread per round trip. The script's own default
spreadPoints = 0 is shown for reference, since it is the reason the TradingView table
looks better than reality.

Data: real XAUUSD M1 from github.com/tiumbj/M1_XAUUSD (DAT_MT_XAUUSD_M1_YYYY.csv).

Usage:  python3 run_ema_years.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SRC = "/tmp/fxdata/m1xau/DAT_MT_XAUUSD_M1_{y}.csv"
YEARS = [2023, 2024, 2025]
OZ, BAL0 = 1.0, 10_000.0
COST = 0.20


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def load(year):
    df = pd.read_csv(SRC.format(y=year), header=None,
                     names=["date", "time", "open", "high", "low", "close", "vol"])
    df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M")
    return (df[["time", "open", "high", "low", "close"]]
            .sort_values("time").reset_index(drop=True))


def resample(df, minutes):
    if minutes == 1:
        return df.reset_index(drop=True)
    return (df.set_index("time").resample(f"{minutes}min")
            .agg(open=("open", "first"), high=("high", "max"),
                 low=("low", "min"), close=("close", "last")).dropna().reset_index())


def run(df, chart_min, htf_min, cost):
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
    cl = c.to_numpy(float)
    buy = bull & (hf > hs) & (cl > mid)
    sell = bear & (hf < hs) & (cl < mid)

    o = chart.open.to_numpy(float)
    trades, pos, entry, entry_t, entry_i = [], 0, np.nan, None, None
    for i in range(1, len(chart)):
        j = i - 1
        tgt = 1 if buy[j] else -1 if sell[j] else (0 if (pos == 1 and bear[j]) or (pos == -1 and bull[j]) else pos)
        if tgt != pos:
            if pos != 0:
                pt = chart.time.iloc[i]
                trades.append(dict(entry_time=entry_t, exit_time=pt,
                                   side="LONG" if pos == 1 else "SHORT",
                                   entry=round(entry, 2), exit=round(o[i], 2),
                                   pnl=round((o[i] - entry) * pos * OZ - cost, 2),
                                   minutes=int((pt - entry_t).total_seconds() // 60)))
            if tgt != 0:
                entry, entry_t, entry_i = o[i], chart.time.iloc[i], i
            pos = tgt
    if pos != 0:
        lt = chart.time.iloc[-1]
        trades.append(dict(entry_time=entry_t, exit_time=lt,
                           side="LONG" if pos == 1 else "SHORT", entry=round(entry, 2),
                           exit=round(cl[-1], 2),
                           pnl=round((cl[-1] - entry) * pos * OZ - cost, 2),
                           minutes=int((lt - entry_t).total_seconds() // 60), open_at_end=True))
    tr = pd.DataFrame(trades)
    if len(tr):
        tr["exit_time"] = pd.to_datetime(tr["exit_time"])
        tr["entry_time"] = pd.to_datetime(tr["entry_time"])
    return tr


def summarize(tr, label):
    if len(tr) == 0:
        print(f"{label:34s}  no trades"); return None
    wins, losses = tr[tr.pnl > 0], tr[tr.pnl <= 0]
    gl = -losses.pnl.sum()
    pf = wins.pnl.sum() / gl if gl > 0 else float("inf")
    eq = BAL0 + tr.pnl.cumsum()
    dd = float((eq - np.maximum.accumulate(eq)).min())
    gross = float(tr.pnl.sum() + COST * len(tr))
    r = dict(n=len(tr), net=round(float(tr.pnl.sum()), 2), wr=round(len(wins) / len(tr) * 100, 1),
             pf=round(pf, 2), dd=round(dd, 2), avg=round(float(tr.pnl.mean()), 3),
             gross=round(gross, 2), cost=round(COST * len(tr), 2),
             longest=int(tr.minutes.max()))
    print(f"{label:34s}{r['n']:>7d}{r['net']:>11.2f}{r['wr']:>7.1f}%{r['pf']:>6.2f}"
          f"{r['dd']:>10.2f}{r['avg']:>11.3f}{r['gross']:>11.2f}{r['cost']:>10.2f}")
    return r


def main():
    print("=" * 108)
    print("EMA 6/9 + BB(20,2) on M1 | EMA 9/12 trend on M5 | 0.01 lot | $0.20/trade")
    print("Full calendar years on the older data — 2023, 2024, 2025 (real XAUUSD M1)")
    print("=" * 108)
    print(f"{'config / year':34s}{'trades':>7s}{'net $':>11s}{'win%':>7s}{'PF':>6s}"
          f"{'maxDD $':>10s}{'avg/trade':>11s}{'gross $':>11s}{'cost $':>10s}")

    res, months_all, curves = {}, {}, {}
    for yr in YEARS:
        df = load(yr)
        px0, px1 = df.close.iloc[0], df.close.iloc[-1]
        for cname, cm, hm in [("M1 chart + M5 trend", 1, 5), ("M5 chart + M5 trend", 5, 5)]:
            tr = run(df, cm, hm, COST)
            key = (cname, yr)
            res[key] = summarize(tr, f"{cname} {yr}")
            if cm == 1:
                curves[yr] = tr
                w = tr.copy()
                w["m"] = w.exit_time.dt.to_period("M")
                months_all[yr] = w.groupby("m").pnl.agg(["sum", "count"])
            if cm == 1:
                tr0 = run(df, 1, 5, 0.0)
                summarize(tr0, f"  [ref] no cost {yr}")
        print(f"{'  gold buy&hold 1 oz ' + str(yr):34s}{'':>7s}{(px1 - px0) * OZ:>11.2f}"
              f"   ({px0:.0f} -> {px1:.0f})")
        print()

    # ---- monthly tables ---------------------------------------------------------
    print("=" * 108)
    print("MONTH BY MONTH — M1 chart + M5 trend (net $, trades)")
    print("=" * 108)
    hdr = f"{'month':10s}" + "".join(f"{str(y):>22s}" for y in YEARS)
    print(hdr)
    for i in range(12):
        row = f"{pd.Timestamp(2023, i + 1, 1).strftime('%b'):10s}"
        for y in YEARS:
            m = months_all[y]
            if i < len(m):
                idx = m.index[i]
                row += f"{m['sum'].iloc[i]:>15.2f}({int(m['count'].iloc[i]):>4d})"
            else:
                row += f"{'':>22s}"
        print(row)
    row = f"{'TOTAL':10s}"
    for y in YEARS:
        m = months_all[y]
        row += f"{m['sum'].sum():>15.2f}({int(m['count'].sum()):>4d})"
    print(row)
    for y in YEARS:
        m = months_all[y]
        print(f"   {y}: {(m['sum'] < 0).sum()}/{len(m)} months negative, "
              f"best {m['sum'].max():+.2f}, worst {m['sum'].min():+.2f}")

    # ---- chart ------------------------------------------------------------------
    fig, ax = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={"height_ratios": [1.5, 1.2, 1.2]})
    for y, col in zip(YEARS, ["#1f77b4", "#d62728", "#2ca02c"]):
        tr = curves[y]
        st = res[("M1 chart + M5 trend", y)]
        ax[0].plot(tr.exit_time, BAL0 + tr.pnl.cumsum(), lw=1.2, color=col,
                   label=f"{y}: {st['net']:+.2f} ({st['n']} trades, PF {st['pf']}, "
                         f"DD {st['dd']:.0f})")
    ax[0].axhline(BAL0, color="k", ls=":", lw=1)
    ax[0].set_ylabel("Equity ($)")
    ax[0].set_title("EMA 6/9 + Bollinger on M1, EMA 9/12 trend on M5 — full years "
                    "(0.01 lot, $0.20/trade)")
    ax[0].legend(fontsize=9)
    ax[0].grid(alpha=0.3)

    w = 0.27
    x = np.arange(12)
    for k, (y, col) in enumerate(zip(YEARS, ["#1f77b4", "#d62728", "#2ca02c"])):
        m = months_all[y]
        vals = list(m["sum"].values) + [np.nan] * (12 - len(m))
        ax[1].bar(x + (k - 1) * w, vals, w, color=col, label=str(y))
    ax[1].axhline(0, color="k", lw=1)
    ax[1].set_xticks(x)
    ax[1].set_xticklabels([pd.Timestamp(2000, i + 1, 1).strftime("%b") for i in range(12)])
    ax[1].set_ylabel("Monthly P/L ($)")
    ax[1].set_title("Month by month (M1 chart + M5 trend)")
    ax[1].legend(fontsize=9)
    ax[1].grid(alpha=0.3, axis="y")

    for y, col in zip(YEARS, ["#1f77b4", "#d62728", "#2ca02c"]):
        tr = curves[y]
        cum = tr.pnl.cumsum() / BAL0 * 100
        ax[2].plot(tr.exit_time, cum, lw=1.2, color=col, label=f"{y}: {cum.iloc[-1]:+.2f}%")
    ax[2].axhline(0, color="k", ls=":", lw=1)
    ax[2].set_ylabel("Return (%)")
    ax[2].set_title("Cumulative return on a $10,000 account")
    ax[2].legend(fontsize=9)
    ax[2].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("results/ema_years.png", dpi=120)
    plt.close(fig)
    print("\nSaved results/ema_years.png")

    # ---- report -----------------------------------------------------------------
    L = ["# EMA MTF (1m & 5m) + Bollinger Bands — full-year backtest on the older data",
         "",
         "Faithful port of the pasted Pine v6 script (visuals dropped). Entry: EMA 6/9 crossover "
         "on the M1 chart + EMA 9/12 trend on M5 from the last CLOSED 5m bar (no repaint) + close "
         "above/below the Bollinger(20,2) middle. Exit: raw opposite EMA cross. Fills at the next "
         "bar's open. 0.01 lot (1 oz) and $0.20 spread per round trip (house rules); the script's "
         "own default of 0 spread is shown as a reference column.",
         "",
         "Data: real XAUUSD M1 (github.com/tiumbj/M1_XAUUSD). 2023 = 371,000 bars approx, "
         "2024 = 355,652, 2025 = 354,011.", "",
         "## Results", "",
         "| config | year | trades | net $ | win% | PF | max DD $ | avg/trade | gross $ | spread cost $ |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for y in YEARS:
        for cname in ["M1 chart + M5 trend", "M5 chart + M5 trend"]:
            st = res[(cname, y)]
            L.append(f"| {cname} | {y} | {st['n']} | ${st['net']:,.2f} | {st['wr']}% | {st['pf']} | "
                     f"${st['dd']:,.2f} | ${st['avg']:+.3f} | ${st['gross']:,.2f} | ${st['cost']:,.2f} |")
    L += ["", "## Month by month — M1 chart + M5 trend ($)", "",
          "| month | " + " | ".join(str(y) for y in YEARS) + " |",
          "|---" * 4 + "|"]
    for i in range(12):
        row = f"| {pd.Timestamp(2023, i + 1, 1).strftime('%b')} |"
        for y in YEARS:
            m = months_all[y]
            row += (f" {m['sum'].iloc[i]:+,.2f} ({int(m['count'].iloc[i])}) |" if i < len(m) else " — |")
        L.append(row)
    row = "| **Total** |"
    for y in YEARS:
        m = months_all[y]
        row += f" **{m['sum'].sum():+,.2f}** ({int(m['count'].sum())}) |"
    L.append(row)
    L += ["", "Chart: results/ema_years.png"]
    with open("results/ema_years_report.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("Saved results/ema_years_report.md")


if __name__ == "__main__":
    main()
