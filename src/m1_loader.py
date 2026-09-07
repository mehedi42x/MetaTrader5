"""
m1_loader.py -- load HistData MT-format M1 (1-minute) bars.

FORMAT
    YYYY.MM.DD,HH:MM,open,high,low,close,volume
    2018.01.01,18:01,1302.340000,1302.820000,1302.340000,1302.590000,0

Timestamps are US Eastern WITH daylight saving (same convention as the
tick archives), so they are localised to America/New_York and converted
to UTC. Volume is always 0 in this feed and is ignored.

IMPORTANT -- M1 DATA HAS NO SPREAD
----------------------------------
The tick archives carried a real bid and ask, so cost could be measured
per trade. These M1 bars are mid/bid-only OHLC: there is no spread in
the file at all. Any backtest on them must therefore IMPOSE a spread
assumption, and that assumption decides the result.

From the 12.8M real ticks already analysed we know the true spread by
UTC hour, so instead of one flat guess we reuse that measured profile
(see SPREAD_BY_HOUR). This keeps the M1 backtest anchored to what the
tick data actually showed rather than to an optimistic constant.
"""

from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd


# Median spread by UTC hour, measured on the real XAUUSD tick archives
# (see results/ARB_REPORT.md section 3.4). Used because M1 files carry
# no bid/ask of their own.
SPREAD_BY_HOUR = {
    0: 0.347, 1: 0.340, 2: 0.337, 3: 0.340, 4: 0.343, 5: 0.330,
    6: 0.330, 7: 0.330, 8: 0.330, 9: 0.330, 10: 0.330, 11: 0.330,
    12: 0.330, 13: 0.345, 14: 0.360, 15: 0.355, 16: 0.340, 17: 0.340,
    18: 0.345, 19: 0.350, 20: 0.502, 21: 0.898, 22: 0.622, 23: 0.577,
}


def load_file(path: str) -> pd.DataFrame:
    df = pd.read_csv(
        path, header=None,
        names=["date", "time", "open", "high", "low", "close", "volume"],
        dtype={"date": str, "time": str},
    )
    ts = pd.to_datetime(df["date"] + " " + df["time"],
                        format="%Y.%m.%d %H:%M")
    ts = (ts.dt.tz_localize("America/New_York",
                            ambiguous="NaT", nonexistent="NaT")
            .dt.tz_convert("UTC"))
    df["dt"] = ts
    df = df.dropna(subset=["dt"]).drop(columns=["date", "time", "volume"])
    return df


def load_dir(directory: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(directory, "DAT_MT_XAUUSD_M1_*.csv")))
    if not files:
        raise FileNotFoundError(f"no M1 csv files in {directory}")
    parts = []
    for f in files:
        d = load_file(f)
        parts.append(d)
        print(f"  {os.path.basename(f):<34} {len(d):>8,} bars  "
              f"{d['dt'].min()} -> {d['dt'].max()}")
    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values("dt").drop_duplicates("dt").reset_index(drop=True)

    df["hour"] = df["dt"].dt.hour
    df["date"] = df["dt"].dt.normalize()
    df["dow"] = df["dt"].dt.dayofweek
    df["year"] = df["dt"].dt.year
    df["spread"] = df["hour"].map(SPREAD_BY_HOUR).astype(float)
    return df


def save_parquet(df: pd.DataFrame, out: str):
    try:
        df.to_parquet(out, index=False)
        print(f"wrote {out}")
    except Exception:
        out = out.replace(".parquet", ".pkl")
        df.to_pickle(out)
        print(f"wrote {out}")
    return out


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "/tmp/m1"
    print("loading M1 files ...")
    df = load_dir(d)
    print(f"\ntotal {len(df):,} bars  {df['dt'].min()} -> {df['dt'].max()}")
    print(f"trading days: {df['date'].nunique():,}")
    print(f"years: {sorted(df['year'].unique())}")
    print(f"price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
    if len(sys.argv) > 2:
        save_parquet(df, sys.argv[2])
