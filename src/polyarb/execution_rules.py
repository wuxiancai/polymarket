from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from typing import List, Optional, Tuple

from .models import ArbOpportunity, Level


# Strictly below 97¢: only opportunities with more than 3¢ per-share spread open.
MAX_TOTAL_OPEN_COST = Decimal("0.97")
# Signed SDK orders can have unequal fee-adjusted shares.  Keep a small absolute
# margin after the losing-leg payout covers both worst-case order spends.
MIN_SETTLEMENT_PROFIT = Decimal("0.001")


def price_caps(opportunity: ArbOpportunity, fee_buffer: float = 0.0) -> Optional[tuple[float, float]]:
    """Split observed headroom while reserving 3¢ profit plus configured fees."""
    yes_price = Decimal(str(opportunity.yes_avg_price))
    no_price = Decimal(str(opportunity.no_avg_price))
    fee = Decimal(str(fee_buffer))
    max_price_total = MAX_TOTAL_OPEN_COST - fee
    if fee < 0 or max_price_total <= 0:
        return None
    observed_total = yes_price + no_price
    if observed_total >= max_price_total:
        return None
    half_headroom = (max_price_total - observed_total) / Decimal("2")
    cents = Decimal("0.01")
    yes_cap = (yes_price + half_headroom).quantize(cents, rounding=ROUND_DOWN)
    no_cap = (no_price + half_headroom).quantize(cents, rounding=ROUND_DOWN)
    if yes_cap <= 0 or no_cap <= 0 or yes_cap + no_cap + fee >= MAX_TOTAL_OPEN_COST:
        # Do not turn a strict <97¢ rule into an equality because the extra
        # headroom happened to round to whole cents.  Fall back to the lowest
        # cent caps that can still include the observed prices.
        yes_cap = yes_price.quantize(cents, rounding=ROUND_UP)
        no_cap = no_price.quantize(cents, rounding=ROUND_UP)
        if yes_cap <= 0 or no_cap <= 0 or yes_cap + no_cap + fee >= MAX_TOTAL_OPEN_COST:
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
