from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from typing import List, Optional, Tuple

from .models import ArbOpportunity, Level


# Signed SDK orders can have unequal fee-adjusted shares.  Keep a small absolute
# margin after the losing-leg payout covers both worst-case order spends.
MIN_SETTLEMENT_PROFIT = Decimal("0.001")


def price_caps(opportunity: ArbOpportunity, fee_buffer: float = 0.0) -> Optional[tuple[float, float]]:
    """Conservative average-price caps for callers without the raw book.

    The actual execution path performs a second depth check and replaces these
    with the final fillable caps.  No fixed 97c threshold is valid across fee
    schedules, so this helper only rejects malformed values.
    """
    yes_price = Decimal(str(opportunity.yes_avg_price))
    no_price = Decimal(str(opportunity.no_avg_price))
    fee = Decimal(str(fee_buffer))
    if fee < 0:
        return None
    observed_total = yes_price + no_price
    if yes_price <= 0 or no_price <= 0 or observed_total >= Decimal("1"):
        return None
    cents = Decimal("0.01")
    yes_cap = yes_price.quantize(cents, rounding=ROUND_UP)
    no_cap = no_price.quantize(cents, rounding=ROUND_UP)
    if yes_cap <= 0 or no_cap <= 0:
        return None
    return float(yes_cap), float(no_cap)


def max_pair_spend(shares: float, yes_max_price: float, no_max_price: float, fee_buffer: float) -> float:
    return max(0.0, shares * (yes_max_price + no_max_price + max(0.0, fee_buffer)))


def pair_has_strict_coverage(
    yes_shares: float,
    no_shares: float,
    yes_max_spend: float,
    no_max_spend: float,
) -> bool:
    """Allow unequal legs when either settlement outcome retains net profit."""
    try:
        min_payout = min(Decimal(str(yes_shares)), Decimal(str(no_shares)))
        total_max_spend = Decimal(str(yes_max_spend)) + Decimal(str(no_max_spend))
    except (InvalidOperation, ValueError):
        return False
    return min_payout > 0 and total_max_spend + MIN_SETTLEMENT_PROFIT <= min_payout


def fee_adjusted_buy_shares(
    *,
    target_shares: float,
    price: float,
    max_spend: float,
    fee_rate: float = 0.0,
    fee_exponent: float = 0.0,
    tick_size: float = 0.01,
) -> float:
    """Mirror the SDK's protected BUY fee adjustment before order signing."""
    try:
        shares = Decimal(str(target_shares))
        unit_price = Decimal(str(price))
        cap = Decimal(str(max_spend))
        rate = Decimal(str(fee_rate))
        exponent = Decimal(str(fee_exponent))
        tick = Decimal(str(tick_size))
    except (InvalidOperation, ValueError):
        return 0.0
    rounding = {
        Decimal("0.1"): (3, 1, 2),
        Decimal("0.01"): (4, 2, 2),
        Decimal("0.005"): (5, 3, 2),
        Decimal("0.0025"): (6, 4, 2),
        Decimal("0.001"): (5, 3, 2),
        Decimal("0.0001"): (6, 4, 2),
    }.get(tick)
    if shares <= 0 or unit_price <= 0 or cap <= 0 or rate < 0 or exponent < 0 or rounding is None:
        return 0.0
    amount = shares * unit_price
    effective_rate = rate * ((unit_price * (Decimal(1) - unit_price)) ** exponent)
    total_cost = amount + shares * effective_rate
    adjusted_amount = amount if cap > total_cost else cap / (Decimal(1) + effective_rate / unit_price)
    amount_precision, price_precision, shares_precision = rounding
    rounded_price = unit_price.quantize(Decimal(10) ** -price_precision, rounding=ROUND_DOWN)
    rounded_amount = adjusted_amount.quantize(Decimal(10) ** -shares_precision, rounding=ROUND_DOWN)
    requested_shares = rounded_amount / rounded_price
    if -requested_shares.as_tuple().exponent > amount_precision:
        requested_shares = requested_shares.quantize(Decimal(10) ** -(amount_precision + 4), rounding=ROUND_UP)
        if -requested_shares.as_tuple().exponent > amount_precision:
            requested_shares = requested_shares.quantize(Decimal(10) ** -amount_precision, rounding=ROUND_UP)
    return float(requested_shares)


def fok_buy_fill(asks: List[Level], shares: float, max_price: float) -> Optional[tuple[float, float]]:
    """Return (cost, average_price) only if the entire requested size fills at the cap."""
    remaining = shares
    cost = 0.0
    for price, available in sorted(asks, key=lambda level: level[0]):
        if price > max_price + 1e-12:
            break
        quantity = min(remaining, available)
        cost += quantity * price
        remaining -= quantity
        if remaining <= 1e-9:
            return cost, cost / shares
    return None


def fak_sell_fill(bids: List[Level], shares: float) -> float:
    """Return the shares immediately sold against the available bid depth."""
    remaining = shares
    for _price, available in sorted(bids, key=lambda level: level[0], reverse=True):
        remaining -= min(remaining, available)
        if remaining <= 1e-9:
            return shares
    return max(0.0, shares - remaining)
