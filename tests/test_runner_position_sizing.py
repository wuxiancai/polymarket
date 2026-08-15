from datetime import datetime, timezone
from pathlib import Path

from polyarb.config import Config
from polyarb.models import BTC_ASSET, ETH_ASSET, ArbOpportunity
from polyarb.runner import PaperRunner


def opportunity(profit: float, total_cost: float = 1000.0, spread_cents: float = 3.0) -> ArbOpportunity:
    yes_price = 0.40
    no_price = 1 - yes_price - (spread_cents / 100)
    return ArbOpportunity(
        pair_key=f"pair-{profit}-{spread_cents}",
        kind="same_market",
        yes_market_id="m1",
        yes_token_id="y1",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="m1",
        no_token_id="n1",
        no_question="Will Bitcoin reach $70,000 in June?",
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-in-june",
        yes_end_date="2099-07-01T00:00:00+00:00",
        no_end_date="2099-07-01T00:00:00+00:00",
        shares=1000.0,
        yes_avg_price=yes_price,
        no_avg_price=no_price,
        total_cost=total_cost,
        min_payout=1000.0,
        guaranteed_profit=profit,
        edge_per_share=profit / 1000.0,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )


def runner(tmp_path) -> PaperRunner:
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3", initial_capital_usdt=1000.0)
    item = PaperRunner(config, BTC_ASSET)
    item.store.initialize()
    return item


def test_runner_uses_fixed_risk_caps_instead_of_spread_tiers(tmp_path):
    item = runner(tmp_path)

    full = item._sized_opportunity(opportunity(profit=54.0, total_cost=1000.0, spread_cents=5.4))
    sixty = item._sized_opportunity(opportunity(profit=53.0, total_cost=1000.0, spread_cents=5.3))
    thirty = item._sized_opportunity(opportunity(profit=45.0, total_cost=1000.0, spread_cents=4.5))
    at_minimum = item._sized_opportunity(
        opportunity(profit=31.0, total_cost=1000.0, spread_cents=3.1)
    )
    too_small = item._sized_opportunity(opportunity(profit=30.0, total_cost=1000.0, spread_cents=3.0))

    assert full is not None
    assert round(full.total_cost, 2) == 100.00
    assert round(full.shares, 2) == 100.00
    assert sixty is not None
    assert round(sixty.total_cost, 2) == 100.00
    assert round(sixty.shares, 2) == 100.00
    assert thirty is not None
    assert round(thirty.total_cost, 2) == 100.00
    assert round(thirty.shares, 2) == 100.00
    assert at_minimum is not None
    assert round(at_minimum.total_cost, 2) == 100.00
    assert round(at_minimum.shares, 2) == 100.00
    assert too_small is not None


def test_runner_respects_risk_cap_within_current_asset_allocation(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3", initial_capital_usdt=1000.0)
    item = PaperRunner(config, ETH_ASSET)
    item.store.initialize()

    sized = item._sized_opportunity(opportunity(profit=31.0, total_cost=1000.0, spread_cents=3.1))

    assert sized is not None
    assert round(sized.total_cost, 2) == 100.00
    assert round(sized.shares, 2) == 100.00


def test_runner_uses_config_allocation_ratios(tmp_path):
    config = Config(
        database_path=Path(tmp_path) / "paper.sqlite3",
        initial_capital_usdt=1000.0,
        allocation_ratios={"BTC": 1.0, "ETH": 0.0, "XRP": 0.0, "SOL": 0.0},
    )
    btc = PaperRunner(config, BTC_ASSET)
    btc.store.initialize()

    sized = btc._sized_opportunity(opportunity(profit=54.0, total_cost=1000.0, spread_cents=5.4))

    assert sized is not None
    assert round(sized.total_cost, 2) == 100.00

    eth = PaperRunner(config, ETH_ASSET)
    eth.store.initialize()

    assert eth._sized_opportunity(opportunity(profit=54.0, total_cost=1000.0, spread_cents=5.4)) is None


def test_runner_skips_opportunity_when_capital_is_insufficient(tmp_path):
    item = runner(tmp_path)
    used = opportunity(profit=27.9998, total_cost=699.995)
    item.store.record_paper_trade(used)

    assert item._sized_opportunity(opportunity(profit=30.0, total_cost=1000.0)) is None
