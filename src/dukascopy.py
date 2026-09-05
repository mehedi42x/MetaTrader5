"""
dukascopy.py
============
Dukascopy tick-data downloader + decoder for XAUUSD (or any instrument).

Dukascopy publishes free historical tick data as one LZMA-compressed binary
file per hour:

    https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5

Notes on the format (these details are what make most naive parsers wrong):

  * MM is **0-indexed** (January = 00, December = 11). DD is 1-indexed.
  * Hours are **UTC** (actually GMT, no DST shifts).
  * The body is raw LZMA1 (alone) — not xz, not gzip. Needs an explicit
    filter spec to decode with Python's lzma module.
  * Each record is 20 bytes, big-endian: >IIIff
        uint32  ms offset from the hour start
        uint32  ask, as an integer in "points"
        uint32  bid, as an integer in "points"
        float32 ask volume (millions)
        float32 bid volume (millions)
  * Prices must be divided by 10**point_digits. For XAUUSD Dukascopy uses
    3 decimals -> divide by 1000. For most FX pairs it is 5 (JPY pairs 3).
  * A missing/empty file (weekend, holiday, market closed) returns HTTP 404
    or a zero-length body — that is normal and must not abort the download.

Usage
-----
    # 2 years of XAUUSD ticks -> data/XAUUSD_ticks.csv
    python src/dukascopy.py --symbol XAUUSD --years 2 --out data/XAUUSD_ticks.csv

    # explicit range, more parallelism, keep the raw cache
    python src/dukascopy.py --symbol XAUUSD \
        --start 2023-09-01 --end 2025-09-01 \
        --workers 12 --cache data/.duka_cache --out data/XAUUSD_ticks.csv

The output CSV is written in MetaTrader5 export format so it can be fed
straight into src/report.py:

    <DATE>	<TIME>	<BID>	<ASK>	<LAST>	<VOLUME>
"""

from __future__ import annotations

import argparse
import datetime as dt
import lzma
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

BASE = "https://datafeed.dukascopy.com/datafeed"
REC = struct.Struct(">IIIff")          # 20 bytes per tick
UA = "Mozilla/5.0 (compatible; tick-research/1.0)"

# instrument -> number of price decimals used by Dukascopy
DIGITS = {
    "XAUUSD": 3, "XAGUSD": 3, "USDJPY": 3, "EURJPY": 3, "GBPJPY": 3,
    "EURUSD": 5, "GBPUSD": 5, "AUDUSD": 5, "USDCHF": 5, "USDCAD": 5,
    "NZDUSD": 5, "EURGBP": 5,
}


def url_for(symbol: str, when: dt.datetime) -> str:
    # NOTE: month is zero-indexed in Dukascopy's path scheme
    return (f"{BASE}/{symbol}/{when.year:04d}/{when.month - 1:02d}/"
            f"{when.day:02d}/{when.hour:02d}h_ticks.bi5")


def _decompress(raw: bytes) -> bytes:
    """Dukascopy uses raw LZMA1 ('alone' format) with unknown size."""
    if not raw:
        return b""
    # Most files are the classic .lzma alone-format container.
    try:
        return lzma.decompress(raw, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError:
        pass
    try:
        return lzma.decompress(raw, format=lzma.FORMAT_AUTO)
    except lzma.LZMAError:
        pass
    # Some hours come as headerless raw streams.
    d = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW,
        filters=[{"id": lzma.FILTER_LZMA1, "preset": 6}],
    )
    return d.decompress(raw)


def fetch_hour(symbol: str, when: dt.datetime, cache: str | None,
               retries: int = 4, timeout: int = 45) -> bytes:
    """Download (and cache) one hourly .bi5 file. Returns b'' when absent."""
    cpath = None
    if cache:
        cpath = os.path.join(cache, symbol,
                             f"{when:%Y%m%d}_{when.hour:02d}h.bi5")
        if os.path.exists(cpath):
            with open(cpath, "rb") as f:
                return f.read()

    url = url_for(symbol, when)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):        # market closed - legitimately empty
                raw = b""
                break
            last = e
        except Exception as e:              # transient network / TLS issues
            last = e
        time.sleep(min(2 ** attempt, 10))
    else:
        raise RuntimeError(f"failed {url}: {last}")

    if cpath:
        os.makedirs(os.path.dirname(cpath), exist_ok=True)
        with open(cpath, "wb") as f:
            f.write(raw)
    return raw


def decode_hour(raw: bytes, when: dt.datetime, digits: int) -> pd.DataFrame:
    """Decode one hour of .bi5 bytes into a tick DataFrame."""
    if not raw:
        return pd.DataFrame(columns=["time", "bid", "ask", "bid_vol", "ask_vol"])
    body = _decompress(raw)
    n = len(body) // REC.size
    if n == 0:
        return pd.DataFrame(columns=["time", "bid", "ask", "bid_vol", "ask_vol"])

    arr = np.frombuffer(body[: n * REC.size], dtype=np.dtype([
        ("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"),
        ("askv", ">f4"), ("bidv", ">f4"),
    ]))

    scale = 10.0 ** digits
    base = np.datetime64(when.replace(tzinfo=None), "ms")
    return pd.DataFrame({
        "time": base + arr["ms"].astype("timedelta64[ms]"),
        "bid": arr["bid"].astype(np.float64) / scale,
        "ask": arr["ask"].astype(np.float64) / scale,
        "bid_vol": arr["bidv"].astype(np.float64),
        "ask_vol": arr["askv"].astype(np.float64),
    })


def download(symbol: str, start: dt.datetime, end: dt.datetime,
             workers: int = 8, cache: str | None = None,
             digits: int | None = None, verbose: bool = True) -> pd.DataFrame:
    """Download every hour in [start, end) and return one tick DataFrame."""
    if digits is None:
        digits = DIGITS.get(symbol.upper(), 5)

    hours = []
    cur = start.replace(minute=0, second=0, microsecond=0)
    while cur < end:
        # Dukascopy has no data Sat, or Sun before ~21:00 UTC
        if not (cur.weekday() == 5 or (cur.weekday() == 6 and cur.hour < 21)):
            hours.append(cur)
        cur += dt.timedelta(hours=1)

    if verbose:
        print(f"[duka] {symbol}  {start:%Y-%m-%d} -> {end:%Y-%m-%d}")
        print(f"[duka] {len(hours):,} hourly files, {workers} workers, digits={digits}")

    frames: list[pd.DataFrame] = []
    done = 0
    t0 = time.time()

    def work(h):
        return h, fetch_hour(symbol, h, cache)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for h, raw in ex.map(work, hours):
            try:
                df = decode_hour(raw, h, digits)
                if len(df):
                    frames.append(df)
            except Exception as e:
                print(f"[duka] WARN decode {h}: {e}", file=sys.stderr)
            done += 1
            if verbose and done % 250 == 0:
                el = time.time() - t0
                rate = done / max(el, 1e-9)
                eta = (len(hours) - done) / max(rate, 1e-9)
                got = sum(len(f) for f in frames)
                print(f"[duka] {done:,}/{len(hours):,} files  "
                      f"{got:,} ticks  {rate:.1f} f/s  ETA {eta/60:.1f} min",
                      flush=True)

    if not frames:
        raise RuntimeError("no data downloaded - check symbol/date range/network")

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values("time", kind="mergesort").reset_index(drop=True)
    out = out[(out["ask"] > out["bid"]) & (out["bid"] > 0)]
    if verbose:
        print(f"[duka] total {len(out):,} ticks  "
              f"{out['time'].iloc[0]} -> {out['time'].iloc[-1]}")
    return out


def to_mt5_csv(df: pd.DataFrame, path: str, verbose: bool = True):
    """Write in MetaTrader5 tick-export format (consumed by src/report.py)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    t = df["time"].dt
    out = pd.DataFrame({
        "<DATE>": t.strftime("%Y.%m.%d"),
        "<TIME>": t.strftime("%H:%M:%S.%f").str[:-3],
        "<BID>": df["bid"].map(lambda x: f"{x:.3f}"),
        "<ASK>": df["ask"].map(lambda x: f"{x:.3f}"),
        "<LAST>": 0,
        "<VOLUME>": (df["bid_vol"] + df["ask_vol"]).round(2),
    })
    out.to_csv(path, sep="\t", index=False)
    if verbose:
        print(f"[duka] wrote {path}  ({os.path.getsize(path)/1e6:,.1f} MB)")


def main():
    ap = argparse.ArgumentParser(description="Download Dukascopy tick data")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--years", type=float, default=2.0,
                    help="how many years back from --end (ignored if --start given)")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--cache", default="data/.duka_cache",
                    help="raw .bi5 cache dir (resumable); '' to disable")
    ap.add_argument("--digits", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    end = dt.datetime.strptime(a.end, "%Y-%m-%d") if a.end else \
        dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start = dt.datetime.strptime(a.start, "%Y-%m-%d") if a.start else \
        end - dt.timedelta(days=int(365.25 * a.years))

    out = a.out or f"data/{a.symbol}_ticks.csv"
    df = download(a.symbol, start, end, workers=a.workers,
                  cache=(a.cache or None), digits=a.digits)
    to_mt5_csv(df, out)
    print("\nNext step:")
    print(f"  python src/report.py {out}")


if __name__ == "__main__":
    main()
