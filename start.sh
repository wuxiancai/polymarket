#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "未发现 .venv，先执行一键部署：bash deploy.sh"
  exit 1
fi

export POLYARB_DB="${POLYARB_DB:-data/paper.sqlite3}"
export MIN_24H_VOLUME_USD="${MIN_24H_VOLUME_USD:-1000}"
export MIN_ARBITRAGE_DEPTH_USD="${MIN_ARBITRAGE_DEPTH_USD:-100}"
export SLIPPAGE_BUFFER_CENTS="${SLIPPAGE_BUFFER_CENTS:-2}"
export MIN_INTERVAL_MINUTES="${MIN_INTERVAL_MINUTES:-15}"
export ALLOW_CURRENT_MONTH_ONLY="${ALLOW_CURRENT_MONTH_ONLY:-true}"
export REFRESH_SECONDS="${REFRESH_SECONDS:-30}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8787}"

echo "启动 Polyarb Web: http://${HOST}:${PORT}"
.venv/bin/python -m polyarb web --host "$HOST" --port "$PORT"
