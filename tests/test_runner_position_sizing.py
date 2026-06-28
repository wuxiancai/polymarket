from datetime import datetime, timezone
from pathlib import Path

from polyarb.config import Config
from polyarb.models import BTC_ASSET, ArbOpportunity
from polyarb.runner import PaperRunner


def opportunity(profit: float, total_cost: float = 1000.0) -> ArbOpportunity:
    return ArbOpportunity(
        pair_key=f"pair-{profit}",
        kind="same_market",
        yes_market_id="m1",
        yes_token_id="y1",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="m1",
        no_token_id="n1",
        no_question="Will Bitcoin reach $70,000 in June?",
        yes_end_date="2026-07-01T00:00:00+00:00",
        no_end_date="2026-07-01T00:00:00+00:00",
        shares=1000.0,
        yes_avg_price=0.40,
        no_avg_price=0.57,
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


def test_runner_uses_full_half_or_thirty_percent_position_by_profit_rate(tmp_path):
    item = runner(tmp_path)

    full = item._sized_opportunity(opportunity(profit=40.0, total_cost=1000.0))
    half = item._sized_opportunity(opportunity(profit=25.0, total_cost=1000.0))
    thirty = item._sized_opportunity(opportunity(profit=15.0, total_cost=1000.0))
    too_small = item._sized_opportunity(opportunity(profit=5.0, total_cost=1000.0))

    assert full is not None
    assert round(full.total_cost, 2) == 700.00
    assert round(full.shares, 2) == 700.00
    assert half is not None
    assert round(half.total_cost, 2) == 350.00
    assert round(half.shares, 2) == 350.00
    assert thirty is not None
    assert round(thirty.total_cost, 2) == 210.00
    assert round(thirty.shares, 2) == 210.00
    assert too_small is None
