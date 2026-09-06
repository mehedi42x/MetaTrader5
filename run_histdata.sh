#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-shot: download the Google Drive folder of HistData XAUUSD tick ZIPs,
# convert to MT5 format, and run BOTH strategies with full reports.
#
#   bash run_histdata.sh
#   FOLDER_ID=<your_drive_folder_id> bash run_histdata.sh
#
# If you already downloaded the zips yourself, skip the download:
#   ZIPDIR=/path/to/zips SKIP_DOWNLOAD=1 bash run_histdata.sh
# ---------------------------------------------------------------------------
set -euo pipefail

FOLDER_ID="${FOLDER_ID:-1_JeIkLaW3yxmb6ai53g_1hoveaw6fJLc}"
ZIPDIR="${ZIPDIR:-data/xauusd_zips}"
OUT="${OUT:-data/XAUUSD_ticks.csv}"

if [ ! -d .venv ]; then
  echo ">> creating venv"
  python3 -m venv .venv
  .venv/bin/pip install -q numpy pandas matplotlib gdown
fi

if [ "${SKIP_DOWNLOAD:-0}" != "1" ]; then
  echo ">> [1/4] downloading HistData XAUUSD tick ZIPs from Google Drive"
  echo "   (32 monthly archives, ~1.2 GB)"
  .venv/bin/python src/histdata.py --gdrive "$FOLDER_ID" --dest "$ZIPDIR" --out "$OUT"
else
  echo ">> [1/4] skipping download, using $ZIPDIR"
  echo ">> [2/4] converting HistData ASCII -> MT5 tick CSV"
  .venv/bin/python src/histdata.py "$ZIPDIR" --out "$OUT"
fi

echo
echo ">> [3/4] TFAM  (tick-flow absorption momentum)"
.venv/bin/python src/report.py "$OUT"

echo
echo ">> [4/4] QAS   (quote asymmetry scalper)"
.venv/bin/python src/run_scalper.py "$OUT"

echo
echo ">> done."
ls -la results/
