from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from zoneinfo import ZoneInfo

from .config import Config
from .runner import PaperRunner, RealtimePaperRunner, ScanResult
from .store import PaperStore

DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class WebState:
    config: Config
    store: PaperStore
    runner: PaperRunner
    latest_result: Optional[ScanResult] = None
    latest_error: Optional[str] = None
    running: bool = False
    realtime: bool = False
    last_event_at: Optional[datetime] = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def run_scan(self) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
        try:
            result = self.runner.run_iteration()
            with self.lock:
                self.latest_result = result
                self.latest_error = None
        except Exception as exc:
            with self.lock:
                self.latest_error = str(exc)
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
        realtime_runner = RealtimePaperRunner(self.config)
        self.runner = realtime_runner
        try:
            asyncio.run(
                realtime_runner.run_forever(
                    on_result=self.update_result,
                    on_event=self.update_event,
                )
            )
        except Exception as exc:
            with self.lock:
                self.latest_error = str(exc)
                self.realtime = False
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

    def snapshot(self) -> dict:
        with self.lock:
            result = self.latest_result
            error = self.latest_error
            running = self.running
            realtime = self.realtime
            last_event_at = self.last_event_at
        return {
            "running": running,
            "realtime": realtime,
            "error": error,
            "markets": len(result.markets) if result else 0,
            "pairs": result.pairs if result else 0,
            "opportunities": len(result.opportunities) if result else 0,
            "scanned_at": format_standard_time(result.scanned_at) if result else None,
            "last_event_at": format_standard_time(last_event_at) if last_event_at else None,
        }


def serve(config: Config, host: str = "127.0.0.1", port: int = 8787, auto_scan: bool = True) -> None:
    store = PaperStore(config.database_path)
    store.initialize()
    runner = PaperRunner(config)
    state = WebState(config=config, store=store, runner=runner)
    if auto_scan:
        _start_realtime_loop(state)

    class Handler(PolyarbHandler):
        web_state = state

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Polyarb Web 已启动: http://{host}:{port}")
    server.serve_forever()


def _start_realtime_loop(state: WebState) -> None:
    thread = threading.Thread(target=state.run_realtime, name="polyarb-realtime-scanner", daemon=True)
    thread.start()


class PolyarbHandler(BaseHTTPRequestHandler):
    web_state: WebState

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._html(render_dashboard(self.web_state))
            return
        if self.path == "/api/status":
            self._json(self.web_state.snapshot())
            return
        if self.path == "/api/report":
            self._json(
                {
                    "status": self.web_state.snapshot(),
                    "trades": self.web_state.store.latest_trades(20),
                    "opportunities": self.web_state.store.latest_opportunities(20),
                }
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/scan":
            thread = threading.Thread(target=self.web_state.run_scan, name="polyarb-manual-scan", daemon=True)
            thread.start()
            self._json({"ok": True, "message": "扫描已触发"})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(HTTPStatus.OK)
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


def render_dashboard(state: WebState) -> str:
    snapshot = state.snapshot()
    trades = state.store.latest_trades(10)
    opportunities = state.store.latest_opportunities(10)
    if snapshot["running"] and snapshot["realtime"]:
        status_text = "实时监听中"
    elif snapshot["running"]:
        status_text = "扫描中"
    elif snapshot["error"]:
        status_text = "监听异常"
    else:
        status_text = "未启动"
    error_html = f"<p class='error'>{escape(snapshot['error'])}</p>" if snapshot["error"] else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Polyarb BTC 套利模拟系统</title>
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
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 11px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 700; background: #fbfcfd; }}
    tr:last-child td {{ border-bottom: 0; }}
    .empty {{ padding: 18px 14px; color: var(--muted); }}
    .error {{ color: var(--danger); font-weight: 700; }}
    .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); }}
    .exec {{ color: var(--accent); }}
    .watch {{ color: var(--warn); }}
    @media (max-width: 760px) {{
      .top {{ align-items: flex-start; flex-direction: column; padding: 18px 0; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      table {{ min-width: 760px; }}
      section {{ overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap top">
      <div>
        <h1>Polyarb BTC 套利模拟系统</h1>
        <p>只读 Polymarket 行情，执行纸面模拟交易；不连接钱包，不真实下单。</p>
      </div>
      <div class="toolbar">
        <button id="scanBtn">触发扫描</button>
        <button class="secondary" id="refreshBtn">刷新页面</button>
      </div>
    </div>
  </header>
  <main class="wrap">
    {error_html}
    <div class="metrics">
      {_metric("状态", status_text)}
      {_metric("市场", snapshot["markets"])}
      {_metric("交易对", snapshot["pairs"])}
      {_metric("机会", snapshot["opportunities"])}
    </div>
    <p>最近扫描：{escape(str(snapshot["scanned_at"] or "尚未完成"))}</p>
    <p>最近盘口事件：{escape(str(snapshot["last_event_at"] or "尚未收到"))}</p>
    <section>
      <h2>最近套利机会</h2>
      {_opportunity_table(opportunities)}
    </section>
    <section>
      <h2>纸面模拟成交</h2>
      {_trade_table(trades)}
    </section>
  </main>
  <script>
    async function triggerScan() {{
      const btn = document.getElementById('scanBtn');
      btn.disabled = true;
      btn.textContent = '扫描中';
      await fetch('/api/scan', {{ method: 'POST' }});
      setTimeout(() => location.reload(), 2000);
    }}
    document.getElementById('scanBtn').addEventListener('click', triggerScan);
    document.getElementById('refreshBtn').addEventListener('click', () => location.reload());
    setInterval(() => location.reload(), 5000);
  </script>
</body>
</html>"""


def _metric(label: str, value: object) -> str:
    return f"<div class='metric'><div class='label'>{escape(label)}</div><div class='value'>{escape(str(value))}</div></div>"


def format_standard_time(value: datetime) -> str:
    return value.astimezone(DISPLAY_TZ).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _opportunity_table(rows: list) -> str:
    if not rows:
        return "<div class='empty'>暂无记录。系统只会在发现正收益组合时写入机会。</div>"
    body = []
    for row in rows:
        cls = "exec" if row.get("executable") else "watch"
        state = "可模拟成交" if row.get("executable") else "仅观察"
        body.append(
            "<tr>"
            f"<td><span class='pill {cls}'>{state}</span><br>{escape(str(row.get('reason', '')))}</td>"
            f"<td>{escape(str(row.get('guaranteed_profit', '')))}</td>"
            f"<td>{escape(str(row.get('shares', '')))}</td>"
            f"<td>YES: {escape(str(row.get('yes_question', '')))}<br>NO: {escape(str(row.get('no_question', '')))}</td>"
            f"<td>{escape(str(row.get('detected_at', '')))}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>状态</th><th>保证利润</th><th>份额</th><th>交易对</th><th>时间</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>"


def _trade_table(rows: list) -> str:
    if not rows:
        return "<div class='empty'>暂无纸面成交。</div>"
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{escape(str(row.get('pair_key', '')))}</td>"
            f"<td>{escape(str(row.get('shares', '')))}</td>"
            f"<td>{escape(str(row.get('total_cost', '')))}</td>"
            f"<td>{escape(str(row.get('guaranteed_profit', '')))}</td>"
            f"<td>{escape(str(row.get('detected_at', '')))}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>交易对</th><th>份额</th><th>成本</th><th>保证利润</th><th>时间</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>"
