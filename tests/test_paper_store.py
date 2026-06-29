from datetime import datetime, timedelta, timezone
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

    store.record_opportunity(opportunity)
    store.record_paper_trade(opportunity)
    rows = store.latest_trades(limit=5)

    assert len(rows) == 1
    assert rows[0]["pair_key"] == "pair-1"
    assert rows[0]["guaranteed_profit"] == 9.0
    assert rows[0]["yes_question"] == "Will Bitcoin reach $70,000 in June?"
    assert rows[0]["no_question"] == "Will Bitcoin reach $70,000 June 22-28?"
    assert rows[0]["yes_event_slug"] == "what-price-will-bitcoin-hit-in-june"
    assert rows[0]["no_event_slug"] == "what-price-will-bitcoin-hit-june-22-28-2026"
    assert rows[0]["yes_end_date"] == "2026-07-01T00:00:00+00:00"
    assert rows[0]["no_end_date"] == "2026-06-29T00:00:00+00:00"
    assert rows[0]["yes_avg_price"] == 0.40
    assert rows[0]["no_avg_price"] == 0.57


def test_paper_store_ignores_dust_trade_that_would_render_as_zero(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    store = PaperStore(db_path)
    store.initialize()
    opportunity = ArbOpportunity(
        pair_key="dust",
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
        shares=0.004,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=0.00388,
        min_payout=0.004,
        guaranteed_profit=0.00012,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )

    store.record_paper_trade(opportunity)

    assert store.latest_trades(limit=5) == []


def test_paper_store_lists_settled_trades_separately_from_positions(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    store = PaperStore(db_path)
    store.initialize()
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    open_trade = ArbOpportunity(
        pair_key="open-btc",
        kind="implication",
        yes_market_id="open-yes",
        yes_token_id="open-y",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="open-no",
        no_token_id="open-n",
        no_question="Will Bitcoin reach $70,000 June 22-28?",
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-june-22-28-2026",
        yes_end_date=(now + timedelta(days=1)).isoformat(),
        no_end_date=(now + timedelta(days=1)).isoformat(),
        shares=100.0,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=97.0,
        min_payout=100.0,
        guaranteed_profit=3.0,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=now - timedelta(hours=2),
    )
    settled_trade = ArbOpportunity(
        pair_key="settled-btc",
        kind="implication",
        yes_market_id="settled-yes",
        yes_token_id="settled-y",
        yes_question="Will Bitcoin reach $70,000 in June?",
        no_market_id="settled-no",
        no_token_id="settled-n",
        no_question="Will Bitcoin reach $70,000 June 22-28?",
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-june-22-28-2026",
        yes_end_date=(now - timedelta(minutes=1)).isoformat(),
        no_end_date=(now - timedelta(minutes=1)).isoformat(),
        shares=100.0,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=97.0,
        min_payout=100.0,
        guaranteed_profit=3.0,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=now - timedelta(hours=1),
    )

    store.record_paper_trade(open_trade)
    store.record_paper_trade(settled_trade)

    positions = store.latest_positions(now=now)
    settled = store.latest_settled_trades(now=now)

    assert [row["pair_key"] for row in positions] == ["open-btc"]
    assert [row["pair_key"] for row in settled] == ["settled-btc"]


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
        "yes_event_slug",
        "yes_end_date",
        "yes_avg_price",
        "no_token_id",
        "no_question",
        "no_event_slug",
        "no_end_date",
        "no_avg_price",
    }.issubset(columns)


def test_paper_store_backfills_existing_trade_prices_from_matching_opportunity(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    detected_at = "2026-06-28T08:10:13.548760+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            create table opportunities (
                id integer primary key autoincrement,
                pair_key text not null,
                kind text not null,
                yes_market_id text not null,
                yes_token_id text not null,
                yes_question text not null,
                no_market_id text not null,
                no_token_id text not null,
                no_question text not null,
                shares real not null,
                yes_avg_price real not null,
                no_avg_price real not null,
                total_cost real not null,
                min_payout real not null,
                guaranteed_profit real not null,
                edge_per_share real not null,
                executable integer not null,
                reason text not null,
                detected_at text not null
            );
            create table paper_trades (
                id integer primary key autoincrement,
                pair_key text not null,
                yes_market_id text not null,
                yes_token_id text not null default '',
                yes_question text not null default '',
                no_market_id text not null,
                no_token_id text not null default '',
                no_question text not null default '',
                shares real not null,
                total_cost real not null,
                min_payout real not null,
                guaranteed_profit real not null,
                detected_at text not null
            );
            """,
        )
        conn.execute(
            """
            insert into opportunities (
                pair_key, kind, yes_market_id, yes_token_id, yes_question,
                no_market_id, no_token_id, no_question, shares, yes_avg_price,
                no_avg_price, total_cost, min_payout, guaranteed_profit,
                edge_per_share, executable, reason, detected_at
            )
            values (
                'same:2636444', 'same_market', '2636444', 'yes-token',
                'Will Ethereum dip to $1,500 June 22-28?',
                '2636444', 'no-token', 'Will Ethereum dip to $1,500 June 22-28?',
                538.62, 0.40, 0.5769, 526.18, 538.62, 12.43544,
                0.02309, 1, 'executable', ?
            )
            """,
            (detected_at,),
        )
        conn.execute(
            """
            insert into paper_trades (
                pair_key, yes_market_id, yes_token_id, yes_question,
                no_market_id, no_token_id, no_question, shares,
                total_cost, min_payout, guaranteed_profit, detected_at
            )
            values (
                'same:2636444', '2636444', 'yes-token',
                'Will Ethereum dip to $1,500 June 22-28?',
                '2636444', 'no-token', 'Will Ethereum dip to $1,500 June 22-28?',
                538.62, 526.18, 538.62, 12.43544, ?
            )
            """,
            (detected_at,),
        )

    store = PaperStore(db_path)
    store.initialize()
    row = store.latest_trades(limit=1)[0]

    assert row["yes_avg_price"] == 0.40
    assert row["no_avg_price"] == 0.5769


def test_paper_store_backfills_existing_trade_end_dates_from_weekly_question(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            create table paper_trades (
                id integer primary key autoincrement,
                pair_key text not null,
                yes_market_id text not null,
                yes_token_id text not null default '',
                yes_question text not null default '',
                yes_end_date text not null default '',
                no_market_id text not null,
                no_token_id text not null default '',
                no_question text not null default '',
                no_end_date text not null default '',
                shares real not null,
                total_cost real not null,
                min_payout real not null,
                guaranteed_profit real not null,
                detected_at text not null
            );
            insert into paper_trades (
                pair_key, yes_market_id, yes_token_id, yes_question, yes_end_date,
                no_market_id, no_token_id, no_question, no_end_date, shares,
                total_cost, min_payout, guaranteed_profit, detected_at
            )
            values (
                'same:2636444', '2636444', 'yes-token',
                'Will Ethereum dip to $1,500 June 22-28?', '',
                '2636444', 'no-token', 'Will Ethereum dip to $1,500 June 22-28?', '',
                538.62, 526.18, 538.62, 12.43544, '2026-06-28T08:10:13.548760+00:00'
            );
            """
        )

    store = PaperStore(db_path)
    store.initialize()
    row = store.latest_trades(limit=1)[0]

    assert row["yes_end_date"] == "2026-06-29T04:00:00+00:00"
    assert row["no_end_date"] == "2026-06-29T04:00:00+00:00"


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
        yes_event_slug="what-price-will-bitcoin-hit-in-june",
        no_event_slug="what-price-will-bitcoin-hit-in-june",
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
