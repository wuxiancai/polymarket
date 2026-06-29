from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Union
from zoneinfo import ZoneInfo

from .config import Config
from .models import DEFAULT_ASSETS, AssetSpec
from .runner import PaperRunner, RealtimePaperRunner, ScanResult
from .store import PaperStore

DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


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


def serve(config: Config, host: str = "127.0.0.1", port: int = 8787, auto_scan: bool = True) -> None:
    store = PaperStore(config.database_path)
    store.initialize()
    states = [
        WebState(config=config, store=store, asset=asset, runner=PaperRunner(config, asset))
        for asset in DEFAULT_ASSETS
    ]
    if auto_scan:
        for state in states:
            _start_realtime_loop(state)

    class Handler(PolyarbHandler):
        web_states = states

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Polyarb Web 已启动: http://{host}:{port}")
    server.serve_forever()


def _start_realtime_loop(state: WebState) -> None:
    thread = threading.Thread(target=state.run_realtime, name="polyarb-realtime-scanner", daemon=True)
    thread.start()


class PolyarbHandler(BaseHTTPRequestHandler):
    web_states: list[WebState]

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._html(render_dashboard(self.web_states))
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


def render_dashboard(states: Union[WebState, list[WebState]]) -> str:
    panels = _as_states(states)
    error_html = _error_html(panels)
    portfolio = _portfolio_payload(panels)
    asset_sections = "\n".join(_asset_section(state) for state in panels)
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
    section {{ margin-top: 16px; overflow-x: auto; overflow-y: hidden; }}
    section h2 {{
      margin: 0;
      padding: 13px 14px;
      font-size: 17px;
      border-bottom: 1px solid var(--line);
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; table-layout: auto; }}
    th, td {{ padding: 11px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 700; background: #fbfcfd; }}
    tr:last-child td {{ border-bottom: 0; }}
    .empty {{ padding: 18px 14px; color: var(--muted); }}
    .error {{ color: var(--danger); font-weight: 700; }}
    .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); }}
    .exec {{ color: var(--accent); }}
    .watch {{ color: var(--warn); }}
    .profit-positive {{ color: var(--accent); }}
    .profit-negative {{ color: var(--danger); }}
    .wide-table {{ min-width: 1540px; table-layout: fixed; }}
    .position-table {{ min-width: 1750px; }}
    .wide-table th, .wide-table td {{ white-space: nowrap; }}
    .wide-table .asset-col {{ width: 64px; }}
    .wide-table .market-col {{ width: 320px; }}
    .wide-table .qty-col {{ width: 120px; }}
    .wide-table .price-col {{ width: 82px; }}
    .wide-table .spread-col {{ width: 90px; }}
    .wide-table .amount-col {{ width: 112px; }}
    .wide-table .money-col {{ width: 112px; }}
    .wide-table .profit-col {{ width: 112px; }}
    .wide-table .time-col {{ width: 150px; }}
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
    .log-table td:first-child {{ white-space: nowrap; color: var(--muted); }}
    .log-level {{ font-weight: 700; }}
    .log-ok {{ color: var(--accent); }}
    .log-error {{ color: var(--danger); }}
    @media (max-width: 760px) {{
      .top {{ align-items: flex-start; flex-direction: column; padding: 18px 0; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .portfolio-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      table {{ min-width: 760px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap top">
      <div>
        <h1>Polymarket 套利模拟系统</h1>
        <p>只读 Polymarket BTC / ETH 行情，执行纸面模拟交易；不连接钱包，不真实下单。</p>
      </div>
      <div class="toolbar">
        <button id="scanBtn">触发扫描</button>
        <button class="secondary" id="refreshBtn">刷新数据</button>
      </div>
    </div>
  </header>
  <main class="wrap">
    <div id="errorBox">{error_html}</div>
    <section>
      <h2>收益概览</h2>
      <div id="portfolioSummary">{portfolio["summary_html"]}</div>
    </section>
    <section>
      <h2>模拟持仓</h2>
      <div id="positionTable">{portfolio["positions_html"]}</div>
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
    async function refreshDashboard() {{
      const response = await fetch('/api/dashboard');
      const payload = await response.json();
      document.getElementById('errorBox').innerHTML = payload.error_html;
      document.getElementById('portfolioSummary').innerHTML = payload.portfolio.summary_html;
      document.getElementById('positionTable').innerHTML = payload.portfolio.positions_html;
      document.getElementById('connectionLog').innerHTML = payload.connection_log_html;
      for (const asset of payload.assets) {{
        setText(asset.symbol + 'StatusValue', asset.status_text);
        setText(asset.symbol + 'MarketsValue', asset.status.markets);
        setText(asset.symbol + 'PairsValue', asset.status.pairs);
        setText(asset.symbol + 'OpportunitiesValue', asset.status.opportunities);
        document.getElementById(asset.symbol + 'OpportunityTable').innerHTML = asset.opportunities_html;
        document.getElementById(asset.symbol + 'TradeTable').innerHTML = asset.trades_html;
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
    document.getElementById('scanBtn').addEventListener('click', triggerScan);
    document.getElementById('refreshBtn').addEventListener('click', refreshDashboard);
    setInterval(refreshDashboard, 5000);
  </script>
</body>
</html>"""


def dashboard_payload(states: Union[WebState, list[WebState]]) -> dict:
    panels = _as_states(states)
    return {
        "error_html": _error_html(panels),
        "portfolio": _portfolio_payload(panels),
        "assets": [_asset_payload(state) for state in panels],
        "connection_log_html": _connection_log_html(panels),
    }


def _as_states(states: Union[WebState, list[WebState]]) -> list[WebState]:
    return states if isinstance(states, list) else [states]


def _portfolio_payload(states: list[WebState]) -> dict:
    if not states:
        return {
            "summary_html": "<div class='empty'>暂无资产配置。</div>",
            "positions_html": "<div class='empty'>暂无持仓。</div>",
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
        allocation = state.config.initial_capital_usdt * state.asset.allocation_ratio
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
        "positions_html": _position_table(positions, states),
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
        "<div class='portfolio-detail'><table><thead><tr>"
        "<th>币种</th><th>分配本金</th><th>已用本金</th><th>剩余本金</th>"
        "<th>收益</th><th>收益率</th><th>持仓数</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )
    return metrics + detail


def _position_table(rows: list, states: list[WebState]) -> str:
    if not rows:
        return "<div class='empty'>暂无持仓。</div>"
    body = []
    for row in rows:
        asset = _asset_symbol_for_row(row, states)
        body.append(
            "<tr>"
            f"<td>{escape(asset)}</td>"
            f"<td>{_profit_text(_signed_money(row.get('guaranteed_profit', 0)), row.get('guaranteed_profit', 0))}</td>"
            f"<td>{_spread(row)}</td>"
            f"<td class='time-cell'>{_time_html(_settlement_time(row))}</td>"
            f"<td class='market-text'>{_market_link(row.get('yes_question', ''), row.get('yes_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('yes_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'yes_avg_price'))}</td>"
            f"<td class='market-text'>{_market_link(row.get('no_question', ''), row.get('no_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('no_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'no_avg_price'))}</td>"
            f"<td>{_money(row.get('total_cost', 0))}</td>"
            f"<td>{_money(row.get('min_payout', 0))}</td>"
            f"<td class='time-cell'>{_time_html(_format_time_value(row.get('detected_at', '')))}</td>"
            "</tr>"
        )
    return (
        "<table class='trade-table wide-table position-table'>"
        "<colgroup><col class='asset-col'><col class='profit-col'><col class='spread-col'><col class='time-col'><col class='market-col'><col class='qty-col'><col class='price-col'><col class='amount-col'>"
        "<col class='market-col'><col class='qty-col'><col class='price-col'><col class='amount-col'><col class='money-col'>"
        "<col class='money-col'><col class='time-col'></colgroup>"
        "<thead><tr><th>币种</th><th>预估收益</th><th>价差</th><th>结算时间UTC+8</th><th>YES 持仓腿</th><th>YES 数量</th><th>YES 价格</th><th>YES 金额</th>"
        "<th>NO 持仓腿</th><th>NO 数量</th><th>NO 价格</th><th>NO 金额</th><th>成本</th><th>最低赔付</th><th>开仓时间</th></tr></thead><tbody>"
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
    asset, _direction, _threshold, period = parsed
    return f"What price will {asset} hit {period}?"


def _condition_label(question: str) -> str:
    parsed = _parse_market_question(question)
    if parsed is None:
        return ""
    _asset, direction, threshold, _period = parsed
    arrow = "↓" if direction == "dip" else "↑"
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
        r"Will ([A-Za-z]+) (dip to|reach|hit) \$([0-9,]+) (.+)\?",
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


def _asset_section(state: WebState) -> str:
    payload = _asset_payload(state)
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


def _asset_payload(state: WebState) -> dict:
    snapshot = state.snapshot()
    opportunities = _filter_rows_by_asset(state.store.latest_opportunities(20), state.asset)[:10]
    trades = _filter_rows_by_asset(state.store.latest_trades(20), state.asset)[:10]
    return {
        "symbol": state.asset.symbol,
        "status": snapshot,
        "status_text": status_label(snapshot),
        "opportunities_html": _opportunity_table(opportunities),
        "trades_html": _trade_table(trades),
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
        "<table class='log-table'><thead><tr><th>时间</th><th>资产</th><th>级别</th><th>事件</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
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
    try:
        yes_price = float(row.get("yes_avg_price") or 0)
        no_price = float(row.get("no_avg_price") or 0)
    except (TypeError, ValueError):
        yes_price = 0.0
        no_price = 0.0
    return f"{(1 - yes_price - no_price) * 100:.2f}¢"


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


def _opportunity_table(rows: list) -> str:
    if not rows:
        return "<div class='empty'>暂无记录。系统只会在发现正收益组合时写入机会。</div>"
    body = []
    for row in rows:
        cls = "exec" if row.get("executable") else "watch"
        state = "可模拟成交" if row.get("executable") else "仅观察"
        detail = _opportunity_status_detail(row)
        body.append(
            "<tr>"
            f"<td><span class='pill {cls}'>{state}</span>{detail}</td>"
            f"<td>{escape(_money(row.get('guaranteed_profit', 0)))}</td>"
            f"<td class='market-text'>{_market_link(row.get('yes_question', ''), row.get('yes_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td class='market-text'>{_market_link(row.get('no_question', ''), row.get('no_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td class='time-cell'>{_time_html(_format_time_value(row.get('detected_at', '')))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>状态</th><th>保证利润</th><th>YES 交易对</th><th>YES 份额</th>"
        "<th>NO 交易对</th><th>NO 份额</th><th>时间</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _opportunity_status_detail(row: dict) -> str:
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


def _trade_table(rows: list) -> str:
    if not rows:
        return "<div class='empty'>暂无成交。</div>"
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{_spread(row)}</td>"
            f"<td>{_profit_text(_signed_money(row.get('guaranteed_profit', 0)), row.get('guaranteed_profit', 0))}</td>"
            f"<td class='time-cell'>{_time_html(_settlement_time(row))}</td>"
            f"<td class='market-text'>{_market_link(row.get('yes_question', ''), row.get('yes_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('yes_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'yes_avg_price'))}</td>"
            f"<td class='market-text'>{_market_link(row.get('no_question', ''), row.get('no_event_slug', ''))}</td>"
            f"<td>{_number(row.get('shares', 0))}</td>"
            f"<td>{_price(row.get('no_avg_price', 0))}</td>"
            f"<td>{_money(_leg_amount(row, 'no_avg_price'))}</td>"
            f"<td>{_money(row.get('total_cost', 0))}</td>"
            f"<td class='time-cell'>{_time_html(_format_time_value(row.get('detected_at', '')))}</td>"
            "</tr>"
        )
    return (
        "<table class='trade-table wide-table'>"
        "<colgroup><col class='spread-col'><col class='profit-col'><col class='time-col'><col class='market-col'><col class='qty-col'><col class='price-col'><col class='amount-col'>"
        "<col class='market-col'><col class='qty-col'><col class='price-col'><col class='amount-col'><col class='money-col'>"
        "<col class='time-col'></colgroup>"
        "<thead><tr><th>价差</th><th>预估收益</th><th>结算时间UTC+8</th><th>YES 持仓腿</th><th>YES 数量</th><th>YES 价格</th><th>YES 金额</th>"
        "<th>NO 持仓腿</th><th>NO 数量</th><th>NO 价格</th><th>NO 金额</th><th>成本</th><th>时间</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )
