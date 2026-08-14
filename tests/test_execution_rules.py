from polyarb.execution_rules import pair_has_strict_coverage


def test_pair_coverage_accepts_unequal_fee_adjusted_legs_with_positive_settlement_profit():
    """A 9.70-share losing leg still leaves $0.20 after worst-case costs."""
    assert pair_has_strict_coverage(
        yes_shares=10.0,
        no_shares=9.7,
        yes_max_spend=4.5,
        no_max_spend=5.0,
    )


def test_pair_coverage_rejects_unequal_legs_without_minimum_settlement_profit():
    assert not pair_has_strict_coverage(
        yes_shares=10.0,
        no_shares=9.7,
        yes_max_spend=4.5,
        no_max_spend=5.1995,
    )
