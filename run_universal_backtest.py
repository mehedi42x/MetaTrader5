"""Backtest of LuxAlgo's "Universal Signal Backtester" logic on XAUUSD 2022.

Ported decision logic (Pine v6, CC BY-NC-SA 4.0, (c) LuxAlgo) — drawing/dashboard
code is not reproduced:

  signal      : predefined cross (default 9/21 EMA, also 12/26 EMA, 50/200 SMA)
  ATR filter  : optional — signals ignored while ATR(14) < SMA(ATR(14), 50)
  entry       : at the CLOSE of the signal bar (the script's own convention)
  TP          : 3 partial targets at 1.0 / 2.0 / 3.0 x ATR(14), each closes 1/3
  SL          : 1.5 / 2.5 / 3.5 x ATR(14); the nearest stop that is touched closes
                the WHOLE remaining position (SL is checked before TPs each bar)
  reversal    : an opposite signal closes whatever is left at the bar close, and a
                new position can be opened on the same bar
  one position at a time, entry price = bar close

Costs: our standard $0.20/oz round trip (spread 20 points) charged pro-rata on every
partial exit.  Size: 0.01 lot = 1 oz.  Balance 10,000.

Data: data/xauusd_m1_2022.csv (354,628 real M1 bars, 2022).

Usage:  python3 run_universal_backtest.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from src.indicators import ema, atr_wilder
from src.backtest import compute_stats

DATA = "data/xauusd_m1_2022.csv"
BALANCE0 = 10_000.0
OZ = 1.0                 # 0.01 lot
COST = 0.20              # $/oz round trip (spread 20 pts)
PERIODS = [
    ("Full year 2022", "2022-01-01", "2022-12-31"),
    ("H1 2022 (dev)", "2022-01-01", "2022-06-30 23:59"),
    ("H2 2022 (out-of-sample)", "2022-07-01", "2022-12-31"),
]
TFS = [("M1", 1), ("M5", 5), ("M15", 15), ("H1", 60)]
PRESETS = {
    "9/21 EMA (default)": dict(fast=9, slow=21, is_ema=True),
    "12/26 EMA": dict(fast=12, slow=26, is_ema=True),
    "50/200 SMA (golden/death)": dict(fast=50, slow=200, is_ema=False),
}
VARIANTS = {
    "default TP1/2/3 + SL1.5": dict(tps=(1.0, 2.0, 3.0), sls=(1.5,)),
    "stop only (SL 1.5, rev exit)": dict(tps=(), sls=(1.5,)),
    "TPs only (no stop)": dict(tps=(1.0, 2.0, 3.0), sls=()),
    "single TP 2.0 + SL 1.5": dict(tps=(2.0,), sls=(1.5,)),
    "wide: TP 2/4/6 + SL 2.0": dict(tps=(2.0, 4.0, 6.0), sls=(2.0,)),
    "tight: TP 0.5/1/1.5 + SL 1.0": dict(tps=(0.5, 1.0, 1.5), sls=(1.0,)),
}


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def resample_ohlc(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes == 1:
        return m1.copy()
    g = (m1.set_index("time").resample(f"{minutes}min")
         .agg(open=("open", "first"), high=("high", "max"),
              low=("low", "min"), close=("close", "last"), n=("close", "size")))
    return g[g.n > 0].drop(columns="n").reset_index()


def bt_universal(df, t0, t1, fast=9, slow=21, is_ema=True, atr_len=14,
                 use_atr_filter=False, atr_filter_len=50, tps=(1.0, 2.0, 3.0),
                 sls=(1.5,), allow_long=True, allow_short=True, costs=True,
                 balance0=BALANCE0):
    """Faithful port of the Universal Signal Backtester trade loop."""
    close = df["close"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    t = pd.to_datetime(df["time"]).to_numpy()

    s = df["close"]
    f = ema(s, fast) if is_ema else sma(s, fast)
    sl_ma = ema(s, slow) if is_ema else sma(s, slow)
    f = f.to_numpy(float)
    sl_ma = sl_ma.to_numpy(float)
    with np.errstate(invalid="ignore"):
        long_sig = (f[:-1] <= sl_ma[:-1]) & (f[1:] > sl_ma[1:])
        short_sig = (f[:-1] >= sl_ma[:-1]) & (f[1:] < sl_ma[1:])
    long_sig = np.concatenate([[False], long_sig])
    short_sig = np.concatenate([[False], short_sig])
    long_sig[~np.isfinite(f) | ~np.isfinite(sl_ma)] = False
    short_sig[~np.isfinite(f) | ~np.isfinite(sl_ma)] = False

    atr = atr_wilder(df["high"], df["low"], df["close"], atr_len).to_numpy(float)
    if use_atr_filter:
        atr_ma = pd.Series(atr).rolling(atr_filter_len).mean().to_numpy(float)
        with np.errstate(invalid="ignore"):
            atr_ok = atr > atr_ma
        atr_ok = np.where(np.isfinite(atr_ma), atr_ok, False)
    else:
        atr_ok = np.ones(len(df), dtype=bool)

    start = np.searchsorted(t, np.datetime64(pd.to_datetime(t0)))
    end = np.searchsorted(t, np.datetime64(pd.to_datetime(t1)), side="right")

    bal = balance0
    trades, eq_ts, eq_val = [], [], []
    active = False
    d = 0
    entry_px = entry_time = None
    entry_idx = 0
    qty_left = 0.0
    trade_pnl = 0.0
    tp_px = np.zeros(len(tps))
    sl_px = np.zeros(len(sls))
    tp_hit = np.zeros(len(tps), dtype=bool)
    tp_count = np.zeros(len(tps), dtype=int)

    def open_trade(dir_, i):
        nonlocal active, d, entry_px, entry_time, entry_idx, qty_left, trade_pnl
        nonlocal tp_px, sl_px, tp_hit
        m = atr[i] if np.isfinite(atr[i]) and atr[i] > 0 else (high[i] - low[i])
        if not np.isfinite(m) or m <= 0:
            return
        active, d = True, dir_
        entry_px, entry_time, entry_idx = close[i], t[i], i
        qty_left, trade_pnl = 1.0, 0.0
        tp_px = np.array([close[i] + dir_ * m * v for v in tps]) if tps else np.zeros(0)
        sl_px = np.array([close[i] - dir_ * m * v for v in sls]) if sls else np.zeros(0)
        tp_hit = np.zeros(len(tps), dtype=bool)

    def cost_for(qty):
        return (COST * qty / OZ) if costs else 0.0

    for i in range(1, min(len(df), end)):
        if i < start:
            continue
        # ---------------- manage an open position on bar i ----------------
        if active:
            hit_sl = None
            for k in range(len(sls)):
                if (d == 1 and low[i] <= sl_px[k]) or (d == -1 and high[i] >= sl_px[k]):
                    hit_sl = k
                    break
            if hit_sl is not None:                       # SL first (conservative)
                px = sl_px[hit_sl]
                trade_pnl += (px - entry_px) * d * OZ * qty_left - cost_for(qty_left)
                qty_left = 0.0
                _record(trades, entry_time, t[i], d, entry_px, px, trade_pnl, i - entry_idx,
                        f"SL{hit_sl + 1}")
                bal += trade_pnl
                tp_hit = tp_hit  # unchanged
                active = False
            else:
                if tps:
                    n_tp = len(tps)
                    tp_qty = 1.0 / n_tp
                    for k in range(n_tp):
                        if tp_hit[k]:
                            continue
                        if (d == 1 and high[i] >= tp_px[k]) or (d == -1 and low[i] <= tp_px[k]):
                            tp_hit[k] = True
                            tp_count[k] += 1
                            trade_pnl += (tp_px[k] - entry_px) * d * OZ * tp_qty - cost_for(tp_qty)
                            qty_left -= tp_qty
                if qty_left <= 1e-9 and active:
                    _record(trades, entry_time, t[i], d, entry_px, close[i], trade_pnl,
                            i - entry_idx, "TP*")
                    bal += trade_pnl
                    active = False
                elif active:                              # opposite signal closes the rest
                    if (d == 1 and short_sig[i]) or (d == -1 and long_sig[i]):
                        trade_pnl += (close[i] - entry_px) * d * OZ * qty_left - cost_for(qty_left)
                        _record(trades, entry_time, t[i], d, entry_px, close[i], trade_pnl,
                                i - entry_idx, "REV")
                        bal += trade_pnl
                        active = False

        # ---------------- new entry on the same bar (script order) ----------
        if not active:
            can_long = long_sig[i] and allow_long and atr_ok[i]
            can_short = short_sig[i] and allow_short and atr_ok[i]
            if can_long:
                open_trade(1, i)
            elif can_short:
                open_trade(-1, i)
            if active and entry_idx == i:                 # roll the trade into the log
                pass

        eq_ts.append(t[i])
        eq_val.append(bal)

    last = min(len(df), end) - 1
    if active:                                            # close leftovers at the last close
        trade_pnl += (close[last] - entry_px) * d * OZ * qty_left - cost_for(qty_left)
        _record(trades, entry_time, t[last], d, entry_px, close[last], trade_pnl,
                last - entry_idx, "END")
        bal += trade_pnl
        active = False

    tr = pd.DataFrame(trades)
    eq = pd.DataFrame({"time": pd.to_datetime(eq_ts), "equity": eq_val})
    eq = eq[eq.time >= pd.to_datetime(t0)].reset_index(drop=True)
    st = compute_stats(tr, eq, balance0) if len(tr) else dict(
        n_trades=0, net_pnl=0.0, return_pct=0.0, profit_factor=0.0, win_rate=0.0,
        max_dd_usd=0.0, max_dd_pct=0.0, expectancy=0.0, avg_win=0.0, avg_loss=0.0)
    st["tp_hits"] = [int(x) for x in tp_count]
    if st.get("n_trades"):
        st["costs"] = round(st["n_trades"] * COST, 2)
    return tr, eq, st


def _record(trades, entry_time, exit_time, d, entry_px, exit_px, pnl, bars, reason):
    trades.append(dict(entry_time=entry_time, exit_time=exit_time,
                       direction="LONG" if d == 1 else "SHORT",
                       entry=round(float(entry_px), 2), exit=round(float(exit_px), 2),
                       sl=float("nan"), tp=float("nan"), lot=0.01,
                       pnl=round(float(pnl), 2), r_multiple=0.0,
                       bars_held=int(bars), exit_reason=reason))


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    print(f"{len(m1):,} M1 bars ({m1.time.min().date()} -> {m1.time.max().date()}) | "
          f"0.01 lot | ${COST:.2f}/trade\n")

    frames = {name: resample_ohlc(m1, mins) for name, mins in TFS}

    # ---------------- main matrix: preset x timeframe, default TP/SL ----------
    print("=" * 112)
    print("Universal Signal Backtester — presets x timeframes, default TP 1/2/3 ATR + SL 1.5 ATR")
    print("=" * 112)
    print(f"{'preset':28s}" + "".join(f"{n:>20s}" for n, _ in TFS))
    main_res = {}
    for pname, p in PRESETS.items():
        row = f"{pname:28s}"
        for tfname, _ in TFS:
            tr, eq, st = bt_universal(frames[tfname], *PERIODS[0][1:], **p)
            main_res[(pname, tfname)] = (st, eq, tr)
            row += f"{st['net_pnl']:>9.2f}({st['n_trades']:>5d})"
        print(row)
    print("\n(numbers = net P/L $ for 2022, brackets = number of trades)\n")

    # best combo detail
    best_key = max(main_res, key=lambda k: main_res[k][0]["net_pnl"])
    print(f">>> best preset/timeframe: {best_key[0]} on {best_key[1]} -> "
          f"${main_res[best_key][0]['net_pnl']:.2f}")

    # ---------------- H1/H2 for the main candidates ----------------
    print("\nH1 (dev) vs H2 (out-of-sample):")
    print(f"{'preset':28s}{'TF':>5s}{'H1 P/L':>12s}{'H2 P/L':>12s}{'year':>12s}{'PF':>7s}")
    for pname in PRESETS:
        for tfname, _ in TFS:
            st0 = main_res[(pname, tfname)][0]
            _, _, h1 = bt_universal(frames[tfname], *PERIODS[1][1:], **PRESETS[pname])
            _, _, h2 = bt_universal(frames[tfname], *PERIODS[2][1:], **PRESETS[pname])
            print(f"{pname:28s}{tfname:>5s}{h1['net_pnl']:>12.2f}{h2['net_pnl']:>12.2f}"
                  f"{st0['net_pnl']:>12.2f}{st0['profit_factor']:>7}")

    # ---------------- TP/SL variants on the default preset ----------------
    print("\nTP/SL variants (9/21 EMA, full year):")
    print(f"{'variant':32s}" + "".join(f"{n:>16s}" for n, _ in TFS) + "   TP hits (M15)")
    var_res = {}
    for vname, v in VARIANTS.items():
        row = f"{vname:32s}"
        for tfname, _ in TFS:
            tr, eq, st = bt_universal(frames[tfname], *PERIODS[0][1:], **v)
            var_res[(vname, tfname)] = (st, eq, tr)
            row += f"{st['net_pnl']:>16.2f}"
        th = var_res[(vname, "M15")][0].get("tp_hits", [])
        row += "   " + "/".join(str(x) for x in th)
        print(row)

    # ---------------- ATR choppiness filter ----------------
    print("\nATR choppiness filter (9/21 EMA, default TP/SL):")
    print(f"{'filter':12s}" + "".join(f"{n:>16s}" for n, _ in TFS))
    filt_res = {}
    for use in (False, True):
        row = f"{'ON' if use else 'OFF':12s}"
        for tfname, _ in TFS:
            tr, eq, st = bt_universal(frames[tfname], *PERIODS[0][1:], use_atr_filter=use)
            filt_res[(use, tfname)] = (st, eq, tr)
            row += f"{st['net_pnl']:>16.2f}"
        print(row)

    # ---------------- H1 configuration sweep (where it works) --------------
    H1_SWEEP = {
        "default 9/21 TP1/2/3 + SL1.5": dict(),
        "wide TP 2/4/6 + SL 2.0": dict(tps=(2, 4, 6), sls=(2.0,)),
        "wider TP 3/6/9 + SL 3.0": dict(tps=(3, 6, 9), sls=(3.0,)),
        "stop only SL 2.0 + reversal": dict(tps=(), sls=(2.0,)),
        "single TP 3.0 + SL 2.0": dict(tps=(3.0,), sls=(2.0,)),
        "wide + ATR choppiness filter": dict(tps=(2, 4, 6), sls=(2.0,), use_atr_filter=True),
        "wide, long only": dict(tps=(2, 4, 6), sls=(2.0,), allow_short=False),
        "wide, short only": dict(tps=(2, 4, 6), sls=(2.0,), allow_long=False),
        "wide 12/26 EMA": dict(fast=12, slow=26, tps=(2, 4, 6), sls=(2.0,)),
        "wide 50/200 SMA": dict(fast=50, slow=200, is_ema=False, tps=(2, 4, 6), sls=(2.0,)),
    }
    print("\nH1 timeframe — configuration sweep (full year, costs on):")
    print(f"{'config':34s}{'P/L':>10s}{'trd':>6s}{'win%':>7s}{'PF':>6s}{'H1':>10s}{'H2':>10s}")
    h1_sweep_res = {}
    for name, kw in H1_SWEEP.items():
        st0 = bt_universal(frames["H1"], *PERIODS[0][1:], **kw)[2]
        st1 = bt_universal(frames["H1"], *PERIODS[1][1:], **kw)[2]
        st2 = bt_universal(frames["H1"], *PERIODS[2][1:], **kw)[2]
        h1_sweep_res[name] = (st0, st1, st2)
        print(f"{name:34s}{st0['net_pnl']:>10.2f}{st0['n_trades']:>6d}{st0['win_rate']:>6.1f}%"
              f"{st0['profit_factor']:>6}{st1['net_pnl']:>10.2f}{st2['net_pnl']:>10.2f}")

    # ---------------- costs on/off ----------------
    print("\nCosts on/off (9/21 EMA, default TP/SL, full year):")
    for tfname, _ in TFS:
        a = bt_universal(frames[tfname], *PERIODS[0][1:], costs=True)[2]["net_pnl"]
        b = bt_universal(frames[tfname], *PERIODS[0][1:], costs=False)[2]["net_pnl"]
        print(f"  {tfname:>4s}: with costs ${a:>9.2f} | without ${b:>9.2f} | costs paid ${b - a:>8.2f}")

    # ---------------- charts ----------------
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [2.2, 1]})
    colors = ["#1f77b4", "#2ca02c", "#d62728", "#ff7f0e"]
    for (tfname, _), c in zip(TFS, colors):
        st, eq, tr = main_res[("9/21 EMA (default)", tfname)]
        ax1.plot(pd.to_datetime(eq["time"]), eq["equity"], color=c, lw=1.4,
                 label=f"9/21 EMA {tfname}: {st['return_pct']:+.2f}% ({st['n_trades']} trd, "
                       f"PF {st['profit_factor']})")
    ax1.axhline(BALANCE0, color="k", ls=":", lw=1)
    ax1.set_ylabel("Equity ($)")
    ax1.set_title("XAUUSD 2022 — LuxAlgo Universal Signal Backtester (9/21 EMA, ATR TP/SL, "
                  "partial exits), 0.01 lot, $0.20/trade", fontsize=12)
    ax1.legend(fontsize=9, loc="upper left")
    ax1.grid(alpha=0.3)

    months = pd.date_range("2022-01-01", "2022-12-01", freq="MS")
    x = np.arange(len(months))
    width = 0.2
    for k, ((tfname, _), c) in enumerate(zip(TFS, colors)):
        vals = []
        for m0 in months:
            m1t = m0 + pd.offsets.MonthEnd(0)
            st = bt_universal(frames[tfname], m0, m1t)[2]
            vals.append(st["net_pnl"])
        ax2.bar(x + (k - 1.5) * width, vals, width, color=c, label=tfname)
    ax2.axhline(0, color="k", lw=1)
    ax2.set_ylabel("Monthly P/L ($)")
    ax2.set_xticks(x)
    ax2.set_xticklabels([m.strftime("%b") for m in months])
    ax2.legend(fontsize=9, ncol=4)
    ax2.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig("results/universal_signal.png", dpi=120)
    plt.close(fig)
    print("\nSaved results/universal_signal.png")

    # ---------------- report ----------------
    lines = ["# XAUUSD 2022 — LuxAlgo “Universal Signal Backtester” port", "",
             "Ported from the Pine v6 indicator (CC BY-NC-SA 4.0, (c) LuxAlgo): predefined "
             "9/21 EMA cross by default, ATR(14)-based TP1/2/3 (partial exits of 1/3 each) and "
             "SL 1.5/2.5/3.5 (nearest touched stop closes the whole remainder, checked before "
             "the TPs each bar), reversal on the opposite signal, entry at the signal bar's close.",
             "",
             "Data: data/xauusd_m1_2022.csv (354,628 real M1 bars). Size 0.01 lot (1 oz), "
             "cost $0.20 per round trip (spread 20 points, charged pro-rata on partial exits).",
             "", "## Presets x timeframes (default TP/SL)", "",
             "| preset | " + " | ".join(n for n, _ in TFS) + " |",
             "|---" * (len(TFS) + 1) + "|"]
    for pname in PRESETS:
        cells = []
        for tfname, _ in TFS:
            st = main_res[(pname, tfname)][0]
            cells.append(f"${st['net_pnl']:,.2f} ({st['n_trades']} trd, PF {st['profit_factor']})")
        lines.append(f"| {pname} | " + " | ".join(cells) + " |")
    lines += ["", "## TP/SL variants (9/21 EMA)", "",
              "| variant | " + " | ".join(n for n, _ in TFS) + " |",
              "|---" * (len(TFS) + 1) + "|"]
    for vname in VARIANTS:
        cells = [f"${var_res[(vname, tf)][0]['net_pnl']:,.2f}" for tf, _ in TFS]
        lines.append(f"| {vname} | " + " | ".join(cells) + " |")
    lines += ["", "## ATR choppiness filter (9/21 EMA)", "",
              "| filter | " + " | ".join(n for n, _ in TFS) + " |",
              "|---" * (len(TFS) + 1) + "|"]
    for use in (False, True):
        cells = [f"${filt_res[(use, tf)][0]['net_pnl']:,.2f}" for tf, _ in TFS]
        lines.append(f"| {'ON' if use else 'OFF'} | " + " | ".join(cells) + " |")
    lines += ["", "## H1 configuration sweep (full year, costs on)", "",
              "| config | P/L | trades | win% | PF | H1 | H2 |",
              "|---|---|---|---|---|---|---|"]
    for name, (st0, st1, st2) in h1_sweep_res.items():
        lines.append(f"| {name} | ${st0['net_pnl']:,.2f} | {st0['n_trades']} | {st0['win_rate']}% "
                     f"| {st0['profit_factor']} | ${st1['net_pnl']:,.2f} | ${st2['net_pnl']:,.2f} |")
    lines += ["", "Chart: results/universal_signal.png",
              "", "Reference points from the same repo: S7 order-block retest +$702 (2022), "
              "EMA 9/12 pure-reverse -$5,446 (2022)."]
    lines += ["", "## Finding", "",
              "* The default configuration loses on M1/M5/M15 and only breaks even on H1 "
              "(+$68 for the year). Cost is the killer on the fast timeframes: the M1 run pays "
              "$3,344 of spread over 16,720 trades, and even with zero costs the M1 signal is "
              "still -$360 (no edge there).",
              "* The ATR choppiness filter helps a lot on the fast timeframes (M1 -$3,704 -> "
              "-$1,597, M5 -$866 -> -$403, M15 -$240 -> -$23) but does not make them positive, "
              "and on H1 it HURTS (-$83 on the wide config).",
              "* On H1 the edge appears only with WIDER targets: TP 3/6/9 ATR + SL 3.0 ATR gives "
              "+$256 (PF 1.22, 36.9% win, H1 +$173 / H2 +$78). The default 1/2/3 targets are too "
              "small relative to the noise; larger stops survive the whipsaw.",
              "* Reference: our S7 order-block retest made +$702 on the same 2022 data, and the "
              "plain EMA 9/12 reverse system lost -$5,446.",
              "",
              "Practical take: this indicator is a signal tester, and its default settings are "
              "not a strategy. If used at all, use H1 + wide ATR targets, and do not run the "
              "preset crosses on M1-M15 on gold."]
    with open("results/universal_report.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("Saved results/universal_report.md")


if __name__ == "__main__":
    main()
