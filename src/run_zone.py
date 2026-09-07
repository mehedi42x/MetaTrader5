"""
run_zone.py -- backtest the ZCB (Zone Compression Breakout) strategy.

Modes:
    python src/run_zone.py sweep   <ticks.csv>   parameter sweep
    python src/run_zone.py single  <ticks.csv>   full run + artefacts

The sweep exists because the user's rule has several free numbers
(zone width, touch count, exit touches, stop, hold). Guessing one
tuning and reporting it would be dishonest -- so we test many and
report what the data says about all of them.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import asdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zone_strategy import ZoneConfig, ZoneStrategy      # noqa: E402
from arb_strategy import stream_ticks                   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")


def run(ticks, cfg, limit=None):
    s = ZoneStrategy(cfg)
    last = None
    for i, (dt, bid, ask) in enumerate(ticks):
        if limit and i >= limit:
            break
        s.on_tick(dt, bid, ask)
        last = (dt, bid, ask)
    if last:
        s.finalize(*last)
    return s


def stats(s: ZoneStrategy):
    tr = s.trades
    if not tr:
        return None
    net = np.array([t.net for t in tr])
    gross = np.array([t.gross for t in tr])
    w, l = net[net > 0].sum(), abs(net[net <= 0].sum())
    eq = s.cfg.initial_balance + np.cumsum(net)
    peak = np.maximum.accumulate(np.concatenate([[s.cfg.initial_balance], eq]))
    dd = (peak - np.concatenate([[s.cfg.initial_balance], eq])).max()
    return {
        "trades": len(tr),
        "net": round(net.sum(), 2),
        "return_pct": round(net.sum() / s.cfg.initial_balance * 100, 2),
        "pf": round(w / l, 3) if l else None,
        "win_rate": round(100 * (net > 0).mean(), 2),
        "expectancy": round(net.mean(), 4),
        "gross_total": round(gross.sum(), 2),
        "cost_total": round(sum(t.cost for t in tr), 2),
        "max_dd": round(dd, 2),
        "avg_dur_s": round(float(np.mean([t.duration_s for t in tr])), 1),
        "final_balance": round(s.balance, 2),
    }


def load_all(path, limit=None):
    out = []
    for i, x in enumerate(stream_ticks(path)):
        if limit and i >= limit:
            break
        out.append(x)
    return out


def sweep(path):
    print("loading ticks for sweep (2024-01 slice) ...")
    ticks = load_all(path, limit=3_000_000)
    print(f"  {len(ticks):,} ticks  {ticks[0][0]} -> {ticks[-1][0]}")

    print("\n" + "=" * 104)
    print("ZCB PARAMETER SWEEP -- user's zone logic")
    print("=" * 104)
    print(f"  {'zone':>6} {'tch':>4} {'brk':>4} {'xtch':>5} {'stop':>6} "
          f"{'hold':>6} | {'trades':>7} {'net$':>10} {'PF':>6} {'win%':>6} "
          f"{'exp$':>8} {'gross$':>9} {'cost$':>9}")

    rows = []
    combos = []
    for zone_w in (0.10, 0.25, 0.50):
        for min_touch in (5, 8):
            for brk in (2, 3):
                combos.append((zone_w, min_touch, brk, 5, 1.5, 900))
    # exit / stop variations on a mid setting
    for xt in (3, 8):
        combos.append((0.25, 5, 2, xt, 1.5, 900))
    for stop in (0.5, 3.0):
        combos.append((0.25, 5, 2, 5, stop, 900))
    for hold in (300, 3600):
        combos.append((0.25, 5, 2, 5, 1.5, hold))

    for zone_w, mt, brk, xt, stop, hold in combos:
        cfg = ZoneConfig(zone_w=zone_w, min_touch=mt, break_zones=brk,
                         exit_touch=xt, hard_stop=stop, max_hold=hold)
        s = run(ticks, cfg)
        st = stats(s)
        if not st:
            print(f"  {zone_w:>6} {mt:>4} {brk:>4} {xt:>5} {stop:>6} {hold:>6} "
                  f"| no trades")
            continue
        rows.append((st["net"], zone_w, mt, brk, xt, stop, hold, st))
        print(f"  {zone_w:>6} {mt:>4} {brk:>4} {xt:>5} {stop:>6} {hold:>6} "
              f"| {st['trades']:>7,} {st['net']:>10.2f} "
              f"{st['pf'] if st['pf'] is not None else 0:>6.3f} "
              f"{st['win_rate']:>6.2f} {st['expectancy']:>8.4f} "
              f"{st['gross_total']:>9.2f} {st['cost_total']:>9.2f}")

    rows.sort(reverse=True)
    print("\n  BEST BY NET:")
    for r in rows[:5]:
        st = r[7]
        print(f"    net ${r[0]:+.2f} PF {st['pf']} zone=${r[1]} touch={r[2]} "
              f"brk={r[3]} xtouch={r[4]} stop=${r[5]} hold={r[6]}s "
              f"trades={st['trades']:,}")

    if rows:
        best = rows[0][7]
        print(f"\n  Best gross (before cost): ${best['gross_total']:+.2f}")
        print(f"  Cost paid:                ${best['cost_total']:.2f}")
    return rows


def single(path):
    cfg = ZoneConfig()
    print("streaming full tick file ...")
    s = ZoneStrategy(cfg)
    last = None
    n = 0
    for dt, bid, ask in stream_ticks(path):
        s.on_tick(dt, bid, ask)
        last = (dt, bid, ask)
        n += 1
        if n % 2_000_000 == 0:
            print(f"  {n:,} ticks  bal ${s.balance:.2f}  trades {len(s.trades)}")
    if last:
        s.finalize(*last)
    st = stats(s)
    print(json.dumps(st, indent=2))

    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/zone_results.json", "w") as f:
        json.dump({"config": asdict(cfg), "ticks": n, "stats": st,
                   "signals": s.n_signals, "skipped": s.skipped,
                   "exit_reasons": {r: sum(1 for t in s.trades
                                           if t.exit_reason == r)
                                    for r in {t.exit_reason for t in s.trades}}},
                  f, indent=2)
    if s.trades:
        with open(f"{OUT}/zone_trades.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(s.trades[0]).keys()))
            w.writeheader()
            for t in s.trades:
                w.writerow(asdict(t))
    print(f"wrote {OUT}/zone_results.json")
    return s


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sweep"
    p = sys.argv[2] if len(sys.argv) > 2 else "/tmp/REAL_XAUUSD.csv"
    if mode == "sweep":
        sweep(p)
    else:
        single(p)
