"""
CUSTOM RED BOX — built ONLY from EMA-cross behaviour.
No ATR, no ADX, no RSI, no volatility measure, no pivots.
The only raw materials are:
  (a) the 1M EMA cross events themselves
  (b) the 5M EMA trend state and when it flips
Everything below is a *count* or an *age in bars* of those two things.
"""
import numpy as np, pandas as pd


def cross_features(df, churn_win=60, recent_win=20):
    """
    BOX-A  (churn / whipsaw zone):
        how many 1M crosses happened in the last `churn_win` bars,
        and how many bars since the previous cross.
    BOX-B  (5M reversal-lag zone):
        how many bars since the 5M trend last flipped, i.e. the window
        where the 5M EMA is still 'catching up' and 1M keeps faking.
    """
    n = len(df)
    bull = df["bull"].to_numpy()
    bear = df["bear"].to_numpy()
    cross = bull | bear

    # ---------- BOX-A ingredients ----------
    # rolling count of crosses (pure event count, nothing else)
    cnt = pd.Series(cross.astype(float)).rolling(churn_win, min_periods=1).sum().to_numpy()
    cnt_recent = pd.Series(cross.astype(float)).rolling(recent_win, min_periods=1).sum().to_numpy()

    # bars since previous cross (gap). small gap = crosses stacking up
    gap = np.full(n, np.nan)
    last = -1
    for i in range(n):
        gap[i] = (i - last) if last >= 0 else np.nan
        if cross[i]:
            last = i

    # mean gap of the last 5 crosses -> tight cluster detector
    cross_idx = np.flatnonzero(cross)
    mean_gap5 = np.full(n, np.nan)
    if len(cross_idx) > 5:
        d = np.diff(cross_idx)
        roll = pd.Series(d).rolling(5).mean().to_numpy()
        # roll[k] belongs to cross_idx[k+1]; valid from that bar onward
        for k in range(len(roll)):
            if not np.isnan(roll[k]):
                a = cross_idx[k + 1]
                b = cross_idx[k + 2] if k + 2 < len(cross_idx) else n
                mean_gap5[a:b] = roll[k]

    # ---------- BOX-B ingredients ----------
    hb = df["htfBull"].to_numpy()
    hs = df["htfBear"].to_numpy()
    state = np.where(hb, 1, np.where(hs, -1, 0))
    flip_age = np.full(n, np.nan)
    last_flip = -1
    prev = 0
    for i in range(n):
        if state[i] != 0 and prev != 0 and state[i] != prev:
            last_flip = i
        if state[i] != 0:
            prev = state[i]
        flip_age[i] = (i - last_flip) if last_flip >= 0 else np.nan

    # was the 1M cross fighting the *previous* 5M direction moments ago?
    # count how many 1M crosses happened since the 5M flip
    cross_since_flip = np.zeros(n)
    c = 0
    for i in range(n):
        if flip_age[i] == 0:
            c = 0
        if cross[i]:
            c += 1
        cross_since_flip[i] = c

    df["xCount60"] = cnt
    df["xCount20"] = cnt_recent
    df["xGap"] = gap
    df["xMeanGap5"] = mean_gap5
    df["flipAge"] = flip_age
    df["xSinceFlip"] = cross_since_flip
    return df
