#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "用法: bash filter_true.sh <input.csv>" >&2
  exit 1
fi

DIR="$(cd "$(dirname "$0")" && pwd)"
python "$DIR/filter_true.py" "$1"
