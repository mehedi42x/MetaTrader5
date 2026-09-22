"""
CROSS EFFICIENCY BOX  —  scale-free by construction.

The chop signature the user describes is: the 1M EMA crosses keep coming back
to the SAME price area.  Measure it as a ratio of two quantities made of the
same units, so price level and volatility cancel out completely:

    path = sum of |price(cross_k) - price(cross_k-1)|   (total distance travelled)
    span = max(price) - min(price)  over the same crosses   (net area covered)
    eff  = span / path                                  (0 = pure chop, 1 = clean trend)

eff is dimensionless. Gold at 1800 with ATR 0.4 and gold at 5200 with ATR 2.0
produce the same eff for the same geometric behaviour.

BOX-B (5M reversal lag) uses the same trick on the crosses that occurred
since the 5M trend flipped: if those crosses are travelling a lot but
covering no ground, the 1M is still hunting for the new direction.
"""
import numpy as np
import pandas as pd


def build(df, mem=10):
    n = len(df)
    c = df["close"].to_numpy(float)
    bull = df["bull"].to_numpy()
    bear = df["bear"].to_numpy()
    cross = bull | bear
    cidx = np.flatnonzero(cross)
    cp = c[cidx]
    m = len(cidx)

    # rolling over CROSS EVENTS (not bars) so quiet periods don't dilute
    step = np.abs(np.diff(cp, prepend=cp[0]))
    path_e = pd.Series(step).rolling(mem).sum().to_numpy()
    hi_e = pd.Series(cp).rolling(mem).max().to_numpy()
    lo_e = pd.Series(cp).rolling(mem).min().to_numpy()
    span_e = hi_e - lo_e
    with np.errstate(divide="ignore", invalid="ignore"):
        eff_e = np.where(path_e > 0, span_e / path_e, np.nan)

    # how far is current price from the middle of that cross band,
    # expressed as a fraction of the band -> 0 = dead centre of the box
    mid_e = (hi_e + lo_e) / 2.0

    # broadcast event values forward onto bars
    eff = np.full(n, np.nan); span = np.full(n, np.nan)
    hi = np.full(n, np.nan); lo = np.full(n, np.nan); mid = np.full(n, np.nan)
    for k in range(m):
        a = cidx[k]
        b = cidx[k + 1] if k + 1 < m else n
        eff[a:b] = eff_e[k]; span[a:b] = span_e[k]
        hi[a:b] = hi_e[k]; lo[a:b] = lo_e[k]; mid[a:b] = mid_e[k]

    df["xEff"] = eff
    df["xSpan"] = span
    df["xHi"] = hi
    df["xLo"] = lo
    # position inside the cross band: 0 centre, 1 at edge
    with np.errstate(divide="ignore", invalid="ignore"):
        df["xPos"] = np.where(span > 0, np.abs(c - mid) / (span / 2.0), np.nan)
    df["inXBand"] = (c <= hi) & (c >= lo)
    return df
