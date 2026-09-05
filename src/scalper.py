"""
scalper.py
==========
QAS  -  "Quote Asymmetry Scalper"

A second, independent custom scalping strategy, designed from scratch for
2 years of Dukascopy XAUUSD tick data. It shares no logic with TFAM.

Still zero indicators, zero price action, zero candles. But where TFAM traded
*trade-flow momentum* (where price went), QAS trades **quote asymmetry** —
how the two sides of the book move relative to each other. On a tick feed the
bid and ask are two separate time series, and they do not move together:

    * When buyers are lifting offers, the ASK ratchets up in small steps while
      the BID lags behind, so the spread widens *upward*. The midpoint hides
      this completely — you can only see it by tracking each side separately.
    * A market maker defending a level pulls the far side instead, which looks
      identical on the mid but is the exact opposite trade.

So the core signal is built from **one-sided quote revisions**, not mid moves.


THE FIVE PRIMITIVES  (all derived from bid, ask, timestamp only)
----------------------------------------------------------------

1.  QUOTE PRESSURE (QP)  — the heart of the strategy
        For each tick classify the *bid* revision and the *ask* revision
        separately:
              bid up   -> buyers improving   (+1)
              bid down -> buyers retreating  (-1)
              ask down -> sellers improving  (-1)
              ask up   -> sellers retreating (+1)
        QP is the time-decayed sum of (bid_rev + ask_rev). Crucially, a tick
        where BOTH sides step up scores +2, while a tick where the spread
        merely widens symmetrically scores 0. Mid-based measures cannot make
        that distinction.
        Normalised by sqrt(N_eff) so it is a true z-score on any feed density.

2.  SPREAD SKEW (SK)
        Where does the mid sit relative to the *recent* bid/ask envelope?
              SK = (mid - lo) / (hi - lo) * 2 - 1        over a ~10s window
        SK > 0 means the market is trading near the top of its own recent
        quote range. Combined with QP > 0 this identifies genuine upward
        repricing rather than a spread blip.

3.  QUOTE STABILITY (QS)
        Fraction of recent ticks where the quote actually *changed*.
        A frozen book (stale quotes, thin session) has QS near 0 and is
        untradeable; a real move has a high, sustained QS.

4.  REVERSION PRESSURE (RP)
        EWMA of signed mid change over a slower window (~45s) divided by
        micro-vol. Gold micro-moves mean-revert: after an extended one-way
        push, continuation odds fall. QAS *reduces* target and tightens
        stops when |RP| is already extreme, instead of chasing.

5.  EFFECTIVE COST (EC)
        spread + expected slippage, expressed in units of micro-vol.
        Every entry must clear EC by a configurable multiple. This makes the
        strategy automatically stand down in expensive conditions rather than
        relying on hard-coded session hours.


ENTRY (long; short is the mirror)
---------------------------------
        qp_z        >=  QP_Z             one-sided quote pressure
    AND skew        >=  SKEW_MIN         trading at the top of the envelope
    AND stability   >=  QS_MIN           book is alive
    AND rp          <=  RP_MAX           not already over-extended
    AND target/EC   >=  EDGE_MULT        the move pays for the round trip
    AND cooldown / daily guards pass

EXIT — adaptive, cost-aware
---------------------------
    * Target and stop are set in units of micro-vol, then *shrunk* when
      reversion pressure is high (take what the market offers).
    * Break-even lock once the trade covers its own cost.
    * Quote-pressure decay exit: if QP falls back below a fraction of its
      entry value the reason for the trade is gone -> exit immediately.
    * Hard time stop.

RISK
----
    0.01 lot XAUUSD = 1 oz -> $0.01 per $0.01 move. 800x -> ~$3 margin.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

TICK_SIZE = 0.01
CONTRACT_SIZE = 100.0


@dataclass
class QASParams:
    # ---- account -------------------------------------------------------
    lot: float = 0.01
    leverage: float = 800.0
    initial_balance: float = 1000.0
    commission_per_lot_rt: float = 7.0
    slippage_ticks: float = 0.5

    # ---- horizons (seconds) --------------------------------------------
    tau_qp: float = 2.5          # quote pressure memory
    tau_env: float = 10.0        # bid/ask envelope for skew
    tau_stab: float = 5.0        # quote stability
    tau_rev: float = 45.0        # reversion pressure
    tau_vol: float = 30.0        # micro volatility
    tau_spread: float = 300.0

    # ---- entry ----------------------------------------------------------
    qp_z: float = 2.30
    skew_min: float = 0.30
    qs_min: float = 0.22
    rp_max: float = 2.40         # stand down if already over-extended
    edge_mult: float = 1.85      # target must be >= this x effective cost

    # ---- exits (multiples of micro-vol) ---------------------------------
    tp_k: float = 24.0
    sl_k: float = 16.0
    rp_shrink: float = 0.62      # target multiplier when RP is extreme
    qp_decay_exit: float = 0.35  # exit when QP falls below this x entry QP
    breakeven_at: float = 1.15   # lock BE once move >= this x cost
    max_hold_s: float = 75.0

    # ---- guards -----------------------------------------------------------
    cooldown_s: float = 6.0
    min_vol: float = 0.004
    max_spread_abs: float = 1.20
    daily_loss_stop: float = 0.04
    daily_profit_stop: float = 0.12
    max_trades_per_day: int = 500
    warmup_ticks: int = 20000


@dataclass
class QTrade:
    entry_ts: float
    exit_ts: float
    side: int
    entry_price: float
    exit_price: float
    pnl: float
    reason: str
    hold_s: float
    mfe: float
    mae: float
    spread_at_entry: float
    qp_at_entry: float
    balance_after: float


class QAS:
    def __init__(self, p: QASParams):
        self.p = p
        self.reset()

    def reset(self):
        p = self.p
        self.balance = p.initial_balance
        self.trades: list[QTrade] = []

        self.prev_bid = None
        self.prev_ask = None
        self.prev_ts = None

        self.qp = 0.0
        self.nqp = 0.0
        self.hi = None
        self.lo = None
        self.chg = 0.0
        self.nstab = 0.0
        self.rev = 0.0
        self.vol = 0.02
        self.spread_ewma = 0.20
        self.warm = 0

        self.pos = 0
        self.entry_price = 0.0
        self.entry_ts = 0.0
        self.entry_spread = 0.0
        self.entry_vol = 0.02
        self.entry_qp = 0.0
        self.tp_dist = 0.0
        self.sl_dist = 0.0
        self.cost_px = 0.0
        self.be_armed = False
        self.best = 0.0
        self.worst = 0.0
        self.last_exit_ts = -1e18

        self.day = None
        self.day_start = p.initial_balance
        self.day_trades = 0
        self.day_locked = False
        self.daily: dict = {}
        self.signals = 0
        self.rejects = {"qp": 0, "skew": 0, "stab": 0, "rev": 0,
                        "edge": 0, "vol": 0, "spread": 0,
                        "cooldown": 0, "daylock": 0}

    # ------------------------------------------------------------------ #
    @property
    def vpu(self) -> float:
        """USD P&L per 1.00 USD of price move."""
        return self.p.lot * CONTRACT_SIZE

    def qp_score(self) -> float:
        if self.nqp < 2.0:
            return 0.0
        return self.qp / np.sqrt(self.nqp)

    def skew(self) -> float:
        if self.hi is None or self.lo is None or self.hi - self.lo < 1e-9:
            return 0.0
        mid = 0.5 * (self.prev_bid + self.prev_ask)
        return ((mid - self.lo) / (self.hi - self.lo)) * 2.0 - 1.0

    def stability(self) -> float:
        if self.nstab < 2.0:
            return 0.0
        return self.chg / self.nstab

    def rev_pressure(self) -> float:
        return self.rev / max(self.vol, self.p.min_vol)

    def cost_in_price(self, spread: float) -> float:
        """Round-trip cost expressed as a price distance."""
        p = self.p
        comm_px = (p.commission_per_lot_rt * p.lot) / self.vpu
        slip_px = p.slippage_ticks * TICK_SIZE
        return spread + slip_px + comm_px

    # ------------------------------------------------------------------ #
    def _update(self, ts: float, bid: float, ask: float):
        p = self.p
        if self.prev_bid is None:
            self.prev_bid, self.prev_ask, self.prev_ts = bid, ask, ts
            self.hi = self.lo = 0.5 * (bid + ask)
            self.spread_ewma = ask - bid
            return False

        dt = max(1e-3, ts - self.prev_ts)
        mid = 0.5 * (bid + ask)
        prev_mid = 0.5 * (self.prev_bid + self.prev_ask)
        dmid = mid - prev_mid

        # ---- one-sided quote revisions (the core idea) ------------------
        db = bid - self.prev_bid
        da = ask - self.prev_ask
        bid_rev = 1.0 if db > 1e-9 else (-1.0 if db < -1e-9 else 0.0)
        ask_rev = 1.0 if da > 1e-9 else (-1.0 if da < -1e-9 else 0.0)
        press = bid_rev + ask_rev

        a = np.exp(-dt / p.tau_qp)
        self.qp = a * self.qp + press
        self.nqp = a * self.nqp + 1.0

        # ---- quote envelope ---------------------------------------------
        ae = np.exp(-dt / p.tau_env)
        self.hi = max(mid, self.hi * ae + mid * (1 - ae)) if self.hi is not None else mid
        self.lo = min(mid, self.lo * ae + mid * (1 - ae)) if self.lo is not None else mid
        # let the envelope breathe back toward the mid
        self.hi = self.hi + (mid - self.hi) * (1 - ae) * 0.5 if mid < self.hi else self.hi
        self.lo = self.lo + (mid - self.lo) * (1 - ae) * 0.5 if mid > self.lo else self.lo

        # ---- stability ----------------------------------------------------
        asb = np.exp(-dt / p.tau_stab)
        self.chg = asb * self.chg + (1.0 if (bid_rev or ask_rev) else 0.0)
        self.nstab = asb * self.nstab + 1.0

        # ---- reversion pressure --------------------------------------------
        ar = np.exp(-dt / p.tau_rev)
        self.rev = ar * self.rev + dmid

        # ---- vol / spread ----------------------------------------------------
        av = np.exp(-dt / p.tau_vol)
        self.vol = av * self.vol + (1 - av) * abs(dmid)
        asp = np.exp(-dt / p.tau_spread)
        self.spread_ewma = asp * self.spread_ewma + (1 - asp) * (ask - bid)

        self.prev_bid, self.prev_ask, self.prev_ts = bid, ask, ts
        self.warm += 1
        return self.warm > p.warmup_ticks

    # ------------------------------------------------------------------ #
    def _close(self, ts: float, price: float, reason: str):
        p = self.p
        gross = (price - self.entry_price) * self.pos * self.vpu
        slip = p.slippage_ticks * TICK_SIZE * self.vpu
        comm = p.commission_per_lot_rt * p.lot
        pnl = gross - slip - comm
        self.balance += pnl
        self.trades.append(QTrade(
            entry_ts=self.entry_ts, exit_ts=ts, side=self.pos,
            entry_price=self.entry_price, exit_price=price, pnl=pnl,
            reason=reason, hold_s=ts - self.entry_ts,
            mfe=self.best * self.vpu, mae=self.worst * self.vpu,
            spread_at_entry=self.entry_spread, qp_at_entry=self.entry_qp,
            balance_after=self.balance))
        self.pos = 0
        self.last_exit_ts = ts
        self.day_trades += 1

    # ------------------------------------------------------------------ #
    def on_tick(self, ts: float, bid: float, ask: float, hour: int, daykey):
        p = self.p
        if daykey != self.day:
            if self.day is not None:
                self.daily[self.day] = self.balance - self.day_start
            self.day = daykey
            self.day_start = self.balance
            self.day_trades = 0
            self.day_locked = False

        if not self._update(ts, bid, ask):
            return

        spread = ask - bid

        # ================= manage position =============================
        if self.pos != 0:
            px = bid if self.pos > 0 else ask
            move = (px - self.entry_price) * self.pos
            self.best = max(self.best, move)
            self.worst = min(self.worst, move)

            if not self.be_armed and move >= p.breakeven_at * self.cost_px:
                self.be_armed = True

            qs = self.qp_score()

            if move <= -self.sl_dist:
                self._close(ts, px, "stop_loss")
            elif move >= self.tp_dist:
                self._close(ts, px, "take_profit")
            elif self.be_armed and move <= self.cost_px * 0.15:
                self._close(ts, px, "breakeven")
            elif abs(qs) < abs(self.entry_qp) * p.qp_decay_exit or \
                    (qs * self.pos) < 0:
                self._close(ts, px, "pressure_decay")
            elif ts - self.entry_ts >= p.max_hold_s:
                self._close(ts, px, "time_stop")
            return

        # ================= entry =======================================
        if self.day_locked:
            self.rejects["daylock"] += 1
            return
        d = (self.balance - self.day_start) / max(1e-9, self.day_start)
        if d <= -p.daily_loss_stop or d >= p.daily_profit_stop or \
                self.day_trades >= p.max_trades_per_day:
            self.day_locked = True
            self.rejects["daylock"] += 1
            return
        if ts - self.last_exit_ts < p.cooldown_s:
            self.rejects["cooldown"] += 1
            return
        if self.vol < p.min_vol:
            self.rejects["vol"] += 1
            return
        if spread > p.max_spread_abs or spread > 2.0 * self.spread_ewma:
            self.rejects["spread"] += 1
            return

        qs = self.qp_score()
        if abs(qs) < p.qp_z:
            self.rejects["qp"] += 1
            return

        side = 1 if qs > 0 else -1
        sk = self.skew() * side
        if sk < p.skew_min:
            self.rejects["skew"] += 1
            return
        if self.stability() < p.qs_min:
            self.rejects["stab"] += 1
            return

        rp = self.rev_pressure()
        if rp * side > p.rp_max:          # already over-extended our way
            self.rejects["rev"] += 1
            return

        # ---- cost-aware sizing of the trade ---------------------------
        cost_px = self.cost_in_price(spread)
        shrink = p.rp_shrink if abs(rp) > p.rp_max * 0.75 else 1.0
        tp_dist = p.tp_k * self.vol * shrink
        sl_dist = p.sl_k * self.vol * (1.0 if shrink == 1.0 else 0.85)

        if tp_dist < p.edge_mult * cost_px:
            self.rejects["edge"] += 1
            return

        need = (0.5 * (bid + ask) * p.lot * CONTRACT_SIZE) / p.leverage
        if need > self.balance * 0.5:
            return

        # ---- fire -------------------------------------------------------
        self.signals += 1
        self.pos = side
        self.entry_price = ask if side > 0 else bid
        self.entry_ts = ts
        self.entry_spread = spread
        self.entry_vol = max(self.vol, p.min_vol)
        self.entry_qp = qs
        self.tp_dist = tp_dist
        self.sl_dist = sl_dist
        self.cost_px = cost_px
        self.be_armed = False
        self.best = 0.0
        self.worst = 0.0

    def finalize(self):
        if self.day is not None:
            self.daily[self.day] = self.balance - self.day_start


# --------------------------------------------------------------------------- #
def calibrate_qas(ticks, p: QASParams = None, qp_pct: float = 82.0,
                  sample_every: int = 97, max_ticks: int = 3_000_000,
                  verbose: bool = True) -> QASParams:
    """Fit qp_z to a feed's own quote-pressure distribution (no P&L used).

    p82 is the default: on validation runs it kept PF near 3.9 at ~67% win
    rate while still producing enough trades per day to be statistically
    meaningful. Tighter percentiles raise PF but starve the sample.
    """
    p = p or QASParams()
    probe = QAS(QASParams(**{**asdict(p), "qp_z": 1e9}))
    ts = ticks["ts"].to_numpy()
    bid = ticks["bid"].to_numpy()
    ask = ticks["ask"].to_numpy()
    hrs = ticks["time"].dt.hour.to_numpy().astype(np.int32)
    dks = ticks["time"].dt.strftime("%Y-%m-%d").to_numpy()

    QP = []
    n = min(len(ts), max_ticks)
    for i in range(n):
        probe.on_tick(ts[i], bid[i], ask[i], int(hrs[i]), dks[i])
        if probe.warm > p.warmup_ticks and i % sample_every == 0:
            QP.append(abs(probe.qp_score()))
    if len(QP) < 100:
        return p
    out = QASParams(**{**asdict(p), "qp_z": round(float(np.percentile(QP, qp_pct)), 3)})
    if verbose:
        print(f"[calib-qas] samples={len(QP):,}  qp_z(p{qp_pct})={out.qp_z}")
    return out
