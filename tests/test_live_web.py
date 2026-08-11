from polyarb.live_web import live_dashboard_payload, render_live_page


def logged_session():
    return {
        "logged_in": True,
        "account": {
            "wallet": "0xwallet",
            "signer": "0xsigner",
            "wallet_type": "DEPOSIT_WALLET",
            "has_relayer": True,
        },
        "balance_pusd": 1000.0,
        "portfolio_value": 1234.5,
        "unrealized_pnl": 12.3,
        "realized_pnl": -4.5,
        "auto_trading_enabled": True,
        "auto_trader_error": None,
        "execution_log": [
            {
                "time": "2026-08-07T00:00:00+00:00",
                "asset": "BTC",
                "pair_key": "pair-1",
                "yes_order_id": "yes-order",
                "no_order_id": "no-order",
                "ok": True,
                "detail": "YES=订单已提交。; NO=订单已提交。",
            }
        ],
        "redemption_log": [
            {
                "time": "2026-08-07T01:00:00+00:00",
                "title": "Will Bitcoin be above $60,000 on August 4?",
                "condition_id": "0xcondition",
                "transaction_hash": "0xredeemed",
                "ok": True,
                "detail": "已自动兑换。",
            }
        ],
        "live_opportunities": [
            {
                "time": "2026-08-07T00:00:00+00:00",
                "asset": "BTC",
                "yes_question": "Will Bitcoin be above $60,000?",
                "no_question": "Will Bitcoin be above $60,000?",
                "guaranteed_profit": 1.2,
                "spread_cents": 3.5,
                "status": "已触发，未成功",
                "detail": "资金不足",
            }
        ],
        "positions": [
            {
                "title": "Will Bitcoin be above $60,000?",
                "outcome": "YES",
                "size": 10,
                "avg_price": 0.42,
                "current_value": 5.0,
                "cash_pnl": 0.8,
                "percent_pnl": 16.68,
                "end_date": "2026-08-10",
            }
        ],
        "closed_positions": [],
        "open_orders": [],
        "trades": [],
    }


def test_live_page_has_simulation_button_and_login_form_when_logged_out():
    html = render_live_page({"logged_in": False}, [])

    assert "模拟交易" in html
    assert "连接 Polymarket 账户" in html
    assert "钱包地址（选填，默认 Polymarket 钱包）" in html
    assert "钱包私钥（签名者私钥）" in html
    assert "Relayer API 密钥（可选）" in html
    assert "Relayer API 地址（签名者地址）" in html
    assert "钱包地址可留空" in html
    assert "Polymarket 默认钱包" in html
    assert "Polymarket 个人资料中的“地址”" in html
    assert "Relayer API 密钥选填" in html
    assert "钱包地址（签名者地址或派生钱包）" not in html
    assert "钱包私钥（签名者地址）" not in html
    assert "Relayer API Key（可选）" not in html
    assert "Relayer 地址（可选）" not in html
    assert "签名私钥" not in html
    assert "真实下单" not in html
    assert "自动真实交易" not in html
    assert "0xsecret" not in html
    assert "if (!payload.logged_in)" in html


def test_live_page_renders_account_positions_and_auto_trading_when_logged_in():
    html = render_live_page(logged_session(), [])

    assert "真实账户" in html
    assert "当前持仓" in html
    assert "自动真实交易" in html
    assert "自动交易已启用" in html
    assert "自动成交记录" in html
    assert "自动兑换记录" in html
    assert "实时交易对" in html
    assert "监控事件" not in html
    assert "实时套利机会" in html
    assert "已触发，未成功" in html
    assert "资金不足" in html
    assert "<td class='profit-negative'>已触发，未成功</td>" in html
    assert "真实下单" not in html
    assert "提交真实订单" not in html
    assert "模拟交易" in html
    assert "Polymarket 真实交易系统" in html


def test_live_dashboard_payload_keeps_login_form_when_logged_out():
    payload = live_dashboard_payload({"logged_in": False}, [])

    assert "连接 Polymarket 账户" in payload["account_html"]
    assert payload["positions_html"] == ""
    assert payload["auto_trade_html"] == ""
    assert payload["opportunities_html"] == ""
    assert "monitored_pairs_html" in payload
    assert "redemption_html" in payload


def test_live_dashboard_payload_omits_markets_when_logged_out():
    payload = live_dashboard_payload({"logged_in": False}, [{"question": "Will Bitcoin rise?"}])

    assert payload["markets"] == []


def test_live_dashboard_payload_keeps_markets_when_logged_in():
    payload = live_dashboard_payload(logged_session(), [{"question": "Will Bitcoin rise?"}])

    assert payload["markets"] == [{"question": "Will Bitcoin rise?"}]


def test_live_page_shows_network_error_guidance_in_scripts():
    html = render_live_page({"logged_in": False}, [])

    assert "网络请求失败" in html
    assert "代理绕过" in html
    assert "response.status >= 500" in html


def test_live_page_renders_allocation_settings_with_persisted_values():
    html = render_live_page(
        {"logged_in": False},
        [],
        {"BTC": 1.0, "ETH": 0.0, "XRP": 0.0, "SOL": 0.0},
    )

    assert "资金分配" in html
    for symbol in ("BTC", "ETH", "XRP", "SOL"):
        assert f'id="liveAlloc{symbol}"' in html
    assert 'id="liveSettingsPassword"' in html
    assert 'id="liveSaveSettingsBtn"' in html
    assert "noneboy780308" not in html
    assert "value='100'" in html
    assert "saveLiveSettings" in html
    assert html.index('id="allocationSettings"') < html.index('id="liveAccount"')


def test_live_dashboard_payload_includes_allocation_settings():
    payload = live_dashboard_payload(
        {"logged_in": False},
        [],
        {"BTC": 1.0, "ETH": 0.0, "XRP": 0.0, "SOL": 0.0},
    )

    assert payload["settings"]["allocation_ratios"] == {
        "BTC": 1.0,
        "ETH": 0.0,
        "XRP": 0.0,
        "SOL": 0.0,
    }


def test_live_opportunities_time_renders_as_beijing_time():
    payload = live_dashboard_payload(logged_session(), [])

    assert "时间UTC+8" in payload["opportunities_html"]
    assert "<span class='time-date'>2026-08-07</span><span class='time-clock'>08:00:00</span>" in payload["opportunities_html"]
    assert "2026-08-07T00:00:00+00:00" not in payload["opportunities_html"]


def test_live_page_renders_simulation_monitored_pairs():
    monitored = (
        "<div class='table-scroll monitored-pairs-scroll'>"
        "<table class='monitored-pair-table'><thead><tr><th>序号</th><th>事件 / 实时条件</th><th>到期日期</th></tr></thead>"
        "<tbody><tr><td>1</td><td>Bitcoin price event</td><td>2026-08-04</td></tr></tbody></table></div>"
    )

    html = render_live_page(
        {"logged_in": False},
        [],
        monitored_pairs_html=monitored,
    )

    assert "实时交易对" in html
    assert "monitored-pair-table" in html
    assert "Bitcoin price event" in html
    assert "监控事件" not in html


def test_live_page_renders_region_restricted_opportunity_and_error():
    session = logged_session()
    session["live_opportunities"][0]["status"] = "区域受限"
    session["auto_trader_error"] = "真实交易区域受限：服务器出口 IP 1.2.3.4（SG）被 Polymarket 限制开仓。"

    html = render_live_page(session, [])

    assert "<td class='profit-negative'>区域受限</td>" in html
    assert "真实交易区域受限" in html
