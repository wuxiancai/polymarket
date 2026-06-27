#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "未发现 .venv，先执行一键部署：bash deploy.sh"
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "未发现 systemd/systemctl；服务器启动必须使用 systemd。"
  exit 1
fi

POLYARB_DB="${POLYARB_DB:-${ROOT_DIR}/data/paper.sqlite3}"
MIN_24H_VOLUME_USD="${MIN_24H_VOLUME_USD:-1000}"
MIN_ARBITRAGE_DEPTH_USD="${MIN_ARBITRAGE_DEPTH_USD:-100}"
SLIPPAGE_BUFFER_CENTS="${SLIPPAGE_BUFFER_CENTS:-2}"
MIN_INTERVAL_MINUTES="${MIN_INTERVAL_MINUTES:-15}"
ALLOW_CURRENT_MONTH_ONLY="${ALLOW_CURRENT_MONTH_ONLY:-true}"
PAPER_INITIAL_CAPITAL_USDT="${PAPER_INITIAL_CAPITAL_USDT:-10000}"
REFRESH_SECONDS="${REFRESH_SECONDS:-30}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8787}"
SERVICE_NAME="${SERVICE_NAME:-polyarb}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

mkdir -p data

SERVICE_CONTENT="[Unit]
Description=Polyarb Polymarket BTC/ETH paper arbitrage dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${ROOT_DIR}
Environment=POLYARB_DB=${POLYARB_DB}
Environment=MIN_24H_VOLUME_USD=${MIN_24H_VOLUME_USD}
Environment=MIN_ARBITRAGE_DEPTH_USD=${MIN_ARBITRAGE_DEPTH_USD}
Environment=SLIPPAGE_BUFFER_CENTS=${SLIPPAGE_BUFFER_CENTS}
Environment=MIN_INTERVAL_MINUTES=${MIN_INTERVAL_MINUTES}
Environment=ALLOW_CURRENT_MONTH_ONLY=${ALLOW_CURRENT_MONTH_ONLY}
Environment=PAPER_INITIAL_CAPITAL_USDT=${PAPER_INITIAL_CAPITAL_USDT}
Environment=REFRESH_SECONDS=${REFRESH_SECONDS}
ExecStart=${ROOT_DIR}/.venv/bin/python -m polyarb web --host ${HOST} --port ${PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"

echo "写入 systemd 服务：${SERVICE_FILE}"
printf '%s\n' "$SERVICE_CONTENT" | sudo tee "$SERVICE_FILE" >/dev/null

echo "重载并启动 systemd 服务：${SERVICE_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
echo "Polyarb 已通过 systemd 启动。"
echo "本机监听：http://${HOST}:${PORT}"
if [[ -n "${LAN_IP}" ]]; then
  echo "局域网访问：http://${LAN_IP}:${PORT}"
else
  echo "局域网访问：http://<服务器IP>:${PORT}"
fi
echo "查看状态：sudo systemctl status ${SERVICE_NAME}"
echo "查看日志：sudo journalctl -u ${SERVICE_NAME} -f"
