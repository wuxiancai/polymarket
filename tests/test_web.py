from pathlib import Path
from datetime import datetime, timezone

from polyarb.config import Config
from polyarb.models import BTC_ASSET, ETH_ASSET, ArbOpportunity
from polyarb.runner import PaperRunner
from polyarb.store import PaperStore
from polyarb.web import WebState, dashboard_payload, format_standard_time, render_dashboard


def test_dashboard_renders_chinese_status(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    btc = WebState(config=config, store=store, asset=BTC_ASSET, runner=PaperRunner(config, BTC_ASSET))
    eth = WebState(config=config, store=store, asset=ETH_ASSET, runner=PaperRunner(config, ETH_ASSET))

    html = render_dashboard([btc, eth])

    assert "Polyarb 套利模拟系统" in html
    assert "Polyarb BTC 套利模拟系统" not in html
    assert "BTC 套利模拟" in html
    assert "ETH 套利模拟" in html
    assert "ETHStatusValue" in html
    assert "触发扫描" in html
    assert "收益概览" in html
    assert "纸面模拟持仓" in html
    assert "10,000.00 USDT" in html
    assert "累计收益" in html
    assert "累计保证收益" not in html
    assert "暂无纸面成交" in html
    assert "最近扫描" not in html
    assert "最近盘口事件" not in html
    assert "location.reload" not in html


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
    assert "暂无纸面成交" in payload["assets"][1]["trades_html"]
    assert "summary_html" in payload["portfolio"]


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

    assert "+9.00 USDT" in payload["portfolio"]["summary_html"]
    assert "0.09%" in payload["portfolio"]["summary_html"]
    assert "7,000.00 USDT" in payload["portfolio"]["summary_html"]
    assert "3,000.00 USDT" in payload["portfolio"]["summary_html"]
    assert "pair-btc" in payload["portfolio"]["positions_html"]
    assert "Will Bitcoin reach $70,000 in June?" in payload["portfolio"]["positions_html"]


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
