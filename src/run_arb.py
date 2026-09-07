"""
run_arb.py -- backtest the ARB strategy on real XAUUSD tick data.

Streams the tick file one row at a time (the full file is 12.8M ticks and
will not fit in memory), feeds every tick to the strategy, then writes:

    results/arb_results.json   headline metrics, incl. train/test split
    results/arb_trades.csv     every trade with its full audit trail
    results/arb_equity.png     equity curve + drawdown

Usage:
    python src/run_arb.py /tmp/REAL_XAUUSD.csv
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arb_strategy import ArbConfig, ArbStrategy, stream_ticks  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "results")


def metrics(trades, initial):
    if not trades:
        return {"trades": 0}
    net = np.array([t.net for t in trades])
    eq = initial + np.cumsum(net)
    wins, losses = net[net > 0], net[net <= 0]
    gp, gl = wins.sum(), abs(losses.sum())
    peak = np.maximum.accumulate(np.concatenate([[initial], eq]))
    dd = (peak - np.concatenate([[initial], eq]))
    ddp = dd / peak * 100

    # daily returns for Sharpe (one trade per day, so trades == days traded)
    ret = net / (initial + np.concatenate([[0], np.cumsum(net)[:-1]]))
    sharpe = (ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0

    return {
        "trades": len(trades),
        "net_profit": round(net.sum(), 2),
        "return_pct": round(net.sum() / initial * 100, 2),
        "final_balance": round(eq[-1], 2),
        "win_rate": round(100 * len(wins) / len(net), 2),
        "wins": int(len(wins)), "losses": int(len(losses)),
        "profit_factor": round(gp / gl, 3) if gl else None,
        "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
        "expectancy": round(net.mean(), 4),
        "avg_win": round(wins.mean(), 3) if len(wins) else 0.0,
        "avg_loss": round(losses.mean(), 3) if len(losses) else 0.0,
        "largest_win": round(net.max(), 2), "largest_loss": round(net.min(), 2),
        "max_drawdown": round(dd.max(), 2),
        "max_drawdown_pct": round(ddp.max(), 2),
        "sharpe": round(sharpe, 2),
        "avg_r": round(float(np.mean([t.r_multiple for t in trades])), 4),
        "total_commission": round(sum(t.commission for t in trades), 2),
        "total_slippage": round(sum(t.slippage for t in trades), 2),
        "gross_before_costs": round(sum(t.gross for t in trades), 2),
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/REAL_XAUUSD.csv"
    cfg = ArbConfig()
    strat = ArbStrategy(cfg)

    print(f"streaming {path} ...")
    n = 0
    last = None
    for ts, bid, ask in stream_ticks(path):
        strat.on_tick(ts, bid, ask)
        last = (ts, bid)
        n += 1
        if n % 2_000_000 == 0:
            print(f"  {n:,} ticks  balance ${strat.balance:.2f}  "
                  f"trades {len(strat.trades)}")
    if last:
        strat.finalize(last[0], last[1])
    print(f"done: {n:,} ticks, {len(strat.trades)} trades")

    tr = strat.trades
    os.makedirs(OUT, exist_ok=True)

    train = [t for t in tr if t.date.startswith("2024")]
    test = [t for t in tr if t.date.startswith("2026")]

    res = {
        "config": {k: v for k, v in asdict(cfg).items()},
        "ticks": n,
        "overall": metrics(tr, cfg.initial_balance),
        "train_2024": metrics(train, cfg.initial_balance),
        "test_2026_holdout": metrics(test, cfg.initial_balance),
        "exit_reasons": {r: sum(1 for t in tr if t.exit_reason == r)
                         for r in {t.exit_reason for t in tr}},
        "by_side": {
            "long": metrics([t for t in tr if t.side > 0], cfg.initial_balance),
            "short": metrics([t for t in tr if t.side < 0], cfg.initial_balance),
        },
        "skipped": strat.skipped,
    }

    with open(f"{OUT}/arb_results.json", "w") as f:
        json.dump(res, f, indent=2)

    import csv as _csv
    with open(f"{OUT}/arb_trades.csv", "w", newline="") as f:
        if tr:
            w = _csv.DictWriter(f, fieldnames=list(asdict(tr[0]).keys()))
            w.writeheader()
            for t in tr:
                w.writerow(asdict(t))

    # ---- chart ---------------------------------------------------------- #
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        net = np.array([t.net for t in tr])
        eq = cfg.initial_balance + np.concatenate([[0], np.cumsum(net)])
        peak = np.maximum.accumulate(eq)
        fig, ax = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                               gridspec_kw={"height_ratios": [3, 1]})
        ax[0].plot(eq, lw=1.6, color="#1a7f37")
        ax[0].axhline(cfg.initial_balance, color="grey", ls="--", lw=0.8)
        n_tr = len(train)
        if n_tr and test:
            ax[0].axvline(n_tr, color="crimson", ls=":", lw=1.5)
            ax[0].text(n_tr, eq.max(), "  holdout 2026 ->", color="crimson",
                       va="top", fontsize=9)
        ax[0].set_title("ARB -- Asian Range Breakout, XAUUSD 0.01 lot, "
                        "real tick data")
        ax[0].set_ylabel("balance ($)")
        ax[0].grid(alpha=.3)
        ax[1].fill_between(range(len(eq)), (eq - peak), color="crimson", alpha=.6)
        ax[1].set_ylabel("drawdown ($)")
        ax[1].set_xlabel("trade #")
        ax[1].grid(alpha=.3)
        plt.tight_layout()
        plt.savefig(f"{OUT}/arb_equity.png", dpi=120)
        print(f"wrote {OUT}/arb_equity.png")
    except Exception as e:
        print("chart skipped:", e)

    print(json.dumps({k: res[k] for k in
                      ("overall", "train_2024", "test_2026_holdout",
                       "exit_reasons")}, indent=2))


if __name__ == "__main__":
    main()
