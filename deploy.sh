#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[1/4] 检查 Python"
"$PYTHON_BIN" --version

echo "[2/4] 创建虚拟环境 .venv"
"$PYTHON_BIN" -m venv .venv

echo "[3/4] 安装项目"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

echo "[4/4] 初始化数据库"
mkdir -p data
POLYARB_DB="${POLYARB_DB:-data/paper.sqlite3}" .venv/bin/python -m polyarb report --limit 1 >/dev/null

echo "部署完成。启动命令：bash start.sh"
