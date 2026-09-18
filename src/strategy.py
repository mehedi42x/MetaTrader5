"""Pure EMA 9/12 Crossover for XAUUSD (M15) — nothing else.

  BUY  when EMA9 crosses ABOVE EMA12 (confirmed on bar close, entry next bar open)
  SELL when EMA9 crosses BELOW EMA12
  EXIT = opposite crossover (position reverses, always in market)

No RSI, no session filter, no SL/TP — crossover only.
"""
import numpy as np
import pandas as pd
from .indicators import ema

PARAMS = dict(
    ema_fast=9,
    ema_slow=12,
)


def add_indicators(df: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = ema(df["close"], p["ema_fast"])
    df["ema_slow"] = ema(df["close"], p["ema_slow"])
    return df


def add_filters(df: pd.DataFrame, trend_span: int = 200) -> pd.DataFrame:
    """Adds the columns needed by the entry filter (see backtest `entry_filter`):
      ema_trend : EMA of the brick close (higher-timeframe-style trend of the
                  brick series itself)
      dist      : |close - EMA12| in $ — how far price has walked from the slow
                  EMA when the cross happens (real crosses have dist ~1.2 $,
                  the EMA9-EMA12 gap itself is only ~0.03 $ and useless)
    """
    df = df.copy()
    df["ema_trend"] = ema(df["close"], trend_span)
    df["dist"] = (df["close"] - df["ema_slow"]).abs()
    return df


def add_mtf_direction(df: pd.DataFrame, mtf_candles: pd.DataFrame,
                      fast: int = 9, slow: int = 12,
                      tf_minutes: int = 15) -> pd.DataFrame:
    """Higher-timeframe EMA direction mapped onto the trading timeframe — no lookahead.

    mtf_candles are timestamped at the START of each candle (pandas resample
    default), so the state of a candle is only known when it CLOSES: we label it
    with start + tf_minutes and merge_asof(backward) onto df["time"].  The result
    column `mtf_dir` is +1 when the higher-TF EMA(fast) is above EMA(slow), -1 below,
    0 before the first higher-TF candle has closed.
    """
    mtf = mtf_candles.copy()
    mtf["ema_fast"] = ema(mtf["close"], fast)
    mtf["ema_slow"] = ema(mtf["close"], slow)
    mtf["mtf_dir"] = np.sign(mtf["ema_fast"] - mtf["ema_slow"]).fillna(0).astype(int)
    mtf["known_at"] = pd.to_datetime(mtf["time"]) + pd.Timedelta(minutes=tf_minutes)
    cols = mtf[["known_at", "mtf_dir"]].sort_values("known_at")

    out = df.copy()
    out["time"] = pd.to_datetime(out["time"])
    out = pd.merge_asof(out.sort_values("time"), cols, left_on="time",
                        right_on="known_at", direction="backward")
    out["mtf_dir"] = out["mtf_dir"].fillna(0).astype(int)
    return out.drop(columns=["known_at"])


def add_signals(df: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """Adds 'signal': +1 = bullish cross, -1 = bearish cross, 0 = none.
    Signal on bar CLOSE, traded on NEXT bar OPEN (no lookahead)."""
    df = df.copy()
    f, s = df["ema_fast"], df["ema_slow"]
    cross_up = (f.shift(1) <= s.shift(1)) & (f > s)
    cross_dn = (f.shift(1) >= s.shift(1)) & (f < s)
    df["signal"] = 0
    df.loc[cross_up, "signal"] = 1
    df.loc[cross_dn, "signal"] = -1
    df.loc[df[["ema_fast", "ema_slow"]].isna().any(axis=1), "signal"] = 0
    return df
