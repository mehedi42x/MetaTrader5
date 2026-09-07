"""
make_grid.py
============
Convert a huge tick CSV into a compact uniform time grid stored as .npz.

Rationale: 12.8M ticks needs ~1.7 GB as a DataFrame, and re-parsing the
589 MB CSV on every research run OOMs a 4 GB box. The grid is built once,
streaming, and lands at a few MB of float32.

    python src/make_grid.py /tmp/REAL_XAUUSD.csv /tmp/grid.npz [step_seconds]

Two things make this memory-safe:
  * timestamps are parsed arithmetically from the fixed-width
    "YYYY.MM.DD" + "HH:MM:SS.mmm" layout instead of pd.to_datetime, which
    is both far faster and avoids large intermediate object arrays;
  * grid slots are flushed to a raw binary spill file as they are produced,
    so nothing accumulates in RAM.

The grid stores last bid, last ask and quote staleness per slot. Staleness
lets downstream code discard "moves" measured across a closed market.
"""

from __future__ import annotations

import gc
import os
import sys
import tempfile

import numpy as np
import pandas as pd

_DAYS = np.array([0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334])


def _epoch_seconds(date_col: np.ndarray, time_col: np.ndarray) -> np.ndarray:
    """Parse 'YYYY.MM.DD' and 'HH:MM:SS.mmm' to epoch seconds, vectorised."""
    d = date_col.astype("U10")
    y = (d.view("U1").reshape(-1, 10)[:, 0:4]).view("U4").ravel().astype(np.int32)
    mo = (d.view("U1").reshape(-1, 10)[:, 5:7]).view("U2").ravel().astype(np.int32)
    da = (d.view("U1").reshape(-1, 10)[:, 8:10]).view("U2").ravel().astype(np.int32)

    t = time_col.astype("U12")
    tv = t.view("U1").reshape(-1, 12)
    hh = tv[:, 0:2].view("U2").ravel().astype(np.int32)
    mi = tv[:, 3:5].view("U2").ravel().astype(np.int32)
    ss = tv[:, 6:8].view("U2").ravel().astype(np.int32)
    ms = tv[:, 9:12].view("U3").ravel().astype(np.int32)

    yr = y - 1970
    leaps = (y - 1969) // 4 - (y - 1901) // 100 + (y - 1601) // 400
    days = yr * 365 + leaps + _DAYS[mo - 1] + (da - 1)
    isleap = ((y % 4 == 0) & (y % 100 != 0)) | (y % 400 == 0)
    days += (isleap & (mo > 2)).astype(np.int32)
    return days * 86400.0 + hh * 3600.0 + mi * 60.0 + ss + ms / 1000.0


def build(src: str, out: str, step: float = 1.0, chunk: int = 400_000):
    print(f"[grid] streaming {src} at {step}s resolution", flush=True)

    spill = tempfile.NamedTemporaryFile(prefix="grid_", suffix=".bin", delete=False)
    spill_path = spill.name
    carry = None
    next_slot = None
    total = 0

    # Only the four columns we need; bid/ask parsed as float directly so no
    # giant object arrays are ever materialised.
    reader = pd.read_csv(src, sep="\t", header=0, chunksize=chunk,
                         usecols=[0, 1, 2, 3],
                         names=["date", "time", "bid", "ask"], skiprows=1,
                         dtype={"date": str, "time": str,
                                "bid": np.float64, "ask": np.float64},
                         na_filter=False, engine="c")
    for ci, ch in enumerate(reader):
        ts = _epoch_seconds(ch["date"].to_numpy(), ch["time"].to_numpy())
        bid = ch["bid"].to_numpy(np.float64)
        ask = ch["ask"].to_numpy(np.float64)
        del ch
        gc.collect()

        ok = np.isfinite(ts) & np.isfinite(bid) & np.isfinite(ask) & (ask > bid)
        ts, bid, ask = ts[ok], bid[ok], ask[ok]
        if ts.size == 0:
            continue

        if carry is not None:
            ts = np.concatenate([[carry[0]], ts])
            bid = np.concatenate([[carry[1]], bid])
            ask = np.concatenate([[carry[2]], ask])
        if next_slot is None:
            next_slot = np.ceil(ts[0] / step) * step

        # Skip over market closures / missing months. Without this, a gap
        # (e.g. 856 days between non-contiguous archives) would allocate a
        # slot for every second in between - tens of millions of rows and
        # an instant OOM. Slots are only emitted where quotes exist.
        MAX_STALE = 3600.0
        if ts[0] - next_slot > MAX_STALE:
            next_slot = np.ceil(ts[0] / step) * step

        last_slot = np.floor(ts[-1] / step) * step
        if last_slot >= next_slot:
            slots = np.arange(next_slot, last_slot + step / 2, step)
            idx = np.searchsorted(ts, slots, side="right") - 1
            keep = idx >= 0
            slots, idx = slots[keep], idx[keep]
            if slots.size:
                fresh = (slots - ts[idx]) <= MAX_STALE
                slots, idx = slots[fresh], idx[fresh]
            if slots.size:
                block = np.empty((slots.size, 4), dtype=np.float64)
                block[:, 0] = slots
                block[:, 1] = bid[idx]
                block[:, 2] = ask[idx]
                block[:, 3] = slots - ts[idx]
                block.tofile(spill)
                next_slot = slots[-1] + step
                total += slots.size

        carry = (ts[-1], bid[-1], ask[-1])
        if (ci + 1) % 5 == 0:
            print(f"[grid] chunk {ci+1}: {total:,} grid points", flush=True)
        del ts, bid, ask
        gc.collect()

    spill.close()
    # memmap the spill so the final assembly never doubles peak memory
    arr = np.memmap(spill_path, dtype=np.float64, mode="r").reshape(-1, 4)
    t = np.array(arr[:, 0], dtype=np.float64)
    bid = np.array(arr[:, 1], dtype=np.float32)
    ask = np.array(arr[:, 2], dtype=np.float32)
    gap = np.array(arr[:, 3], dtype=np.float32)
    t0, t1 = float(arr[0, 0]), float(arr[-1, 0])
    n = len(arr)
    del arr
    os.unlink(spill_path)

    np.savez(out, t=t, bid=bid, ask=ask, gap=gap, step=step)
    print(f"[grid] wrote {out}  {n:,} points "
          f"({os.path.getsize(out)/1e6:.1f} MB)")
    print(f"[grid] span {pd.to_datetime(t0,unit='s')} -> "
          f"{pd.to_datetime(t1,unit='s')}")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2],
          float(sys.argv[3]) if len(sys.argv) > 3 else 1.0)
