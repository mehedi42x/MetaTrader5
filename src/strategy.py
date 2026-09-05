"""
strategy.py
===========
TFAM  -  "Tick-Flow Absorption Momentum"
A 100% custom, indicator-free, price-action-free XAUUSD micro strategy.

No moving averages, no RSI, no candles, no support/resistance, no chart
patterns.  The only inputs are raw tick primitives:

    bid, ask, timestamp

and everything derived from them at the microstructure level:

    1.  TICK RULE FLOW  (F)
        Every tick is classified by the direction of the mid change:
        +1 uptick, -1 downtick, 0 unchanged.  Flow is an exponentially
        weighted sum with a *time* decay (tau_f), not a bar count, so it is
        immune to tick-density changes between sessions.

    2.  FLOW EFFICIENCY  (E)
        E = |mid_now - mid_(t-tau)| / (sum of |mid changes| over tau)
        A value near 1 means the market moved in a straight line: liquidity
        is being consumed on one side.  Near 0 means bid-ask bounce noise.
        This is the single most important filter - it separates real
        absorption from chop, and it uses no price pattern at all.

    3.  TICK ARRIVAL INTENSITY  (I)
        EWMA of 1/inter-arrival-time.  Institutional sweeps arrive as
        bursts; the strategy only trades when the current intensity is a
        multiple of its own slow baseline (self-normalising, no fixed
        thresholds, no session hard-coding).

    4.  MICRO-VOLATILITY  (S)
        EWMA of |mid change| per tick -> used to size TP/SL in *units of the
        market's own current noise*, never in fixed pips.

    5.  SPREAD STATE  (P)
        Live spread vs. its own EWMA baseline.  Trading is blocked whenever
        the spread is expensive relative to the expected capture - this
        alone kills the rollover-hours account destroyer.

ENTRY (long; short is the mirror):
        flow_z      >= FLOW_Z          (directional pressure)
    AND efficiency  >= EFF_MIN         (pressure is *moving* price)
    AND intensity   >= INTENS_MULT     (pressure is *fast*)
    AND spread      <= SPREAD_MULT * spread_baseline
    AND spread      <= SPREAD_EDGE_FRAC * expected_capture
    AND not in cooldown, not in blocked hour, daily loss limit not hit

EXIT - three independent legs, all measured in *ticks of live micro-vol*:
    a) Hard stop      : SL_K  * S
    b) Micro take     : TP_K  * S           (base target)
    c) Flow-flip exit : if flow reverses beyond -FLIP_Z the trade is closed
                        immediately (the reason for the trade is gone)
    d) Trailing lock  : once +TRAIL_ARM * S is reached, a trailing stop of
                        TRAIL_K * S follows the best price
    e) Time stop      : MAX_HOLD_S seconds - micro edges decay, dead trades
                        are pure spread risk

RISK / ACCOUNT MODEL:
    0.01 lot XAUUSD = 1 troy ounce  ->  $0.01 P&L per $0.01 price move
    800x leverage   ->  margin = 2400 / 800 * 1 oz  ~= $3.00 per position
    Every fill pays the full spread (buy at ask, sell at bid) + commission.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np

TICK_SIZE = 0.01
CONTRACT_SIZE = 100.0     # ounces per 1.0 lot


@dataclass
class Params:
    # ---- position / account -------------------------------------------
    lot: float = 0.01
    leverage: float = 800.0
    initial_balance: float = 1000.0
    commission_per_lot_rt: float = 7.0      # USD per 1.0 lot round turn
    slippage_ticks: float = 0.5             # avg adverse slip on entry+exit

    # ---- signal horizons (seconds, NOT bars) ---------------------------
    tau_flow: float = 3.0                   # fast flow memory
    tau_eff: float = 6.0                    # efficiency window
    tau_intens_fast: float = 5.0
    tau_intens_slow: float = 900.0
    tau_vol: float = 30.0
    tau_spread: float = 300.0
    tau_flow_var: float = 1800.0            # for z-scoring flow

    # ---- entry thresholds ----------------------------------------------
    flow_z: float = 2.15
    eff_min: float = 1.90                   # random walk = 1.0; >1 = directional
    intens_mult: float = 1.55
    spread_mult: float = 1.25               # vs own baseline
    spread_edge_frac: float = 0.55          # spread must be < 55% of target

    # ---- exits (multiples of live micro-vol S, in price units) ---------
    tp_k: float = 26.0
    sl_k: float = 18.0
    trail_arm_k: float = 14.0
    trail_k: float = 8.0
    flip_z: float = 1.30
    max_hold_s: float = 90.0

    # ---- guards ---------------------------------------------------------
    cooldown_s: float = 8.0
    blocked_hours: tuple = (21, 22)         # rollover / illiquid
    allowed_hours: tuple = (7,8,9,10,11,12,13,14,15,16,17,18)  # London+NY only
    daily_loss_stop: float = 0.04           # 4% of day-start equity
    daily_profit_stop: float = 0.10         # bank the day at +10%
    max_trades_per_day: int = 400
    min_vol: float = 0.004                  # dead-market filter (price units)


@dataclass
class Trade:
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
    balance_after: float


class TFAM:
    """Event-driven tick strategy. Feed it ticks one by one."""

    def __init__(self, p: Params):
        self.p = p
        self.reset()

    # ------------------------------------------------------------------ #
    def reset(self):
        p = self.p
        self.balance = p.initial_balance
        self.equity = p.initial_balance
        self.trades: list[Trade] = []
        self.equity_curve: list[tuple[float, float]] = []

        self.prev_mid = None
        self.prev_ts = None
        self.flow = 0.0
        self.nflow = 0.0
        self.flow_var = 1.0
        self.disp = 0.0          # sum |dmid| ewma  (denominator of efficiency)
        self.net = 0.0           # signed dmid ewma (numerator of efficiency)
        self.neff = 0.0          # effective tick count in the same window
        self.i_fast = 0.0
        self.i_slow = 0.0
        self.vol = 0.02
        self.spread_ewma = 0.20
        self.warm = 0
        self._ec = 0

        self.pos = 0             # 0 flat, +1 long, -1 short
        self.entry_price = 0.0
        self.entry_ts = 0.0
        self.entry_spread = 0.0
        self.best = 0.0
        self.worst = 0.0
        self.trail_active = False
        self.trail_level = 0.0
        self.tp = 0.0
        self.sl = 0.0
        self.last_exit_ts = -1e18

        self.day = None
        self.day_start_equity = p.initial_balance
        self.day_trades = 0
        self.day_locked = False
        self.daily: dict = {}

        self.rejects = {
            "flow": 0, "eff": 0, "intens": 0, "spread": 0,
            "vol": 0, "cooldown": 0, "hour": 0, "daylock": 0,
        }
        self.signals = 0

    # ------------------------------------------------------------------ #
    @property
    def value_per_price_unit(self) -> float:
        """USD P&L for a 1.00 USD move in gold, for the configured lot."""
        return self.p.lot * CONTRACT_SIZE

    @property
    def margin_per_trade(self) -> float:
        return (self.entry_price * self.p.lot * CONTRACT_SIZE) / self.p.leverage

    # ------------------------------------------------------------------ #
    def _update_state(self, ts: float, bid: float, ask: float):
        p = self.p
        mid = 0.5 * (bid + ask)
        spread = ask - bid

        if self.prev_mid is None:
            self.prev_mid, self.prev_ts = mid, ts
            self.spread_ewma = spread
            return mid, spread, False

        dt = max(1e-3, ts - self.prev_ts)
        dmid = mid - self.prev_mid

        # tick-rule sign
        s = 1.0 if dmid > 1e-9 else (-1.0 if dmid < -1e-9 else 0.0)

        # --- time-decayed flow --------------------------------------------
        a = np.exp(-dt / p.tau_flow)
        self.flow = a * self.flow + s
        self.nflow = a * self.nflow + 1.0

        # slow variance of flow for self-normalising z-score
        av = np.exp(-dt / p.tau_flow_var)
        self.flow_var = av * self.flow_var + (1 - av) * self.flow * self.flow

        # --- efficiency components ----------------------------------------
        ae = np.exp(-dt / p.tau_eff)
        self.net = ae * self.net + dmid
        self.disp = ae * self.disp + abs(dmid)
        self.neff = ae * self.neff + 1.0

        # --- intensity ------------------------------------------------------
        inst = 1.0 / dt
        af = np.exp(-dt / p.tau_intens_fast)
        asl = np.exp(-dt / p.tau_intens_slow)
        self.i_fast = af * self.i_fast + (1 - af) * inst
        self.i_slow = asl * self.i_slow + (1 - asl) * inst

        # --- micro volatility (per-tick absolute move) ----------------------
        avv = np.exp(-dt / p.tau_vol)
        self.vol = avv * self.vol + (1 - avv) * abs(dmid)

        # --- spread baseline --------------------------------------------------
        asp = np.exp(-dt / p.tau_spread)
        self.spread_ewma = asp * self.spread_ewma + (1 - asp) * spread

        self.prev_mid, self.prev_ts = mid, ts
        self.warm += 1
        return mid, spread, self.warm > 5000

    # ------------------------------------------------------------------ #
    def flow_score(self) -> float:
        """Density-invariant order-flow imbalance z-score.

        flow is a time-decayed sum of +-1 tick signs over N_eff effective
        ticks. Under the null (independent signs) its std is sqrt(N_eff),
        so dividing by that gives a true z-score that means the same thing
        on a 500k-ticks/day real feed and on a thin feed alike.
        """
        if self.nflow < 2.0:
            return 0.0
        return self.flow / np.sqrt(self.nflow)

    # ------------------------------------------------------------------ #
    def efficiency(self) -> float:
        """Density-invariant directional efficiency.

        For a pure random walk of N steps, |net| ~ sqrt(N) * mean|dmid| while
        dispersion = N * mean|dmid|, so |net|/disp ~ 1/sqrt(N) - i.e. the raw
        ratio depends on tick density and is useless across feeds.

        Normalising by sqrt(N_eff) removes that dependence:
            E* = |net| * sqrt(N_eff) / disp
        E* ~= 1.0  -> random walk / bid-ask bounce
        E* >> 1.0  -> genuine one-sided liquidity consumption
        """
        if self.disp <= 1e-12 or self.neff < 2.0:
            return 0.0
        return abs(self.net) * np.sqrt(self.neff) / self.disp

    # ------------------------------------------------------------------ #
    def _close(self, ts: float, price: float, reason: str):
        p = self.p
        gross = (price - self.entry_price) * self.pos * self.value_per_price_unit
        slip = p.slippage_ticks * TICK_SIZE * self.value_per_price_unit
        comm = p.commission_per_lot_rt * p.lot
        pnl = gross - slip - comm
        self.balance += pnl
        self.trades.append(
            Trade(
                entry_ts=self.entry_ts, exit_ts=ts, side=self.pos,
                entry_price=self.entry_price, exit_price=price, pnl=pnl,
                reason=reason, hold_s=ts - self.entry_ts,
                mfe=self.best * self.value_per_price_unit,
                mae=self.worst * self.value_per_price_unit,
                spread_at_entry=self.entry_spread,
                balance_after=self.balance,
            )
        )
        self.pos = 0
        self.last_exit_ts = ts
        self.day_trades += 1

    # ------------------------------------------------------------------ #
    def on_tick(self, ts: float, bid: float, ask: float, hour: int, daykey):
        p = self.p

        # ---- new day bookkeeping -----------------------------------------
        if daykey != self.day:
            if self.day is not None:
                self.daily[self.day] = self.balance - self.day_start_equity
            self.day = daykey
            self.day_start_equity = self.balance
            self.day_trades = 0
            self.day_locked = False

        mid, spread, ready = self._update_state(ts, bid, ask)
        if not ready:
            return

        # ================= position management =========================
        if self.pos != 0:
            px = bid if self.pos > 0 else ask          # exit price (mark)
            move = (px - self.entry_price) * self.pos
            self.best = max(self.best, move)
            self.worst = min(self.worst, move)

            # trailing arm
            if not self.trail_active and self.best >= p.trail_arm_k * self.entry_vol:
                self.trail_active = True
            if self.trail_active:
                lvl = self.best - p.trail_k * self.entry_vol
                self.trail_level = max(self.trail_level, lvl)

            fz = self.flow_score()

            if move <= -p.sl_k * self.entry_vol:
                self._close(ts, px, "stop_loss")
            elif move >= p.tp_k * self.entry_vol:
                self._close(ts, px, "take_profit")
            elif self.trail_active and move <= self.trail_level:
                self._close(ts, px, "trail")
            elif fz * self.pos <= -p.flip_z:
                self._close(ts, px, "flow_flip")
            elif ts - self.entry_ts >= p.max_hold_s:
                self._close(ts, px, "time_stop")
            self._ec += 1
            if self._ec % 250 == 0:
                self.equity_curve.append((ts, self.balance + move * self.value_per_price_unit))
            return

        self._ec += 1
        if self._ec % 250 == 0:
            self.equity_curve.append((ts, self.balance))

        # ================= entry filters ================================
        if self.day_locked:
            self.rejects["daylock"] += 1
            return
        dd = (self.balance - self.day_start_equity) / max(1e-9, self.day_start_equity)
        if dd <= -p.daily_loss_stop or dd >= p.daily_profit_stop or self.day_trades >= p.max_trades_per_day:
            self.day_locked = True
            self.rejects["daylock"] += 1
            return
        if hour in p.blocked_hours or (p.allowed_hours and hour not in p.allowed_hours):
            self.rejects["hour"] += 1
            return
        if ts - self.last_exit_ts < p.cooldown_s:
            self.rejects["cooldown"] += 1
            return
        if self.vol < p.min_vol:
            self.rejects["vol"] += 1
            return

        fz = self.flow_score()
        if abs(fz) < p.flow_z:
            self.rejects["flow"] += 1
            return

        eff = self.efficiency()
        if eff < p.eff_min:
            self.rejects["eff"] += 1
            return
        if np.sign(self.net) != np.sign(fz):
            self.rejects["eff"] += 1
            return

        if self.i_slow <= 0 or self.i_fast < p.intens_mult * self.i_slow:
            self.rejects["intens"] += 1
            return

        target = p.tp_k * self.vol
        if spread > p.spread_mult * self.spread_ewma or spread > p.spread_edge_frac * target:
            self.rejects["spread"] += 1
            return

        # ---- margin sanity (800x) ----------------------------------------
        need = (mid * p.lot * CONTRACT_SIZE) / p.leverage
        if need > self.balance * 0.5:
            return

        # ================= fire ==========================================
        self.signals += 1
        side = 1 if fz > 0 else -1
        self.pos = side
        self.entry_price = ask if side > 0 else bid     # pay the spread
        self.entry_ts = ts
        self.entry_spread = spread
        self.entry_vol = max(self.vol, p.min_vol)       # freeze vol at entry
        self.best = 0.0
        self.worst = 0.0
        self.trail_active = False
        self.trail_level = -1e18

    # ------------------------------------------------------------------ #
    def finalize(self):
        if self.day is not None:
            self.daily[self.day] = self.balance - self.day_start_equity


# --------------------------------------------------------------------------- #
def calibrate(ticks, p: Params = None, sample_every: int = 97,
              fz_pct: float = 95.0, eff_pct: float = 90.0,
              max_ticks: int = 3_000_000, verbose: bool = True) -> Params:
    """Auto-calibrate entry thresholds to a specific tick feed.

    The signal definitions are density-invariant, but the *right percentile*
    to trade at still depends on how noisy a given broker's feed is. This
    runs the state machine over a warm-up slice WITHOUT trading, measures the
    real distribution of |flow_score| and efficiency, and sets the thresholds
    at the requested percentiles.

    This is calibration, not curve fitting: no P&L is used, only the shape of
    the signal distribution.
    """
    p = p or Params()
    probe = TFAM(Params(**{**{k: v for k, v in asdict(p).items()}, "flow_z": 1e9}))
    ts = ticks["ts"].to_numpy()
    bid = ticks["bid"].to_numpy()
    ask = ticks["ask"].to_numpy()
    hrs = ticks["time"].dt.hour.to_numpy().astype(np.int32)
    dks = ticks["time"].dt.strftime("%Y-%m-%d").to_numpy()

    n = min(len(ts), max_ticks)
    FZ, EF = [], []
    for i in range(n):
        probe.on_tick(ts[i], bid[i], ask[i], int(hrs[i]), dks[i])
        if probe.warm > 20000 and i % sample_every == 0:
            FZ.append(abs(probe.flow_score()))
            EF.append(probe.efficiency())
    if len(FZ) < 100:
        if verbose:
            print("[calib] not enough samples, keeping defaults")
        return p

    fz = float(np.percentile(FZ, fz_pct))
    ef = float(np.percentile(EF, eff_pct))
    out = Params(**{**{k: v for k, v in asdict(p).items()},
                    "flow_z": round(fz, 3), "eff_min": round(ef, 3)})
    if verbose:
        print(f"[calib] samples={len(FZ):,}  flow_z(p{fz_pct})={out.flow_z}  "
              f"eff_min(p{eff_pct})={out.eff_min}")
    return out
