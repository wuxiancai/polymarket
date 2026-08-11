#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

SERVICE_NAME="${SERVICE_NAME:-polyarb}"
STOP_GRACE_SECONDS="${POLYARB_STOP_GRACE_SECONDS:-1}"
FAILED=0

echo "停止 Polyarb 服务：${SERVICE_NAME}"

systemd_unit_exists=false
if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files --type=service --no-legend 2>/dev/null \
    | awk -v service="${SERVICE_NAME}.service" '$1 == service { found=1 } END { exit found ? 0 : 1 }'; then
    systemd_unit_exists=true
  fi
  if [[ -e "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
    systemd_unit_exists=true
  fi
fi

if [[ "$systemd_unit_exists" == "true" ]]; then
  echo "停止 systemd 服务：${SERVICE_NAME}"
  if sudo systemctl stop "$SERVICE_NAME"; then
    echo "systemd 服务已停止：${SERVICE_NAME}"
  else
    echo "停止 systemd 服务失败：sudo systemctl stop ${SERVICE_NAME}" >&2
    FAILED=1
  fi
else
  echo "未发现 systemd 服务：${SERVICE_NAME}"
fi

if command -v pkill >/dev/null 2>&1; then
  if pkill -TERM -f '[p]ython .* -m polyarb' >/dev/null 2>&1; then
    echo "已向本机 polyarb 进程发送停止信号"
  else
    echo "未发现本机 polyarb 进程"
  fi

  if command -v pgrep >/dev/null 2>&1; then
    sleep "$STOP_GRACE_SECONDS"
    remaining_pids="$(pgrep -f '[p]ython .* -m polyarb' || true)"
    if [[ -n "$remaining_pids" ]]; then
      echo "强制停止未退出进程：${remaining_pids}"
      pkill -KILL -f '[p]ython .* -m polyarb' >/dev/null 2>&1 || true
    fi
  fi
fi

if [[ "$FAILED" -eq 1 ]]; then
  exit 1
fi

echo "Polyarb 服务已停止。"
