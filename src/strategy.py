"""Gold Trend-Momentum v1 for XAUUSD (M15).

Logic (signal on bar CLOSE, entry NEXT bar OPEN -> no lookahead bias):
  Trend filter:
    LONG-only  when Close > EMA20 > EMA50
    SHORT-only when Close < EMA20 < EMA50
  Momentum trigger (RSI-14 crosses midline in trend direction):
    LONG  = RSI[t-1] < 50 and RSI[t] >= 50
    SHORT = RSI[t-1] > 50 and RSI[t] <= 50
  Session filter: entries only 07:00-21:00 GMT (London + New York)
  Risk: SL = 2 x ATR(14), TP = 4 x ATR(14)  => 1:2 risk:reward, 1% risk/trade
"""
import pandas as pd
from .indicators import ema, rsi_wilder, atr_wilder

PARAMS = dict(
    ema_fast=20,
    ema_slow=50,
    rsi_period=14,
    rsi_mid=50.0,
    atr_period=14,
    sl_atr_mult=2.0,
    tp_atr_mult=4.0,
    session_start=7,    # GMT hour (inclusive)
    session_end=21,     # GMT hour (exclusive)
)


def add_indicators(df: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = ema(df["close"], p["ema_fast"])
    df["ema_slow"] = ema(df["close"], p["ema_slow"])
    df["rsi"] = rsi_wilder(df["close"], p["rsi_period"])
    df["atr"] = atr_wilder(df["high"], df["low"], df["close"], p["atr_period"])
    return df


def add_signals(df: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """Adds 'signal': +1 long, -1 short, 0 none. Entry is taken on the NEXT bar,
    so the session filter is evaluated on the next bar's timestamp."""
    df = df.copy()
    uptrend = (df["close"] > df["ema_fast"]) & (df["ema_fast"] > df["ema_slow"])
    downtrend = (df["close"] < df["ema_fast"]) & (df["ema_fast"] < df["ema_slow"])
    rsi = df["rsi"]
    mid = p["rsi_mid"]
    df["signal"] = 0
    df.loc[uptrend & (rsi.shift(1) < mid) & (rsi >= mid), "signal"] = 1
    df.loc[downtrend & (rsi.shift(1) > mid) & (rsi <= mid), "signal"] = -1
    # session filter on the ENTRY bar (next bar)
    nxt = pd.to_datetime(df["time"]).shift(-1)
    entry_hour = nxt.dt.hour + nxt.dt.minute / 60.0
    in_session = (entry_hour >= p["session_start"]) & (entry_hour < p["session_end"])
    df.loc[~in_session.fillna(False), "signal"] = 0
    # indicator warmup
    df.loc[df[["ema_slow", "rsi", "atr"]].isna().any(axis=1), "signal"] = 0
    return df
