"""
run_scalper.py
==============
Backtest + full report for the QAS (Quote Asymmetry Scalper) strategy.

    python src/run_scalper.py data/XAUUSD_ticks.csv

Writes to results/:
    QAS_REPORT.md      full report (same depth as the TFAM report)
    qas_results.json
    qas_trades.csv
    qas_equity.png
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scalper import QAS, QASParams, calibrate_qas, TICK_SIZE, CONTRACT_SIZE  # noqa: E402
from mt5_loader import load_ticks                                            # noqa: E402
import report as rep                                                         # noqa: E402

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")


def run(ticks: pd.DataFrame, p: QASParams, verbose=True) -> QAS:
    st = QAS(p)
    ts = ticks["ts"].to_numpy()
    bid = ticks["bid"].to_numpy()
    ask = ticks["ask"].to_numpy()
    hrs = ticks["time"].dt.hour.to_numpy().astype(np.int32)
    dks = ticks["time"].dt.strftime("%Y-%m-%d").to_numpy()
    n = len(ts)
    step = max(1, n // 20)
    for i in range(n):
        st.on_tick(ts[i], bid[i], ask[i], int(hrs[i]), dks[i])
        if verbose and i % step == 0:
            print(f"[qas] {100*i/n:5.1f}%  trades={len(st.trades):,}  "
                  f"bal=${st.balance:,.2f}", flush=True)
    if st.pos != 0:
        st._close(ts[-1], bid[-1] if st.pos > 0 else ask[-1], "eod_flat")
    st.finalize()
    return st


class _Shim:
    """Adapt QAS to the shared report builder in report.py."""
    def __init__(self, st: QAS, p: QASParams):
        self.trades = st.trades
        self.balance = st.balance
        self.daily = st.daily
        self.signals = st.signals
        self.rejects = st.rejects
        self.p = p


def main():
    if len(sys.argv) < 2:
        print("usage: python src/run_scalper.py /path/to/ticks.csv")
        sys.exit(1)
    os.makedirs(RESULTS, exist_ok=True)

    ticks = load_ticks(sys.argv[1])

    if "--no-calib" in sys.argv:
        p = QASParams()
    else:
        print("[qas] calibrating quote-pressure threshold to this feed ...")
        p = calibrate_qas(ticks, QASParams())

    st = run(ticks, p)
    if not st.trades:
        print("no trades generated")
        return

    R, tr = rep.build_report(_Shim(st, p), ticks, p)
    R["strategy"] = "QAS - Quote Asymmetry Scalper"

    with open(os.path.join(RESULTS, "qas_results.json"), "w") as f:
        json.dump(R, f, indent=2, default=str)
    tr.to_csv(os.path.join(RESULTS, "qas_trades.csv"), index=False)

    md = rep.render_markdown(R).replace(
        "# TFAM — REAL TICK DATA BACKTEST REPORT",
        "# QAS — Quote Asymmetry Scalper — REAL TICK DATA REPORT")
    with open(os.path.join(RESULTS, "QAS_REPORT.md"), "w") as f:
        f.write(md)
    try:
        rep.make_charts(R, tr, p, os.path.join(RESULTS, "qas_equity.png"))
    except Exception as e:
        print("chart skipped:", e)

    print("\n=== QAS DONE ===")
    print(json.dumps(R["summary"], indent=2))


if __name__ == "__main__":
    main()
