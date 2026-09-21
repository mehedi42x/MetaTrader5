"""
Trade Hunter - Red Box strategy backtester (Pine v6 -> Python port)
Data: XAUUSD M1 2021-2025 (github.com/tiumbj/M1_XAUUSD)
"""
import numpy as np, pandas as pd, os, sys, json

DATA = "/home/user/data/repo"
COLS = ["date", "time", "open", "high", "low", "close", "vol"]


def load(years=(2021, 2022, 2023, 2024, 2025)):
    fr = []
    for y in years:
        p = f"{DATA}/DAT_MT_XAUUSD_M1_{y}.csv"
        d = pd.read_csv(p, header=None, names=COLS)
        fr.append(d)
    df = pd.concat(fr, ignore_index=True)
    df["dt"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M")
    df = df.sort_values("dt").drop_duplicates("dt").reset_index(drop=True)
    return df[["dt", "open", "high", "low", "close"]]


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def rma(x, n):
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def build_features(df, fast=6, slow=9, htf_fast=9, htf_slow=12, htf="5min", fail=3, zone=5.0):
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    f = ema(c, fast); s = ema(c, slow)
    df["emaF"], df["emaS"] = f, s
    df["bull"] = (f > s) & (np.roll(f, 1) <= np.roll(s, 1))
    df["bear"] = (f < s) & (np.roll(f, 1) >= np.roll(s, 1))
    df.loc[0, ["bull", "bear"]] = False

    # ---- HTF (5m) EMAs, non-repaint: previous closed 5m bar value ----
    g = df.set_index("dt")["close"].resample(htf).last().dropna()
    hf = pd.Series(ema(g.to_numpy(), htf_fast), index=g.index).shift(1)
    hs = pd.Series(ema(g.to_numpy(), htf_slow), index=g.index).shift(1)
    # value available to 1m bars belonging to that 5m bucket
    buck = df["dt"].dt.floor(htf)
    df["htfF"] = buck.map(hf).to_numpy()
    df["htfS"] = buck.map(hs).to_numpy()
    df["htfBull"] = df["htfF"] > df["htfS"]
    df["htfBear"] = df["htfF"] < df["htfS"]

    # ---- pivot high (1 left, `fail` right) confirmed at bar i ----
    n = len(h)
    ph = np.full(n, np.nan)
    for i in range(1 + fail, n):
        p = i - fail
        if h[p] > h[p - 1] and all(h[p] > h[p + k] for k in range(1, fail + 1)):
            ph[i] = h[p]
    df["ph"] = ph

    # ---- red box state (port of Pine box logic) ----
    inside = np.zeros(n, bool)
    top = btm = np.nan
    active = False
    for i in range(n):
        if not np.isnan(ph[i]):
            top = ph[i]; btm = top - zone
            if btm <= c[i] <= top:
                active = True
        if active:
            if btm <= c[i] <= top:
                inside[i] = True
            else:
                active = False
    df["inBox"] = inside

    # extra filters
    df["atr14"] = rma(np.maximum.reduce([h - l,
                                         np.abs(h - np.roll(c, 1)),
                                         np.abs(l - np.roll(c, 1))]), 14)
    df["sep"] = np.abs(f - s)
    ema50 = ema(c, 50)
    df["ema50"] = ema50
    df["slope50"] = ema50 - np.roll(ema50, 5)
    df["adx"] = adx(h, l, c, 14)
    df["hour"] = df["dt"].dt.hour
    return df


def adx(h, l, c, n=14):
    up = h - np.roll(h, 1); dn = np.roll(l, 1) - l
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h - l, np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))])
    atr = rma(tr, n)
    pdi = 100 * rma(plus, n) / np.where(atr == 0, np.nan, atr)
    mdi = 100 * rma(minus, n) / np.where(atr == 0, np.nan, atr)
    dx = 100 * np.abs(pdi - mdi) / np.where((pdi + mdi) == 0, np.nan, pdi + mdi)
    return np.nan_to_num(rma(np.nan_to_num(dx), n))


def run(df, use_box=True, trigger=2.0, dist=1.5, cap=2.0, qty=10.0,
        spread=0.0, hard_sl=None, atr_min=None, atr_max=None, sep_min=None,
        adx_min=None, hours=None, trend_align=False, time_stop=None, label=""):
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    bull = df["bull"].to_numpy(); bear = df["bear"].to_numpy()
    hb = df["htfBull"].to_numpy(); hs = df["htfBear"].to_numpy()
    box = df["inBox"].to_numpy()
    atr = df["atr14"].to_numpy(); sep = df["sep"].to_numpy()
    ad = df["adx"].to_numpy(); hour = df["hour"].to_numpy()
    e50 = df["ema50"].to_numpy(); sl50 = df["slope50"].to_numpy()
    dt = df["dt"].to_numpy()
    n = len(df)

    ok = np.ones(n, bool)
    if atr_min is not None: ok &= atr >= atr_min
    if atr_max is not None: ok &= atr <= atr_max
    if sep_min is not None: ok &= sep >= sep_min
    if adx_min is not None: ok &= ad >= adx_min
    if hours is not None:
        ok &= np.isin(hour, list(hours))
    okL = ok.copy(); okS = ok.copy()
    if trend_align:
        okL &= (c > e50) & (sl50 > 0)
        okS &= (c < e50) & (sl50 < 0)

    pos = 0            # 1 long, -1 short
    entry = 0.0
    entry_i = 0
    stop = np.nan
    trail_on = False
    trades = []

    def close_trade(i, px, reason):
        nonlocal pos, stop, trail_on
        pnl = (px - entry) * qty * pos - spread * qty
        trades.append(dict(entry_time=dt[entry_i], exit_time=dt[i], side=pos,
                           entry=entry, exit=px, pnl=pnl, bars=i - entry_i, reason=reason))
        pos = 0; stop = np.nan; trail_on = False

    for i in range(60, n):
        # ---- intrabar: stop from previous bar ----
        if pos != 0 and not np.isnan(stop):
            if pos > 0 and l[i] <= stop:
                close_trade(i, stop, "trail")
            elif pos < 0 and h[i] >= stop:
                close_trade(i, stop, "trail")
        if pos != 0 and hard_sl is not None:
            if pos > 0 and l[i] <= entry - hard_sl:
                close_trade(i, entry - hard_sl, "sl")
            elif pos < 0 and h[i] >= entry + hard_sl:
                close_trade(i, entry + hard_sl, "sl")
        if pos != 0 and time_stop is not None and i - entry_i >= time_stop:
            close_trade(i, c[i], "time")

        # ---- signals on close ----
        blocked = use_box and box[i]
        vb = bull[i] and hb[i] and not blocked and okL[i]
        vs = bear[i] and hs[i] and not blocked and okS[i]

        if pos > 0 and bear[i]:
            close_trade(i, c[i], "reverse")
        elif pos < 0 and bull[i]:
            close_trade(i, c[i], "reverse")

        if vb and pos <= 0:
            if pos < 0: close_trade(i, c[i], "flip")
            pos = 1; entry = c[i]; entry_i = i; stop = np.nan; trail_on = False
        elif vs and pos >= 0:
            if pos > 0: close_trade(i, c[i], "flip")
            pos = -1; entry = c[i]; entry_i = i; stop = np.nan; trail_on = False

        # ---- trailing update ----
        if pos > 0:
            if h[i] >= entry + trigger: trail_on = True
            if trail_on:
                tgt = h[i] - dist
                mx = entry + cap
                lock = entry + (trigger - dist)
                stop = min(max(stop if not np.isnan(stop) else lock, tgt), mx)
        elif pos < 0:
            if l[i] <= entry - trigger: trail_on = True
            if trail_on:
                tgt = l[i] + dist
                mn = entry - cap
                lock = entry - (trigger - dist)
                stop = max(min(stop if not np.isnan(stop) else lock, tgt), mn)

    t = pd.DataFrame(trades)
    return stats(t, label), t


def stats(t, label=""):
    if len(t) == 0:
        return dict(label=label, trades=0)
    p = t["pnl"].to_numpy()
    eq = np.cumsum(p)
    dd = eq - np.maximum.accumulate(eq)
    wins = p[p > 0]; loss = p[p <= 0]
    gp = wins.sum(); gl = -loss.sum()
    yrs = (t["exit_time"].iloc[-1] - t["entry_time"].iloc[0]) / np.timedelta64(365, "D")
    return dict(label=label, trades=len(t), win_rate=100 * len(wins) / len(p),
                net=p.sum(), avg=p.mean(), pf=(gp / gl if gl else np.inf),
                max_dd=dd.min(), avg_win=wins.mean() if len(wins) else 0,
                avg_loss=loss.mean() if len(loss) else 0,
                trades_per_yr=len(p) / float(yrs), expectancy=p.mean(),
                best=p.max(), worst=p.min())
