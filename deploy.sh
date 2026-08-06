#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

echo "[1/4] 检查 Python（需要 3.11+）"
"$PYTHON_BIN" --version
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'

echo "[2/4] 创建虚拟环境 .venv"
"$PYTHON_BIN" -m venv .venv

echo "[3/4] 安装项目"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

echo "[4/4] 初始化数据库"
mkdir -p data
POLYARB_DB="${POLYARB_DB:-data/paper.sqlite3}" .venv/bin/python -m polyarb report --limit 1 >/dev/null

echo "部署完成。启动命令：bash start.sh"
