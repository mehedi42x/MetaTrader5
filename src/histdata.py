"""
histdata.py
===========
Loader for HistData.com ASCII tick-data archives, plus a Google Drive
folder downloader for the monthly ZIPs.

HistData ASCII tick format (inside HISTDATA_COM_ASCII_XAUUSD_T{YYYYMM}.zip)
---------------------------------------------------------------------------
One CSV, no header, one line per tick:

    20240101 170000123,2062.63,2063.13,0
    |               |  |        |       |
    |               |  |        |       +-- volume (almost always 0 for XAUUSD)
    |               |  |        +---------- ask
    |               |  +------------------- bid
    |               +---------------------- milliseconds (3 digits, NO separator)
    +-------------------------------------- YYYYMMDD HHMMSS

Critical details that break naive parsers:

  * The time field is `HHMMSSmmm` with **no colons and no decimal point** —
    the last three digits are milliseconds glued onto the seconds.
  * Timestamps are **US Eastern time (EST/EDT) WITH daylight saving shifts**,
    not UTC and not broker server time. To compare against an MT5 feed you
    must convert; this module returns UTC and can optionally shift to a
    broker offset.
  * Volume is 0 for XAUUSD — it carries no information, ignore it.
  * Bid/ask can momentarily be equal or crossed in thin periods; those rows
    are dropped.

Usage
-----
    # load every monthly zip in a directory into one tick frame
    python src/histdata.py data/xauusd_zips --out data/XAUUSD_ticks.csv

    # download the Google Drive folder first (needs network access to Drive)
    python src/histdata.py --gdrive <FOLDER_ID> --dest data/xauusd_zips
"""

from __future__ import annotations

import argparse
import glob
import io
import os
import re
import sys
import zipfile

import numpy as np
import pandas as pd

# HistData timestamps are US Eastern with DST
HISTDATA_TZ = "America/New_York"


# --------------------------------------------------------------------------- #
def read_zip(path: str, verbose: bool = True) -> pd.DataFrame:
    """Read one HISTDATA_..._T{YYYYMM}.zip into a tick DataFrame (UTC)."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError(f"no CSV inside {path}")
        with z.open(names[0]) as f:
            df = pd.read_csv(
                io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                header=None, names=["dt", "bid", "ask", "vol"],
                dtype={"dt": str}, na_filter=False, engine="c",
            )
    if verbose:
        print(f"[histdata] {os.path.basename(path)}: {len(df):,} raw rows")
    return _parse(df)


def _parse(df: pd.DataFrame) -> pd.DataFrame:
    s = df["dt"].str.strip()

    # "20240101 170000123" -> date part + HHMMSS + mmm
    date = s.str.slice(0, 8)
    hms = s.str.slice(9, 15)
    ms = s.str.slice(15, 18)

    t = pd.to_datetime(date + hms, format="%Y%m%d%H%M%S", errors="coerce")
    t = t + pd.to_timedelta(pd.to_numeric(ms, errors="coerce").fillna(0), unit="ms")

    out = pd.DataFrame({
        "time_et": t,
        "bid": pd.to_numeric(df["bid"], errors="coerce"),
        "ask": pd.to_numeric(df["ask"], errors="coerce"),
    })
    out = out.dropna()

    # US Eastern (with DST) -> UTC. Ambiguous/nonexistent DST instants are
    # dropped rather than guessed.
    et = out["time_et"].dt.tz_localize(
        HISTDATA_TZ, ambiguous="NaT", nonexistent="NaT")
    out["time"] = et.dt.tz_convert("UTC").dt.tz_localize(None)
    out = out.dropna(subset=["time"])

    out = out[(out["ask"] > out["bid"]) & (out["bid"] > 0)]
    return out[["time", "bid", "ask"]].reset_index(drop=True)


# --------------------------------------------------------------------------- #
def load_dir(folder: str, verbose: bool = True) -> pd.DataFrame:
    """Load and concatenate every HistData monthly zip in a folder."""
    zips = sorted(glob.glob(os.path.join(folder, "*.zip")))
    if not zips:
        raise FileNotFoundError(f"no .zip files in {folder}")
    if verbose:
        print(f"[histdata] {len(zips)} monthly archives in {folder}")

    frames = []
    for p in zips:
        try:
            frames.append(read_zip(p, verbose=verbose))
        except Exception as e:
            print(f"[histdata] WARN {os.path.basename(p)}: {e}", file=sys.stderr)

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("time", kind="mergesort").reset_index(drop=True)
    df = df.drop_duplicates(subset=["time", "bid", "ask"])
    df["ts"] = df["time"].values.astype("datetime64[ms]").astype("int64") / 1000.0

    if verbose:
        span = (df["time"].iloc[-1] - df["time"].iloc[0]).days
        print(f"[histdata] TOTAL {len(df):,} ticks  "
              f"{df['time'].iloc[0]} -> {df['time'].iloc[-1]}  ({span} days)")
    return df[["time", "ts", "bid", "ask"]]


def to_mt5_csv(df: pd.DataFrame, path: str, verbose: bool = True):
    """Write MT5 tick-export format so src/report.py can consume it."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    t = df["time"].dt
    pd.DataFrame({
        "<DATE>": t.strftime("%Y.%m.%d"),
        "<TIME>": t.strftime("%H:%M:%S.%f").str[:-3],
        "<BID>": df["bid"].map(lambda x: f"{x:.3f}"),
        "<ASK>": df["ask"].map(lambda x: f"{x:.3f}"),
        "<LAST>": 0,
        "<VOLUME>": 0,
    }).to_csv(path, sep="\t", index=False)
    if verbose:
        print(f"[histdata] wrote {path} ({os.path.getsize(path)/1e6:,.1f} MB)")


# --------------------------------------------------------------------------- #
def download_gdrive_folder(folder_id: str, dest: str):
    """Download every file in a public Google Drive folder (needs gdown)."""
    try:
        import gdown
    except ImportError:
        print("gdown not installed:  pip install gdown", file=sys.stderr)
        sys.exit(1)
    os.makedirs(dest, exist_ok=True)
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    print(f"[gdrive] downloading folder {folder_id} -> {dest}")
    gdown.download_folder(url=url, output=dest, quiet=False,
                          use_cookies=False, remaining_ok=True)


def main():
    ap = argparse.ArgumentParser(description="HistData tick loader")
    ap.add_argument("folder", nargs="?", help="directory containing monthly zips")
    ap.add_argument("--gdrive", help="Google Drive folder ID to download first")
    ap.add_argument("--dest", default="data/xauusd_zips")
    ap.add_argument("--out", default="data/XAUUSD_ticks.csv")
    a = ap.parse_args()

    if a.gdrive:
        download_gdrive_folder(a.gdrive, a.dest)
        folder = a.dest
    else:
        folder = a.folder or a.dest

    df = load_dir(folder)
    to_mt5_csv(df, a.out)
    print("\nNext:")
    print(f"  python src/report.py {a.out}        # TFAM")
    print(f"  python src/run_scalper.py {a.out}   # QAS")


if __name__ == "__main__":
    main()
