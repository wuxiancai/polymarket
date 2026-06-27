from datetime import datetime, timezone

from polyarb.parser import parse_market


NOW = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)


def test_parser_excludes_five_minute_market():
    parsed = parse_market(
        "Bitcoin Up or Down - June 27, 8:00AM-8:05AM ET",
        "2026-06-27T12:05:00Z",
        NOW,
    )

    assert parsed is None


def test_parser_accepts_15_minute_market():
    parsed = parse_market(
        "Bitcoin Up or Down - June 27, 8:00AM-8:15AM ET",
        "2026-06-27T12:15:00Z",
        NOW,
    )

    assert parsed is not None
    assert parsed.kind == "updown"
    assert parsed.period == "intraday"
    assert parsed.duration_minutes == 15


def test_parser_accepts_current_month_reach_and_rejects_year_end_long_term():
    monthly = parse_market(
        "Will Bitcoin reach $80,000 in June?",
        "2026-07-01T04:00:00Z",
        NOW,
    )
    long_term = parse_market(
        "Will Bitcoin reach $80,000 by December 31, 2026?",
        "2027-01-01T05:00:00Z",
        NOW,
    )

    assert monthly is not None
    assert monthly.kind == "reach"
    assert monthly.period == "month"
    assert monthly.threshold == 80000
    assert long_term is None


def test_parser_accepts_weekly_dip_window():
    parsed = parse_market(
        "Will Bitcoin dip to $50,000 June 22-28?",
        "2026-06-29T04:00:00Z",
        NOW,
    )

    assert parsed is not None
    assert parsed.kind == "dip"
    assert parsed.period == "week"
    assert parsed.threshold == 50000
