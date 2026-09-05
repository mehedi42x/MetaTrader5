"""
mt5_loader.py
=============
Robust loader for large real MetaTrader5 tick exports (XAUUSD.txt / .csv).

Handles the common MT5 export layouts automatically:

  <DATE>	<TIME>	<BID>	<ASK>	<LAST>	<VOLUME>
  2020.01.02	00:00:01.123	1517.20	1517.55	0	0

  DATE,TIME,BID,ASK,LAST,VOLUME
  TIME,BID,ASK,LAST,VOLUME,FLAGS

Separator (tab / comma / semicolon) and date format are auto-detected.
Reads in chunks so a 480 MB file never blows up memory, and can optionally
stream month-by-month for very large multi-year files.
"""

from __future__ import annotations

import os
import numpy as np
import pandas as pd


def _norm(c: str) -> str:
    return c.strip().lower().replace("<", "").replace(">", "").replace(" ", "")


def sniff(path: str, n: int = 5) -> dict:
    """Peek at the file and report the detected layout."""
    with open(path, "r", errors="replace") as f:
        head = [f.readline().rstrip("\n") for _ in range(n)]
    head = [h for h in head if h]
    sep = "\t" if "\t" in head[0] else ("," if "," in head[0] else ";")
    cols = [_norm(c) for c in head[0].split(sep)]
    has_header = any(c in ("date", "time", "bid", "ask", "timestamp") for c in cols)
    return {"sep": sep, "columns": cols, "has_header": has_header, "sample": head}


def load_ticks(path: str, chunksize: int = 4_000_000, verbose: bool = True) -> pd.DataFrame:
    """Load a full MT5 tick export into a DataFrame with ts/bid/ask/time."""
    info = sniff(path)
    sep, cols, hdr = info["sep"], info["columns"], info["has_header"]
    if verbose:
        size_mb = os.path.getsize(path) / 1e6
        print(f"[loader] {path}  {size_mb:,.1f} MB")
        print(f"[loader] sep={sep!r} header={hdr} cols={cols}")
        for s in info["sample"][:3]:
            print("[loader] sample:", s[:120])

    parts = []
    reader = pd.read_csv(
        path, sep=sep, header=0 if hdr else None,
        chunksize=chunksize, engine="c", low_memory=False,
        dtype=str, na_filter=False,
    )
    total = 0
    for i, ch in enumerate(reader):
        ch.columns = [_norm(str(c)) for c in ch.columns]
        parts.append(_parse_chunk(ch))
        total += len(ch)
        if verbose:
            print(f"[loader] chunk {i+1}: {total:,} rows")
    df = pd.concat(parts, ignore_index=True)
    del parts

    df = df.dropna(subset=["time", "bid", "ask"])
    df = df[(df["ask"] > df["bid"]) & (df["bid"] > 0)]
    df = df.sort_values("time", kind="mergesort").reset_index(drop=True)
    # Resolution-agnostic epoch seconds. pandas may store datetime64 as
    # ns / us / ms depending on version and input, so convert explicitly
    # instead of assuming nanoseconds (this silently broke timestamps by
    # 1000x and made every trade appear to last microseconds).
    df["ts"] = df["time"].values.astype("datetime64[ms]").astype("int64") / 1000.0
    if verbose:
        print(f"[loader] clean ticks: {len(df):,}")
        print(f"[loader] range: {df['time'].iloc[0]} -> {df['time'].iloc[-1]}")
    return df[["time", "ts", "bid", "ask"]]


def _parse_chunk(ch: pd.DataFrame) -> pd.DataFrame:
    cols = list(ch.columns)

    # ---- locate the timestamp -------------------------------------------
    if "date" in cols and "time" in cols:
        t = ch["date"].str.strip() + " " + ch["time"].str.strip()
    elif "time" in cols:
        t = ch["time"].str.strip()
    elif "timestamp" in cols:
        t = ch["timestamp"].str.strip()
    else:  # headerless -> positional
        ch.columns = ["date", "time", "bid", "ask"] + cols[4:]
        t = ch["date"].str.strip() + " " + ch["time"].str.strip()
        cols = list(ch.columns)

    t = t.str.replace(".", "-", regex=False, n=2)  # 2020.01.02 -> 2020-01-02
    time = pd.to_datetime(t, errors="coerce", format="mixed")

    bid = pd.to_numeric(ch["bid"], errors="coerce") if "bid" in cols else np.nan
    ask = pd.to_numeric(ch["ask"], errors="coerce") if "ask" in cols else np.nan

    out = pd.DataFrame({"time": time, "bid": bid, "ask": ask})

    # some exports leave bid/ask empty on trade ticks -> forward fill quotes
    out["bid"] = out["bid"].replace(0, np.nan).ffill()
    out["ask"] = out["ask"].replace(0, np.nan).ffill()
    return out


if __name__ == "__main__":
    import sys
    p = sys.argv[1]
    print(sniff(p))
