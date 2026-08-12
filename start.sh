#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "未发现 .venv，先执行一键部署：bash deploy.sh"
  exit 1
fi

if ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  echo "当前 .venv 使用 Python 3.11 以下版本；请删除 .venv 后重新执行 bash deploy.sh"
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "未发现 systemd/systemctl；服务器启动必须使用 systemd。"
  exit 1
fi

SERVICE_NAME="${SERVICE_NAME:-polyarb}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

existing_service_db() {
  systemctl show "$SERVICE_NAME" -p Environment 2>/dev/null \
    | tr ' ' '\n' \
    | sed -n 's/^Environment=POLYARB_DB=//p; s/^POLYARB_DB=//p' \
    | head -n 1
}

if [[ -z "${POLYARB_DB:-}" ]]; then
  EXISTING_POLYARB_DB="$(existing_service_db || true)"
  if [[ -n "$EXISTING_POLYARB_DB" && -e "$EXISTING_POLYARB_DB" ]]; then
    POLYARB_DB="$EXISTING_POLYARB_DB"
    echo "沿用已有 systemd 数据库：${POLYARB_DB}"
  else
    POLYARB_DB="${ROOT_DIR}/data/paper.sqlite3"
  fi
fi
MIN_24H_VOLUME_USD="${MIN_24H_VOLUME_USD:-1000}"
MIN_ARBITRAGE_DEPTH_USD="${MIN_ARBITRAGE_DEPTH_USD:-100}"
SLIPPAGE_BUFFER_CENTS="${SLIPPAGE_BUFFER_CENTS:-3}"
MIN_INTERVAL_MINUTES="${MIN_INTERVAL_MINUTES:-15}"
ALLOW_CURRENT_MONTH_ONLY="${ALLOW_CURRENT_MONTH_ONLY:-true}"
PAPER_INITIAL_CAPITAL_USDT="${PAPER_INITIAL_CAPITAL_USDT:-10000}"
REFRESH_SECONDS="${REFRESH_SECONDS:-30}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8787}"
POLYMARKET_WALLET_ADDRESS="${POLYMARKET_WALLET_ADDRESS:-}"
POLYMARKET_PRIVATE_KEY="${POLYMARKET_PRIVATE_KEY:-}"
POLYMARKET_RELAYER_API_KEY="${POLYMARKET_RELAYER_API_KEY:-}"
POLYMARKET_RELAYER_API_KEY_ADDRESS="${POLYMARKET_RELAYER_API_KEY_ADDRESS:-}"
POLYMARKET_AUTO_LOGIN="${POLYMARKET_AUTO_LOGIN:-false}"

mkdir -p data

systemd_env_line() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" ]]; then
    return
  fi
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//%/%%}"
  printf 'Environment="%s=%s"\n' "$name" "$value"
}

if [[ -n "${http_proxy:-}" && -z "${ws_proxy:-}" ]]; then
  ws_proxy="$http_proxy"
fi
if [[ -n "${https_proxy:-}" && -z "${wss_proxy:-}" ]]; then
  wss_proxy="$https_proxy"
fi
if [[ -n "${HTTP_PROXY:-}" && -z "${WS_PROXY:-}" ]]; then
  WS_PROXY="$HTTP_PROXY"
fi
if [[ -n "${HTTPS_PROXY:-}" && -z "${WSS_PROXY:-}" ]]; then
  WSS_PROXY="$HTTPS_PROXY"
fi

PROXY_ENV_LINES=""
for env_name in \
  http_proxy https_proxy ftp_proxy all_proxy no_proxy ws_proxy wss_proxy \
  HTTP_PROXY HTTPS_PROXY FTP_PROXY ALL_PROXY NO_PROXY WS_PROXY WSS_PROXY; do
  line="$(systemd_env_line "$env_name")"
  if [[ -n "$line" ]]; then
    PROXY_ENV_LINES+="${line}"$'\n'
  fi
done

LIVE_ENV_LINES=""
for env_name in \
  POLYMARKET_WALLET_ADDRESS POLYMARKET_PRIVATE_KEY \
  POLYMARKET_RELAYER_API_KEY POLYMARKET_RELAYER_API_KEY_ADDRESS \
  POLYMARKET_AUTO_LOGIN; do
  line="$(systemd_env_line "$env_name")"
  if [[ -n "$line" ]]; then
    LIVE_ENV_LINES+="${line}"$'\n'
  fi
done

SERVICE_CONTENT="[Unit]
Description=Polyarb Polymarket BTC/ETH/XRP/SOL live + paper dashboard
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
${PROXY_ENV_LINES}
${LIVE_ENV_LINES}
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
