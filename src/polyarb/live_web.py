from __future__ import annotations

from html import escape
from typing import Dict, List, Optional

from .models import DEFAULT_ALLOCATION_RATIOS, DEFAULT_ASSETS


def render_live_page(
    session: dict,
    markets: List[dict],
    allocation_ratios: Optional[Dict[str, float]] = None,
    monitored_pairs_html: str = "",
) -> str:
    logged_in = bool(session.get("logged_in"))
    error_html = _error_html(session)
    account_html = _account_html(session) if logged_in else _login_html()
    positions_html = _positions_html(session.get("positions", [])) if logged_in else ""
    closed_html = _closed_html(session.get("closed_positions", [])) if logged_in else ""
    orders_html = _orders_html(session.get("open_orders", [])) if logged_in else ""
    trades_html = _trades_html(session.get("trades", [])) if logged_in else ""
    auto_trade_html = _auto_trade_html(session) if logged_in else ""
    execution_log_html = _execution_log_html(session.get("execution_log", [])) if logged_in else ""
    opportunities_html = (
        _live_opportunities_html(session.get("live_opportunities", [])) if logged_in else ""
    )
    settings_html = _settings_html(allocation_ratios)
    monitored_pairs_panel = _monitored_pairs_panel_html(monitored_pairs_html)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Polymarket 真实交易系统</title>
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
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }}
    header {{ border-bottom: 1px solid var(--line); background: var(--panel); }}
    .wrap {{ width: min(1180px, calc(100vw - 32px)); margin: 0 auto; }}
    .top {{ min-height: 92px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }}
    h1 {{ margin: 0; font-size: 28px; line-height: 1.15; }}
    p {{ color: var(--muted); margin: 8px 0 0; }}
    main {{ padding: 22px 0 36px; }}
    .toolbar {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    button, .nav-btn {{ border: 1px solid #17624c; background: var(--accent); color: white; min-height: 40px; padding: 0 14px; border-radius: 6px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; }}
    button.secondary, .nav-btn.secondary {{ background: white; color: var(--ink); border-color: var(--line); }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; margin-top: 16px; padding: 14px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 12px; }}
    .metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ margin-top: 6px; font-size: 22px; font-weight: 800; overflow-wrap: anywhere; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .form-grid label {{ display: grid; gap: 6px; color: var(--muted); font-size: 13px; font-weight: 700; }}
    .form-grid input, .form-grid select {{ min-width: 0; min-height: 40px; padding: 0 10px; border: 1px solid var(--line); border-radius: 6px; font-size: 15px; color: var(--ink); background: #fff; }}
    .form-actions {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 12px; }}
    .message {{ min-height: 18px; font-size: 13px; }}
    .message.ok {{ color: var(--accent); }}
    .message.error {{ color: var(--danger); }}
    .settings-row {{
      display: grid;
      grid-template-columns: repeat(4, minmax(100px, 1fr)) minmax(170px, auto) auto auto;
      gap: 10px;
      align-items: end;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-top: 16px;
      padding: 14px;
    }}
    .settings-title {{ align-self: center; font-weight: 800; white-space: nowrap; }}
    .settings-field {{ display: grid; gap: 4px; min-width: 0; }}
    .settings-field label {{ color: var(--muted); font-size: 13px; font-weight: 700; }}
    .settings-input {{ min-width: 0; min-height: 40px; padding: 0 10px; border: 1px solid var(--line); border-radius: 6px; font-size: 15px; color: var(--ink); background: #fff; }}
    .settings-field.settings-password-field {{ min-width: 170px; }}
    .settings-message {{ align-self: center; min-width: 120px; min-height: 18px; font-size: 13px; }}
    .settings-message.ok {{ color: var(--accent); }}
    .settings-message.error {{ color: var(--danger); }}
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
    .monitored-pairs-scroll {{ max-height: 250px; overflow-y: auto; overflow-x: auto; }}
    .monitored-pair-table .condition-details {{ margin-top: 6px; }}
    .monitored-pair-table .condition-details summary {{ cursor: pointer; color: var(--accent); font-weight: 700; }}
    .monitored-pair-table .condition-tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
    .monitored-pair-table .condition-tag {{ display: inline-block; padding: 2px 8px; border: 1px solid var(--line); border-radius: 999px; background: #fbfcfd; color: var(--ink); font-weight: 700; }}
    .near-condition {{ margin-top: 6px; font-weight: 800; color: var(--accent); }}
    .error {{ color: var(--danger); font-weight: 700; }}
    .table-scroll {{ max-height: 360px; overflow: auto; }}
    table {{ width: max-content; min-width: 100%; border-collapse: collapse; font-size: 14px; table-layout: auto; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); background: #fbfcfd; }}
    tr:last-child td {{ border-bottom: 0; }}
    .empty {{ padding: 16px 12px; color: var(--muted); }}
    .profit-positive {{ color: var(--accent); }}
    .profit-negative {{ color: var(--danger); }}
    @media (max-width: 760px) {{
      .wrap {{ width: 100%; padding: 0 12px; }}
      .top {{ flex-direction: column; align-items: flex-start; gap: 12px; min-height: auto; padding: 16px 0; }}
      h1 {{ font-size: 22px; }}
      main {{ padding: 14px 0 24px; }}
      .toolbar {{ width: 100%; }}
      button, .nav-btn {{ width: 100%; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
      .form-grid {{ grid-template-columns: 1fr; }}
      .settings-row {{ grid-template-columns: 1fr; }}
      .settings-title {{ grid-column: 1 / -1; }}
      .settings-field.settings-password-field {{ min-width: 0; }}
      #liveSaveSettingsBtn {{ grid-column: 1 / -1; }}
      .settings-message {{ grid-column: 1 / -1; min-width: 0; }}
      .market-text {{ min-width: 0; max-width: none; }}
      .panel {{ border-radius: 12px; }}
    }}
    @media (max-width: 640px) {{
      .monitored-pair-table thead {{ display: none; }}
      .monitored-pair-table tr {{
        display: block;
        margin: 10px;
        padding: 10px 12px;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: #fff;
      }}
      .monitored-pair-table td {{
        display: grid;
        grid-template-columns: 96px minmax(0, 1fr);
        gap: 10px;
        align-items: start;
        padding: 7px 0;
        border-bottom: 1px dashed var(--line);
        text-align: right;
        overflow-wrap: anywhere;
      }}
      .monitored-pair-table td:last-child {{ border-bottom: 0; }}
      .monitored-pair-table td::before {{
        color: var(--muted);
        content: "";
        font-size: 12px;
        font-weight: 700;
        line-height: 1.35;
        text-align: left;
      }}
      .monitored-pair-table td:nth-child(1)::before {{ content: "序号"; }}
      .monitored-pair-table td:nth-child(2)::before {{ content: "事件 / 实时条件"; }}
      .monitored-pair-table td:nth-child(3)::before {{ content: "到期日期"; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap top">
      <div>
        <h1>Polymarket 真实交易系统</h1>
        <p>使用 Polymarket 账户资金交易，读取账户持仓与收益。</p>
      </div>
      <div class="toolbar">
        <a class="nav-btn secondary" href="/simulation">模拟交易</a>
        {_logout_button() if logged_in else ""}
      </div>
    </div>
  </header>
  <main class="wrap">
    <div id="liveError">{error_html}</div>
    {settings_html}
    <div id="liveAccount">{account_html}</div>
    {auto_trade_html}
    {execution_log_html}
    {monitored_pairs_panel}
    {opportunities_html}
    <div id="livePositions">{positions_html}</div>
    <div id="liveClosed">{closed_html}</div>
    <div id="liveOrders">{orders_html}</div>
    <div id="liveTrades">{trades_html}</div>
  </main>
  <script>
    function setText(id, value) {{
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    }}
    function setHtml(id, html) {{
      const el = document.getElementById(id);
      if (el) el.innerHTML = html;
    }}
    async function liveRefresh() {{
      const response = await fetch('/api/live/dashboard');
      const payload = await response.json();
      if (!payload.logged_in) {{
        setHtml('liveError', payload.error_html || '');
        return;
      }}
      setHtml('liveError', payload.error_html || '');
      setHtml('liveAccount', payload.account_html || '');
      setHtml('liveAutoTrade', payload.auto_trade_html || '');
      setHtml('liveExecutionLog', payload.execution_log_html || '');
      setHtml('liveMonitoredPairs', payload.monitored_pairs_html || '');
      setHtml('liveOpportunities', payload.opportunities_html || '');
      setHtml('livePositions', payload.positions_html || '');
      setHtml('liveClosed', payload.closed_html || '');
      setHtml('liveOrders', payload.orders_html || '');
      setHtml('liveTrades', payload.trades_html || '');
      bindLiveEvents();
    }}
    async function liveLogin() {{
      const message = document.getElementById('liveLoginMessage');
      const button = document.getElementById('liveLoginBtn');
      if (!message || !button) return;
      button.disabled = true;
      button.textContent = '登录中';
      try {{
        const response = await fetch('/api/live/login', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            wallet: document.getElementById('liveWallet').value,
            private_key: document.getElementById('livePrivateKey').value,
            relayer_api_key: document.getElementById('liveRelayerKey').value,
            relayer_api_key_address: document.getElementById('liveRelayerAddress').value,
          }}),
        }});
        const payload = await response.json();
        if (response.ok) {{
          window.location.reload();
        }} else {{
          message.textContent = payload.message || '登录失败';
          message.className = 'message error';
        }}
      }} finally {{
        button.disabled = false;
        button.textContent = '登录真实账户';
      }}
    }}
    async function liveLogout() {{
      await fetch('/api/live/logout', {{ method: 'POST' }});
      window.location.reload();
    }}
    async function liveAutoToggle() {{
      const enabled = !document.getElementById('liveAutoTradeBtn')?.dataset.enabled;
      const response = await fetch('/api/live/auto', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ enabled: Boolean(enabled) }}),
      }});
      const payload = await response.json();
      window.alert(payload.message || '自动交易状态已更新');
      await liveRefresh();
    }}
    async function liveCancel(orderId) {{
      if (!window.confirm('确认取消订单 ' + orderId + '?')) return;
      const response = await fetch('/api/live/cancel', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ order_id: orderId }}),
      }});
      const payload = await response.json();
      window.alert(payload.message || '取消请求已提交');
      await liveRefresh();
    }}
    function applyLiveAllocations(allocations) {{
      for (const symbol of ['BTC', 'ETH', 'XRP', 'SOL']) {{
        const input = document.getElementById('liveAlloc' + symbol);
        if (input) input.value = allocations[symbol] ?? 0;
      }}
    }}
    async function saveLiveSettings() {{
      const allocations = {{}};
      for (const symbol of ['BTC', 'ETH', 'XRP', 'SOL']) {{
        allocations[symbol] = Number(document.getElementById('liveAlloc' + symbol).value || 0);
      }}
      const password = document.getElementById('liveSettingsPassword').value;
      const button = document.getElementById('liveSaveSettingsBtn');
      const message = document.getElementById('liveSettingsMessage');
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
          document.getElementById('liveSettingsPassword').value = '';
          applyLiveAllocations(payload.allocations || {{}});
          await liveRefresh();
        }}
      }} finally {{
        button.disabled = false;
        button.textContent = '保存设置';
      }}
    }}
    function bindLiveEvents() {{
      document.getElementById('liveLoginBtn')?.addEventListener('click', liveLogin);
      document.getElementById('liveLogoutBtn')?.addEventListener('click', liveLogout);
      document.getElementById('liveAutoTradeBtn')?.addEventListener('click', liveAutoToggle);
    }}
    function bindLiveSettings() {{
      document.getElementById('liveSaveSettingsBtn')?.addEventListener('click', saveLiveSettings);
      document.getElementById('liveSettingsPassword')?.addEventListener('keydown', (event) => {{
        if (event.key === 'Enter') {{
          event.preventDefault();
          saveLiveSettings();
        }}
      }});
    }}
    bindLiveEvents();
    bindLiveSettings();
    setInterval(liveRefresh, 5000);
  </script>
</body>
</html>"""


def live_dashboard_payload(
    session: dict,
    markets: List[dict],
    allocation_ratios: Optional[Dict[str, float]] = None,
    monitored_pairs_html: str = "",
) -> dict:
    logged_in = bool(session.get("logged_in"))
    return {
        "logged_in": logged_in,
        "error_html": _error_html(session),
        "account_html": _account_html(session) if logged_in else _login_html(),
        "auto_trade_html": _auto_trade_html(session) if logged_in else "",
        "execution_log_html": _execution_log_html(session.get("execution_log", [])) if logged_in else "",
        "monitored_pairs_html": monitored_pairs_html,
        "opportunities_html": (
            _live_opportunities_html(session.get("live_opportunities", [])) if logged_in else ""
        ),
        "positions_html": _positions_html(session.get("positions", [])) if logged_in else "",
        "closed_html": _closed_html(session.get("closed_positions", [])) if logged_in else "",
        "orders_html": _orders_html(session.get("open_orders", [])) if logged_in else "",
        "trades_html": _trades_html(session.get("trades", [])) if logged_in else "",
        "markets": markets,
        "settings": {"allocation_ratios": _allocation_ratios(allocation_ratios)},
    }


def _monitored_pairs_panel_html(content: str = "") -> str:
    body = content or "<div class='empty'>暂无交易对，等待首次扫描或行情源恢复。</div>"
    return (
        "<div class='panel'><h2>实时交易对</h2>"
        f"<div id='liveMonitoredPairs'>{body}</div></div>"
    )


def _settings_html(allocation_ratios: Optional[Dict[str, float]] = None) -> str:
    ratios = _allocation_ratios(allocation_ratios)
    fields = []
    for asset in DEFAULT_ASSETS:
        percent = ratios.get(asset.symbol, asset.allocation_ratio) * 100
        fields.append(
            "<div class='settings-field'>"
            f"<label for=\"liveAlloc{escape(asset.symbol)}\">{escape(asset.symbol)}</label>"
            f"<input class='settings-input' id=\"liveAlloc{escape(asset.symbol)}\" type='number' min='0' max='100' step='0.1' value='{escape(f'{percent:g}')}'>"
            "</div>"
        )
    password_field = (
        "<div class='settings-field settings-password-field'>"
        "<label for=\"liveSettingsPassword\">确认密码</label>"
        "<input class='settings-input' id=\"liveSettingsPassword\" type='password' autocomplete='off' placeholder='请输入密码'>"
        "</div>"
    )
    return (
        "<div class='settings-row' id=\"allocationSettings\">"
        "<span class='settings-title'>资金分配</span>"
        + "".join(fields)
        + password_field
        + "<button class='secondary' id=\"liveSaveSettingsBtn\" type='button'>保存设置</button>"
        + "<span class='settings-message' id=\"liveSettingsMessage\"></span>"
        + "</div>"
    )


def _allocation_ratios(allocation_ratios: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    ratios = dict(DEFAULT_ALLOCATION_RATIOS)
    if allocation_ratios:
        for symbol in DEFAULT_ALLOCATION_RATIOS:
            try:
                ratios[symbol] = float(allocation_ratios.get(symbol, ratios[symbol]))
            except (TypeError, ValueError):
                continue
    return ratios


def _login_html() -> str:
    return (
        "<div class='panel'>"
        "<h2>连接 Polymarket 账户</h2>"
        "<div class='form-grid'>"
        "<label>钱包地址<input id='liveWallet' type='text' autocomplete='off'></label>"
        "<label>签名私钥<input id='livePrivateKey' type='password' autocomplete='off'></label>"
        "<label>Relayer API Key（可选）<input id='liveRelayerKey' type='password' autocomplete='off'></label>"
        "<label>Relayer 地址（可选）<input id='liveRelayerAddress' type='text' autocomplete='off'></label>"
        "</div>"
        "<div class='form-actions'><button id='liveLoginBtn'>登录真实账户</button>"
        "<span class='message' id='liveLoginMessage'></span></div>"
        "</div>"
    )


def _logout_button() -> str:
    return "<button class='secondary' id='liveLogoutBtn'>退出登录</button>"


def _error_html(session: dict) -> str:
    error = session.get("error")
    if not error:
        return ""
    return f"<p class='error'>{escape(str(error))}</p>"


def _account_html(session: dict) -> str:
    account = session.get("account") or {}
    metrics = (
        "<div class='metrics'>"
        f"{_metric('pUSD 余额', _money(session.get('balance_pusd')), 'balancePusdValue')}"
        f"{_metric('总资产', _money(session.get('portfolio_value')), 'portfolioValueValue')}"
        f"{_metric('未实现收益', _signed_money(session.get('unrealized_pnl')), 'unrealizedPnlValue', _profit_class(session.get('unrealized_pnl')))}"
        f"{_metric('已实现收益', _signed_money(session.get('realized_pnl')), 'realizedPnlValue', _profit_class(session.get('realized_pnl')))}"
        "</div>"
    )
    rows = [
        ("钱包", account.get("wallet")),
        ("签名地址", account.get("signer")),
        ("账户类型", _wallet_type_label(account.get("wallet_type"))),
        ("Relayer API Key", "已配置" if account.get("has_relayer") else "未配置"),
    ]
    body = "".join(f"<tr><td>{escape(k)}</td><td>{escape(str(v))}</td></tr>" for k, v in rows)
    return (
        "<div class='panel'>"
        "<h2>真实账户</h2>"
        f"{metrics}"
        "<div class='table-scroll'><table><thead><tr><th>字段</th><th>值</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
        "</div>"
    )


def _auto_trade_html(session: dict) -> str:
    enabled = bool(session.get("auto_trading_enabled"))
    status = "自动交易已启用" if enabled else "自动交易已停止"
    button_text = "停止自动交易" if enabled else "启用自动交易"
    enabled_flag = "1" if enabled else "0"
    error = session.get("auto_trader_error")
    return (
        "<div class='panel'>"
        "<h2>自动真实交易</h2>"
        f"<div class='label'>状态：{escape(status)}</div>"
        f"<div class='form-actions'><button id='liveAutoTradeBtn' data-enabled='{enabled_flag}'>{escape(button_text)}</button></div>"
        + (f"<div class='error'>{escape(str(error))}</div>" if error else "")
        + "</div>"
    )


def _execution_log_html(rows: List[dict]) -> str:
    if not rows:
        return "<div class='panel'><h2>自动成交记录</h2><div class='empty'>暂无记录。</div></div>"
    body = []
    for row in rows:
        ok = "成功" if row.get("ok") else "失败"
        body.append(
            "<tr>"
            f"<td>{escape(_text(row.get('time')))}</td>"
            f"<td>{escape(_text(row.get('asset')))}</td>"
            f"<td>{escape(_text(row.get('pair_key')))}</td>"
            f"<td>{escape(_text(row.get('yes_order_id')))}</td>"
            f"<td>{escape(_text(row.get('no_order_id')))}</td>"
            f"<td>{escape(ok)}</td>"
            f"<td>{escape(_text(row.get('detail')))}</td>"
            "</tr>"
        )
    return (
        "<div class='panel'><h2>自动成交记录</h2>"
        "<div class='table-scroll'><table><thead><tr>"
        "<th>时间</th><th>币种</th><th>交易对</th><th>YES 订单</th><th>NO 订单</th><th>状态</th><th>说明</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></div>"
    )


def _live_opportunities_html(rows: List[dict]) -> str:
    if not rows:
        return "<div class='panel'><h2>实时套利机会</h2><div class='empty'>暂无交易机会。</div></div>"
    body = []
    for row in rows:
        status = str(row.get("status") or "仅观察")
        status_class = {
            "已成交": "profit-positive",
            "可成交": "profit-positive",
            "资金不足": "profit-negative",
        }.get(status, "")
        try:
            spread_text = f"{float(row.get('spread_cents') or 0):.2f}¢"
        except (TypeError, ValueError):
            spread_text = "0.00¢"
        body.append(
            "<tr>"
            f"<td>{escape(_text(row.get('time')))}</td>"
            f"<td>{escape(_text(row.get('asset')))}</td>"
            f"<td>{escape(_text(row.get('yes_question')))}</td>"
            f"<td>{escape(_text(row.get('no_question')))}</td>"
            f"<td>{escape(_money(row.get('guaranteed_profit')))}</td>"
            f"<td>{escape(spread_text)}</td>"
            f"<td class='{status_class}'>{escape(status)}</td>"
            f"<td>{escape(_text(row.get('detail')))}</td>"
            "</tr>"
        )
    return (
        "<div class='panel'><h2>实时套利机会</h2>"
        "<div class='table-scroll'><table><thead><tr>"
        "<th>时间</th><th>币种</th><th>YES 交易对</th><th>NO 交易对</th><th>保证利润</th><th>价差</th><th>状态</th><th>说明</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></div>"
    )


def _positions_html(rows: List[dict]) -> str:
    return _table_panel("当前持仓", rows, (
        ("title", "市场"),
        ("outcome", "方向"),
        ("size", "份额"),
        ("avg_price", "均价"),
        ("current_value", "当前价值"),
        ("cash_pnl", "未实现收益"),
        ("percent_pnl", "收益率"),
        ("end_date", "结束日期"),
    ), "livePositions")


def _closed_html(rows: List[dict]) -> str:
    return _table_panel("已结束持仓收益", rows, (
        ("title", "市场"),
        ("outcome", "方向"),
        ("total_bought", "累计买入"),
        ("realized_pnl", "已实现收益"),
        ("timestamp", "结束时间"),
    ), "liveClosed")


def _orders_html(rows: List[dict]) -> str:
    return _table_panel("未完成订单", rows, (
        ("id", "订单 ID"),
        ("side", "方向"),
        ("outcome", "方向"),
        ("price", "价格"),
        ("original_size", "数量"),
        ("size_matched", "已成交"),
        ("status", "状态"),
        ("created_at", "创建时间"),
    ), "liveOrders", cancelable=True)


def _trades_html(rows: List[dict]) -> str:
    return _table_panel("最近成交", rows, (
        ("id", "成交 ID"),
        ("side", "方向"),
        ("outcome", "方向"),
        ("price", "价格"),
        ("size", "数量"),
        ("status", "状态"),
        ("matched_at", "时间"),
    ), "liveTrades")


def _table_panel(title: str, rows: List[dict], columns, panel_id: str, cancelable: bool = False) -> str:
    if not rows:
        return f"<div class='panel'><h2>{escape(title)}</h2><div class='empty'>暂无记录。</div></div>"
    headers = "".join(f"<th>{escape(label)}</th>" for _key, label in columns)
    if cancelable:
        headers += "<th></th>"
    body = []
    for row in rows:
        cells = []
        for key, _label in columns:
            value = row.get(key)
            if key in {"cash_pnl", "realized_pnl"}:
                text = _signed_money(value)
                cells.append(f"<td class='{_profit_class(value)}'>{escape(text)}</td>")
            elif key in {"price", "avg_price"}:
                cells.append(f"<td>{escape(_price(value))}</td>")
            elif key in {"current_value", "total_bought", "size", "original_size", "size_matched"}:
                cells.append(f"<td>{escape(_money(value))}</td>")
            elif key == "percent_pnl":
                cells.append(f"<td>{escape(_percent(value))}</td>")
            else:
                cells.append(f"<td>{escape(_text(value))}</td>")
        if cancelable:
            order_id = str(row.get("id") or "")
            cells.append(f"<td><button onclick=\"liveCancel('{escape(order_id)}')\">取消</button></td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f"<div class='panel'><h2>{escape(title)}</h2>"
        f"<div class='table-scroll'><table><thead><tr>{headers}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div></div>"
    )


def _metric(label: str, value: str, element_id: str, value_class: str = "") -> str:
    classes = "value"
    if value_class:
        classes += f" {value_class}"
    return (
        f"<div class='metric'><div class='label'>{escape(label)}</div>"
        f"<div class='{escape(classes)}' id='{escape(element_id)}'>{escape(value)}</div></div>"
    )


def _wallet_type_label(value: object) -> str:
    return {
        "EOA": "EOA 钱包",
        "POLY_PROXY": "Polymarket 代理钱包",
        "GNOSIS_SAFE": "多签钱包",
        "DEPOSIT_WALLET": "存款钱包",
    }.get(str(value or ""), str(value or "-"))


def _money(value: object) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _signed_money(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    sign = "+" if number >= 0 else "-"
    return f"{sign}{abs(number):,.2f}"


def _percent(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:.2f}%"


def _price(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:.2f}"


def _profit_class(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return "profit-positive" if number >= 0 else "profit-negative"


def _text(value: object) -> str:
    if value is None:
        return "-"
    return str(value)
