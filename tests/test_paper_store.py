from datetime import datetime, timezone
import sqlite3

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

    store.record_opportunity(opportunity)
    store.record_paper_trade(opportunity)
    rows = store.latest_trades(limit=5)

    assert len(rows) == 1
    assert rows[0]["pair_key"] == "pair-1"
    assert rows[0]["guaranteed_profit"] == 9.0
    assert rows[0]["yes_question"] == "Will Bitcoin reach $70,000 in June?"
    assert rows[0]["no_question"] == "Will Bitcoin reach $70,000 June 22-28?"
    assert rows[0]["yes_end_date"] == "2026-07-01T00:00:00+00:00"
    assert rows[0]["no_end_date"] == "2026-06-29T00:00:00+00:00"
    assert rows[0]["yes_avg_price"] == 0.40
    assert rows[0]["no_avg_price"] == 0.57


def test_paper_store_migrates_existing_trade_table(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            create table paper_trades (
                id integer primary key autoincrement,
                pair_key text not null,
                yes_market_id text not null,
                no_market_id text not null,
                shares real not null,
                total_cost real not null,
                min_payout real not null,
                guaranteed_profit real not null,
                detected_at text not null
            );
            """
        )

    store = PaperStore(db_path)
    store.initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(paper_trades)").fetchall()}

    assert {
        "yes_token_id",
        "yes_question",
        "yes_end_date",
        "yes_avg_price",
        "no_token_id",
        "no_question",
        "no_end_date",
        "no_avg_price",
    }.issubset(columns)


def test_latest_positions_excludes_settled_trades(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    store = PaperStore(db_path)
    store.initialize()
    opportunity = ArbOpportunity(
        pair_key="settled",
        kind="same_market",
        yes_market_id="m1",
        yes_token_id="y1",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="m1",
        no_token_id="n1",
        no_question="Will Bitcoin reach $70,000 in June?",
        yes_end_date="2026-06-01T00:00:00+00:00",
        no_end_date="2026-06-01T00:00:00+00:00",
        shares=100.0,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=97.0,
        min_payout=100.0,
        guaranteed_profit=3.0,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
    )

    store.record_paper_trade(opportunity)

    assert store.latest_trades(limit=5)
    assert store.latest_positions(limit=5, now=datetime(2026, 6, 2, tzinfo=timezone.utc)) == []
