"""Sideways-market filters for the M1 EMA 6/9 + Bollinger system — which one saves it?

Base system (the user's Pine strategy, M1 chart): EMA 6/9 crossover, EMA 9/12 trend on
M5 (last closed bar), close on the correct side of the Bollinger(20,2) middle; exit on
the raw opposite cross; fill at the next bar's open; 0.01 lot, $0.20 per trade.

The base system loses every month because it fires 11,000-12,500 times a year in every
market condition. This script adds one "sideways" filter at a time (and then the best
combinations) and measures whether any of them turns the system around.

Filters tested (all evaluated on closed M1 bars):
  ADX(14)            > threshold        trend strength
  Choppiness(14)     < threshold        <38.2 = trending, >61.8 = ranging
  Efficiency ratio   > threshold        Kaufman: |close-close[n]| / sum|close-close[i]|
  ATR ratio          > threshold        ATR(14) / ATR(50): volatility expanding
  BB width           > threshold        (upper-lower)/middle / its 240-bar average
  EMA separation     > threshold        |EMA6-EMA9| / ATR(14) in ATR units
  Cooldown           = N bars           block new entries for N bars after an exit

Selection: tuned on the 2023-2025 full years, then checked out-of-sample on 2022 and on
the real September 2026 window (data/xauusd_m1_2026-09.csv, Exness MT5 feed).

Usage:  python3 run_sideways_filter.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SRC = "/tmp/fxdata/m1xau/DAT_MT_XAUUSD_M1_{y}.csv"
RECENT = "data/xauusd_m1_2026-09.csv"
YEARS = [2023, 2024, 2025]
OZ, COST, BAL0 = 1.0, 0.20, 10_000.0


# ----------------------------------------------------------------- helpers
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def wilder(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def load_year(y):
    df = pd.read_csv(SRC.format(y=y), header=None,
                     names=["date", "time", "open", "high", "low", "close", "vol"])
    df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M")
    return df[["time", "open", "high", "low", "close"]].sort_values("time").reset_index(drop=True)


def load_recent():
    df = pd.read_csv(RECENT, parse_dates=["time"])
    df = df[df.time >= "2026-09-14"].reset_index(drop=True)   # last 5 sessions
    return df[["time", "open", "high", "low", "close"]]


def resample(df, minutes):
    if minutes == 1:
        return df.reset_index(drop=True)
    return (df.set_index("time").resample(f"{minutes}min")
            .agg(open=("open", "first"), high=("high", "max"),
                 low=("low", "min"), close=("close", "last")).dropna().reset_index())


def adx(h, l, c, n=14):
    up = h.diff()
    dn = -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = wilder(tr, n)
    pdi = 100 * wilder(pd.Series(plus, index=h.index), n) / atr
    mdi = 100 * wilder(pd.Series(minus, index=h.index), n) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return wilder(dx.fillna(0), n)


def choppiness(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr1 = tr.rolling(n).sum()
    rng = h.rolling(n).max() - l.rolling(n).min()
    return 100 * np.log10((atr1 / rng).replace(0, np.nan)) / np.log10(n)


def efficiency_ratio(c, n=10):
    change = (c - c.shift(n)).abs()
    vol = c.diff().abs().rolling(n).sum()
    return (change / vol.replace(0, np.nan)).fillna(0)


def build(df):
    """Everything the strategy and the filters need, on the M1 clock."""
    chart = resample(df, 1)
    c = chart["close"]
    h, l = chart["high"], chart["low"]
    f, s = ema(c, 6), ema(c, 9)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    upper, lower = mid + 2 * sd, mid - 2 * sd

    htf = resample(df, 5)
    htf["f"], htf["s"] = ema(htf.close, 9), ema(htf.close, 12)
    htf["ct"] = htf.time + pd.Timedelta(minutes=5)
    m = pd.merge_asof(chart[["time"]].reset_index(),
                      htf[["ct", "f", "s"]].rename(columns={"ct": "time"}).sort_values("time"),
                      on="time", direction="backward").set_index("index").reindex(chart.index)

    atr14 = wilder(pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                             axis=1).max(axis=1), 14)
    atr50 = wilder(pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                             axis=1).max(axis=1), 50)

    d = dict(
        time=chart["time"].to_numpy(),
        open=chart["open"].to_numpy(float),
        close=c.to_numpy(float),
        bull=(f.shift(1) <= s.shift(1)) & (f > s),
        bear=(f.shift(1) >= s.shift(1)) & (f < s),
        mid=mid.to_numpy(float),
        htf_bull=(m["f"] > m["s"]).to_numpy(),
        htf_bear=(m["f"] < m["s"]).to_numpy(),
        adx=adx(h, l, c, 14).to_numpy(float),
        chop=choppiness(h, l, c, 14).to_numpy(float),
        er=efficiency_ratio(c, 10).to_numpy(float),
        atr_ratio=(atr14 / atr50).to_numpy(float),
        bbw=((upper - lower) / mid).to_numpy(float),
        bbw_rel=(((upper - lower) / mid) /
                 (((upper - lower) / mid).rolling(240).mean())).to_numpy(float),
        ema_sep=((f - s).abs() / atr14).to_numpy(float),
    )
    d["bbw_rel"] = np.nan_to_num(d["bbw_rel"], nan=0.0, posinf=0.0)
    for k in ("adx", "chop", "er", "atr_ratio", "bbw", "ema_sep"):
        d[k] = np.nan_to_num(d[k], nan=0.0, posinf=0.0, neginf=0.0)
    # base entry conditions
    d["base_buy"] = d["bull"] & d["htf_bull"] & (d["close"] > d["mid"])
    d["base_sell"] = d["bear"] & d["htf_bear"] & (d["close"] < d["mid"])
    return d


def simulate(d, buy, sell, cooldown=0):
    """Sequential engine: signal at close -> fill next open; exit on the raw cross."""
    o, cl, t = d["open"], d["close"], d["time"]
    bull, bear = d["bull"], d["bear"]
    n = len(o)
    trades, pos, entry, entry_i = [], 0, np.nan, None
    last_exit = -10 ** 9
    for i in range(1, n):
        j = i - 1
        if pos == 1 and bear[j]:
            tgt = 0
        elif pos == -1 and bull[j]:
            tgt = 0
        elif pos == 0 and (i - last_exit) > cooldown:
            tgt = 1 if buy[j] else -1 if sell[j] else 0
        else:
            tgt = pos
        if tgt != pos:
            if pos != 0:
                trades.append(((o[i] - entry) * pos * OZ - COST, pos))
                last_exit = i
            if tgt != 0:
                entry = o[i]
            pos = tgt
    if pos != 0:
        trades.append(((cl[n - 1] - entry) * pos * OZ - COST, pos))
    return np.array([x[0] for x in trades]) if trades else np.array([])


def stats(pnl, label):
    if len(pnl) == 0:
        return dict(label=label, n=0, net=0.0, wr=0.0, pf=0.0, dd=0.0, gross=0.0, cost=0.0)
    w, l = pnl[pnl > 0], pnl[pnl <= 0]
    pf = w.sum() / -l.sum() if l.sum() < 0 else float("inf")
    eq = BAL0 + np.cumsum(pnl)
    dd = float((eq - np.maximum.accumulate(eq)).min())
    return dict(label=label, n=len(pnl), net=round(float(pnl.sum()), 2),
                wr=round(len(w) / len(pnl) * 100, 1), pf=round(pf, 2), dd=round(dd, 2),
                gross=round(float(pnl.sum() + COST * len(pnl)), 2),
                cost=round(COST * len(pnl), 2))


FILTERS = {
    "none": lambda d: (d["base_buy"], d["base_sell"], 0),
    "ADX>20": lambda d: (d["base_buy"] & (d["adx"] > 20), d["base_sell"] & (d["adx"] > 20), 0),
    "ADX>25": lambda d: (d["base_buy"] & (d["adx"] > 25), d["base_sell"] & (d["adx"] > 25), 0),
    "ADX>30": lambda d: (d["base_buy"] & (d["adx"] > 30), d["base_sell"] & (d["adx"] > 30), 0),
    "Chop<38.2": lambda d: (d["base_buy"] & (d["chop"] < 38.2), d["base_sell"] & (d["chop"] < 38.2), 0),
    "Chop<45": lambda d: (d["base_buy"] & (d["chop"] < 45), d["base_sell"] & (d["chop"] < 45), 0),
    "ER>0.2": lambda d: (d["base_buy"] & (d["er"] > 0.2), d["base_sell"] & (d["er"] > 0.2), 0),
    "ER>0.3": lambda d: (d["base_buy"] & (d["er"] > 0.3), d["base_sell"] & (d["er"] > 0.3), 0),
    "ER>0.4": lambda d: (d["base_buy"] & (d["er"] > 0.4), d["base_sell"] & (d["er"] > 0.4), 0),
    "ATRratio>1.0": lambda d: (d["base_buy"] & (d["atr_ratio"] > 1.0), d["base_sell"] & (d["atr_ratio"] > 1.0), 0),
    "ATRratio>1.2": lambda d: (d["base_buy"] & (d["atr_ratio"] > 1.2), d["base_sell"] & (d["atr_ratio"] > 1.2), 0),
    "BBwidth>avg": lambda d: (d["base_buy"] & (d["bbw_rel"] > 1.0), d["base_sell"] & (d["bbw_rel"] > 1.0), 0),
    "BBwidth>1.2avg": lambda d: (d["base_buy"] & (d["bbw_rel"] > 1.2), d["base_sell"] & (d["bbw_rel"] > 1.2), 0),
    "EMASep>0.05ATR": lambda d: (d["base_buy"] & (d["ema_sep"] > 0.05), d["base_sell"] & (d["ema_sep"] > 0.05), 0),
    "EMASep>0.10ATR": lambda d: (d["base_buy"] & (d["ema_sep"] > 0.10), d["base_sell"] & (d["ema_sep"] > 0.10), 0),
    "Cooldown 5": lambda d: (d["base_buy"], d["base_sell"], 5),
    "Cooldown 15": lambda d: (d["base_buy"], d["base_sell"], 15),
    "Cooldown 30": lambda d: (d["base_buy"], d["base_sell"], 30),
}


def eval_config(name, fn, data):
    per_year, curves = {}, {}
    for y, d in data.items():
        b, s, cd = fn(d)
        pnl = simulate(d, b, s, cd)
        per_year[y] = stats(pnl, name)
        curves[y] = pnl
    tot = sum(per_year[y]["net"] for y in per_year)
    n = sum(per_year[y]["n"] for y in per_year)
    return per_year, tot, n, curves


def print_table(rows, title):
    print("=" * 116)
    print(title)
    print("=" * 116)
    print(f"{'filter':16s}" + "".join(f"{str(y) + ' net':>11s}{'trd':>7s}" for y in YEARS)
          + f"{'3-yr total':>12s}{'PF 3yr':>8s}{'all years +':>12s}")
    for name, per_year, tot, n, _curves in rows:
        line = f"{name:16s}"
        for y in YEARS:
            line += f"{per_year[y]['net']:>11.2f}{per_year[y]['n']:>7d}"
        wins = sum(1 for y in YEARS if per_year[y]["net"] > 0)
        w = sum(per_year[y]["gross"] / 2 for y in YEARS)  # rough
        line += f"{tot:>12.2f}{'':>8s}{str(wins) + '/3':>12s}"
        print(line)
    print()


def main():
    print("loading years 2022-2025 ...")
    data = {}
    for y in YEARS:
        data[y] = build(load_year(y))
    d22 = build(load_year(2022))
    d26 = build(load_recent())

    results = []
    for name, fn in FILTERS.items():
        per_year, tot, n, curves = eval_config(name, fn, data)
        results.append((name, per_year, tot, n, curves))
    print_table(results, "SINGLE FILTERS — M1 EMA 6/9 + BB + M5 trend, 0.01 lot, $0.20/trade")

    # ---- combinations of the strongest families --------------------------------
    def combo(adx_th=None, chop_th=None, er_th=None, atr_th=None, bbw_th=None,
              sep_th=None, cd=0):
        def f(d):
            b, s = d["base_buy"], d["base_sell"]
            if adx_th is not None:
                b, s = b & (d["adx"] > adx_th), s & (d["adx"] > adx_th)
            if chop_th is not None:
                b, s = b & (d["chop"] < chop_th), s & (d["chop"] < chop_th)
            if er_th is not None:
                b, s = b & (d["er"] > er_th), s & (d["er"] > er_th)
            if atr_th is not None:
                b, s = b & (d["atr_ratio"] > atr_th), s & (d["atr_ratio"] > atr_th)
            if bbw_th is not None:
                b, s = b & (d["bbw_rel"] > bbw_th), s & (d["bbw_rel"] > bbw_th)
            if sep_th is not None:
                b, s = b & (d["ema_sep"] > sep_th), s & (d["ema_sep"] > sep_th)
            return b, s, cd
        return f

    COMBOS = {
        "ADX>25 + Chop<45": combo(adx_th=25, chop_th=45),
        "ADX>25 + ER>0.3": combo(adx_th=25, er_th=0.3),
        "ADX>30 + ER>0.3": combo(adx_th=30, er_th=0.3),
        "Chop<45 + ER>0.3": combo(chop_th=45, er_th=0.3),
        "ADX>25 + ATR>1.0": combo(adx_th=25, atr_th=1.0),
        "ER>0.3 + CD15": combo(er_th=0.3, cd=15),
        "ADX>25 + ER>0.3 + CD15": combo(adx_th=25, er_th=0.3, cd=15),
        "ADX>30 + ER>0.4 + ATR>1.0": combo(adx_th=30, er_th=0.4, atr_th=1.0),
        "Chop<38.2 + ER>0.4 + ATR>1.2": combo(chop_th=38.2, er_th=0.4, atr_th=1.2),
        "ADX>30 + Chop<38.2 + ER>0.4": combo(adx_th=30, chop_th=38.2, er_th=0.4),
        "ADX>25 + ER>0.3 + BBwidth>1.2": combo(adx_th=25, er_th=0.3, bbw_th=1.2),
        "ER>0.4 + BBwidth>1.2 + CD15": combo(er_th=0.4, bbw_th=1.2, cd=15),
    }
    combo_rows = []
    for name, fn in COMBOS.items():
        per_year, tot, n, curves = eval_config(name, fn, data)
        combo_rows.append((name, per_year, tot, n, curves))
    combo_rows.sort(key=lambda r: -r[2])
    print_table(combo_rows, "COMBINATIONS (sorted by 3-year total)")

    # ---- ranking ---------------------------------------------------------------
    all_rows = results + combo_rows
    ranked = sorted(all_rows, key=lambda r: -r[2])
    print("TOP 8 BY 3-YEAR TOTAL P/L:")
    print(f"{'config':30s}{'3-yr net':>11s}{'trades':>9s}{'2023':>10s}{'2024':>10s}{'2025':>10s}"
          f"{'pos years':>11s}")
    for name, per_year, tot, n, _ in ranked[:8]:
        wins = sum(1 for y in YEARS if per_year[y]["net"] > 0)
        print(f"{name:30s}{tot:>11.2f}{n:>9d}{per_year[2023]['net']:>10.2f}"
              f"{per_year[2024]['net']:>10.2f}{per_year[2025]['net']:>10.2f}{wins:>8d}/3")

    # ---- out-of-sample check on the best few -----------------------------------
    shortlist = [r for r in ranked[:6]]
    print("\nOUT-OF-SAMPLE (not used for tuning):")
    print(f"{'config':30s}{'2022 net':>11s}{'trd':>7s}{'Sep2026 net':>13s}{'trd':>7s}")
    oos = {}
    for name, per_year, tot, n, _ in shortlist:
        fn = FILTERS.get(name) or COMBOS.get(name)
        p22 = simulate(d22, *fn(d22))
        p26 = simulate(d26, *fn(d26))
        s22, s26 = stats(p22, name), stats(p26, name)
        oos[name] = (s22, s26)
        print(f"{name:30s}{s22['net']:>11.2f}{s22['n']:>7d}{s26['net']:>13.2f}{s26['n']:>7d}")

    # ---- the winner ------------------------------------------------------------
    best_name, best_year, best_tot, best_n, best_curves = ranked[0]
    print(f"\n>>> BEST on 2023-2025: {best_name}  (3-yr {best_tot:+.2f}, {best_n} trades)")
    s22, s26 = oos[best_name]
    print(f"    out-of-sample: 2022 {s22['net']:+.2f} ({s22['n']} trd) | "
          f"Sep 2026 {s26['net']:+.2f} ({s26['n']} trd)")

    # ---- chart -----------------------------------------------------------------
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [1.6, 1]})
    picks = [r for r in ranked if r[0] in ("none", best_name)] + ranked[:3]
    seen, show = set(), []
    for r in picks:
        if r[0] not in seen:
            seen.add(r[0])
            show.append(r)
    colors = ["#888888", "#d62728", "#1f77b4", "#2ca02c", "#9467bd"]
    for (name, per_year, tot, n, curves), col in zip(show[:5], colors):
        allx, ally, run = [], [], BAL0
        for y in YEARS:
            pnl = curves[y]
            d = data[y]
            t = pd.DatetimeIndex(pd.to_datetime(d["time"]))
            if len(pnl) == 0:
                continue
            # place each trade at the bar it closed - approximate by spreading
            idx = np.linspace(0, len(t) - 1, len(pnl)).astype(int)
            allx.extend(t[idx])
            ally.extend(run + np.cumsum(pnl))
            run += pnl.sum()
        axes[0].plot(allx, ally, lw=1.3, color=col,
                     label=f"{name}: 3-yr {tot:+.2f} ({n:,} trades)")
    axes[0].axhline(BAL0, color="k", ls=":", lw=1)
    axes[0].set_ylabel("Equity ($)")
    axes[0].set_title("M1 EMA 6/9 + Bollinger with sideways filters — 2023→2025 "
                      "(0.01 lot, $0.20/trade)")
    axes[0].legend(fontsize=8.5)
    axes[0].grid(alpha=0.3)

    labels = [r[0] for r in ranked[:10]]
    vals = [r[2] for r in ranked[:10]]
    axes[1].barh(range(len(labels)), vals,
                 color=["#089981" if v > 0 else "#f23645" for v in vals])
    axes[1].set_yticks(range(len(labels)))
    axes[1].set_yticklabels(labels, fontsize=8)
    axes[1].invert_yaxis()
    axes[1].axvline(0, color="k", lw=1)
    axes[1].set_xlabel("3-year net P/L ($, 2023-2025)")
    axes[1].set_title("Top 10 configurations")
    axes[1].grid(alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig("results/sideways_filter.png", dpi=120)
    plt.close(fig)
    print("Saved results/sideways_filter.png")

    # ---- report ----------------------------------------------------------------
    L = ["# Sideways-market filters on the M1 EMA 6/9 + Bollinger system", "",
         "Base system = the pasted Pine strategy: EMA 6/9 crossover on M1 + EMA 9/12 trend on M5 "
         "(last closed bar) + close on the correct side of the Bollinger(20,2) middle; exit on the "
         "raw opposite cross; fill at the next bar's open. 0.01 lot, $0.20 per trade.",
         "",
         "Tuned on the 2023-2025 full years (real XAUUSD M1), then checked on 2022 and on the "
         "September 2026 window, neither of which was used for tuning.", "",
         "## Single filters", "",
         "| filter | 2023 | 2024 | 2025 | 3-yr total | trades | positive years |",
         "|---|---|---|---|---|---|---|"]
    for name, per_year, tot, n, _ in results:
        wins = sum(1 for y in YEARS if per_year[y]["net"] > 0)
        L.append(f"| {name} | ${per_year[2023]['net']:,.2f} | ${per_year[2024]['net']:,.2f} | "
                 f"${per_year[2025]['net']:,.2f} | **${tot:,.2f}** | {n:,} | {wins}/3 |")
    L += ["", "## Combinations (sorted by 3-year total)", "",
          "| combination | 2023 | 2024 | 2025 | 3-yr total | trades | positive years |",
          "|---|---|---|---|---|---|---|"]
    for name, per_year, tot, n, _ in combo_rows:
        wins = sum(1 for y in YEARS if per_year[y]["net"] > 0)
        L.append(f"| {name} | ${per_year[2023]['net']:,.2f} | ${per_year[2024]['net']:,.2f} | "
                 f"${per_year[2025]['net']:,.2f} | **${tot:,.2f}** | {n:,} | {wins}/3 |")
    L += ["", "## Out-of-sample check (2022 and September 2026 — not used for tuning)", "",
          "| config | 2022 net $ | 2022 trades | Sep 2026 net $ | Sep 2026 trades |",
          "|---|---|---|---|---|"]
    for name, _, _, _, _ in shortlist:
        s22, s26 = oos[name]
        L.append(f"| {name} | ${s22['net']:,.2f} | {s22['n']} | ${s26['net']:,.2f} | {s26['n']} |")
    L += ["", f"## Best on the tuning window: **{best_name}**", "",
          f"3-year net **${best_tot:+,.2f}** on {best_n:,} trades.",
          f"Out-of-sample: 2022 ${s22['net']:+,.2f} ({s22['n']} trades), "
          f"Sep 2026 ${s26['net']:+,.2f} ({s26['n']} trades).", "",
          "Chart: results/sideways_filter.png"]
    with open("results/sideways_filter_report.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("Saved results/sideways_filter_report.md")
    return ranked, oos, results, combo_rows


if __name__ == "__main__":
    main()
