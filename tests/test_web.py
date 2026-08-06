from dataclasses import replace
from pathlib import Path
from datetime import datetime, timedelta, timezone

from polyarb.config import Config
from polyarb.models import DEFAULT_ASSETS, BTC_ASSET, ETH_ASSET, ArbOpportunity, Market, Predicate
from polyarb.runner import PaperRunner, RealtimePaperRunner, ScanResult
from polyarb.store import PaperStore
from polyarb.web import (
    WebState,
    _profit_class,
    dashboard_payload,
    format_standard_time,
    render_dashboard,
    save_allocation_settings,
)


def test_dashboard_renders_chinese_status(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    html = render_dashboard([btc, eth])

    assert "Polymarket 套利模拟系统" in html
    assert ".spread-value" in html
    assert "color: #2563eb" in html
    assert "Polyarb 套利模拟系统" not in html
    assert "BTC 套利模拟" in html
    assert "ETH 套利模拟" in html
    assert "ETHStatusValue" in html
    assert "触发扫描" in html
    assert "收益概览" in html
    assert "模拟持仓" in html
    assert "虚拟" not in html
    assert "纸面模拟持仓" not in html
    assert "模拟成交" in html
    assert "纸面模拟成交" not in html
    assert "Polymarket 连接日志" in html
    assert "暂无连接日志" in html
    assert "10,000.00" in html
    assert "USDT" not in html
    assert "累计收益" in html
    assert "累计预估收益" not in html
    assert "收益率" in html
    assert "预估收益率" not in html
    assert "累计保证收益" not in html
    assert "暂无成交" in html
    assert "最近扫描" not in html
    assert "最近盘口事件" not in html
    assert "location.reload" not in html
    assert "profit-positive" in html


def test_dashboard_renders_allocation_settings_above_earnings_overview(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))

    html = render_dashboard(state)

    assert html.index('id="allocationSettings"') < html.index("<h2>收益概览</h2>")
    for symbol in ("BTC", "ETH", "XRP", "SOL"):
        assert f'id="alloc{symbol}"' in html
    assert 'id="settingsPassword"' in html
    assert 'id="saveSettingsBtn"' in html
    assert "noneboy780308" not in html


def test_save_allocation_settings_updates_running_state_and_dashboard(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3", initial_capital_usdt=1000.0)
    store = PaperStore(config.database_path)
    store.initialize()
    states = [
        WebState(config=config, store=store, asset=asset, runner=PaperRunner(config, asset))
        for asset in DEFAULT_ASSETS
    ]

    ok, message, allocations, status = save_allocation_settings(
        states,
        {
            "allocations": {"BTC": 100, "ETH": 0, "XRP": 0, "SOL": 0},
            "password": "noneboy780308",
        },
    )

    assert ok is True
    assert status == 200
    assert message == "资金分配设置已保存。"
    assert allocations == {"BTC": 100.0, "ETH": 0.0, "XRP": 0.0, "SOL": 0.0}
    assert store.allocation_ratios() == {"BTC": 1.0, "ETH": 0.0, "XRP": 0.0, "SOL": 0.0}
    assert states[0].config.allocation_ratios["BTC"] == 1.0
    assert states[0].runner.config.allocation_ratios["ETH"] == 0.0
    payload = dashboard_payload(states)
    assert payload["settings"]["allocation_ratios"] == {"BTC": 1.0, "ETH": 0.0, "XRP": 0.0, "SOL": 0.0}
    assert "1,000.00" in payload["portfolio"]["summary_html"]


def test_save_allocation_settings_requires_password_and_100_percent_total(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3", initial_capital_usdt=1000.0)
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))

    ok, message, _allocations, status = save_allocation_settings(
        [state],
        {
            "allocations": {"BTC": 100, "ETH": 0, "XRP": 0, "SOL": 0},
            "password": "wrong-password",
        },
    )
    assert ok is False
    assert status == 401
    assert "密码错误" in message

    ok, message, _allocations, status = save_allocation_settings(
        [state],
        {
            "allocations": {"BTC": 100, "ETH": 1, "XRP": 0, "SOL": 0},
            "password": "noneboy780308",
        },
    )
    assert ok is False
    assert status == 400
    assert "100%" in message


def monitored_market(market_id: str, question: str, end_date: str, event_slug: str = "") -> Market:
    end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    return Market(
        id=market_id,
        question=question,
        slug=f"m-{market_id}",
        event_slug=event_slug or f"event-{market_id}",
        end_date=end_date,
        yes_token_id=f"{market_id}-y",
        no_token_id=f"{market_id}-n",
        volume_24h=1500.0,
        liquidity=1000.0,
        predicate=Predicate(
            kind="above",
            threshold=60000,
            period="day",
            start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end=end,
            duration_minutes=1440,
        ),
    )


def test_dashboard_shows_monitored_pairs_sorted_by_expiry(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    state.latest_result = ScanResult(
        markets=[
            monitored_market("far", "Will the price of Bitcoin be above $60,000 on August 5?", "2026-08-05T16:00:00Z"),
            monitored_market("near", "Will the price of Bitcoin be above $60,000 on August 4?", "2026-08-04T16:00:00Z"),
        ],
        pairs=2,
        opportunities=[],
        scanned_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )

    payload = dashboard_payload([state])
    html = payload["monitored_pairs_html"]

    assert "<th>序号</th>" in html
    assert html.index("on August 4") < html.index("on August 5")
    assert html.index("<td>1</td>") < html.index("<td>2</td>")
    page = render_dashboard([state])
    assert page.index("<h2>实时交易对</h2>") < page.index("<h2>模拟持仓</h2>")
    assert "monitored-pairs-scroll" in page


def test_dashboard_collapses_condition_prices_by_event(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    state.latest_result = ScanResult(
        markets=[
            monitored_market(
                "near",
                "Will the price of Bitcoin be above $60,000 on August 4?",
                "2026-08-04T16:00:00Z",
                event_slug="price-event",
            ),
            monitored_market(
                "far",
                "Will the price of Bitcoin be above $65,000 on August 4?",
                "2026-08-04T16:00:00Z",
                event_slug="price-event",
            ),
        ],
        pairs=1,
        opportunities=[],
        scanned_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )

    html = dashboard_payload([state])["monitored_pairs_html"]

    assert html.count("<td>1</td>") == 1
    assert "<td>2</td>" not in html
    assert "其他 1 个条件" in html


def test_dashboard_renders_greater_less_than_price_event(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    state.latest_result = ScanResult(
        markets=[
            monitored_market(
                "less",
                "Will the price of Bitcoin be less than $54,000 on August 4?",
                "2026-08-04T16:00:00Z",
                event_slug="bitcoin-price-on-august-4-2026",
            ),
            monitored_market(
                "greater",
                "Will the price of Bitcoin be greater than $72,000 on August 4?",
                "2026-08-04T16:00:00Z",
                event_slug="bitcoin-price-on-august-4-2026",
            ),
            monitored_market(
                "range",
                "Will the price of Bitcoin be between $54,000 and $56,000 on August 4?",
                "2026-08-04T16:00:00Z",
                event_slug="bitcoin-price-on-august-4-2026",
            ),
        ],
        pairs=3,
        opportunities=[],
        scanned_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )

    html = dashboard_payload([state])["monitored_pairs_html"]

    assert "What price will Bitcoin be on August 4?" in html
    assert "↓ 54,000" in html
    assert "↑ 72,000" in html
    assert "54,000-56,000" in html


def test_dashboard_monitored_pairs_falls_back_to_realtime_runner_markets(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    runner = RealtimePaperRunner(config, BTC_ASSET)
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=runner)
    runner.markets = [
        monitored_market(
            "near",
            "Will the price of Bitcoin be above $60,000 on August 4?",
            "2026-08-04T16:00:00Z",
            event_slug="price-event",
        )
    ]

    html = dashboard_payload([state])["monitored_pairs_html"]

    assert "What price will Bitcoin be on August 4?" in html
    assert "等待首次扫描" not in html


def test_dashboard_renders_xrp_and_solana_asset_panels(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    states = [
        WebState(config=config, store=store, asset=asset, runner=PaperRunner(config, asset))
        for asset in DEFAULT_ASSETS
    ]

    html = render_dashboard(states)

    for symbol in ("BTC", "ETH", "XRP", "SOL"):
        assert f"{symbol} 套利模拟" in html
        assert f"{symbol}StatusValue" in html
        assert f"{symbol}OpportunityTable" in html


def test_dashboard_tables_are_left_aligned_and_content_sized(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    html = render_dashboard([btc, eth])

    assert "table { width: max-content; min-width: 100%; border-collapse: collapse; font-size: 14px; table-layout: auto; }" in html
    assert "th, td { padding: 11px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }" in html
    assert "table-layout: fixed" not in html
    assert ".wide-table .id-col" not in html
    assert "table { min-width: 760px; }" not in html


def test_dashboard_has_mobile_browser_layout_css(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    store.record_opportunity(
        ArbOpportunity(
            pair_key="mobile-layout",
            kind="same_market",
            yes_market_id="yes-mobile",
            yes_token_id="yes-token-mobile",
            yes_question="Will Bitcoin reach $70,000 in June?",
            no_market_id="no-mobile",
            no_token_id="no-token-mobile",
            no_question="Will Bitcoin reach $70,000 in June?",
            yes_event_slug="what-price-will-bitcoin-hit-in-june",
            no_event_slug="what-price-will-bitcoin-hit-in-june",
            yes_end_date="2099-07-01T00:00:00+00:00",
            no_end_date="2099-07-01T00:00:00+00:00",
            shares=100,
            yes_avg_price=0.40,
            no_avg_price=0.57,
            total_cost=97,
            min_payout=100,
            guaranteed_profit=3,
            edge_per_share=0.03,
            executable=True,
            reason="executable",
            detected_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        )
    )
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    html = render_dashboard([btc, eth])

    assert "@media (max-width: 760px)" in html
    assert "@media (max-width: 640px)" in html
    assert ".wrap { width: 100%; padding: 0 12px; }" in html
    assert ".toolbar { width: 100%; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }" in html
    assert ".table-scroll, .log-scroll { max-height: none; overflow: visible; }" in html
    assert "table td { display: grid; grid-template-columns: 96px minmax(0, 1fr);" in html
    assert ".portfolio-table td:nth-child(2)::before { content: \"分配本金\"; }" in html
    assert ".opportunity-table td:nth-child(5)::before { content: \"YES 交易对\"; }" in html
    assert ".trade-table td:nth-child(5)::before { content: \"交易币对\"; }" in html
    assert ".open-position-table td:nth-child(6)::before { content: \"交易币对\"; }" in html
    assert ".settled-position-table td:nth-child(7)::before { content: \"交易币对\"; }" in html
    assert ".open-position-table td:nth-child(15)::before { content: \"开仓时间\"; }" in html
    assert ".settled-position-table td:nth-child(16)::before { content: \"开仓时间\"; }" in html
    assert "YES 持仓腿" not in html
    assert "NO 持仓腿" not in html
    assert ".log-table td:nth-child(4)::before { content: \"事件\"; }" in html
    assert "<table class='portfolio-table'>" in html
    assert "<table class='opportunity-table'>" in html


def test_dashboard_shows_realtime_listening_status(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(
        config=config,
        store=store,
        asset=BTC_ASSET,
        runner=PaperRunner(config, BTC_ASSET),
        running=True,
        realtime=True,
    )

    html = render_dashboard(state)

    assert "实时监听中" in html


def test_dashboard_header_shows_live_clock_and_runtime(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))

    html = render_dashboard(state)

    assert "当前时间" in html
    assert "运行时间" in html
    assert 'id="currentTimeValue"' in html
    assert 'id="runDurationValue"' in html
    assert 'data-started-at="' in html
    assert "timeZone: 'Asia/Shanghai'" in html
    assert "updateRuntimeClock" in html
    assert "setInterval(updateRuntimeClock, 1000)" in html


def test_dashboard_runtime_starts_at_earliest_database_data_time(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    with store._connect() as conn:
        conn.execute(
            """
            insert into opportunities (
                pair_key, kind, yes_market_id, yes_token_id, yes_question, yes_event_slug, yes_end_date,
                no_market_id, no_token_id, no_question, no_event_slug, no_end_date, shares, yes_avg_price,
                no_avg_price, total_cost, min_payout, guaranteed_profit,
                edge_per_share, executable, reason, detected_at
            )
            values (
                'newer', 'same_market', 'm1', 'y1', 'Will Bitcoin reach $70,000 in June?', '', '',
                'm1', 'n1', 'Will Bitcoin reach $70,000 in June?', '', '', 100, 0.40,
                0.57, 97, 100, 3, 0.03, 1, 'executable', '2026-06-27T12:00:00+00:00'
            )
            """
        )
        conn.execute(
            """
            insert into paper_trades (
                pair_key, yes_market_id, yes_token_id, yes_question, yes_event_slug, yes_end_date, yes_avg_price,
                no_market_id, no_token_id, no_question, no_event_slug, no_end_date, no_avg_price, shares,
                total_cost, min_payout, guaranteed_profit, is_virtual, detected_at
            )
            values (
                'older', 'm2', 'y2', 'Will Bitcoin reach $65,000 in June?', '', '', 0.40,
                'm2', 'n2', 'Will Bitcoin reach $65,000 in June?', '', '', 0.57, 100,
                97, 100, 3, 0, '2026-06-26T08:30:00+00:00'
            )
            """
        )
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))

    html = render_dashboard(state)

    assert 'data-started-at="2026-06-26T08:30:00+00:00"' in html


def test_dashboard_refresh_preserves_table_scroll_positions(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    html = render_dashboard([btc, eth])

    assert "function updateHtmlPreservingScroll(containerId, html)" in html
    assert "scroller.scrollTop = position.top" in html
    assert "scroller.scrollLeft = position.left" in html
    for target in (
        "settledPositionTable",
    ):
        assert f"updateHtmlPreservingScroll('{target}'" in html
        assert f"document.getElementById('{target}').innerHTML" not in html
    for target in (
        "BTCOpportunityTable",
        "BTCTradeTable",
        "ETHOpportunityTable",
        "ETHTradeTable",
    ):
        assert f'id="{target}"' in html
    assert "updateHtmlPreservingScroll(asset.symbol + 'OpportunityTable', asset.opportunities_html)" in html
    assert "updateHtmlPreservingScroll(asset.symbol + 'TradeTable', asset.trades_html)" in html
    assert "document.getElementById(asset.symbol + 'OpportunityTable').innerHTML" not in html
    assert "document.getElementById(asset.symbol + 'TradeTable').innerHTML" not in html


def test_dashboard_payload_contains_fragments(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    btc = WebState(
        config=config,
        store=store,
        asset=BTC_ASSET,
        runner=PaperRunner(config, BTC_ASSET),
        running=True,
        realtime=True,
    )
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    payload = dashboard_payload([btc, eth])

    assert payload["assets"][0]["symbol"] == "BTC"
    assert payload["assets"][0]["status_text"] == "实时监听中"
    assert payload["assets"][1]["symbol"] == "ETH"
    assert "暂无成交" in payload["assets"][1]["trades_html"]
    assert "summary_html" in payload["portfolio"]
    assert "connection_log_html" in payload


def test_dashboard_connection_log_updates(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    state.add_connection_log("info", "Gamma API 正在拉取 BTC 市场")
    state.add_connection_log("error", "request failed: https://gamma-api.polymarket.com/events: [Errno 101] Network is unreachable")

    payload = dashboard_payload(state)

    assert "Gamma API 正在拉取 BTC 市场" in payload["connection_log_html"]
    assert "行情源连接失败" in payload["connection_log_html"]
    assert "BTC" in payload["connection_log_html"]
    assert "class='log-scroll'" in payload["connection_log_html"]
    html = render_dashboard(state)
    assert ".table-scroll { max-height: 356px; overflow-y: auto; overflow-x: auto; }" in html
    assert ".log-scroll { max-height: 356px; overflow-y: auto; overflow-x: auto; }" in html


def test_dashboard_uses_shared_id_sequence_across_assets_and_tables(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))
    btc_opportunity = ArbOpportunity(
        pair_key="id-btc",
        kind="implication",
        yes_market_id="btc-yes",
        yes_token_id="btc-y",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="btc-no",
        no_token_id="btc-n",
        no_question="Will Bitcoin reach $70,000 in June?",
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-in-june",
        yes_end_date="2099-07-01T00:00:00+00:00",
        no_end_date="2099-07-01T00:00:00+00:00",
        yes_avg_price=0.40,
        no_avg_price=0.57,
        shares=100,
        total_cost=97,
        min_payout=100,
        guaranteed_profit=3,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )
    eth_opportunity = ArbOpportunity(
        pair_key="id-eth",
        kind="implication",
        yes_market_id="eth-yes",
        yes_token_id="eth-y",
        yes_question="Will Ethereum dip to $1,500 June 22-28?",
        no_market_id="eth-no",
        no_token_id="eth-n",
        no_question="Will Ethereum dip to $1,500 June 22-28?",
        yes_event_slug="what-price-will-ethereum-hit-june-22-28-2026",
        no_event_slug="what-price-will-ethereum-hit-june-22-28-2026",
        yes_end_date="2099-07-01T00:00:00+00:00",
        no_end_date="2099-07-01T00:00:00+00:00",
        yes_avg_price=0.40,
        no_avg_price=0.57,
        shares=100,
        total_cost=97,
        min_payout=100,
        guaranteed_profit=3,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 1, tzinfo=timezone.utc),
    )
    store.record_opportunity(btc_opportunity)
    store.record_paper_trade(btc_opportunity)
    store.record_opportunity(eth_opportunity)

    payload = dashboard_payload([btc, eth])

    assert payload["portfolio"]["positions_html"].startswith("<div class='table-scroll'><table")
    assert "<th>ID</th><th>币种</th>" in payload["portfolio"]["positions_html"]
    assert "<th>ID</th><th>价差</th>" in payload["assets"][0]["trades_html"]
    assert "<th>ID</th><th>状态</th>" in payload["assets"][0]["opportunities_html"]
    assert "<tr><td>1</td><td>BTC</td>" in payload["portfolio"]["positions_html"]
    assert "<tr><td>1</td><td><span class='spread-value'>3.00¢</span>" in payload["assets"][0]["trades_html"]
    assert "<tr><td>1</td><td><span class='pill done'>已成交</span>" in payload["assets"][0]["opportunities_html"]
    assert "<tr><td>2</td><td><span class='pill exec'>可模拟成交</span>" in payload["assets"][1]["opportunities_html"]


def test_dashboard_shows_profit_and_positions(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    opportunity = ArbOpportunity(
        pair_key="pair-btc",
        kind="implication",
        yes_market_id="month70",
        yes_token_id="y-month",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="week70",
        no_token_id="n-week",
        no_question="Will Bitcoin reach $70,000 June 22-28?",
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-june-22-28-2026",
        yes_end_date="2099-07-01T00:00:00+00:00",
        no_end_date="2099-06-29T00:00:00+00:00",
        shares=300.0,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=291.0,
        min_payout=300.0,
        guaranteed_profit=9.0,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )
    store.record_paper_trade(opportunity)
    settled_opportunity = ArbOpportunity(
        pair_key="settled-btc",
        kind="implication",
        yes_market_id="settled-month70",
        yes_token_id="settled-y-month",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="settled-week70",
        no_token_id="settled-n-week",
        no_question="Will Bitcoin reach $70,000 June 22-28?",
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-june-22-28-2026",
        yes_end_date="2020-06-28T00:00:00+00:00",
        no_end_date="2020-06-28T00:00:00+00:00",
        shares=200.0,
        yes_avg_price=0.40,
        no_avg_price=0.575,
        total_cost=195.0,
        min_payout=200.0,
        guaranteed_profit=5.0,
        edge_per_share=0.025,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 11, 0, tzinfo=timezone.utc),
    )
    store.record_paper_trade(settled_opportunity)
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    payload = dashboard_payload([btc, eth])

    settled_html = payload["portfolio"]["settled_positions_html"]
    assert "已结束持仓收益" in render_dashboard([btc, eth])
    assert "settled-btc" not in settled_html
    assert "<th>交易对</th>" not in settled_html
    assert "<th>交易币对</th>" in settled_html
    assert "<th>YES 持仓腿</th>" not in settled_html
    assert "<th>NO 持仓腿</th>" not in settled_html
    assert "<th>币种</th>" in settled_html
    assert "<th>收益</th>" in settled_html
    assert "<th>收益率</th>" in settled_html
    assert "<th>结束时间UTC+8</th>" in settled_html
    assert "+5.00" in settled_html
    assert "2.56%" in settled_html
    assert "What price will Bitcoin hit in June?" in settled_html
    assert "条件：↑ 70,000" in settled_html
    assert "40.00¢" in settled_html
    assert "57.50¢" in settled_html
    assert "2.50¢" in settled_html
    assert "<span class='time-date'>2020-06-28</span><span class='time-clock'>08:00:00</span>" in settled_html

    assert "+5.00" in payload["portfolio"]["summary_html"]
    assert "970.00" not in payload["portfolio"]["summary_html"]
    assert "+30.00" not in payload["portfolio"]["summary_html"]
    assert "+9.00" not in payload["portfolio"]["summary_html"]
    assert "0.05%" in payload["portfolio"]["summary_html"]
    assert "累计收益" in payload["portfolio"]["summary_html"]
    assert "累计预估收益" not in payload["portfolio"]["summary_html"]
    assert "<th>收益</th>" in payload["portfolio"]["summary_html"]
    assert "<th>收益率</th>" in payload["portfolio"]["summary_html"]
    assert "<th>预估收益</th>" not in payload["portfolio"]["summary_html"]
    assert "<th>预估收益率</th>" not in payload["portfolio"]["summary_html"]
    assert "4,000.00" in payload["portfolio"]["summary_html"]
    assert "3,000.00" in payload["portfolio"]["summary_html"]
    assert "USDT" not in payload["portfolio"]["summary_html"]
    position_html = payload["portfolio"]["positions_html"]
    assert position_html.index("<th>币种</th>") < position_html.index("<th>预估收益</th>")
    assert position_html.index("<th>预估收益</th>") < position_html.index("<th>价差</th>")
    assert position_html.index("<th>价差</th>") < position_html.index("<th>结算时间UTC+8</th>")
    assert position_html.index("<th>结算时间UTC+8</th>") < position_html.index("<th>交易币对</th>")
    assert "<th>YES 持仓腿</th>" not in position_html
    assert "<th>NO 持仓腿</th>" not in position_html
    assert "<th>结算时间</th>" not in position_html
    assert "pair-btc" not in payload["portfolio"]["positions_html"]
    assert "<th>交易对</th>" not in payload["portfolio"]["positions_html"]
    assert "Will Bitcoin reach $70,000 in June?" not in payload["portfolio"]["positions_html"]
    assert "https://polymarket.com/event/what-price-will-bitcoin-hit-in-june" in payload["portfolio"]["positions_html"]
    assert "class='trade-table" in payload["portfolio"]["positions_html"]
    assert "class='market-card" in payload["portfolio"]["positions_html"]
    assert "class='market-event'" in payload["portfolio"]["positions_html"]
    assert "class='market-condition'" in payload["portfolio"]["positions_html"]
    assert "事件：" not in payload["portfolio"]["positions_html"]
    assert "What price will Bitcoin hit in June?" in payload["portfolio"]["positions_html"]
    assert "条件：↑ 70,000" in payload["portfolio"]["positions_html"]
    assert "YES 数量" in payload["portfolio"]["positions_html"]
    assert "YES 价格" in payload["portfolio"]["positions_html"]
    assert "YES 金额" in payload["portfolio"]["positions_html"]
    assert "NO 数量" in payload["portfolio"]["positions_html"]
    assert "NO 价格" in payload["portfolio"]["positions_html"]
    assert "NO 金额" in payload["portfolio"]["positions_html"]
    assert "结算时间" in payload["portfolio"]["positions_html"]
    assert "YES 份额" not in payload["portfolio"]["positions_html"]
    assert "NO 份额" not in payload["portfolio"]["positions_html"]
    assert "300.00" in payload["portfolio"]["positions_html"]
    assert "300.0000" not in payload["portfolio"]["positions_html"]
    assert "40.00¢" in payload["portfolio"]["positions_html"]
    assert "57.00¢" in payload["portfolio"]["positions_html"]
    assert "<span class='spread-value'>3.00¢</span>" in payload["portfolio"]["positions_html"]
    assert "0.40" not in payload["portfolio"]["positions_html"]
    assert "0.57" not in payload["portfolio"]["positions_html"]
    assert "120.00" in payload["portfolio"]["positions_html"]
    assert "171.00" in payload["portfolio"]["positions_html"]
    assert "USDT" not in payload["portfolio"]["positions_html"]
    assert "预估收益" in payload["portfolio"]["positions_html"]
    assert "<span class='time-date'>2026-06-27</span><span class='time-clock'>20:00:00</span>" in payload["portfolio"]["positions_html"]
    assert "<span class='time-date'>2099-07-01</span><span class='time-clock'>08:00:00</span>" in payload["portfolio"]["positions_html"]
    assert "2026-06-27 20:00:00" not in payload["portfolio"]["positions_html"]
    assert "2099-07-01 08:00:00" not in payload["portfolio"]["positions_html"]
    assert "2026-06-27T12:00:00+00:00" not in payload["portfolio"]["positions_html"]

    trade_html = payload["assets"][0]["trades_html"]
    assert "https://polymarket.com/event/what-price-will-bitcoin-hit-in-june" in trade_html
    assert "pair-btc" not in trade_html
    assert "<th>交易对</th>" not in trade_html
    assert "class='trade-table" in trade_html
    assert "class='market-card" in trade_html
    assert "事件：" not in trade_html
    assert "What price will Bitcoin hit in June?" in trade_html
    assert "条件：↑ 70,000" in trade_html
    assert "YES 数量" in trade_html
    assert "YES 价格" in trade_html
    assert "YES 金额" in trade_html
    assert trade_html.index("<th>价差</th>") < trade_html.index("<th>预估收益</th>")
    assert trade_html.index("<th>预估收益</th>") < trade_html.index("<th>结算时间UTC+8</th>")
    assert trade_html.index("<th>结算时间UTC+8</th>") < trade_html.index("<th>交易币对</th>")
    assert "<th>YES 持仓腿</th>" not in trade_html
    assert "<th>NO 持仓腿</th>" not in trade_html
    assert "<th>结算时间</th>" not in trade_html
    assert "NO 数量" in trade_html
    assert "NO 价格" in trade_html
    assert "NO 金额" in trade_html
    assert "结算时间" in trade_html
    assert "YES 份额" not in trade_html
    assert "NO 份额" not in trade_html
    assert "300.00" in trade_html
    assert "300.0000" not in trade_html
    assert "40.00¢" in trade_html
    assert "57.00¢" in trade_html
    assert "<span class='spread-value'>3.00¢</span>" in trade_html
    assert "0.40" not in trade_html
    assert "0.57" not in trade_html
    assert "120.00" in trade_html
    assert "171.00" in trade_html
    assert "USDT" not in trade_html
    assert "<span class='time-date'>2099-07-01</span><span class='time-clock'>08:00:00</span>" in trade_html
    assert "2099-07-01 08:00:00" not in trade_html


def test_opportunity_table_hides_internal_english_reason(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    opportunity = ArbOpportunity(
        pair_key="pair-btc",
        kind="same_market",
        yes_market_id="m1",
        yes_token_id="y1",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="m1",
        no_token_id="n1",
        no_question="Will Bitcoin reach $70,000 in June?",
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-in-june",
        yes_end_date="2026-07-01T00:00:00+00:00",
        no_end_date="2026-07-01T00:00:00+00:00",
        shares=300.0,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=291.0,
        min_payout=300.0,
        guaranteed_profit=9.0,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )
    store.record_opportunity(opportunity)
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))

    payload = dashboard_payload([state])

    html = payload["assets"][0]["opportunities_html"]
    assert "可模拟成交" in html
    assert "https://polymarket.com/event/what-price-will-bitcoin-hit-in-june" in html
    assert "9.00" in html
    assert "9.0</td>" not in html
    assert "executable" not in html


def test_opportunity_table_shows_spread_and_execution_state(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    traded = ArbOpportunity(
        pair_key="traded-btc",
        kind="same_market",
        yes_market_id="m1",
        yes_token_id="y1",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="m1",
        no_token_id="n1",
        no_question="Will Bitcoin reach $70,000 in June?",
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-in-june",
        yes_end_date="2026-07-01T00:00:00+00:00",
        no_end_date="2026-07-01T00:00:00+00:00",
        shares=300.0,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=291.0,
        min_payout=300.0,
        guaranteed_profit=9.0,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )
    thin_spread = ArbOpportunity(
        pair_key="thin-btc",
        kind="same_market",
        yes_market_id="m2",
        yes_token_id="y2",
        yes_question="Will Bitcoin reach $75,000 in June?",
        no_market_id="m2",
        no_token_id="n2",
        no_question="Will Bitcoin reach $75,000 in June?",
        yes_event_slug="will-bitcoin-reach-75000-in-june",
        no_event_slug="will-bitcoin-reach-75000-in-june",
        yes_end_date="2026-07-01T00:00:00+00:00",
        no_end_date="2026-07-01T00:00:00+00:00",
        shares=300.0,
        yes_avg_price=0.40,
        no_avg_price=0.585,
        total_cost=295.5,
        min_payout=300.0,
        guaranteed_profit=4.5,
        edge_per_share=0.015,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 1, tzinfo=timezone.utc),
    )
    no_trade_boundary = ArbOpportunity(
        pair_key="no-trade-boundary-btc",
        kind="same_market",
        yes_market_id="m4",
        yes_token_id="y4",
        yes_question="Will Bitcoin reach $85,000 in June?",
        no_market_id="m4",
        no_token_id="n4",
        no_question="Will Bitcoin reach $85,000 in June?",
        yes_event_slug="will-bitcoin-reach-85000-in-june",
        no_event_slug="will-bitcoin-reach-85000-in-june",
        yes_end_date="2026-07-01T00:00:00+00:00",
        no_end_date="2026-07-01T00:00:00+00:00",
        shares=300.0,
        yes_avg_price=0.40,
        no_avg_price=0.575,
        total_cost=292.5,
        min_payout=300.0,
        guaranteed_profit=7.5,
        edge_per_share=0.025,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 3, tzinfo=timezone.utc),
    )
    executable_boundary = ArbOpportunity(
        pair_key="executable-boundary-btc",
        kind="same_market",
        yes_market_id="m5",
        yes_token_id="y5",
        yes_question="Will Bitcoin reach $90,000 in June?",
        no_market_id="m5",
        no_token_id="n5",
        no_question="Will Bitcoin reach $90,000 in June?",
        yes_event_slug="will-bitcoin-reach-90000-in-june",
        no_event_slug="will-bitcoin-reach-90000-in-june",
        yes_end_date="2026-07-01T00:00:00+00:00",
        no_end_date="2026-07-01T00:00:00+00:00",
        shares=300.0,
        yes_avg_price=0.40,
        no_avg_price=0.574,
        total_cost=292.2,
        min_payout=300.0,
        guaranteed_profit=7.8,
        edge_per_share=0.026,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 4, tzinfo=timezone.utc),
    )
    cooldown_duplicate = replace(
        traded,
        guaranteed_profit=12.0,
        shares=400.0,
        total_cost=388.0,
        min_payout=400.0,
        detected_at=datetime(2026, 6, 27, 12, 0, 10, tzinfo=timezone.utc),
    )
    executable = ArbOpportunity(
        pair_key="open-btc",
        kind="same_market",
        yes_market_id="m3",
        yes_token_id="y3",
        yes_question="Will Bitcoin reach $80,000 in June?",
        no_market_id="m3",
        no_token_id="n3",
        no_question="Will Bitcoin reach $80,000 in June?",
        yes_event_slug="will-bitcoin-reach-80000-in-june",
        no_event_slug="will-bitcoin-reach-80000-in-june",
        yes_end_date="2026-07-01T00:00:00+00:00",
        no_end_date="2026-07-01T00:00:00+00:00",
        shares=300.0,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=291.0,
        min_payout=300.0,
        guaranteed_profit=9.0,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 2, tzinfo=timezone.utc),
    )
    for opportunity in (traded, cooldown_duplicate, thin_spread, executable, no_trade_boundary, executable_boundary):
        store.record_opportunity(opportunity)
    store.record_paper_trade(traded)
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))

    payload = dashboard_payload([state])

    html = payload["assets"][0]["opportunities_html"]
    assert html.index("<th>状态</th>") < html.index("<th>价差</th>")
    assert html.index("<th>价差</th>") < html.index("<th>保证利润</th>")
    assert "已成交" in html
    assert "冷却中" in html
    assert "同交易对冷却中" in html
    assert "可模拟成交" in html
    assert "仅观察" in html
    assert "<span class='spread-value'>3.00¢</span>" in html
    assert "<span class='spread-value'>2.50¢</span>" in html
    assert "<span class='spread-value'>2.60¢</span>" in html
    assert "<span class='pill watch'>仅观察</span></td><td><span class='spread-value'>2.50¢</span>" in html
    assert "<span class='pill exec'>可模拟成交</span></td><td><span class='spread-value'>2.60¢</span>" in html
    assert "<span class='spread-value'>1.50¢</span>" in html


def test_dashboard_infers_event_link_and_condition_for_legacy_rows(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    with store._connect() as conn:
        conn.execute(
            """
            insert into paper_trades (
                pair_key, yes_market_id, yes_token_id, yes_question, yes_event_slug,
                yes_end_date, yes_avg_price, no_market_id, no_token_id, no_question,
                no_event_slug, no_end_date, no_avg_price, shares, total_cost,
                min_payout, guaranteed_profit, detected_at
            )
            values (
                'same:2636444', '2636444', 'yes-token',
                'Will Ethereum dip to $1,500 June 22-28?', '',
                '2099-06-29T04:00:00+00:00', 0.07,
                '2636444', 'no-token', 'Will Ethereum dip to $1,500 June 22-28?', '',
                '2099-06-29T04:00:00+00:00', 0.91,
                538.62, 526.18, 538.62, 12.43544, '2026-06-28T08:10:13+00:00'
            )
            """
        )
    state = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    payload = dashboard_payload([state])
    html = payload["portfolio"]["positions_html"]

    assert "https://polymarket.com/event/what-price-will-ethereum-hit-june-22-28-2026" in html
    assert "事件：" not in html
    assert "What price will Ethereum hit June 22-28?" in html
    assert "条件：↓ 1,500" in html


def test_dashboard_hides_settled_positions(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    settled_at = datetime.now(timezone.utc) - timedelta(days=1)
    opportunity = ArbOpportunity(
        pair_key="settled-btc",
        kind="same_market",
        yes_market_id="m1",
        yes_token_id="y1",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="m1",
        no_token_id="n1",
        no_question="Will Bitcoin reach $70,000 in June?",
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-in-june",
        yes_end_date=settled_at.isoformat(),
        no_end_date=settled_at.isoformat(),
        shares=100.0,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=97.0,
        min_payout=100.0,
        guaranteed_profit=3.0,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )
    store.record_paper_trade(opportunity)
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))

    payload = dashboard_payload([btc])

    assert "暂无持仓" in payload["portfolio"]["positions_html"]
    assert "+3.00" in payload["portfolio"]["settled_positions_html"]
    assert "settled-btc" not in payload["portfolio"]["positions_html"]


def test_dashboard_shortens_network_error(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    state.latest_error = (
        "request failed: https://gamma-api.polymarket.com/events?tag_slug=bitcoin"
        "&closed=false&active=true&limit=500: <urlopen error [Errno 101] Network is unreachable>"
    )

    html = render_dashboard(state)

    assert "BTC: 行情源连接失败" in html
    assert "tag_slug=bitcoin" not in html


def test_standard_time_is_precise_to_seconds():
    value = datetime(2026, 6, 27, 12, 39, 35, 953435, tzinfo=timezone.utc)

    assert format_standard_time(value) == "2026-06-27 20:39:35"


def test_profit_class_uses_green_for_win_and_red_for_loss():
    assert _profit_class(0) == "profit-positive"
    assert _profit_class(0.1) == "profit-positive"
    assert _profit_class(-0.1) == "profit-negative"
