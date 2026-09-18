"""Smart Money Concepts (LuxAlgo) — Python port of the DECISION logic.

Ported from Pine Script "Smart Money Concepts [LuxAlgo]" v5
(CC BY-NC-SA 4.0, © LuxAlgo). Only the parts that produce trading information are
ported — all drawing (labels/lines/boxes) is dropped.

Ported pieces, keeping the original names:
  leg(size)             -> fractal pivot scan: a bar is a swing point when its
                           high/low is beyond every high/low of the `size` bars
                           that follow it (high[size] > highest(size), etc.)
  getCurrentStructure() -> keeps the last confirmed swing high / swing low level
  displayStructure()    -> BOS / CHoCH when the close crosses that level, and the
                           trend bias update (BULLISH / BEARISH)
  premium/discount      -> trailing swing extremes + equilibrium (50%) level
  fair value gaps       -> 3-candle imbalance with LuxAlgo's auto threshold
  order blocks          -> block stored on every structure break (parsed H/L scan)

Everything is evaluated on CLOSED bars: a value at index i is known at the close of
bar i and is traded at the open of bar i+1 (the backtest does the shift).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BULLISH, BEARISH = 1, -1
HIGH_VOL_ATR_LEN = 200


def _leg(df: pd.DataFrame, size: int) -> np.ndarray:
    """Pine: leg(size) — 0 = bearish leg (a swing high just formed),
    1 = bullish leg (a swing low just formed)."""
    high = df["high"]
    low = df["low"]
    new_leg_high = high.shift(size) > high.rolling(size).max()
    new_leg_low = low.shift(size) < low.rolling(size).min()
    nh = new_leg_high.to_numpy()
    nl = new_leg_low.to_numpy()
    leg = np.zeros(len(df), dtype=int)
    cur = 0
    for i in range(len(df)):
        if nh[i]:
            cur = 0          # BEARISH_LEG
        elif nl[i]:
            cur = 1          # BULLISH_LEG
        leg[i] = cur
    return leg


def compute_structure(df: pd.DataFrame, size: int, swing: dict | None = None) -> dict:
    """Pine: getCurrentStructure(size) + displayStructure().

    Returns dict of arrays (index = bar of the chart):
      leg, bias, event (+1 bull / -1 bear), tag ('BOS'/'CHoCH'),
      high_level, low_level, pivot_high_price, pivot_low_price

    `swing` = result of the same function for the swing structure size; used for the
    internal structure's extra condition (internal level != swing level), exactly like
    the Pine code's `internalHigh.currentLevel != swingHigh.currentLevel`.
    """
    n = len(df)
    leg = _leg(df, size)
    ch = np.zeros(n, dtype=int)
    ch[1:] = np.sign(np.diff(leg)).astype(int)
    pivot_low = ch == 1
    pivot_high = ch == -1

    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)

    bias = np.zeros(n, dtype=int)
    event = np.zeros(n, dtype=int)
    tag = np.array([""] * n, dtype=object)
    high_level = np.full(n, np.nan)
    low_level = np.full(n, np.nan)
    pivot_high_price = np.full(n, np.nan)
    pivot_low_price = np.full(n, np.nan)

    lvl_h = np.nan          # swingHigh.currentLevel
    lvl_l = np.nan          # swingLow.currentLevel
    crossed_h = True        # swingHigh.crossed (nothing to cross before first pivot)
    crossed_l = True
    b = 0
    lvl_h_prev = np.nan     # level value one bar ago (Pine compares with level[1])
    lvl_l_prev = np.nan

    for i in range(n):
        lvl_h_prev, lvl_l_prev = lvl_h, lvl_l
        # ---- pivot updates happen before the break checks (same as the script) ----
        if pivot_high[i]:
            j = i - size
            if j >= 0:
                lvl_h = high[j]
                crossed_h = False
                pivot_high_price[i] = lvl_h
        if pivot_low[i]:
            j = i - size
            if j >= 0:
                lvl_l = low[j]
                crossed_l = False
                pivot_low_price[i] = lvl_l

        prev_close = close[i - 1] if i > 0 else close[i]
        prev_h = lvl_h_prev if not np.isnan(lvl_h_prev) else lvl_h
        prev_l = lvl_l_prev if not np.isnan(lvl_l_prev) else lvl_l

        # ---- bullish break: close crosses above the last swing high ----
        if not crossed_h and not np.isnan(lvl_h):
            extra = True
            if swing is not None:
                sl = swing["high_level"][i]
                extra = (not np.isnan(sl)) and (lvl_h != sl)
            if prev_close <= prev_h < close[i] and extra:
                tag[i] = "CHoCH" if b == BEARISH else "BOS"
                crossed_h = True
                b = BULLISH
                event[i] = 1

        # ---- bearish break: close crosses below the last swing low ----
        if not crossed_l and not np.isnan(lvl_l):
            extra = True
            if swing is not None:
                sl = swing["low_level"][i]
                extra = (not np.isnan(sl)) and (lvl_l != sl)
            if prev_close >= prev_l > close[i] and extra:
                tag[i] = "CHoCH" if b == BULLISH else "BOS"
                crossed_l = True
                b = BEARISH
                event[i] = -1

        bias[i] = b
        high_level[i] = lvl_h
        low_level[i] = lvl_l

    return dict(leg=leg, bias=bias, event=event, tag=tag,
                high_level=high_level, low_level=low_level,
                pivot_high=pivot_high_price, pivot_low=pivot_low_price)


def premium_discount(df: pd.DataFrame, structure: dict) -> dict:
    """Pine: updateTrailingExtremes() + drawPremiumDiscountZones().

    trailing.top    = highest high since the last swing high pivot (reset to the pivot)
    trailing.bottom = lowest low since the last swing low pivot
    equilibrium     = (top + bottom) / 2 ; above = premium, below = discount
    """
    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    top = np.full(n, np.nan)
    bottom = np.full(n, np.nan)
    t_top = np.nan
    t_bot = np.nan
    for i in range(n):
        if not np.isnan(structure["pivot_high"][i]):
            t_top = structure["pivot_high"][i]
        if not np.isnan(structure["pivot_low"][i]):
            t_bot = structure["pivot_low"][i]
        t_top = np.nanmax([high[i], t_top]) if not (np.isnan(high[i]) and np.isnan(t_top)) else np.nan
        t_bot = np.nanmin([low[i], t_bot]) if not (np.isnan(low[i]) and np.isnan(t_bot)) else np.nan
        top[i] = t_top
        bottom[i] = t_bot
    eq = (top + bottom) / 2.0
    return dict(top=top, bottom=bottom, equilibrium=eq)


def fair_value_gaps(df: pd.DataFrame, auto_threshold: bool = True) -> dict:
    """Pine: drawFairValueGaps() — 3-candle imbalance with LuxAlgo's auto threshold.

    bullish: currentLow > last2High and lastClose > last2High and barDelta% > thr
    bearish: currentHigh < last2Low and lastClose < last2Low and -barDelta% > thr
    threshold = cum(|barDelta%|) / bar_index * 2   (auto)
    """
    n = len(df)
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    delta_pct = np.zeros(n)
    delta_pct[1:] = (c[:-1] - o[:-1]) / (o[:-1] * 100.0)
    thr = np.zeros(n)
    if auto_threshold:
        run = np.cumsum(np.abs(delta_pct))
        idx = np.arange(1, n + 1)
        thr = run / idx * 2.0
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)
    for i in range(2, n):
        last_close = c[i - 1]
        last2_high = h[i - 2]
        last2_low = l[i - 2]
        if l[i] > last2_high and last_close > last2_high and delta_pct[i - 1] > thr[i - 1]:
            bull[i] = True
        if h[i] < last2_low and last_close < last2_low and -delta_pct[i - 1] > thr[i - 1]:
            bear[i] = True
    return dict(bullish=bull, bearish=bear, threshold=thr)


def order_blocks(df: pd.DataFrame, structure: dict, use_atr_filter: bool = True) -> list[dict]:
    """Pine: storeOrdeBlock() — on every break, store the bar with the most extreme
    parsed high/low between the broken pivot and the break bar."""
    from .indicators import atr_wilder

    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    times = pd.to_datetime(df["time"]).to_numpy()
    if use_atr_filter:
        vol = atr_wilder(df["high"], df["low"], df["close"], HIGH_VOL_ATR_LEN).to_numpy()
    else:
        tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(df["close"].to_numpy(), 1)),
                                              np.abs(low - np.roll(df["close"].to_numpy(), 1))))
        vol = np.cumsum(tr) / np.arange(1, n + 1)
    hi_vol = (high - low) >= (2 * np.nan_to_num(vol))
    parsed_high = np.where(hi_vol, low, high)
    parsed_low = np.where(hi_vol, high, low)

    out = []
    ev = structure["event"]
    leg = structure["leg"]
    for i in range(1, n):
        if ev[i] == 0:
            continue
        # find the pivot bar that was just broken: walk back to the last leg change
        j = i
        while j > 0 and leg[j] == leg[i]:
            j -= 1
        if j <= 0:
            continue
        if ev[i] == 1:      # bullish break -> OB built from the lowest parsed low
            seg = parsed_low[j:i + 1]
            k = j + int(np.nanargmin(seg))
            out.append(dict(bias=BULLISH, index=k, time=times[k],
                            top=parsed_high[k], bottom=parsed_low[k]))
        else:               # bearish break -> OB built from the highest parsed high
            seg = parsed_high[j:i + 1]
            k = j + int(np.nanargmax(seg))
            out.append(dict(bias=BEARISH, index=k, time=times[k],
                            top=parsed_high[k], bottom=parsed_low[k]))
    return out
