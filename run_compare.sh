#!/usr/bin/env bash
set -euo pipefail

# 简单的通宵批跑脚本
# 用法: bash run_compare.sh [PDF1] [PDF2] [SKIP_CSV]

DIR="$(cd "$(dirname "$0")" && pwd)"
# 既然你的 Python 脚本已经有默认目录，这里也保持一致比较好
PDF1="${1:-/data/guozehua/comparePDFs/aai.pdf}"
PDF2="${2:-/data/guozehua/comparePDFs/ed4.pdf}"
SKIP_CSV="${3:-}"

# 统一把日志放到 output/log 下，保持整洁
LOG_DIR="$DIR/output/log"
mkdir -p "$LOG_DIR"

TS="$(date +%Y%m%dT%H%M%S)"
OUT="results-${TS}.csv"
# 日志文件路径
LOG_FILE="$LOG_DIR/bash_run_${TS}.log"

cd "$DIR"

echo "========================================================"
echo " 🚀 任务启动: $(date)"
echo " 📄 PDF1: $PDF1"
echo " 📄 PDF2: $PDF2"
if [[ -n "$SKIP_CSV" ]]; then
    echo " ⏭️  跳过CSV: $SKIP_CSV"
fi
echo " 📝 日志: $LOG_FILE"
echo "========================================================"

# --- 核心修改部分 ---

# 1. 将所有后续命令放在一个子 Shell 中运行
# 2. 将其放入后台 (&)
# 3. 将所有输出 (stdout 和 stderr) 重定向到日志文件
(
    echo "[RUN] $(date -Iseconds) start compare"
    echo "[RUN] pdf1=$PDF1"
    echo "[RUN] pdf2=$PDF2"
        echo "[RUN] out=$OUT"
        if [[ -n "$SKIP_CSV" ]]; then
            echo "[RUN] skip_csv=$SKIP_CSV"
        fi
    
        # 你的 Python 运行命令 (固定阈值为 0.7，本轮需要更低的SigLIP阈值)
        if [[ -n "$SKIP_CSV" ]]; then
            conda run -n pdf_compare python compare_pdfs.py "$PDF1" "$PDF2" --threshold 0.7 --skip-csv "$SKIP_CSV" -o "$OUT"
        else
            conda run -n pdf_compare python compare_pdfs.py "$PDF1" "$PDF2" --threshold 0.7 -o "$OUT"
        fi
    
    echo "[RUN] $(date -Iseconds) done"
    echo "[RUN] csv saved at: $OUT"
) >> "$LOG_FILE" 2>&1 &  # 关键：全部追加到日志，并在后台运行

# 获取刚才后台进程的 PID
BG_PID=$!

# 4. 使用 tail -f --pid 自动追踪
# 当 BG_PID 进程结束时，tail 也会自动退出，不需要你手动 Ctrl+C
echo "📺 正在监控日志 (进程 PID: $BG_PID)..."
tail -f --pid=$BG_PID "$LOG_FILE"

# 任务结束后的提示
echo ""
echo "✅ 任务已完成，日志监控自动退出。"