from datetime import datetime, timezone

from polyarb.parser import parse_market


NOW = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
AUG_2 = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def test_parser_rejects_minute_and_hourly_markets():
    for question in (
        "Bitcoin Up or Down - June 27, 8:00AM-8:05AM ET",
        "Bitcoin Up or Down - June 27, 8:00AM-8:15AM ET",
        "Bitcoin Up or Down - August 2, 2AM ET",
        "Bitcoin Up or Down - August 2, 12:00AM-4:00AM ET",
    ):
        assert parse_market(question, "2026-08-02T08:00:00Z", AUG_2) is None


def test_parser_accepts_daily_updown_on_date():
    parsed = parse_market(
        "Bitcoin Up or Down on August 2?",
        "2026-08-02T16:00:00Z",
        AUG_2,
    )

    assert parsed is not None
    assert parsed.kind == "updown"
    assert parsed.period == "day"


def test_parser_accepts_xrp_and_solana_daily_updown():
    cases = [
        ("XRP", "XRP Up or Down on August 2?", "2026-08-02T16:00:00Z"),
        ("Solana", "Solana Up or Down on August 2?", "2026-08-02T16:00:00Z"),
    ]
    for asset_name, question, end_date in cases:
        parsed = parse_market(question, end_date, AUG_2, asset_name=asset_name)

        assert parsed is not None
        assert parsed.period == "day"


def test_parser_accepts_daily_above_below_range_and_hit_price():
    cases = [
        (
            "Will the price of Bitcoin be above $54,000 on August 4?",
            "2026-08-04T16:00:00Z",
            "above",
            54000,
        ),
        (
            "Will the price of Bitcoin be below $54,000 on August 4?",
            "2026-08-04T16:00:00Z",
            "below",
            54000,
        ),
        (
            "Will the price of Bitcoin be between $54,000 and $56,000 on August 4?",
            "2026-08-04T16:00:00Z",
            "range",
            54000,
        ),
        (
            "Will Bitcoin hit $60,000 on August 4?",
            "2026-08-04T16:00:00Z",
            "reach",
            60000,
        ),
    ]
    for question, end_date, expected_kind, expected_threshold in cases:
        parsed = parse_market(question, end_date, AUG_2)

        assert parsed is not None
        assert parsed.period == "day"
        assert parsed.kind == expected_kind
        assert parsed.threshold == expected_threshold


def test_parser_rejects_current_month_and_far_future_year_end():
    monthly = parse_market(
        "Will Bitcoin reach $80,000 in August?",
        "2026-09-01T04:00:00Z",
        AUG_2,
    )
    far_year = parse_market(
        "Will Bitcoin reach $80,000 by December 31, 2026?",
        "2027-01-01T05:00:00Z",
        AUG_2,
    )
    near_month = parse_market(
        "Will Bitcoin reach $80,000 in August?",
        "2026-09-01T04:00:00Z",
        datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert monthly is None
    assert far_year is None
    assert near_month is None


def test_parser_accepts_near_expiry_quarter_and_year():
    year = parse_market(
        "Will Bitcoin reach $80,000 by December 31, 2026?",
        "2027-01-01T05:00:00Z",
        datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc),
    )
    quarter = parse_market(
        "Will Bitcoin reach $90,000 by September 30?",
        "2026-10-01T04:00:00Z",
        datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )

    assert year is not None
    assert year.period == "year"
    assert year.threshold == 80000
    assert quarter is not None
    assert quarter.period == "quarter"
    assert quarter.threshold == 90000


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


def test_parser_accepts_decimal_thresholds_for_xrp_and_solana():
    xrp = parse_market(
        "Will XRP reach $1.50 July 27-August 2?",
        "2026-08-03T04:00:00Z",
        AUG_2,
        asset_name="XRP",
    )
    solana = parse_market(
        "Will Solana dip to $60 July 27-August 2?",
        "2026-08-03T04:00:00Z",
        AUG_2,
        asset_name="Solana",
    )

    assert xrp is not None
    assert xrp.threshold == 1.5
    assert solana is not None
    assert solana.threshold == 60.0


def test_parser_accepts_ethereum_weekly_reach_window():
    parsed = parse_market(
        "Will Ethereum reach $3,000 June 22-28?",
        "2026-06-29T04:00:00Z",
        NOW,
        asset_name="Ethereum",
    )

    assert parsed is not None
    assert parsed.kind == "reach"
    assert parsed.period == "week"
    assert parsed.threshold == 3000
