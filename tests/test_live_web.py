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
        "live_events": [
            {
                "id": "90177",
                "slug": "bitcoin-event",
                "title": "Bitcoin event",
                "markets": [{"question": "Will Bitcoin be above $60,000?"}],
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
                "status": "资金不足",
                "detail": "available < target_budget",
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
    assert "监控事件" in html
    assert "实时套利机会" in html
    assert "资金不足" in html
    assert "真实下单" not in html
    assert "提交真实订单" not in html
    assert "模拟交易" in html
    assert "Polymarket 真实交易系统" in html


def test_live_dashboard_payload_keeps_login_form_when_logged_out():
    payload = live_dashboard_payload({"logged_in": False}, [])

    assert "连接 Polymarket 账户" in payload["account_html"]
    assert payload["positions_html"] == ""
    assert payload["auto_trade_html"] == ""
    assert payload["events_html"] == ""
    assert payload["opportunities_html"] == ""
