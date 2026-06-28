from datetime import datetime, timezone

from polyarb.arbitrage import build_pairs, evaluate_pair
from polyarb.config import Config
from polyarb.models import Market, OrderBook, Predicate


NOW = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)


def market(market_id, question, kind, threshold, period, start, end, yes, no, volume=1500):
    return Market(
        id=market_id,
        question=question,
        slug=f"m-{market_id}",
        event_slug="bitcoin",
        end_date=end.isoformat(),
        yes_token_id=yes,
        no_token_id=no,
        volume_24h=float(volume),
        liquidity=1000.0,
        predicate=Predicate(
            kind=kind,
            threshold=threshold,
            period=period,
            start=start,
            end=end,
            duration_minutes=int((end - start).total_seconds() // 60),
        ),
    )


def book(token, asks):
    return OrderBook(token_id=token, bids=[], asks=asks, timestamp_ms=1, hash="h")


def test_reach_week_implies_current_month_and_creates_buy_month_yes_week_no_pair():
    weekly = market(
        "week70",
        "Will Bitcoin reach $70,000 June 22-28?",
        "reach",
        70000,
        "week",
        datetime(2026, 6, 22, tzinfo=timezone.utc),
        datetime(2026, 6, 29, tzinfo=timezone.utc),
        "y-week",
        "n-week",
    )
    monthly = market(
        "month70",
        "Will Bitcoin reach $70,000 in June?",
        "reach",
        70000,
        "month",
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        "y-month",
        "n-month",
    )

    pairs = [pair for pair in build_pairs([weekly, monthly]) if pair.kind == "implication"]

    assert len(pairs) == 1
    assert pairs[0].yes_market.id == "month70"
    assert pairs[0].no_market.id == "week70"


def test_marginal_depth_stops_before_unprofitable_level():
    cfg = Config(min_24h_volume_usd=1000, min_arbitrage_depth_usd=100, slippage_buffer_cents=2)
    yes_market = market(
        "month70",
        "Will Bitcoin reach $70,000 in June?",
        "reach",
        70000,
        "month",
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        "y-month",
        "n-month",
    )
    no_market = market(
        "week70",
        "Will Bitcoin reach $70,000 June 22-28?",
        "reach",
        70000,
        "week",
        datetime(2026, 6, 22, tzinfo=timezone.utc),
        datetime(2026, 6, 29, tzinfo=timezone.utc),
        "y-week",
        "n-week",
    )
    pair = [pair for pair in build_pairs([no_market, yes_market]) if pair.kind == "implication"][0]
    books = {
        "y-month": book("y-month", [(0.40, 300.0), (0.45, 300.0)]),
        "n-week": book("n-week", [(0.57, 300.0), (0.58, 300.0)]),
    }

    opportunity = evaluate_pair(pair, books, cfg)

    assert opportunity is not None
    assert opportunity.executable is True
    assert opportunity.yes_end_date == "2026-07-01T00:00:00+00:00"
    assert opportunity.no_end_date == "2026-06-29T00:00:00+00:00"
    assert opportunity.shares == 300.0
    assert round(opportunity.total_cost, 2) == 291.00
    assert round(opportunity.guaranteed_profit, 2) == 9.00


def test_volume_and_depth_gates_block_execution_but_record_opportunity():
    cfg = Config(min_24h_volume_usd=1000, min_arbitrage_depth_usd=100, slippage_buffer_cents=2)
    yes_market = market(
        "month70",
        "Will Bitcoin reach $70,000 in June?",
        "reach",
        70000,
        "month",
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        "y-month",
        "n-month",
        volume=100,
    )
    no_market = market(
        "week70",
        "Will Bitcoin reach $70,000 June 22-28?",
        "reach",
        70000,
        "week",
        datetime(2026, 6, 22, tzinfo=timezone.utc),
        datetime(2026, 6, 29, tzinfo=timezone.utc),
        "y-week",
        "n-week",
        volume=100,
    )
    pair = [pair for pair in build_pairs([no_market, yes_market]) if pair.kind == "implication"][0]
    books = {
        "y-month": book("y-month", [(0.40, 20.0)]),
        "n-week": book("n-week", [(0.57, 20.0)]),
    }

    opportunity = evaluate_pair(pair, books, cfg)

    assert opportunity is not None
    assert opportunity.executable is False
    assert "24h volume below" in opportunity.reason
