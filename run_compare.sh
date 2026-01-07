#!/usr/bin/env bash
set -euo pipefail

# 简单的通宵批跑脚本：
#   bash run_compare.sh [PDF1] [PDF2]

DIR="$(cd "$(dirname "$0")" && pwd)"
PDF1="${1:-/data/guozehua/comparePDFs/aai.pdf}"
PDF2="${2:-/data/guozehua/comparePDFs/ed4.pdf}"
TS="$(date +%Y%m%dT%H%M%S)"
OUT="results-${TS}.csv"
LOG="run-${TS}.log"

cd "$DIR"

echo "[RUN] $(date -Iseconds) start compare" | tee -a "$LOG"
echo "[RUN] pdf1=$PDF1" | tee -a "$LOG"
echo "[RUN] pdf2=$PDF2" | tee -a "$LOG"
echo "[RUN] out=$OUT" | tee -a "$LOG"

python compare_pdfs.py "$PDF1" "$PDF2" -o "$OUT" | tee -a "$LOG"

echo "[RUN] $(date -Iseconds) done" | tee -a "$LOG"
echo "[RUN] csv saved at: $OUT" | tee -a "$LOG"