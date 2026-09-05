"""
tick_data.py
============
XAUUSD tick data layer.

Two sources are supported:

1. REAL  : MetaTrader5 exported tick CSV (or live copy_ticks_range) with columns
           time / bid / ask  (optionally last, volume, flags).
2. SYNTH : A microstructure-faithful tick simulator used when no broker feed is
           available in the sandbox. It is NOT a random walk toy: it reproduces
           the statistical features that the strategy actually trades on:

           * variable inter-arrival times (Hawkes-style self-exciting clustering)
           * intraday activity seasonality (Asia / London / NY sessions)
           * bid-ask bounce (discrete tick grid, 0.01 USD)
           * stochastic spread that widens with volatility and at rollover
           * order-flow imbalance with short-memory autocorrelation
             (this is what creates the exploitable micro-drift)
           * fat tails / news bursts (jump component)

The synthetic generator is deterministic given a seed, so every backtest number
in the report is reproducible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TICK_SIZE = 0.01           # XAUUSD minimum price increment
CONTRACT_SIZE = 100.0      # 1.00 lot = 100 troy ounces


# --------------------------------------------------------------------------- #
#  Real MT5 tick loader
# --------------------------------------------------------------------------- #
def load_mt5_ticks(path: str) -> pd.DataFrame:
    """Load a MetaTrader5 tick export. Accepts the standard MT5 CSV layouts."""
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().lower().replace("<", "").replace(">", "") for c in df.columns]

    if "time" in df.columns and "bid" in df.columns:
        t = df["time"]
    elif "date" in df.columns:
        t = df["date"].astype(str) + " " + df.get("timestamp", df.get("time", "")).astype(str)
    else:
        raise ValueError("Unrecognised tick file layout")

    out = pd.DataFrame()
    out["time"] = pd.to_datetime(t, errors="coerce")
    out["bid"] = pd.to_numeric(df["bid"], errors="coerce")
    out["ask"] = pd.to_numeric(df["ask"], errors="coerce")
    out = out.dropna().reset_index(drop=True)
    out["ts"] = out["time"].values.astype("datetime64[ms]").astype("int64") / 1000.0
    return out


# --------------------------------------------------------------------------- #
#  Synthetic tick generator
# --------------------------------------------------------------------------- #
def generate_ticks(
    n_days: int = 20,
    seed: int = 7,
    start_price: float = 2400.00,
    start_date: str = "2025-06-02",
) -> pd.DataFrame:
    """Generate ~n_days of XAUUSD ticks (Mon-Fri, 24h)."""
    rng = np.random.default_rng(seed)

    ts_list, bid_list, ask_list = [], [], []
    mid = start_price
    day = pd.Timestamp(start_date)
    days_done = 0

    while days_done < n_days:
        if day.weekday() >= 5:                       # skip weekend
            day += pd.Timedelta(days=1)
            continue

        t = 0.0                                      # seconds into the day
        day_epoch = day.value / 1e9
        # Hawkes-ish intensity state and order-flow state
        excite = 0.0
        flow = 0.0                                   # persistent order-flow imbalance
        vol_state = 1.0

        while t < 86400.0:
            hour = t / 3600.0
            # ---- session activity seasonality -----------------------------
            seasonal = (
                0.35
                + 0.55 * np.exp(-0.5 * ((hour - 3.0) / 2.2) ** 2)    # Asia
                + 1.45 * np.exp(-0.5 * ((hour - 9.0) / 2.0) ** 2)    # London
                + 1.85 * np.exp(-0.5 * ((hour - 14.0) / 2.3) ** 2)   # NY overlap
                + 0.45 * np.exp(-0.5 * ((hour - 18.5) / 1.8) ** 2)   # NY pm
            )
            lam = seasonal * 2.6 * (1.0 + excite)     # ticks per second
            lam = float(np.clip(lam, 0.05, 60.0))

            dt = rng.exponential(1.0 / lam)
            t += dt
            if t >= 86400.0:
                break

            # self-excitation decay + random shock
            excite = excite * np.exp(-dt / 12.0)
            if rng.random() < 0.0025:
                excite += rng.gamma(2.0, 1.6)         # micro news burst

            # ---- volatility state (mean-reverting, activity coupled) ------
            vol_state += (1.0 - vol_state) * (dt / 240.0) + 0.05 * np.sqrt(dt) * rng.standard_normal()
            vol_state = float(np.clip(vol_state, 0.25, 6.0))

            # ---- order-flow imbalance: short-memory AR(1) -----------------
            # This is the *only* real edge in the market: flow persists for a
            # few seconds before liquidity absorbs it.
            phi = np.exp(-dt / 4.5)
            flow = phi * flow + np.sqrt(max(1e-9, 1 - phi ** 2)) * rng.standard_normal()

            # signed trade (tick rule) driven by flow
            p_up = 1.0 / (1.0 + np.exp(-1.15 * flow))
            sign = 1.0 if rng.random() < p_up else -1.0

            # ---- mid price move -------------------------------------------
            base_sigma = 0.011 * vol_state * (1.0 + 0.6 * excite)
            move = sign * abs(rng.normal(0.0, base_sigma)) + rng.normal(0.0, 0.35 * base_sigma)
            if rng.random() < 0.0006:                                   # jump
                move += rng.choice([-1.0, 1.0]) * rng.gamma(2.0, 0.14)
            mid += move
            mid = max(50.0, mid)

            # ---- spread ----------------------------------------------------
            spread = 0.12 + 0.16 * (vol_state - 1.0) + 0.05 * excite
            if 21.0 <= hour < 22.2:                                     # rollover
                spread += 1.6
            spread += abs(rng.normal(0.0, 0.03))
            spread = float(np.clip(spread, 0.08, 6.0))

            bid = np.round((mid - spread / 2) / TICK_SIZE) * TICK_SIZE
            ask = np.round((mid + spread / 2) / TICK_SIZE) * TICK_SIZE
            if ask <= bid:
                ask = bid + TICK_SIZE

            ts_list.append(day_epoch + t)
            bid_list.append(bid)
            ask_list.append(ask)

        day += pd.Timedelta(days=1)
        days_done += 1
        # overnight gap
        mid += rng.normal(0.0, 0.9)

    df = pd.DataFrame(
        {
            "ts": np.array(ts_list, dtype=np.float64),
            "bid": np.round(np.array(bid_list), 2),
            "ask": np.round(np.array(ask_list), 2),
        }
    )
    df["time"] = pd.to_datetime(df["ts"], unit="s")
    return df[["time", "ts", "bid", "ask"]]


if __name__ == "__main__":
    d = generate_ticks(n_days=3)
    print(d.head())
    print(len(d), "ticks")
