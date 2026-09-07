"""
ZCB -- Zone Compression Breakout
================================
The user's specified logic, implemented exactly as described, then
backtested honestly on real ticks.

THE SPEC (user's words, translated)
-----------------------------------
  "price dhoro 500.45, 500.46, 500.47, 500.45, 500.46, 500.50, 500.55,
   500.46, 500.45 -- aivabe move kore, mane akta zone-e 4 bar er beshi
   jai fire jai, tarpor price jei dike move korbe sei dike trade place
   hobe. 800x leverage e 0.01 lot. Close er khetre same system: 1 ta
   zone-e price bar bar obosthan kore reverse korar chesta korle tokhon
   close. Ai process 1 minute er moddhe hobe -- trade place er jonno
   1m analysis, close er jonno 1m analysis."

IMPLEMENTED RULES
-----------------
  ZONE      Price is bucketed into fixed-width zones (zone_w dollars).
            floor(price / zone_w) is the zone id.
  TOUCH     A "touch" is counted when price ENTERS a zone it was not
            already in. Sitting still inside a zone does not add touches.
  CHARGE    Within a rolling 1-minute window, if one zone accumulates
            more than `min_touch` touches, that zone is armed.
  ENTRY     When price leaves an armed zone by `break_zones` zones,
            enter in that direction. Buy at ask, sell at bid.
  EXIT      Same logic applied in reverse. While in a trade, a rolling
            1-minute window watches for a NEW zone accumulating more
            than `exit_touch` touches. If that congestion zone forms
            and it sits against the trade (price has stalled and is
            trying to turn), close the position.
  BACKSTOP  A hard stop and a max hold time, because the exit rule alone
            can leave a position open indefinitely while price runs away.
  SIZE      0.01 lot = 1.0 oz, 800x leverage.

This module is deliberately parameterised so the backtest can sweep
zone width, touch counts and the exit settings rather than assuming one
particular tuning is the right one.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ZoneConfig:
    zone_w: float = 0.10          # $ per zone
    min_touch: int = 5            # "4 bar er beshi" -> more than 4
    entry_window: float = 60.0    # seconds (1-minute analysis)
    break_zones: int = 2          # zones away from the armed zone = break

    exit_touch: int = 5           # congestion touches that trigger a close
    exit_window: float = 60.0     # seconds (1-minute analysis)

    hard_stop: float = 1.50       # $/oz backstop
    max_hold: float = 900.0       # seconds
    take_profit: float = 0.0      # 0 = disabled, rely on the zone exit

    max_spread: float = 0.60      # do not enter through a wide spread
    trade_hours: tuple = (6, 20)  # UTC window; avoids the rollover hours

    lots: float = 0.01
    contract_size: float = 100.0
    leverage: float = 800.0
    commission_per_lot: float = 7.0
    slippage: float = 0.01
    initial_balance: float = 1000.0

    @property
    def ounces(self) -> float:
        return self.lots * self.contract_size

    @property
    def commission(self) -> float:
        return self.commission_per_lot * self.lots


@dataclass
class ZTrade:
    entry_time: str
    exit_time: str
    side: int
    entry_price: float
    exit_price: float
    exit_reason: str
    zone_touches: int
    entry_spread: float
    gross: float
    cost: float
    net: float
    balance: float
    duration_s: float


class _ZoneWindow:
    """Rolling time window counting how often price entered each zone."""

    __slots__ = ("window", "buf", "counts", "cur")

    def __init__(self, window: float):
        self.window = window
        self.buf: deque = deque()      # (timestamp, zone)
        self.counts: dict[int, int] = {}
        self.cur = None

    def clear(self):
        self.buf.clear()
        self.counts.clear()
        self.cur = None

    def update(self, ts: float, zone: int) -> int:
        """Feed a point; return the touch count of `zone` in the window."""
        if zone != self.cur:
            self.buf.append((ts, zone))
            self.counts[zone] = self.counts.get(zone, 0) + 1
            self.cur = zone
        cutoff = ts - self.window
        while self.buf and self.buf[0][0] < cutoff:
            _, z = self.buf.popleft()
            c = self.counts.get(z, 0) - 1
            if c <= 0:
                self.counts.pop(z, None)
            else:
                self.counts[z] = c
        return self.counts.get(zone, 0)

    def hottest(self):
        if not self.counts:
            return None, 0
        z = max(self.counts, key=self.counts.get)
        return z, self.counts[z]


class ZoneStrategy:
    def __init__(self, cfg: ZoneConfig | None = None):
        self.cfg = cfg or ZoneConfig()
        self.balance = self.cfg.initial_balance
        self.trades: list[ZTrade] = []
        self.entry_win = _ZoneWindow(self.cfg.entry_window)
        self.exit_win = _ZoneWindow(self.cfg.exit_window)

        self.armed_zone: int | None = None
        self.armed_touches = 0
        self.pos = 0
        self.entry_px = 0.0
        self.entry_ts = 0.0
        self.entry_dt = None
        self.entry_spread = 0.0
        self.peak = 0.0
        self.n_signals = 0
        self.skipped: dict[str, int] = {}

    def _skip(self, r):
        self.skipped[r] = self.skipped.get(r, 0) + 1

    def _close(self, ts: float, dt, px: float, reason: str):
        cfg = self.cfg
        oz = cfg.ounces
        gross = (px - self.entry_px) * self.pos * oz
        cost = cfg.slippage * oz * 2 + cfg.commission
        net = gross - cost
        self.balance += net
        self.trades.append(ZTrade(
            entry_time=self.entry_dt.isoformat(), exit_time=dt.isoformat(),
            side=self.pos, entry_price=round(self.entry_px, 3),
            exit_price=round(px, 3), exit_reason=reason,
            zone_touches=self.armed_touches,
            entry_spread=round(self.entry_spread, 4),
            gross=round(gross, 4), cost=round(cost, 4), net=round(net, 4),
            balance=round(self.balance, 2),
            duration_s=round(ts - self.entry_ts, 1),
        ))
        self.pos = 0
        self.armed_zone = None
        self.exit_win.clear()

    def on_tick(self, dt: datetime, bid: float, ask: float):
        cfg = self.cfg
        ts = dt.timestamp()
        mid = 0.5 * (bid + ask)
        spread = ask - bid
        zone = math.floor(mid / cfg.zone_w)

        # ---------------- manage an open position ---------------------- #
        if self.pos != 0:
            px = bid if self.pos > 0 else ask
            move = (px - self.entry_px) * self.pos

            if move <= -cfg.hard_stop:
                self._close(ts, dt, px, "stop")
                return
            if cfg.take_profit and move >= cfg.take_profit:
                self._close(ts, dt, px, "tp")
                return
            if ts - self.entry_ts >= cfg.max_hold:
                self._close(ts, dt, px, "time")
                return

            # the user's exit: a new zone that price keeps returning to
            touches = self.exit_win.update(ts, zone)
            if touches >= cfg.exit_touch:
                self._close(ts, dt, px, "zone_reverse")
            return

        # ---------------- look for an entry ---------------------------- #
        h = dt.hour
        if not (cfg.trade_hours[0] <= h < cfg.trade_hours[1]):
            return

        touches = self.entry_win.update(ts, zone)
        if touches >= cfg.min_touch:
            self.armed_zone = zone
            self.armed_touches = touches

        if self.armed_zone is None:
            return

        dz = zone - self.armed_zone
        if abs(dz) < cfg.break_zones:
            return

        # zone broke -- take the trade
        self.n_signals += 1
        if spread > cfg.max_spread:
            self._skip("spread")
            self.armed_zone = None
            return

        self.pos = 1 if dz > 0 else -1
        self.entry_px = ask if self.pos > 0 else bid
        self.entry_ts = ts
        self.entry_dt = dt
        self.entry_spread = spread
        self.exit_win.clear()
        self.armed_zone = None

    def finalize(self, dt, bid, ask):
        if self.pos != 0:
            self._close(dt.timestamp(), dt, bid if self.pos > 0 else ask, "eod")
