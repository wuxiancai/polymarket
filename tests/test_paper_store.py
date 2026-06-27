from datetime import datetime, timezone

from polyarb.models import ArbOpportunity
from polyarb.store import PaperStore


def test_paper_store_records_opportunity_and_trade(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    store = PaperStore(db_path)
    store.initialize()
    opportunity = ArbOpportunity(
        pair_key="pair-1",
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

    store.record_opportunity(opportunity)
    store.record_paper_trade(opportunity)
    rows = store.latest_trades(limit=5)

    assert len(rows) == 1
    assert rows[0]["pair_key"] == "pair-1"
    assert rows[0]["guaranteed_profit"] == 9.0
