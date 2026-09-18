"""Pure EMA 9/12 Crossover for XAUUSD (M15) — nothing else.

  BUY  when EMA9 crosses ABOVE EMA12 (confirmed on bar close, entry next bar open)
  SELL when EMA9 crosses BELOW EMA12
  EXIT = opposite crossover (position reverses, always in market)

No RSI, no session filter, no SL/TP — crossover only.
"""
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
