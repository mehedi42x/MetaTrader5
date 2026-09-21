"""
Step 1 (EMPIRICAL, no formula): run the raw baseline strategy (1M cross + 5M trend,
NO red box, NO filters) and record rich price-structure context at every entry bar.
We then let the DATA tell us where losses cluster.
"""
import numpy as np, pandas as pd, engine as e


def swing_context(df, look=60, piv_l=3, piv_r=3):
    """Pure price-structure descriptors at each bar - no strategy assumptions."""
    h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    n = len(h)

    # rolling extremes of the last `look` bars (structure the price sits inside)
    hh = pd.Series(h).rolling(look).max().to_numpy()
    ll = pd.Series(l).rolling(look).min().to_numpy()

    # confirmed fractal pivots (3 left / 3 right) -> last known pivot high/low
    isph = np.zeros(n, bool); ispl = np.zeros(n, bool)
    for i in range(piv_l, n - piv_r):
        w = h[i - piv_l:i + piv_r + 1]
        if h[i] == w.max() and (w.argmax() == piv_l):
            isph[i] = True
        w2 = l[i - piv_l:i + piv_r + 1]
        if l[i] == w2.min() and (w2.argmin() == piv_l):
            ispl[i] = True
    # value becomes *known* only piv_r bars later
    lastph = np.full(n, np.nan); lastpl = np.full(n, np.nan)
    ph_age = np.full(n, np.nan); pl_age = np.full(n, np.nan)
    cph = np.nan; cpl = np.nan; cphi = -1; cpli = -1
    for i in range(n):
        j = i - piv_r
        if j >= 0 and isph[j]:
            cph = h[j]; cphi = j
        if j >= 0 and ispl[j]:
            cpl = l[j]; cpli = j
        lastph[i] = cph; lastpl[i] = cpl
        ph_age[i] = i - cphi if cphi >= 0 else np.nan
        pl_age[i] = i - cpli if cpli >= 0 else np.nan

    df["hh60"] = hh; df["ll60"] = ll
    df["lastPH"] = lastph; df["lastPL"] = lastpl
    df["phAge"] = ph_age; df["plAge"] = pl_age
    # how many times price revisited the pivot-high level (stalling proxy)
    df["rangePct"] = (c - ll) / np.where((hh - ll) == 0, np.nan, hh - ll)
    df["distPH"] = lastph - c          # >0 => price below pivot high
    df["distPL"] = c - lastpl          # >0 => price above pivot low
    df["range60"] = hh - ll
    return df


def collect(df, spread=0.2, label=""):
    """Run baseline (no box/filter) and attach entry-bar context to each trade."""
    stats, t = e.run(df, qty=1.0, spread=spread, use_box=False, label=label)
    if len(t) == 0:
        return t
    idx = {d: i for i, d in enumerate(df["dt"].to_numpy())}
    rows = [idx[d] for d in t["entry_time"].to_numpy()]
    cols = ["atr14", "sep", "adx", "hour", "close", "lastPH", "lastPL", "phAge", "plAge",
            "hh60", "ll60", "rangePct", "distPH", "distPL", "range60", "inBox"]
    for col in cols:
        t[col] = df[col].to_numpy()[rows]
    t["entry_bar"] = rows
    t["win"] = t["pnl"] > 0
    # normalised structure position
    t["distPH_atr"] = t["distPH"] / t["atr14"]
    t["distPL_atr"] = t["distPL"] / t["atr14"]
    t["range_atr"] = t["range60"] / t["atr14"]
    t["sep_atr"] = t["sep"] / t["atr14"]
    return t
