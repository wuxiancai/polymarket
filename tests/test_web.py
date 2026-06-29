from pathlib import Path
from datetime import datetime, timedelta, timezone

from polyarb.config import Config
from polyarb.models import BTC_ASSET, ETH_ASSET, ArbOpportunity
from polyarb.runner import PaperRunner
from polyarb.store import PaperStore
from polyarb.web import WebState, _profit_class, dashboard_payload, format_standard_time, render_dashboard


def test_dashboard_renders_chinese_status(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    html = render_dashboard([btc, eth])

    assert "Polymarket 套利模拟系统" in html
    assert "Polyarb 套利模拟系统" not in html
    assert "BTC 套利模拟" in html
    assert "ETH 套利模拟" in html
    assert "ETHStatusValue" in html
    assert "触发扫描" in html
    assert "收益概览" in html
    assert "模拟持仓" in html
    assert "纸面模拟持仓" not in html
    assert "模拟成交" in html
    assert "纸面模拟成交" not in html
    assert "Polymarket 连接日志" in html
    assert "暂无连接日志" in html
    assert "10,000.00" in html
    assert "USDT" not in html
    assert "累计预估收益" in html
    assert "累计保证收益" not in html
    assert "暂无成交" in html
    assert "最近扫描" not in html
    assert "最近盘口事件" not in html
    assert "location.reload" not in html
    assert "profit-positive" in html


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
        yes_end_date="2026-07-01T00:00:00+00:00",
        no_end_date="2026-06-29T00:00:00+00:00",
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
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    payload = dashboard_payload([btc, eth])

    assert "+9.00" in payload["portfolio"]["summary_html"]
    assert "0.09%" in payload["portfolio"]["summary_html"]
    assert "7,000.00" in payload["portfolio"]["summary_html"]
    assert "3,000.00" in payload["portfolio"]["summary_html"]
    assert "USDT" not in payload["portfolio"]["summary_html"]
    position_html = payload["portfolio"]["positions_html"]
    assert position_html.index("<th>币种</th>") < position_html.index("<th>预估收益</th>")
    assert position_html.index("<th>预估收益</th>") < position_html.index("<th>YES 持仓腿</th>")
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
    assert "0.40" not in payload["portfolio"]["positions_html"]
    assert "0.57" not in payload["portfolio"]["positions_html"]
    assert "120.00" in payload["portfolio"]["positions_html"]
    assert "171.00" in payload["portfolio"]["positions_html"]
    assert "USDT" not in payload["portfolio"]["positions_html"]
    assert "预估收益" in payload["portfolio"]["positions_html"]
    assert "2026-06-27 20:00:00" in payload["portfolio"]["positions_html"]
    assert "2026-07-01 08:00:00" in payload["portfolio"]["positions_html"]
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
    assert "0.40" not in trade_html
    assert "0.57" not in trade_html
    assert "120.00" in trade_html
    assert "171.00" in trade_html
    assert "USDT" not in trade_html
    assert "2026-07-01 08:00:00" in trade_html


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
                '2026-06-29T04:00:00+00:00', 0.07,
                '2636444', 'no-token', 'Will Ethereum dip to $1,500 June 22-28?', '',
                '2026-06-29T04:00:00+00:00', 0.91,
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
