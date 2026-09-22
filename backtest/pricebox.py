"""
PRICE-LEVEL CROSS BOX — the user's actual idea, vectorised with numpy only.

Idea: a chop box is a PRICE AREA that the 1M EMA cross keeps returning to.
So we look at the PRICES of recent crosses, not their count.

For every bar:
  - take the prices of the last `mem` crosses (a rolling window of cross EVENTS,
    not of bars - so a quiet hour does not dilute it)
  - count how many of them lie within +/- h/2 of the current close
  - if that count >= k  ->  we are inside a cross-cluster box -> BLOCK

Band height h is self-scaling: it is the median absolute deviation of those
same cross prices (pure cross data, no indicator).

BOX-B (5M reversal lag): the 5M trend has just flipped; the 1M EMA is still
oscillating around the new direction. We detect it with cross data only:
bars since the 5M flip, combined with whether the 1M cross direction
disagrees with the cross that came before it (a flip-flop).
"""
import numpy as np
import pandas as pd


def build(df, mem=12, look_bars=240):
    """Attach cross-cluster descriptors. Pure cross-price geometry."""
    n = len(df)
    c = df["close"].to_numpy(float)
    bull = df["bull"].to_numpy()
    bear = df["bear"].to_numpy()
    cross = bull | bear
    cidx = np.flatnonzero(cross)
    cprice = c[cidx]
    cdir = np.where(bull[cidx], 1, -1)

    clusterN = np.zeros(n)          # how many recent crosses sit near current price
    bandH = np.full(n, np.nan)      # self-scaling band height
    spanRec = np.full(n, np.nan)    # price span covered by the last `mem` crosses
    flipflop = np.zeros(n)          # direction alternations among last `mem` crosses

    # pointer over cross events
    for i in range(n):
        # index of last cross at or before bar i
        j = np.searchsorted(cidx, i, side="right") - 1
        if j < mem - 1:
            continue
        lo = j - mem + 1
        pr = cprice[lo:j + 1]
        di = cdir[lo:j + 1]
        # only consider crosses that are recent in TIME too
        if i - cidx[lo] > look_bars:
            # shrink window to those within look_bars
            keep = (i - cidx[lo:j + 1]) <= look_bars
            if keep.sum() < 4:
                continue
            pr = pr[keep]
            di = di[keep]
        med = np.median(pr)
        mad = np.median(np.abs(pr - med))
        bandH[i] = mad
        spanRec[i] = pr.max() - pr.min()
        if mad > 0:
            clusterN[i] = np.sum(np.abs(pr - c[i]) <= mad)
        else:
            clusterN[i] = len(pr)
        flipflop[i] = np.sum(di[1:] != di[:-1])

    df["clusterN"] = clusterN
    df["bandH"] = bandH
    df["spanRec"] = spanRec
    df["flipflop"] = flipflop
    # how tight the cluster is relative to its own span
    df["tight"] = df["bandH"] / df["spanRec"].replace(0, np.nan)
    return df
