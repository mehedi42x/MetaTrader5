"""
ARB -- Asian Range Breakout
===========================

A custom XAUUSD strategy derived entirely from tick-data statistics.
No indicators. No candlestick or chart patterns. Every rule below traces
back to a measurement made on 12.8 million real gold ticks.

--------------------------------------------------------------------------
WHY THIS STRATEGY EXISTS
--------------------------------------------------------------------------
Research on the real tick history (src/research.py .. research4.py) killed
the obvious ideas and left exactly one survivor.

  * Sub-minute scalping is arithmetically impossible. Mean absolute tick
    move is $0.051 while the mean spread is $0.451 -- the cost is 8.9x the
    signal. Tick-direction autocorrelation is ~0 beyond lag 2.

  * Horizon is the only way to out-earn the spread. Mean |move| grows from
    $0.179 at 10s to $2.006 at 900s and $4.545 at 3600s, i.e. from 0.34x
    the round-trip cost to 8.7x it. Nothing under ~5 minutes can pay
    for itself, so the strategy must hold for hours, not seconds.

  * Raw directional signals do not survive cost. A 900s-lookback breakout
    earns +$0.252 gross against $0.524 of cost -- the sign is real but the
    size is half of what is needed. Bucketing by volatility and spread
    did not rescue it.

  * Spread is violently time-dependent, and predictable. Median spread is
    $0.330 during 07:00-12:00 UTC but $0.90 at 21:00 and $0.62 at 22:00.
    In hours 22, 23, 00 and 21, between 22% and 42% of all quotes sit in
    the widest decile. Those "moves" are market makers withdrawing quotes,
    not gold moving. Trading must be confined to the liquid window.

The survivor is a *structural* effect rather than a statistical one, which
is why it holds up out of sample:

  Gold's Asian session (00:00-06:00 UTC) is thin and range-bound -- it is
  mostly position-keeping, with little fresh information. London opening
  at ~07:00 brings the day's real order flow. When that flow is strong
  enough to push price out of the range the Asian session spent six hours
  building, it is revealing genuine directional interest, and that
  interest tends to persist for hours. Crucially, this breakout happens
  during the cheapest-spread window of the entire day, so the cost side
  of the trade is near its daily minimum at exactly the moment the signal
  fires.

The strategy is therefore: measure the Asian range, trade the first London
breakout of it, and size the exit to the range itself.

--------------------------------------------------------------------------
THE RULES
--------------------------------------------------------------------------
  RANGE     From 00:00 to 06:00 UTC, record the highest and lowest mid
            price. R = high - low.
  ENTRY     From 07:00 UTC, the first time mid closes outside [low, high],
            enter in the direction of the break. Buy at the ask, sell at
            the bid. One trade per day, maximum.
  CUTOFF    No new entry after 12:00 UTC -- the edge is concentrated in
            the London morning and the spread widens later.
  TARGET    0.75 x R in profit.
  STOP      1.00 x R against.
  TIME EXIT Flat at 16:00 UTC regardless.
  SIZE      0.01 lots (1 troy ounce), 800x leverage.

Note the target is *smaller* than the stop. That is deliberate and it is
what the data asked for: the win rate is high (67%) because a genuine
London breakout usually runs at least three quarters of the Asian range,
but the stop must sit outside the range to avoid being taken out by the
noise of the break itself. Every tighter-stop variant tested (sl 0.5R,
0.75R) was worse in both train and test.

--------------------------------------------------------------------------
PARAMETER SELECTION
--------------------------------------------------------------------------
tp_k and sl_k were chosen on 2024 data only (Jan/Feb/Mar) and then applied
unchanged to the held-out 2026-08 month. The 2026 result was never used to
pick a parameter. See results/ARB_REPORT.md for both periods side by side.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass
class ArbConfig:
    # session windows, UTC hours
    asia_start: int = 0
    asia_end: int = 6
    entry_start: int = 7
    entry_cutoff: int = 12      # no new entries at/after this hour
    exit_hour: int = 16         # forced flat

    # exit geometry, as multiples of the Asian range R
    tp_k: float = 0.75
    sl_k: float = 1.00

    # sanity guards
    min_range_abs: float = 1.0    # ignore days with a degenerate range ($)
    max_range_pct: float = 2.0    # ignore days already in a violent move (%)
    max_spread: float = 1.00      # never enter through a blown-out spread ($)
    min_asia_ticks: int = 500     # need a real Asian session to measure

    # account / instrument
    lots: float = 0.01
    contract_size: float = 100.0   # oz per 1.0 lot
    leverage: float = 800.0
    commission_per_lot: float = 7.0   # $ round turn per 1.0 lot
    slippage: float = 0.01            # $/oz per side
    initial_balance: float = 1000.0

    @property
    def ounces(self) -> float:
        return self.lots * self.contract_size          # 1.0 oz at 0.01 lots

    @property
    def commission(self) -> float:
        return self.commission_per_lot * self.lots     # $0.07 round turn


@dataclass
class Trade:
    date: str
    side: int                 # +1 long, -1 short
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    exit_reason: str
    asia_range: float
    asia_high: float
    asia_low: float
    entry_spread: float
    gross: float              # $ before costs
    commission: float
    slippage: float
    net: float                # $ after costs
    r_multiple: float
    balance: float
    margin_used: float
    duration_min: float


# --------------------------------------------------------------------------- #
# Per-day state machine
# --------------------------------------------------------------------------- #
class _DayState:
    """Tracks one UTC day: build the range, then look for the breakout."""

    __slots__ = ("date", "hi", "lo", "n_asia", "done", "pos",
                 "entry_px", "entry_t", "entry_spread", "side", "tp", "sl", "rng")

    def __init__(self, date):
        self.date = date
        self.hi = float("-inf")
        self.lo = float("inf")
        self.n_asia = 0
        self.done = False        # already traded today
        self.pos = False         # currently in a position
        self.entry_px = 0.0
        self.entry_t = None
        self.entry_spread = 0.0
        self.side = 0
        self.tp = 0.0
        self.sl = 0.0
        self.rng = 0.0


class ArbStrategy:
    """Tick-driven Asian Range Breakout. Feed it ticks in time order."""

    def __init__(self, cfg: ArbConfig | None = None):
        self.cfg = cfg or ArbConfig()
        self.balance = self.cfg.initial_balance
        self.trades: list[Trade] = []
        self._day: _DayState | None = None
        self.skipped: dict[str, int] = {}

    # -- helpers ---------------------------------------------------------- #
    def _skip(self, reason: str):
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def _close(self, day: _DayState, ts: datetime, px: float, reason: str):
        cfg = self.cfg
        oz = cfg.ounces
        gross = (px - day.entry_px) * day.side * oz
        slip = cfg.slippage * oz * 2          # entry + exit
        comm = cfg.commission
        net = gross - slip - comm
        self.balance += net
        margin = day.entry_px * oz / cfg.leverage
        self.trades.append(Trade(
            date=str(day.date), side=day.side,
            entry_time=day.entry_t.isoformat(), entry_price=round(day.entry_px, 3),
            exit_time=ts.isoformat(), exit_price=round(px, 3),
            exit_reason=reason, asia_range=round(day.rng, 3),
            asia_high=round(day.hi, 3), asia_low=round(day.lo, 3),
            entry_spread=round(day.entry_spread, 4),
            gross=round(gross, 4), commission=round(comm, 4),
            slippage=round(slip, 4), net=round(net, 4),
            r_multiple=round(net / (day.rng * oz), 4) if day.rng else 0.0,
            balance=round(self.balance, 2), margin_used=round(margin, 2),
            duration_min=round((ts - day.entry_t).total_seconds() / 60, 1),
        ))
        day.pos = False
        day.done = True

    # -- main entry point ------------------------------------------------- #
    def on_tick(self, ts: datetime, bid: float, ask: float):
        cfg = self.cfg
        d = ts.date()

        if self._day is None or self._day.date != d:
            # a new day: if yesterday somehow left a position open, drop it
            self._day = _DayState(d)
        day = self._day

        h = ts.hour
        mid = 0.5 * (bid + ask)
        spread = ask - bid

        # ---- 1. build the Asian range -----------------------------------
        if cfg.asia_start <= h < cfg.asia_end:
            if mid > day.hi:
                day.hi = mid
            if mid < day.lo:
                day.lo = mid
            day.n_asia += 1
            return

        # ---- 2. manage an open position ---------------------------------
        if day.pos:
            if h >= cfg.exit_hour:
                self._close(day, ts, bid if day.side > 0 else ask, "time")
                return
            # exit fills: longs leave at the bid, shorts at the ask
            px = bid if day.side > 0 else ask
            move = (px - day.entry_px) * day.side
            if move >= day.tp:
                self._close(day, ts, px, "tp")
            elif move <= -day.sl:
                self._close(day, ts, px, "sl")
            return

        # ---- 3. hunt for the breakout -----------------------------------
        if day.done:
            return
        if not (cfg.entry_start <= h < cfg.entry_cutoff):
            return
        if day.n_asia < cfg.min_asia_ticks:
            return

        rng = day.hi - day.lo
        if rng < cfg.min_range_abs:
            return
        if rng / mid * 100 > cfg.max_range_pct:
            return
        if spread > cfg.max_spread:
            self._skip("spread_too_wide")
            return

        if mid > day.hi:
            side, fill = 1, ask          # buy at the ask
        elif mid < day.lo:
            side, fill = -1, bid         # sell at the bid
        else:
            return

        day.pos = True
        day.side = side
        day.rng = rng
        day.entry_px = fill
        day.entry_t = ts
        day.entry_spread = spread
        day.tp = cfg.tp_k * rng
        day.sl = cfg.sl_k * rng

    def finalize(self, ts: datetime | None = None, px: float | None = None):
        """Close any position still open at the end of the data."""
        day = self._day
        if day and day.pos and ts is not None:
            self._close(day, ts, px, "eod")


# --------------------------------------------------------------------------- #
# Tick source
# --------------------------------------------------------------------------- #
def stream_ticks(path: str):
    """Yield (datetime UTC, bid, ask) from an MT5-style tab/comma tick file."""
    with open(path, "r", newline="") as fh:
        sample = fh.readline()
        fh.seek(0)
        delim = "\t" if "\t" in sample else ","
        rdr = csv.reader(fh, delimiter=delim)
        first = True
        for row in rdr:
            if not row or len(row) < 3:
                continue
            if first:
                first = False
                try:
                    float(row[-2])
                except ValueError:
                    continue          # header line
            try:
                if len(row) >= 4 and ":" in row[1]:
                    ts = datetime.strptime(f"{row[0]} {row[1]}",
                                           "%Y.%m.%d %H:%M:%S.%f")
                    bid, ask = float(row[2]), float(row[3])
                else:
                    ts = datetime.fromisoformat(row[0])
                    bid, ask = float(row[1]), float(row[2])
            except (ValueError, IndexError):
                continue
            if ask <= bid:
                continue
            yield ts.replace(tzinfo=timezone.utc), bid, ask
