from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Union
from zoneinfo import ZoneInfo

from .config import Config
from .live import LiveCredentials, LiveSession, live_credentials_from_env
from .live_web import live_dashboard_payload, render_live_page
from .models import DEFAULT_ASSETS, AssetSpec
from .runner import MIN_SPREAD_TO_OPEN_CENTS, PaperRunner, RealtimePaperRunner, ScanResult
from .store import PaperStore

DISPLAY_TZ = ZoneInfo("Asia/Shanghai")
APP_STARTED_AT = datetime.now(timezone.utc)


@dataclass
class WebState:
    config: Config
    store: PaperStore
    asset: AssetSpec
    runner: PaperRunner
    latest_result: Optional[ScanResult] = None
    latest_error: Optional[str] = None
    running: bool = False
    realtime: bool = False
    last_event_at: Optional[datetime] = None
    connection_logs: list[dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


    def run_scan(self) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
        self.add_connection_log("info", "手动扫描已触发")
        try:
            result = self.runner.run_iteration()
            with self.lock:
                self.latest_result = result
                self.latest_error = None
            self.add_connection_log(
                "ok",
                f"手动扫描完成：市场 {len(result.markets)}，交易对 {result.pairs}，机会 {len(result.opportunities)}",
            )
        except Exception as exc:
            with self.lock:
                self.latest_error = str(exc)
            self.add_connection_log("error", f"手动扫描失败：{exc}")
        finally:
            with self.lock:
                self.running = False

    def run_realtime(self) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
            self.realtime = True
            self.latest_error = None
        self.add_connection_log("info", "实时监听启动")
        realtime_runner = RealtimePaperRunner(self.config, self.asset)
        self.runner = realtime_runner
        try:
            asyncio.run(
                realtime_runner.run_forever(
                    on_result=self.update_result,
                    on_event=self.update_event,
                    on_log=self.add_connection_log,
                )
            )
        except Exception as exc:
            with self.lock:
                self.latest_error = str(exc)
                self.realtime = False
            self.add_connection_log("error", f"实时监听已停止：{exc}")
        finally:
            with self.lock:
                self.running = False

    def update_result(self, result: ScanResult) -> None:
        with self.lock:
            self.latest_result = result
            self.latest_error = None

    def update_event(self, event_at: datetime) -> None:
        with self.lock:
            self.last_event_at = event_at

    def add_connection_log(self, level: str, message: str) -> None:
        with self.lock:
            self.connection_logs.append(
                {
                    "asset": self.asset.symbol,
                    "level": level,
                    "message": message,
                    "time": datetime.now(timezone.utc),
                }
            )
            self.connection_logs = self.connection_logs[-80:]

    def snapshot(self) -> dict:
        with self.lock:
            result = self.latest_result
            error = self.latest_error
            running = self.running
            realtime = self.realtime
            last_event_at = self.last_event_at
            connection_logs = list(self.connection_logs)
        return {
            "asset": self.asset.symbol,
            "running": running,
            "realtime": realtime,
            "error": error,
            "markets": len(result.markets) if result else 0,
            "pairs": result.pairs if result else 0,
            "opportunities": len(result.opportunities) if result else 0,
            "scanned_at": format_standard_time(result.scanned_at) if result else None,
            "last_event_at": format_standard_time(last_event_at) if last_event_at else None,
            "connection_logs": connection_logs,
        }


@dataclass
class MonitoredEventGroup:
    event_slug: str
    title: str
    end_at: datetime
    near_condition: str
    conditions: list[str]


def serve(config: Config, host: str = "127.0.0.1", port: int = 8787, auto_scan: bool = True) -> None:
    store = PaperStore(config.database_path)
    store.initialize()
    config = replace(config, allocation_ratios=store.allocation_ratios())
    live_session = LiveSession()
    env_credentials = live_credentials_from_env()
    auto_login = os.getenv("POLYMARKET_AUTO_LOGIN", "").lower() in {"1", "true", "yes", "on"}
    if auto_login and env_credentials is not None:
        try:
            live_session.connect(env_credentials)
        except Exception as exc:
            print(f"真实账户环境登录失败：{exc}")
    states = [
        WebState(config=config, store=store, asset=asset, runner=PaperRunner(config, asset))
        for asset in DEFAULT_ASSETS
    ]
    if auto_scan:
        for state in states:
            _start_realtime_loop(state)

    class Handler(PolyarbHandler):
        web_states = states

    Handler.live_session = live_session

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Polyarb Web 已启动: http://{host}:{port}")
    server.serve_forever()


def _start_realtime_loop(state: WebState) -> None:
    thread = threading.Thread(target=state.run_realtime, name="polyarb-realtime-scanner", daemon=True)
    thread.start()


class PolyarbHandler(BaseHTTPRequestHandler):
    web_states: list[WebState]
    live_session: LiveSession

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._html(
                render_live_page(
                    self.live_session.dashboard(),
                    _live_markets(self.web_states),
                )
            )
            return
        if self.path == "/simulation" or self.path.startswith("/simulation?"):
            self._html(render_dashboard(self.web_states))
            return
        if self.path == "/api/live/dashboard":
            self._json(
                live_dashboard_payload(
                    self.live_session.dashboard(),
                    _live_markets(self.web_states),
                )
            )
            return
        if self.path == "/api/status":
            self._json({"assets": [state.snapshot() for state in self.web_states]})
            return
        if self.path == "/api/dashboard":
            self._json(dashboard_payload(self.web_states))
            return
        if self.path == "/api/report":
            self._json(
                {
                    "status": {"assets": [state.snapshot() for state in self.web_states]},
                    "trades": self.web_states[0].store.latest_trades(20),
                    "opportunities": self.web_states[0].store.latest_opportunities(20),
                }
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/live/login":
            self._live_login()
            return
        if self.path == "/api/live/logout":
            self.live_session.logout()
            self._json({"ok": True, "message": "已退出登录。"})
            return
        if self.path == "/api/live/order":
            self._live_order()
            return
        if self.path == "/api/live/cancel":
            self._live_cancel()
            return
        if self.path == "/api/scan":
            for state in self.web_states:
                thread = threading.Thread(
                    target=state.run_scan,
                    name=f"polyarb-{state.asset.symbol.lower()}-manual-scan",
                    daemon=True,
                )
                thread.start()
            self._json({"ok": True, "message": "扫描已触发"})
            return
        if self.path == "/api/settings":
            self._save_settings()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _read_json_body(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _live_login(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            self._json({"ok": False, "message": "请求格式错误。"}, HTTPStatus.BAD_REQUEST)
            return
        wallet = str(payload.get("wallet") or "").strip()
        private_key = str(payload.get("private_key") or "").strip()
        if not wallet or not private_key:
            self._json({"ok": False, "message": "请输入钱包地址和签名私钥。"}, HTTPStatus.BAD_REQUEST)
            return
        credentials = LiveCredentials(
            wallet=wallet,
            private_key=private_key,
            relayer_api_key=str(payload.get("relayer_api_key") or "").strip(),
            relayer_api_key_address=str(payload.get("relayer_api_key_address") or "").strip(),
        )
        try:
            data = self.live_session.connect(credentials)
            self._json(live_dashboard_payload(data, _live_markets(self.web_states)))
        except Exception as exc:
            self._json({"ok": False, "message": f"登录失败：{exc}"}, HTTPStatus.UNAUTHORIZED)

    def _live_order(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            self._json({"ok": False, "message": "请求格式错误。"}, HTTPStatus.BAD_REQUEST)
            return
        if not self.live_session.is_logged_in():
            self._json({"ok": False, "message": "请先登录真实账户。"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            result = self.live_session.place_order(
                token_id=str(payload.get("token_id") or ""),
                side=str(payload.get("side") or "BUY"),
                order_type=str(payload.get("order_type") or "market"),
                amount=str(payload.get("amount") or ""),
                shares=str(payload.get("shares") or ""),
                price=str(payload.get("price") or ""),
                confirm=bool(payload.get("confirm")),
            )
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            self._json(result, status)
        except Exception as exc:
            self._json({"ok": False, "message": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _live_cancel(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            self._json({"ok": False, "message": "请求格式错误。"}, HTTPStatus.BAD_REQUEST)
            return
        if not self.live_session.is_logged_in():
            self._json({"ok": False, "message": "请先登录真实账户。"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            result = self.live_session.cancel_order(str(payload.get("order_id") or ""))
            self._json(result)
        except Exception as exc:
            self._json({"ok": False, "message": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _save_settings(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            self._json({"ok": False, "message": "请求格式错误，设置未保存。"}, HTTPStatus.BAD_REQUEST)
            return
        ok, message, allocations, status = save_allocation_settings(self.web_states, payload)
        if not ok:
            self._json({"ok": False, "message": message}, status)
            return
        self._json({"ok": True, "message": message, "allocations": allocations})

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, data: dict, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, text: str) -> None:
        payload = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def render_dashboard(states: Union[WebState, list[WebState]]) -> str:
    panels = _as_states(states)
    error_html = _error_html(panels)
    id_map = _dashboard_id_map(panels)
    portfolio = _portfolio_payload(panels, id_map)
    settings_html = _settings_html(panels)
    monitored_pairs_html = _monitored_event_groups_html(_monitored_event_groups(panels))
    asset_sections = "\n".join(_asset_section(state, id_map) for state in panels)
    started_at = escape(_runtime_started_at(panels).isoformat())
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Polymarket 套利模拟系统</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --ink: #18212f;
      --muted: #647084;
      --line: #d9dee7;
      --panel: #ffffff;
      --accent: #1f7a5f;
      --danger: #b42318;
      --warn: #8a5a00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    .wrap {{
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
    }}
    .top {{
      min-height: 92px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
    }}
    h1 {{ margin: 0; font-size: 28px; line-height: 1.15; letter-spacing: 0; }}
    p {{ color: var(--muted); margin: 8px 0 0; }}
    main {{ padding: 22px 0 36px; }}
    .toolbar {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    .runtime-panel {{
      min-width: 250px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      color: var(--ink);
      font-size: 14px;
      line-height: 1.45;
    }}
    .runtime-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      white-space: nowrap;
    }}
    .runtime-label {{ color: var(--muted); }}
    .runtime-value {{ font-weight: 800; font-variant-numeric: tabular-nums; }}
    button {{
      border: 1px solid #17624c;
      background: var(--accent);
      color: white;
      min-height: 40px;
      padding: 0 14px;
      border-radius: 6px;
      font-weight: 700;
      cursor: pointer;
    }}
    button.secondary {{
      background: white;
      color: var(--ink);
      border-color: var(--line);
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .portfolio-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }}
    .settings-row {{
      display: grid;
      grid-template-columns: auto repeat(4, minmax(92px, 1fr)) minmax(170px, 1fr) auto auto;
      align-items: end;
      gap: 10px;
      margin-bottom: 16px;
      padding: 12px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .settings-title {{ align-self: center; font-weight: 800; white-space: nowrap; }}
    .settings-field {{ display: grid; gap: 4px; min-width: 0; }}
    .settings-field label {{ color: var(--muted); font-size: 13px; font-weight: 700; }}
    .settings-input {{
      width: 100%;
      min-width: 0;
      min-height: 40px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font-size: 15px;
      color: var(--ink);
      background: #fff;
    }}
    .settings-field.settings-password-field {{ min-width: 170px; }}
    .settings-message {{ align-self: center; min-width: 120px; min-height: 18px; font-size: 13px; }}
    .settings-message.ok {{ color: var(--accent); }}
    .settings-message.error {{ color: var(--danger); }}
    .portfolio-detail {{ margin-top: 12px; overflow-x: auto; }}
    .asset-panel {{ margin-top: 28px; margin-bottom: 56px; }}
    .asset-title {{ margin: 0 0 14px; font-size: 22px; line-height: 1.2; }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{ padding: 14px; }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ margin-top: 6px; font-size: 24px; font-weight: 800; }}
    section {{ margin-top: 16px; overflow: hidden; }}
    section h2 {{
      margin: 0;
      padding: 13px 14px;
      font-size: 17px;
      border-bottom: 1px solid var(--line);
    }}
    table {{ width: max-content; min-width: 100%; border-collapse: collapse; font-size: 14px; table-layout: auto; }}
    th, td {{ padding: 11px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 700; background: #fbfcfd; }}
    tr:last-child td {{ border-bottom: 0; }}
    .empty {{ padding: 18px 14px; color: var(--muted); }}
    .error {{ color: var(--danger); font-weight: 700; }}
    .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); }}
    .exec {{ color: var(--accent); }}
    .done {{ color: var(--muted); }}
    .watch {{ color: var(--warn); }}
    .spread-value {{ color: #2563eb; font-weight: 800; }}
    .profit-positive {{ color: var(--accent); }}
    .profit-negative {{ color: var(--danger); }}
    .wide-table th, .wide-table td {{ white-space: nowrap; }}
    .market-text {{ white-space: normal; overflow-wrap: break-word; word-break: normal; line-height: 1.35; }}
    .market-card {{ display: block; color: var(--ink); text-decoration: none; white-space: normal; overflow-wrap: break-word; }}
    a.market-card:hover .market-event {{ text-decoration: underline; }}
    .market-event {{ display: block; font-weight: 700; white-space: normal; overflow-wrap: break-word; }}
    .market-condition {{
      display: inline-block;
      margin-top: 6px;
      padding: 2px 8px;
      border: 1px solid #b9d9cf;
      border-radius: 999px;
      background: #f2fbf7;
      color: var(--accent);
      font-weight: 700;
    }}
    .time-cell {{ white-space: normal; line-height: 1.35; }}
    .time-date, .time-clock {{ display: block; white-space: nowrap; }}
    .table-scroll {{ max-height: 356px; overflow-y: auto; overflow-x: auto; }}
    .table-scroll thead th {{ position: sticky; top: 0; z-index: 1; }}
    .log-scroll {{ max-height: 356px; overflow-y: auto; overflow-x: auto; }}
    .monitored-pairs-scroll {{ max-height: 250px; overflow-y: auto; overflow-x: auto; }}
    .monitored-pair-table .condition-details {{ margin-top: 6px; }}
    .monitored-pair-table .condition-details summary {{ cursor: pointer; color: var(--accent); font-weight: 700; }}
    .monitored-pair-table .condition-tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
    .monitored-pair-table .condition-tag {{ display: inline-block; padding: 2px 8px; border: 1px solid var(--line); border-radius: 999px; background: #fbfcfd; color: var(--ink); font-weight: 700; }}
    .near-condition {{ margin-top: 6px; font-weight: 800; color: var(--accent); }}
    .log-table td:first-child {{ white-space: nowrap; color: var(--muted); }}
    .log-level {{ font-weight: 700; }}
    .log-ok {{ color: var(--accent); }}
    .log-error {{ color: var(--danger); }}
    @media (max-width: 760px) {{
      .wrap {{ width: 100%; padding: 0 12px; }}
      .top {{ align-items: flex-start; flex-direction: column; gap: 14px; min-height: auto; padding: 16px 0; }}
      h1 {{ font-size: 22px; }}
      p {{ font-size: 14px; line-height: 1.45; }}
      main {{ padding: 14px 0 24px; }}
      .toolbar {{ width: 100%; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
      .runtime-panel {{ grid-column: 1 / -1; width: 100%; min-width: 0; padding: 10px 12px; border-radius: 10px; }}
      .runtime-row {{ gap: 8px; }}
      button {{ width: 100%; min-height: 44px; border-radius: 10px; }}
      .settings-row {{ grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: stretch; }}
      .settings-title {{ grid-column: 1 / -1; }}
      .settings-field.settings-password-field {{ grid-column: 1 / -1; min-width: 0; }}
      #saveSettingsBtn {{ grid-column: 1 / -1; }}
      .settings-message {{ grid-column: 1 / -1; min-width: 0; }}
      .metrics, .portfolio-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
      .metric {{ min-width: 0; padding: 11px 10px; border-radius: 10px; }}
      .label {{ font-size: 12px; }}
      .value {{ font-size: 19px; overflow-wrap: anywhere; }}
      .asset-panel {{ margin-top: 22px; margin-bottom: 34px; }}
      .asset-title {{ font-size: 20px; margin-bottom: 10px; }}
      section {{ margin-top: 12px; border-radius: 12px; }}
      section h2 {{ padding: 12px; font-size: 16px; }}
      .table-scroll, .log-scroll {{ -webkit-overflow-scrolling: touch; }}
      th, td {{ padding: 9px 10px; font-size: 13px; }}
      .market-text {{ min-width: 220px; max-width: 280px; }}
    }}
    @media (max-width: 640px) {{
      .portfolio-detail {{ margin-top: 8px; overflow: visible; }}
      .table-scroll, .log-scroll {{ max-height: none; overflow: visible; }}
      .table-scroll thead th {{ position: static; }}
      .monitored-pairs-scroll {{ max-height: 250px; overflow-y: auto; overflow-x: auto; }}
      table {{ width: 100%; min-width: 0; font-size: 13px; }}
      table thead {{ display: none; }}
      table tbody, table tr, table td {{ display: block; width: 100%; }}
      table tr {{ margin: 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 12px; background: #fff; }}
      table td {{ display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 10px; align-items: start; padding: 7px 0; border-bottom: 1px dashed var(--line); text-align: right; overflow-wrap: anywhere; }}
      table td:last-child {{ border-bottom: 0; }}
      table td::before {{ color: var(--muted); content: ""; font-size: 12px; font-weight: 700; line-height: 1.35; text-align: left; }}
      .wide-table th, .wide-table td {{ white-space: normal; }}
      .market-text {{ min-width: 0; max-width: none; }}
      .market-card {{ text-align: right; }}
      .market-event {{ display: inline; }}
      .market-condition {{ margin-top: 4px; }}
      .time-date, .time-clock {{ display: inline; white-space: normal; }}
      .time-clock::before {{ content: " "; }}
      .portfolio-table td:nth-child(1)::before {{ content: "币种"; }}
      .portfolio-table td:nth-child(2)::before {{ content: "分配本金"; }}
      .portfolio-table td:nth-child(3)::before {{ content: "已用本金"; }}
      .portfolio-table td:nth-child(4)::before {{ content: "剩余本金"; }}
      .portfolio-table td:nth-child(5)::before {{ content: "收益"; }}
      .portfolio-table td:nth-child(6)::before {{ content: "收益率"; }}
      .portfolio-table td:nth-child(7)::before {{ content: "持仓数"; }}
      .monitored-pair-table td:nth-child(1)::before {{ content: "序号"; }}
      .monitored-pair-table td:nth-child(2)::before {{ content: "事件 / 实时条件"; }}
      .monitored-pair-table td:nth-child(3)::before {{ content: "到期日期"; }}
      .opportunity-table td:nth-child(1)::before {{ content: "ID"; }}
      .opportunity-table td:nth-child(2)::before {{ content: "状态"; }}
      .opportunity-table td:nth-child(3)::before {{ content: "价差"; }}
      .opportunity-table td:nth-child(4)::before {{ content: "保证利润"; }}
      .opportunity-table td:nth-child(5)::before {{ content: "YES 交易对"; }}
      .opportunity-table td:nth-child(6)::before {{ content: "YES 份额"; }}
      .opportunity-table td:nth-child(7)::before {{ content: "NO 交易对"; }}
      .opportunity-table td:nth-child(8)::before {{ content: "NO 份额"; }}
      .opportunity-table td:nth-child(9)::before {{ content: "时间"; }}
      .trade-table td:nth-child(1)::before {{ content: "ID"; }}
      .trade-table td:nth-child(2)::before {{ content: "价差"; }}
      .trade-table td:nth-child(3)::before {{ content: "预估收益"; }}
      .trade-table td:nth-child(4)::before {{ content: "结算时间"; }}
      .trade-table td:nth-child(5)::before {{ content: "交易币对"; }}
      .trade-table td:nth-child(6)::before {{ content: "YES 数量"; }}
      .trade-table td:nth-child(7)::before {{ content: "YES 价格"; }}
      .trade-table td:nth-child(8)::before {{ content: "YES 金额"; }}
      .trade-table td:nth-child(9)::before {{ content: "NO 数量"; }}
      .trade-table td:nth-child(10)::before {{ content: "NO 价格"; }}
      .trade-table td:nth-child(11)::before {{ content: "NO 金额"; }}
      .trade-table td:nth-child(12)::before {{ content: "成本"; }}
      .trade-table td:nth-child(13)::before {{ content: "时间"; }}
      .open-position-table td:nth-child(1)::before {{ content: "ID"; }}
      .open-position-table td:nth-child(2)::before {{ content: "币种"; }}
      .open-position-table td:nth-child(3)::before {{ content: "预估收益"; }}
      .open-position-table td:nth-child(4)::before {{ content: "价差"; }}
      .open-position-table td:nth-child(5)::before {{ content: "结算时间"; }}
      .open-position-table td:nth-child(6)::before {{ content: "交易币对"; }}
      .open-position-table td:nth-child(7)::before {{ content: "YES 数量"; }}
      .open-position-table td:nth-child(8)::before {{ content: "YES 价格"; }}
      .open-position-table td:nth-child(9)::before {{ content: "YES 金额"; }}
      .open-position-table td:nth-child(10)::before {{ content: "NO 数量"; }}
      .open-position-table td:nth-child(11)::before {{ content: "NO 价格"; }}
      .open-position-table td:nth-child(12)::before {{ content: "NO 金额"; }}
      .open-position-table td:nth-child(13)::before {{ content: "成本"; }}
      .open-position-table td:nth-child(14)::before {{ content: "最低赔付"; }}
      .open-position-table td:nth-child(15)::before {{ content: "开仓时间"; }}
      .settled-position-table td:nth-child(1)::before {{ content: "ID"; }}
      .settled-position-table td:nth-child(2)::before {{ content: "币种"; }}
      .settled-position-table td:nth-child(3)::before {{ content: "收益"; }}
      .settled-position-table td:nth-child(4)::before {{ content: "收益率"; }}
      .settled-position-table td:nth-child(5)::before {{ content: "价差"; }}
      .settled-position-table td:nth-child(6)::before {{ content: "结束时间"; }}
      .settled-position-table td:nth-child(7)::before {{ content: "交易币对"; }}
      .settled-position-table td:nth-child(8)::before {{ content: "YES 数量"; }}
      .settled-position-table td:nth-child(9)::before {{ content: "YES 价格"; }}
      .settled-position-table td:nth-child(10)::before {{ content: "YES 金额"; }}
      .settled-position-table td:nth-child(11)::before {{ content: "NO 数量"; }}
      .settled-position-table td:nth-child(12)::before {{ content: "NO 价格"; }}
      .settled-position-table td:nth-child(13)::before {{ content: "NO 金额"; }}
      .settled-position-table td:nth-child(14)::before {{ content: "成本"; }}
      .settled-position-table td:nth-child(15)::before {{ content: "最低赔付"; }}
      .settled-position-table td:nth-child(16)::before {{ content: "开仓时间"; }}
      .log-table td:nth-child(1)::before {{ content: "时间"; }}
      .log-table td:nth-child(2)::before {{ content: "资产"; }}
      .log-table td:nth-child(3)::before {{ content: "级别"; }}
      .log-table td:nth-child(4)::before {{ content: "事件"; }}
    }}
    @media (max-width: 420px) {{
      .metrics, .portfolio-grid {{ grid-template-columns: 1fr; }}
      .settings-row {{ grid-template-columns: 1fr; }}
      .toolbar {{ grid-template-columns: 1fr; }}
      table tr {{ margin: 8px; }}
      table td {{ grid-template-columns: 88px minmax(0, 1fr); }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap top">
      <div>
        <h1>Polymarket 套利模拟系统</h1>
        <p>只读 Polymarket BTC / ETH / XRP / SOL 行情，执行纸面模拟交易；不连接钱包，不真实下单。</p>
      </div>
      <div class="toolbar">
        <div class="runtime-panel" data-started-at="{started_at}">
          <div class="runtime-row">
            <span class="runtime-label">当前时间：</span>
            <span class="runtime-value" id="currentTimeValue">--</span>
          </div>
          <div class="runtime-row">
            <span class="runtime-label">运行时间：</span>
            <span class="runtime-value" id="runDurationValue">--</span>
          </div>
        </div>
        <button id="scanBtn">触发扫描</button>
        <button class="secondary" id="refreshBtn">刷新数据</button>
      </div>
    </div>
  </header>
  <main class="wrap">
    <div id="errorBox">{error_html}</div>
    {settings_html}
    <section>
      <h2>收益概览</h2>
      <div id="portfolioSummary">{portfolio["summary_html"]}</div>
    </section>
    <section>
      <h2>实时交易对</h2>
      <div id="monitoredPairs">{monitored_pairs_html}</div>
    </section>
    <section>
      <h2>模拟持仓</h2>
      <div id="positionTable">{portfolio["positions_html"]}</div>
    </section>
    <section>
      <h2>已结束持仓收益</h2>
      <div id="settledPositionTable">{portfolio["settled_positions_html"]}</div>
    </section>
    {asset_sections}
    <section>
      <h2>Polymarket 连接日志</h2>
      <div id="connectionLog">{_connection_log_html(panels)}</div>
    </section>
  </main>
  <script>
    function setText(id, value) {{
      document.getElementById(id).textContent = value;
    }}
    function formatCurrentTime(now) {{
      const parts = new Intl.DateTimeFormat('zh-CN', {{
        timeZone: 'Asia/Shanghai',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }}).formatToParts(now).reduce((values, part) => {{
        values[part.type] = part.value;
        return values;
      }}, {{}});
      const year = parts.year;
      const month = parts.month;
      const day = parts.day;
      const hour = parts.hour;
      const minute = parts.minute;
      const second = parts.second;
      return `${{year}}-${{month}}-${{day}} ${{hour}}:${{minute}}:${{second}}`;
    }}
    function formatRuntime(startedAt, now) {{
      const totalSeconds = Math.max(0, Math.floor((now.getTime() - startedAt.getTime()) / 1000));
      const days = Math.floor(totalSeconds / 86400);
      const hours = Math.floor((totalSeconds % 86400) / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      return `${{days}} 天 ${{hours}} 小时 ${{minutes}} 分钟`;
    }}
    function updateRuntimeClock() {{
      const panel = document.querySelector('.runtime-panel');
      const startedAt = new Date(panel.dataset.startedAt);
      const now = new Date();
      setText('currentTimeValue', formatCurrentTime(now));
      setText('runDurationValue', formatRuntime(startedAt, now));
    }}
    function updateHtmlPreservingScroll(containerId, html) {{
      const container = document.getElementById(containerId);
      if (!container) {{
        return;
      }}
      const scrollPositions = Array.from(container.querySelectorAll('.table-scroll, .log-scroll')).map((scroller) => ({{
        top: scroller.scrollTop,
        left: scroller.scrollLeft,
      }}));
      container.innerHTML = html;
      Array.from(container.querySelectorAll('.table-scroll, .log-scroll')).forEach((scroller, index) => {{
        const position = scrollPositions[index];
        if (!position) {{
          return;
        }}
        scroller.scrollTop = position.top;
        scroller.scrollLeft = position.left;
      }});
    }}
    async function refreshDashboard() {{
      const response = await fetch('/api/dashboard');
      const payload = await response.json();
      updateHtmlPreservingScroll('errorBox', payload.error_html);
      updateHtmlPreservingScroll('monitoredPairs', payload.monitored_pairs_html);
      updateHtmlPreservingScroll('portfolioSummary', payload.portfolio.summary_html);
      updateHtmlPreservingScroll('positionTable', payload.portfolio.positions_html);
      updateHtmlPreservingScroll('settledPositionTable', payload.portfolio.settled_positions_html);
      updateHtmlPreservingScroll('connectionLog', payload.connection_log_html);
      for (const asset of payload.assets) {{
        setText(asset.symbol + 'StatusValue', asset.status_text);
        setText(asset.symbol + 'MarketsValue', asset.status.markets);
        setText(asset.symbol + 'PairsValue', asset.status.pairs);
        setText(asset.symbol + 'OpportunitiesValue', asset.status.opportunities);
        updateHtmlPreservingScroll(asset.symbol + 'OpportunityTable', asset.opportunities_html);
        updateHtmlPreservingScroll(asset.symbol + 'TradeTable', asset.trades_html);
      }}
    }}
    async function triggerScan() {{
      const btn = document.getElementById('scanBtn');
      btn.disabled = true;
      btn.textContent = '扫描中';
      await fetch('/api/scan', {{ method: 'POST' }});
      setTimeout(async () => {{
        await refreshDashboard();
        btn.disabled = false;
        btn.textContent = '触发扫描';
      }}, 2000);
    }}
    async function saveSettings() {{
      const allocations = {{}};
      for (const symbol of ['BTC', 'ETH', 'XRP', 'SOL']) {{
        allocations[symbol] = Number(document.getElementById('alloc' + symbol).value || 0);
      }}
      const password = document.getElementById('settingsPassword').value;
      const button = document.getElementById('saveSettingsBtn');
      const message = document.getElementById('settingsMessage');
      button.disabled = true;
      button.textContent = '保存中';
      try {{
        const response = await fetch('/api/settings', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ allocations, password }}),
        }});
        const payload = await response.json();
        message.textContent = payload.message || (response.ok ? '已保存' : '保存失败');
        message.className = 'settings-message ' + (response.ok ? 'ok' : 'error');
        if (response.ok) {{
          document.getElementById('settingsPassword').value = '';
          await refreshDashboard();
        }}
      }} finally {{
        button.disabled = false;
        button.textContent = '保存设置';
      }}
    }}
    document.getElementById('scanBtn').addEventListener('click', triggerScan);
    document.getElementById('refreshBtn').addEventListener('click', refreshDashboard);
    document.getElementById('saveSettingsBtn').addEventListener('click', saveSettings);
    document.getElementById('settingsPassword').addEventListener('keydown', (event) => {{
      if (event.key === 'Enter') {{
        event.preventDefault();
        saveSettings();
      }}
    }});
    updateRuntimeClock();
    setInterval(updateRuntimeClock, 1000);
    setInterval(refreshDashboard, 5000);
  </script>
</body>
</html>"""


def _runtime_started_at(states: list[WebState]) -> datetime:
    if not states:
        return APP_STARTED_AT
    first_data_at = states[0].store.first_data_at()
    return first_data_at or APP_STARTED_AT


def dashboard_payload(states: Union[WebState, list[WebState]]) -> dict:
    panels = _as_states(states)
    id_map = _dashboard_id_map(panels)
    return {
        "error_html": _error_html(panels),
        "monitored_pairs_html": _monitored_event_groups_html(_monitored_event_groups(panels)),
        "portfolio": _portfolio_payload(panels, id_map),
        "settings": _settings_payload(panels),
        "assets": [_asset_payload(state, id_map) for state in panels],
        "connection_log_html": _connection_log_html(panels),
    }


def _as_states(states: Union[WebState, list[WebState]]) -> list[WebState]:
    return states if isinstance(states, list) else [states]


def save_allocation_settings(
    states: list[WebState],
    payload: dict,
) -> tuple[bool, str, dict, int]:
    if not states:
        return False, "暂无运行状态，设置未保存。", {}, HTTPStatus.BAD_REQUEST
    allocations = payload.get("allocations") if isinstance(payload, dict) else None
    password = payload.get("password") if isinstance(payload, dict) else None
    if not isinstance(allocations, dict) or not isinstance(password, str) or not password:
        return False, "请输入各币种百分比和确认密码。", {}, HTTPStatus.BAD_REQUEST
    raw_allocations = {str(key).upper(): value for key, value in allocations.items()}
    ratios = {}
    try:
        for asset in DEFAULT_ASSETS:
            if asset.symbol not in raw_allocations:
                return False, f"缺少 {asset.symbol} 分配比例。", {}, HTTPStatus.BAD_REQUEST
            percent = float(raw_allocations[asset.symbol])
            if percent < 0 or percent > 100:
                return False, "百分比必须在 0-100 之间。", {}, HTTPStatus.BAD_REQUEST
            ratios[asset.symbol] = percent / 100.0
    except (TypeError, ValueError):
        return False, "分配比例必须是有效数字。", {}, HTTPStatus.BAD_REQUEST
    if abs(sum(ratios.values()) - 1.0) > 0.0001:
        return False, "四个币种百分比之和必须为 100%。", {}, HTTPStatus.BAD_REQUEST
    store = states[0].store
    if not store.verify_settings_password(password):
        return False, "密码错误，设置未保存。", {}, HTTPStatus.UNAUTHORIZED
    store.save_allocation_ratios(ratios)
    _apply_allocation_ratios(states, ratios)
    percentages = {symbol: round(value * 100, 6) for symbol, value in ratios.items()}
    return True, "资金分配设置已保存。", percentages, HTTPStatus.OK


def _apply_allocation_ratios(states: list[WebState], ratios: dict) -> None:
    for state in states:
        new_config = replace(state.config, allocation_ratios=dict(ratios))
        state.config = new_config
        if state.runner is not None:
            state.runner.config = new_config


def _allocation_ratio(state: WebState) -> float:
    ratios = state.config.allocation_ratios or {}
    try:
        return float(ratios.get(state.asset.symbol, state.asset.allocation_ratio))
    except (TypeError, ValueError):
        return state.asset.allocation_ratio


def _allocation_ratios(states: list[WebState]) -> dict:
    if not states:
        return {}
    ratios = states[0].config.allocation_ratios or {}
    return {
        asset.symbol: ratios.get(asset.symbol, asset.allocation_ratio)
        for asset in DEFAULT_ASSETS
    }


def _settings_payload(states: list[WebState]) -> dict:
    return {"allocation_ratios": _allocation_ratios(states)}


def _settings_html(states: list[WebState]) -> str:
    if not states:
        return ""
    ratios = _allocation_ratios(states)
    fields = []
    for asset in DEFAULT_ASSETS:
        percent = ratios.get(asset.symbol, asset.allocation_ratio) * 100
        fields.append(
            "<div class='settings-field'>"
            f"<label for=\"alloc{escape(asset.symbol)}\">{escape(asset.symbol)}</label>"
            f"<input class='settings-input' id=\"alloc{escape(asset.symbol)}\" type='number' min='0' max='100' step='0.1' value='{escape(f'{percent:g}')}'>"
            "</div>"
        )
    password_field = (
        "<div class='settings-field settings-password-field'>"
        "<label for=\"settingsPassword\">确认密码</label>"
        "<input class='settings-input' id=\"settingsPassword\" type='password' autocomplete='off' placeholder='请输入密码'>"
        "</div>"
    )
    return (
        "<div class='settings-row' id=\"allocationSettings\">"
        "<span class='settings-title'>资金分配</span>"
        + "".join(fields)
        + password_field
        + "<button class='secondary' id=\"saveSettingsBtn\" type='button'>保存设置</button>"
        + "<span class='settings-message' id=\"settingsMessage\"></span>"
        + "</div>"
    )


def _dashboard_id_map(states: list[WebState]) -> dict[str, int]:
    if not states:
        return {}
    store = states[0].store
    rows = []
    for row in store.latest_opportunities(10000):
        rows.append(row)
    for row in store.latest_trades(10000):
        rows.append(row)
    sortable = []
    seen_keys = set()
    for row in rows:
        key = _dashboard_row_key(row)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        sortable.append((_dashboard_row_time(row), key))
    sortable.sort(key=lambda item: (item[0], item[1]))
    return {key: index for index, (_time, key) in enumerate(sortable, start=1)}


def _dashboard_row_key(row: dict) -> str:
    pair_key = str(row.get("pair_key") or "")
    detected_at = str(row.get("detected_at") or "")
    if pair_key or detected_at:
        return f"{pair_key}|{detected_at}"
    row_id = str(row.get("id") or "")
    return f"id:{row_id}" if row_id else ""


def _dashboard_row_time(row: dict) -> datetime:
    return _parse_time_value(row.get("detected_at")) or datetime.min.replace(tzinfo=timezone.utc)


def _dashboard_id(row: dict, id_map: dict[str, int]) -> str:
    value = id_map.get(_dashboard_row_key(row))
    return escape(str(value)) if value is not None else "-"


def _scroll_table(table_html: str) -> str:
    return f"<div class='table-scroll'>{table_html}</div>"


def _monitored_event_groups(states: list[WebState]) -> list[MonitoredEventGroup]:
    groups = {}
    books = {}
    for state in states:
        markets, state_books = _latest_markets_and_books(state)
        books.update(state_books)
        for market in markets:
            slug = market.event_slug or market.slug or market.id
            group = groups.setdefault(slug, {"markets": [], "conditions": set(), "end_at": None})
            group["markets"].append(market)
            group["conditions"].add(_market_condition_text(market))
            parsed_end = _parse_time_value(market.end_date)
            if parsed_end is not None and (group["end_at"] is None or parsed_end > group["end_at"]):
                group["end_at"] = parsed_end

    result = []
    for slug, group in groups.items():
        conditions = sorted(group["conditions"])
        near_condition = _near_condition(group["markets"], books)
        if near_condition not in conditions:
            conditions.insert(0, near_condition)
        result.append(
            MonitoredEventGroup(
                event_slug=slug,
                title=_event_title(group["markets"][0].question),
                end_at=group["end_at"] or datetime.max.replace(tzinfo=timezone.utc),
                near_condition=near_condition,
                conditions=conditions,
            )
        )
    result.sort(key=lambda item: item.end_at)
    return result


def _latest_markets_and_books(state: WebState) -> tuple[list, dict]:
    with state.lock:
        result = state.latest_result
        markets = list(result.markets) if result else []
        books = dict(result.books) if result else {}
    if not markets and isinstance(state.runner, RealtimePaperRunner):
        markets = list(state.runner.markets)
        books = dict(state.runner.books)
    return markets, books


def _live_markets(states: list[WebState]) -> list[dict]:
    rows = []
    seen = set()
    for state in states:
        markets, _books = _latest_markets_and_books(state)
        for market in markets:
            for token_id, outcome in ((market.yes_token_id, "YES"), (market.no_token_id, "NO")):
                if not token_id or token_id in seen:
                    continue
                seen.add(token_id)
                rows.append(
                    {
                        "token_id": token_id,
                        "asset": state.asset.symbol,
                        "question": market.question,
                        "outcome": outcome,
                        "slug": market.slug,
                        "event_slug": market.event_slug,
                    }
                )
    rows.sort(key=lambda row: (str(row["question"]), str(row["outcome"])))
    return rows[:500]


def _market_condition_text(market) -> str:
    return _condition_label(market.question) or "Up or Down"


def _near_condition(markets, books) -> str:
    best = None
    for market in markets:
        book = books.get(market.yes_token_id)
        score = None
        if book is not None:
            prices = []
            if book.best_ask is not None:
                prices.append(book.best_ask)
            if book.best_bid is not None:
                prices.append(book.best_bid)
            if prices:
                score = abs(sum(prices) / len(prices) - 0.5)
        if score is not None and (best is None or score < best[0]):
            best = (score, _market_condition_text(market))
    if best is not None:
        return best[1]
    top = max(markets, key=lambda market: market.volume_24h)
    return _market_condition_text(top)


def _monitored_event_groups_html(groups: list[MonitoredEventGroup]) -> str:
    if not groups:
        return "<div class='empty'>暂无交易对，等待首次扫描或行情源恢复。</div>"
    rows = []
    for index, group in enumerate(groups, start=1):
        other_conditions = [item for item in group.conditions if item != group.near_condition]
        details = ""
        if other_conditions:
            tags = "".join(f"<span class='condition-tag'>{escape(item)}</span>" for item in other_conditions)
            details = (
                "<details class='condition-details'>"
                f"<summary>其他 {len(other_conditions)} 个条件</summary>"
                f"<div class='condition-tags'>{tags}</div>"
                "</details>"
            )
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td class='market-text'>{_market_link(group.title, group.event_slug)}"
            f"<div class='near-condition'>{escape(group.near_condition)}</div>{details}</td>"
            f"<td class='time-cell'>{_time_html(_format_time_value(group.end_at))}</td>"
            "</tr>"
        )
    return (
        "<div class='table-scroll monitored-pairs-scroll'>"
        "<table class='monitored-pair-table'>"
        "<thead><tr><th>序号</th><th>事件 / 实时条件</th><th>到期日期</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _portfolio_payload(states: list[WebState], id_map: dict[str, int]) -> dict:
    if not states:
        return {
            "summary_html": "<div class='empty'>暂无资产配置。</div>",
            "positions_html": "<div class='empty'>暂无持仓。</div>",
            "settled_positions_html": "<div class='empty'>暂无已结束持仓。</div>",
        }
    store = states[0].store
    positions = store.latest_positions(100)
    settled_trades = store.latest_settled_trades(100)
    asset_summaries = []
    total_cost = 0.0
    total_profit = 0.0
    for state in states:
        rows = _filter_rows_by_asset(positions, state.asset)
        settled_rows = _filter_rows_by_asset(settled_trades, state.asset)
        cost = _sum_float(rows, "total_cost")
        profit = _sum_float(settled_rows, "guaranteed_profit")
        allocation = state.config.initial_capital_usdt * _allocation_ratio(state)
        asset_summaries.append(
            {
                "symbol": state.asset.symbol,
                "allocation": allocation,
                "used": cost,
                "available": allocation - cost,
                "profit": profit,
                "return_rate": _rate(profit, allocation),
                "positions": len(rows),
            }
        )
        total_cost += cost
        total_profit += profit
    total_capital = states[0].config.initial_capital_usdt
    summary = {
        "initial_capital": total_capital,
        "used": total_cost,
        "available": total_capital - total_cost,
        "profit": total_profit,
        "return_rate": _rate(total_profit, total_capital),
        "assets": asset_summaries,
    }
    return {
        "summary": summary,
        "summary_html": _portfolio_summary_html(summary),
        "positions_html": _position_table(positions, states, id_map),
        "settled_positions_html": _settled_position_table(settled_trades, states, id_map),
    }


def _portfolio_summary_html(summary: dict) -> str:
    metrics = (
        "<div class='portfolio-grid'>"
        f"{_metric('初始本金', _money(summary['initial_capital']), 'initialCapitalValue')}"
        f"{_metric('已用本金', _money(summary['used']), 'usedCapitalValue')}"
        f"{_metric('累计收益', _signed_money(summary['profit']), 'profitValue', _profit_class(summary['profit']))}"
        f"{_metric('收益率', _percent(summary['return_rate']), 'returnRateValue', _profit_class(summary['return_rate']))}"
        "</div>"
    )
    body = []
    for asset in summary["assets"]:
        body.append(
            "<tr>"
            f"<td>{escape(str(asset['symbol']))}</td>"
            f"<td>{_money(asset['allocation'])}</td>"
            f"<td>{_money(asset['used'])}</td>"
            f"<td>{_money(asset['available'])}</td>"
            f"<td>{_profit_text(_signed_money(asset['profit']), asset['profit'])}</td>"
            f"<td>{_profit_text(_percent(asset['return_rate']), asset['return_rate'])}</td>"
            f"<td>{escape(str(asset['positions']))}</td>"
            "</tr>"
        )
    detail = (
        "<div class='portfolio-detail table-scroll'><table class='portfolio-table'><thead><tr>"
        "<th>币种</th><th>分配本金</th><th>已用本金</th><th>剩余本金</th>"
        "<th>收益</th><th>收益率</th><th>持仓数</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )
    return metrics + detail


def _position_table(rows: list, states: list[WebState], id_map: dict[str, int]) -> str:
    if not rows:
        return "<div class='empty'>暂无持仓。</div>"
    return _position_table_html(rows, states, id_map)


def _position_table_html(rows: list, states: list[WebState], id_map: dict[str, int]) -> str:
    body = []
    for row in rows:
        asset = _asset_symbol_for_row(row, states)
        body.append(
            "<tr>"
            f"<td>{_dashboard_id(row, id_map)}</td>"
            f"<td>{escape(asset)}</td>"
            f"<td>{_profit_text(_signed_money(row.get('guaranteed_profit', 0)), row.get('guaranteed_profit', 0))}</td>"
            f"<td>{_spread(row)}</td>"
            f"<td class='time-cell'>{_time_html(_settlement_time(row))}</td>"
            f"<td class='market-text'>{_market_link(row.get('yes_question', ''), row.get('yes_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('yes_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'yes_avg_price'))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('no_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'no_avg_price'))}</td>"
            f"<td>{_money(row.get('total_cost', 0))}</td>"
            f"<td>{_money(row.get('min_payout', 0))}</td>"
            f"<td class='time-cell'>{_time_html(_format_time_value(row.get('detected_at', '')))}</td>"
            "</tr>"
        )
    return _scroll_table(
        "<table class='trade-table wide-table position-table open-position-table'>"
        "<colgroup><col class='id-col'><col class='asset-col'><col class='profit-col'><col class='spread-col'><col class='time-col'><col class='market-col'><col class='qty-col'><col class='price-col'><col class='amount-col'>"
        "<col class='qty-col'><col class='price-col'><col class='amount-col'><col class='money-col'>"
        "<col class='money-col'><col class='time-col'></colgroup>"
        "<thead><tr><th>ID</th><th>币种</th><th>预估收益</th><th>价差</th><th>结算时间UTC+8</th><th>交易币对</th><th>YES 数量</th><th>YES 价格</th><th>YES 金额</th>"
        "<th>NO 数量</th><th>NO 价格</th><th>NO 金额</th><th>成本</th><th>最低赔付</th><th>开仓时间</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _settled_position_table(rows: list, states: list[WebState], id_map: dict[str, int]) -> str:
    if not rows:
        return "<div class='empty'>暂无已结束持仓。</div>"
    return _settled_position_table_html(rows, states, id_map)


def _settled_position_table_html(rows: list, states: list[WebState], id_map: dict[str, int]) -> str:
    body = []
    for row in rows:
        asset = _asset_symbol_for_row(row, states)
        profit = row.get("guaranteed_profit", 0)
        total_cost = row.get("total_cost", 0)
        profit_value = _to_float(profit)
        total_cost_value = _to_float(total_cost)
        return_rate = _rate(profit_value, total_cost_value)
        body.append(
            "<tr>"
            f"<td>{_dashboard_id(row, id_map)}</td>"
            f"<td>{escape(asset)}</td>"
            f"<td>{_profit_text(_signed_money(profit), profit)}</td>"
            f"<td>{_profit_text(_percent(return_rate), return_rate)}</td>"
            f"<td>{_spread(row)}</td>"
            f"<td class='time-cell'>{_time_html(_settlement_time(row))}</td>"
            f"<td class='market-text'>{_market_link(row.get('yes_question', ''), row.get('yes_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('yes_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'yes_avg_price'))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('no_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'no_avg_price'))}</td>"
            f"<td>{_money(total_cost)}</td>"
            f"<td>{_money(row.get('min_payout', 0))}</td>"
            f"<td class='time-cell'>{_time_html(_format_time_value(row.get('detected_at', '')))}</td>"
            "</tr>"
        )
    return _scroll_table(
        "<table class='trade-table wide-table position-table settled-position-table'>"
        "<colgroup><col class='id-col'><col class='asset-col'><col class='profit-col'><col class='profit-col'><col class='spread-col'><col class='time-col'><col class='market-col'><col class='qty-col'><col class='price-col'><col class='amount-col'>"
        "<col class='qty-col'><col class='price-col'><col class='amount-col'><col class='money-col'>"
        "<col class='money-col'><col class='time-col'></colgroup>"
        "<thead><tr><th>ID</th><th>币种</th><th>收益</th><th>收益率</th><th>价差</th><th>结束时间UTC+8</th><th>交易币对</th><th>YES 数量</th><th>YES 价格</th><th>YES 金额</th>"
        "<th>NO 数量</th><th>NO 价格</th><th>NO 金额</th><th>成本</th><th>最低赔付</th><th>开仓时间</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _asset_symbol_for_row(row: dict, states: list[WebState]) -> str:
    for state in states:
        needle = state.asset.title_name.lower()
        yes_question = str(row.get("yes_question", "")).lower()
        no_question = str(row.get("no_question", "")).lower()
        if needle in yes_question or needle in no_question:
            return state.asset.symbol
    return "-"


def _market_link(text: object, event_slug: object) -> str:
    question = str(text or "")
    label = escape(question)
    event_title = _event_title(question)
    condition = _condition_label(question)
    slug = str(event_slug or "").strip() or _infer_event_slug(question)
    if event_title or condition:
        parts = []
        if event_title:
            parts.append(f"<span class='market-event'>{escape(event_title)}</span>")
        if condition:
            parts.append(f"<span class='market-condition'>条件：{escape(condition)}</span>")
        label = "".join(parts)
    if not slug:
        return f"<span class='market-card'>{label}</span>"
    href = f"https://polymarket.com/event/{slug}"
    return f"<a class='market-card' href='{escape(href)}' target='_blank' rel='noopener noreferrer'>{label}</a>"


def _event_title(question: str) -> str:
    parsed = _parse_market_question(question)
    if parsed is None:
        return question
    asset, direction, _threshold, period = parsed
    if direction in {"above", "below", "range"}:
        return f"What price will {asset} be on {period}?"
    return f"What price will {asset} hit {period}?"


def _condition_label(question: str) -> str:
    parsed = _parse_market_question(question)
    if parsed is None:
        return ""
    _asset, direction, threshold, _period = parsed
    if direction == "range":
        return threshold
    arrow = "↓" if direction in {"dip", "below"} else "↑"
    return f"{arrow} {threshold}"


def _infer_event_slug(question: str) -> str:
    title = _event_title(question)
    if not title or title == question:
        return ""
    slug = title.lower().replace("?", "")
    slug = re.sub(r"[$,]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    if re.search(r"\b\d{1,2}-\d{1,2}\b", title):
        slug = f"{slug}-2026"
    return slug


def _parse_market_question(question: str) -> Optional[tuple[str, str, str, str]]:
    match = re.search(
        r"Will the price of ([A-Za-z]+) be (above|below|greater than|less than) "
        r"\$([0-9][0-9,]*(?:\.[0-9]+)?k?) on (.+)\?",
        question,
        re.IGNORECASE,
    )
    if match:
        asset, direction, threshold, period = match.groups()
        direction = "above" if direction in {"above", "greater than"} else "below"
        return asset, direction, threshold, period

    match = re.search(
        r"Will the price of ([A-Za-z]+) be between \$([0-9][0-9,]*(?:\.[0-9]+)?k?) "
        r"and \$([0-9][0-9,]*(?:\.[0-9]+)?k?) on (.+)\?",
        question,
        re.IGNORECASE,
    )
    if match:
        asset, low, high, period = match.groups()
        return asset, "range", f"{low}-{high}", period

    match = re.search(
        r"Will ([A-Za-z]+) (dip to|reach|hit) \$([0-9][0-9,]*(?:\.[0-9]+)?k?) (.+)\?",
        question,
        re.IGNORECASE,
    )
    if not match:
        return None
    asset, verb, threshold, period = match.groups()
    direction = "dip" if verb.lower() == "dip to" else "hit"
    if period.startswith("in "):
        period_text = period
    else:
        period_text = period
    return asset, direction, threshold, period_text


def _asset_section(state: WebState, id_map: dict[str, int]) -> str:
    payload = _asset_payload(state, id_map)
    symbol = state.asset.symbol
    return f"""
    <div class="asset-panel" id="{escape(symbol)}Panel">
      <h2 class="asset-title">{escape(symbol)} 套利模拟</h2>
      <div class="metrics">
        {_metric("状态", payload["status_text"], f"{symbol}StatusValue")}
        {_metric("市场", payload["status"]["markets"], f"{symbol}MarketsValue")}
        {_metric("交易对", payload["status"]["pairs"], f"{symbol}PairsValue")}
        {_metric("机会", payload["status"]["opportunities"], f"{symbol}OpportunitiesValue")}
      </div>
      <section>
        <h2>最近套利机会</h2>
        <div id="{escape(symbol)}OpportunityTable">{payload["opportunities_html"]}</div>
      </section>
      <section>
        <h2>模拟成交</h2>
        <div id="{escape(symbol)}TradeTable">{payload["trades_html"]}</div>
      </section>
    </div>"""


def _asset_payload(state: WebState, id_map: dict[str, int]) -> dict:
    snapshot = state.snapshot()
    opportunities = _filter_rows_by_asset(state.store.latest_opportunities(100), state.asset)
    trades = _filter_rows_by_asset(state.store.latest_trades(100), state.asset)
    opportunities = _mark_executed_opportunities(opportunities, trades, state.config.cooldown_seconds)
    return {
        "symbol": state.asset.symbol,
        "status": snapshot,
        "status_text": status_label(snapshot),
        "opportunities_html": _opportunity_table(opportunities, id_map),
        "trades_html": _trade_table(trades, id_map),
    }


def _filter_rows_by_asset(rows: list, asset: AssetSpec) -> list:
    needle = asset.title_name.lower()
    filtered = []
    for row in rows:
        yes_question = str(row.get("yes_question", "")).lower()
        no_question = str(row.get("no_question", "")).lower()
        if needle in yes_question or needle in no_question:
            filtered.append(row)
    return filtered


def _mark_executed_opportunities(
    opportunities: list,
    trades: list,
    cooldown_seconds: int,
) -> list:
    executed_rows = {_opportunity_execution_key(row): row for row in trades}
    marked = []
    for row in opportunities:
        item = dict(row)
        key = _opportunity_execution_key(item)
        if key in executed_rows:
            item["_execution_type"] = "paper"
            item.update(_execution_display_values(executed_rows[key]))
        else:
            cooldown_match = _cooldown_execution_match(item, trades, cooldown_seconds)
            if cooldown_match is not None:
                item["_execution_type"] = "cooldown"
                item["_cooldown_seconds_remaining"] = cooldown_match
            else:
                item["_execution_type"] = ""
        marked.append(item)
    return marked


def _execution_display_values(row: dict) -> dict:
    keys = (
        "guaranteed_profit",
        "shares",
        "yes_avg_price",
        "no_avg_price",
        "total_cost",
        "min_payout",
    )
    return {key: row.get(key) for key in keys if key in row}


def _cooldown_execution_match(opportunity: dict, executions: list, cooldown_seconds: int) -> Optional[int]:
    opportunity_pair = str(opportunity.get("pair_key") or "")
    opportunity_time = _parse_time_value(opportunity.get("detected_at"))
    if not opportunity_pair or opportunity_time is None or cooldown_seconds <= 0:
        return None
    closest_delta = None
    for execution in executions:
        if str(execution.get("pair_key") or "") != opportunity_pair:
            continue
        execution_time = _parse_time_value(execution.get("detected_at"))
        if execution_time is None:
            continue
        delta = (opportunity_time - execution_time).total_seconds()
        if delta < 0 or delta >= cooldown_seconds:
            continue
        if closest_delta is None or delta < closest_delta:
            closest_delta = delta
    if closest_delta is None:
        return None
    return max(1, int(cooldown_seconds - closest_delta))


def _opportunity_execution_key(row: dict) -> tuple[str, str]:
    return (str(row.get("pair_key") or ""), str(row.get("detected_at") or ""))


def _error_html(states: list[WebState]) -> str:
    errors = []
    for state in states:
        snapshot = state.snapshot()
        if snapshot["error"]:
            errors.append(f"<p class='error'>{escape(state.asset.symbol)}: {escape(_friendly_error(snapshot['error']))}</p>")
    return "".join(errors)


def _connection_log_html(states: list[WebState]) -> str:
    logs = []
    for state in states:
        for entry in state.snapshot()["connection_logs"]:
            logs.append(entry)
    if not logs:
        return "<div class='empty'>暂无连接日志。</div>"
    logs.sort(key=lambda entry: entry["time"], reverse=True)
    rows = []
    for entry in logs[:40]:
        level = str(entry.get("level") or "info")
        rows.append(
            "<tr>"
            f"<td>{escape(format_standard_time(entry['time']))}</td>"
            f"<td>{escape(str(entry.get('asset') or '-'))}</td>"
            f"<td><span class='log-level log-{escape(level)}'>{escape(_log_level_label(level))}</span></td>"
            f"<td>{escape(_friendly_error(str(entry.get('message') or '')))}</td>"
            "</tr>"
        )
    return (
        "<div class='log-scroll'><table class='log-table'><thead><tr><th>时间</th><th>资产</th><th>级别</th><th>事件</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _log_level_label(level: str) -> str:
    if level == "ok":
        return "正常"
    if level == "error":
        return "错误"
    return "信息"


def _friendly_error(error: str) -> str:
    if "Network is unreachable" in error and "gamma-api.polymarket.com" in error:
        return "行情源连接失败：服务器无法访问 Polymarket Gamma API（Network is unreachable）。"
    if "Network is unreachable" in error:
        return "网络连接失败：服务器出站网络不可达。"
    if "gamma-api.polymarket.com" in error:
        return "行情源连接失败：Polymarket Gamma API 请求失败。"
    return error


def status_label(snapshot: dict) -> str:
    if snapshot["running"] and snapshot["realtime"]:
        return "实时监听中"
    if snapshot["running"]:
        return "扫描中"
    if snapshot["error"]:
        return "监听异常"
    return "未启动"


def _metric(label: str, value: object, element_id: str, value_class: str = "") -> str:
    classes = "value"
    if value_class:
        classes += f" {value_class}"
    return (
        f"<div class='metric'><div class='label'>{escape(label)}</div>"
        f"<div class='{escape(classes)}' id='{escape(element_id)}'>{escape(str(value))}</div></div>"
    )


def _sum_float(rows: list, key: str) -> float:
    total = 0.0
    for row in rows:
        try:
            total += float(row.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _to_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _rate(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _money(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:,.2f}"


def _signed_money(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    sign = "+" if number >= 0 else "-"
    return f"{sign}{abs(number):,.2f}"


def _profit_text(text: str, value: object) -> str:
    return f"<span class='{_profit_class(value)}'>{escape(text)}</span>"


def _profit_class(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return "profit-negative" if number < 0 else "profit-positive"


def _percent(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number * 100:.2f}%"


def _number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:,.2f}"


def _price(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number * 100:.2f}¢"


def _spread(row: dict) -> str:
    return f"<span class='spread-value'>{_spread_cents(row):.2f}¢</span>"


def _spread_cents(row: dict) -> float:
    try:
        yes_price = float(row.get("yes_avg_price") or 0)
        no_price = float(row.get("no_avg_price") or 0)
    except (TypeError, ValueError):
        yes_price = 0.0
        no_price = 0.0
    return round((1 - yes_price - no_price) * 100, 10)


def _leg_amount(row: dict, price_key: str) -> float:
    try:
        shares = float(row.get("shares") or 0)
        price = float(row.get(price_key) or 0)
    except (TypeError, ValueError):
        return 0.0
    return shares * price


def format_standard_time(value: datetime) -> str:
    return value.astimezone(DISPLAY_TZ).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _format_time_value(value: object) -> str:
    if isinstance(value, datetime):
        return format_standard_time(value)
    text = str(value or "")
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return format_standard_time(parsed)


def _time_html(value: str) -> str:
    date, separator, clock = str(value or "").partition(" ")
    if not separator:
        return escape(date)
    return f"<span class='time-date'>{escape(date)}</span><span class='time-clock'>{escape(clock)}</span>"


def _settlement_time(row: dict) -> str:
    dates = [_parse_time_value(row.get("yes_end_date")), _parse_time_value(row.get("no_end_date"))]
    known_dates = [value for value in dates if value is not None]
    if not known_dates:
        return "-"
    return format_standard_time(max(known_dates))


def _parse_time_value(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "")
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _opportunity_table(rows: list, id_map: dict[str, int]) -> str:
    if not rows:
        return "<div class='empty'>暂无记录。系统只会在发现正收益组合时写入机会。</div>"
    body = []
    for row in rows:
        cls, state = _opportunity_state(row)
        detail = _opportunity_status_detail(row)
        body.append(
            "<tr>"
            f"<td>{_dashboard_id(row, id_map)}</td>"
            f"<td><span class='pill {cls}'>{state}</span>{detail}</td>"
            f"<td>{_spread(row)}</td>"
            f"<td>{escape(_money(row.get('guaranteed_profit', 0)))}</td>"
            f"<td class='market-text'>{_market_link(row.get('yes_question', ''), row.get('yes_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td class='market-text'>{_market_link(row.get('no_question', ''), row.get('no_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td class='time-cell'>{_time_html(_format_time_value(row.get('detected_at', '')))}</td>"
            "</tr>"
        )
    return _scroll_table(
        "<table class='opportunity-table'><thead><tr><th>ID</th><th>状态</th><th>价差</th><th>保证利润</th><th>YES 交易对</th><th>YES 份额</th>"
        "<th>NO 交易对</th><th>NO 份额</th><th>时间</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _opportunity_state(row: dict) -> tuple[str, str]:
    if row.get("_execution_type") == "paper":
        return "done", "已成交"
    if row.get("_execution_type") == "cooldown":
        return "watch", "冷却中"
    if _spread_cents(row) <= MIN_SPREAD_TO_OPEN_CENTS:
        return "watch", "仅观察"
    if row.get("executable"):
        return "exec", "可模拟成交"
    return "watch", "仅观察"


def _opportunity_status_detail(row: dict) -> str:
    if row.get("_execution_type") == "cooldown":
        seconds = row.get("_cooldown_seconds_remaining")
        if seconds:
            return f"<div class='label'>同交易对冷却中，约 {escape(str(seconds))} 秒后才允许再次成交</div>"
        return "<div class='label'>同交易对冷却中，未写入成交</div>"
    reason = str(row.get("reason") or "")
    if not reason or reason == "executable":
        return ""
    return f"<div class='label'>{escape(_reason_label(reason))}</div>"


def _reason_label(reason: str) -> str:
    if reason.startswith("24h volume below"):
        return "24 小时成交额不足"
    if reason.startswith("arbitrage depth below"):
        return "可成交深度不足"
    return reason


def _trade_table(rows: list, id_map: dict[str, int], empty_text: str = "暂无成交。") -> str:
    if not rows:
        return f"<div class='empty'>{escape(empty_text)}</div>"
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{_dashboard_id(row, id_map)}</td>"
            f"<td>{_spread(row)}</td>"
            f"<td>{_profit_text(_signed_money(row.get('guaranteed_profit', 0)), row.get('guaranteed_profit', 0))}</td>"
            f"<td class='time-cell'>{_time_html(_settlement_time(row))}</td>"
            f"<td class='market-text'>{_market_link(row.get('yes_question', ''), row.get('yes_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('yes_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'yes_avg_price'))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('no_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'no_avg_price'))}</td>"
            f"<td>{_money(row.get('total_cost', 0))}</td>"
            f"<td class='time-cell'>{_time_html(_format_time_value(row.get('detected_at', '')))}</td>"
            "</tr>"
        )
    return _scroll_table(
        "<table class='trade-table wide-table'>"
        "<colgroup><col class='id-col'><col class='spread-col'><col class='profit-col'><col class='time-col'><col class='market-col'><col class='qty-col'><col class='price-col'><col class='amount-col'>"
        "<col class='qty-col'><col class='price-col'><col class='amount-col'><col class='money-col'>"
        "<col class='time-col'></colgroup>"
        "<thead><tr><th>ID</th><th>价差</th><th>预估收益</th><th>结算时间UTC+8</th><th>交易币对</th><th>YES 数量</th><th>YES 价格</th><th>YES 金额</th>"
        "<th>NO 数量</th><th>NO 价格</th><th>NO 金额</th><th>成本</th><th>时间</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )
