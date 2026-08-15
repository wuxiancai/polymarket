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
    return OrderBook(token_id=token, bids=[], asks=asks, timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000), hash="h")


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
    cfg = Config(min_24h_volume_usd=1000, min_arbitrage_depth_usd=100, min_profit_usd=0.01, min_roi=0)
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
    assert round(opportunity.total_cost, 2) == 291.60
    assert round(opportunity.guaranteed_profit, 2) == 8.40


def test_dynamic_fee_and_safety_can_reject_an_apparent_best_ask_arbitrage():
    cfg = Config(min_profit_usd=1.0, min_roi=0.01, safety_buffer_per_share=0.002, min_arbitrage_depth_usd=0)
    same = market(
        "same", "Will Bitcoin reach $70,000 in June?", "reach", 70000, "week",
        datetime(2026, 6, 22, tzinfo=timezone.utc), datetime(2026, 6, 29, tzinfo=timezone.utc), "yes", "no"
    )
    pair = [item for item in build_pairs([same]) if item.kind == "same_market"][0]
    books = {
        "yes": OrderBook("yes", [], [(0.48, 100)], int(datetime.now(timezone.utc).timestamp() * 1000), "", fee_rate=0.07, fee_exponent=1),
        "no": OrderBook("no", [], [(0.48, 100)], int(datetime.now(timezone.utc).timestamp() * 1000), "", fee_rate=0.07, fee_exponent=1),
    }

    opportunity = evaluate_pair(pair, books, cfg)

    assert opportunity is not None
    assert opportunity.yes_fee > 1
    assert opportunity.no_fee > 1
    assert opportunity.executable is False
    assert "net profit" in opportunity.reason


def test_engine_selects_profit_maximizing_depth_not_maximum_depth():
    cfg = Config(min_profit_usd=0.01, min_roi=0, safety_buffer_per_share=0)
    same = market(
        "same", "Will Bitcoin reach $70,000 in June?", "reach", 70000, "week",
        datetime(2026, 6, 22, tzinfo=timezone.utc), datetime(2026, 6, 29, tzinfo=timezone.utc), "yes", "no"
    )
    pair = [item for item in build_pairs([same]) if item.kind == "same_market"][0]
    stamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    books = {
        "yes": OrderBook("yes", [], [(0.40, 100), (0.60, 100)], stamp, ""),
        "no": OrderBook("no", [], [(0.55, 100), (0.60, 100)], stamp, ""),
    }

    opportunity = evaluate_pair(pair, books, cfg)

    assert opportunity is not None
    assert opportunity.shares == 100
    assert round(opportunity.guaranteed_profit, 2) == 5.0


def test_stale_books_are_never_evaluated():
    cfg = Config(stale_book_ms=1_000)
    same = market(
        "same", "Will Bitcoin reach $70,000 in June?", "reach", 70000, "week",
        datetime(2026, 6, 22, tzinfo=timezone.utc), datetime(2026, 6, 29, tzinfo=timezone.utc), "yes", "no"
    )
    pair = [item for item in build_pairs([same]) if item.kind == "same_market"][0]
    stale = int(datetime.now(timezone.utc).timestamp() * 1000) - 1_001

    assert evaluate_pair(pair, {"yes": OrderBook("yes", [], [(0.4, 10)], stale, ""), "no": OrderBook("no", [], [(0.5, 10)], stale, "")}, cfg) is None


def test_volume_and_depth_gates_block_execution_but_record_opportunity():
    cfg = Config(min_24h_volume_usd=1000, min_arbitrage_depth_usd=100, min_profit_usd=0.01, min_roi=0)
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
