#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-shot: download 2 years of Dukascopy XAUUSD ticks and run both strategies.
#
#   bash run_dukascopy.sh              # 2 years, default settings
#   SYMBOL=XAUUSD YEARS=2 bash run_dukascopy.sh
#
# The download is resumable: raw .bi5 files are cached in data/.duka_cache,
# so re-running after an interruption only fetches what is missing.
# ---------------------------------------------------------------------------
set -euo pipefail

SYMBOL="${SYMBOL:-XAUUSD}"
YEARS="${YEARS:-2}"
WORKERS="${WORKERS:-10}"
OUT="data/${SYMBOL}_ticks.csv"

if [ ! -d .venv ]; then
  echo ">> creating venv"
  python3 -m venv .venv
  .venv/bin/pip install -q numpy pandas matplotlib
fi

echo ">> [1/3] downloading ${YEARS}y of ${SYMBOL} tick data from Dukascopy"
echo "   (~17,500 hourly files; expect 30-90 min and ~2-4 GB of CSV)"
.venv/bin/python src/dukascopy.py \
    --symbol "$SYMBOL" --years "$YEARS" \
    --workers "$WORKERS" --out "$OUT"

echo
echo ">> [2/3] TFAM  (tick-flow absorption momentum)"
.venv/bin/python src/report.py "$OUT"

echo
echo ">> [3/3] QAS   (quote asymmetry scalper)"
.venv/bin/python src/run_scalper.py "$OUT"

echo
echo ">> done. see results/"
ls -la results/
