from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from .config import Config
from dataclasses import replace

from .models import ArbOpportunity, ArbPair, Market, OrderBook, Predicate


def build_pairs(markets: Iterable[Market]) -> List[ArbPair]:
    items = list(markets)
    pairs: List[ArbPair] = []
    seen = set()

    for market in items:
        key = f"same:{market.id}"
        pairs.append(
            ArbPair(
                pair_key=key,
                kind="same_market",
                yes_market=market,
                yes_token_id=market.yes_token_id,
                no_market=market,
                no_token_id=market.no_token_id,
            )
        )
        seen.add(key)

    for a in items:
        for b in items:
            if a.id == b.id:
                continue
            if _implies(a.predicate, b.predicate):
                pair = ArbPair(
                    pair_key=f"implication:{a.id}->{b.id}",
                    kind="implication",
                    yes_market=b,
                    yes_token_id=b.yes_token_id,
                    no_market=a,
                    no_token_id=a.no_token_id,
                )
                if pair.pair_key not in seen:
                    pairs.append(pair)
                    seen.add(pair.pair_key)
    return pairs


def evaluate_pair(pair: ArbPair, books: Dict[str, OrderBook], config: Config) -> Optional[ArbOpportunity]:
    yes_book = books.get(pair.yes_token_id)
    no_book = books.get(pair.no_token_id)
    if yes_book is None or no_book is None:
        return None
    if not _books_are_fresh(yes_book, no_book, config):
        return None
    result = _best_size(yes_book, no_book, config)
    if result is None:
        return None
    shares, yes_cost, no_cost, yes_fee, no_fee, slippage_cost, safety_buffer = result
    yes_avg = yes_cost / shares
    no_avg = no_cost / shares
    total_cost = yes_cost + no_cost + yes_fee + no_fee + safety_buffer
    min_payout = shares
    guaranteed_profit = min_payout - total_cost
    edge_per_share = guaranteed_profit / shares if shares else 0.0
    roi = guaranteed_profit / total_cost if total_cost > 0 else 0.0
    executable = guaranteed_profit >= config.min_profit_usd and roi >= config.min_roi
    reason = "executable" if executable else _decision_reason(guaranteed_profit, roi, config)
    min_volume = min(pair.yes_market.volume_24h, pair.no_market.volume_24h)
    if min_volume < config.min_24h_volume_usd:
        executable = False
        reason = f"24h volume below ${config.min_24h_volume_usd:g}"
    elif yes_cost + no_cost < config.min_arbitrage_depth_usd:
        executable = False
        reason = f"arbitrage depth below ${config.min_arbitrage_depth_usd:g}"

    return ArbOpportunity(
        pair_key=pair.pair_key,
        kind=pair.kind,
        yes_market_id=pair.yes_market.id,
        yes_token_id=pair.yes_token_id,
        yes_question=pair.yes_market.question,
        no_market_id=pair.no_market.id,
        no_token_id=pair.no_token_id,
        no_question=pair.no_market.question,
        yes_event_slug=pair.yes_market.event_slug,
        no_event_slug=pair.no_market.event_slug,
        yes_end_date=pair.yes_market.end_date,
        no_end_date=pair.no_market.end_date,
        shares=shares,
        yes_avg_price=yes_avg,
        no_avg_price=no_avg,
        total_cost=total_cost,
        min_payout=min_payout,
        guaranteed_profit=guaranteed_profit,
        edge_per_share=edge_per_share,
        executable=executable,
        reason=reason,
        detected_at=datetime.now(timezone.utc),
        yes_fee=yes_fee,
        no_fee=no_fee,
        slippage_cost=slippage_cost,
        safety_buffer=safety_buffer,
        roi=roi,
    )


def find_opportunities(markets: Iterable[Market], books: Dict[str, OrderBook], config: Config) -> List[ArbOpportunity]:
    opportunities = []
    for pair in build_pairs(markets):
        opportunity = evaluate_pair(pair, books, config)
        if opportunity is not None:
            opportunities.append(opportunity)
    return sorted(opportunities, key=lambda item: item.guaranteed_profit, reverse=True)


def preflight_execution(
    opportunity: ArbOpportunity,
    books: Dict[str, OrderBook],
    config: Config,
) -> Optional[Tuple[ArbOpportunity, float, float]]:
    """Reprice a chosen size from the latest local books immediately before FOK.

    The returned caps are the final level needed to fill the target quantity,
    never a cap inferred only from a prior VWAP.  This is the last local guard;
    the exchange-side FOK is still authoritative.
    """
    yes_book = books.get(opportunity.yes_token_id)
    no_book = books.get(opportunity.no_token_id)
    if yes_book is None or no_book is None or not _books_are_fresh(yes_book, no_book, config):
        return None
    yes = calculate_vwap(yes_book.sorted_asks(), opportunity.shares)
    no = calculate_vwap(no_book.sorted_asks(), opportunity.shares)
    if yes is None or no is None:
        return None
    yes_cost, yes_avg = yes
    no_cost, no_avg = no
    yes_fee = _fee_for_fill(yes_book.sorted_asks(), opportunity.shares, yes_book.fee_rate, yes_book.fee_exponent)
    no_fee = _fee_for_fill(no_book.sorted_asks(), opportunity.shares, no_book.fee_rate, no_book.fee_exponent)
    safety = opportunity.shares * max(0.0, config.safety_buffer_per_share + config.fee_buffer)
    total_cost = yes_cost + no_cost + yes_fee + no_fee + safety
    profit = opportunity.shares - total_cost
    roi = profit / total_cost if total_cost else 0.0
    if profit < config.min_profit_usd or roi < config.min_roi:
        return None
    yes_cap = _last_fill_price(yes_book.sorted_asks(), opportunity.shares)
    no_cap = _last_fill_price(no_book.sorted_asks(), opportunity.shares)
    if yes_cap is None or no_cap is None or yes_cap + no_cap >= 1:
        return None
    slippage = max(0.0, yes_cost - opportunity.shares * yes_book.sorted_asks()[0][0]) + max(0.0, no_cost - opportunity.shares * no_book.sorted_asks()[0][0])
    return replace(
        opportunity,
        yes_avg_price=yes_avg,
        no_avg_price=no_avg,
        total_cost=total_cost,
        min_payout=opportunity.shares,
        guaranteed_profit=profit,
        edge_per_share=profit / opportunity.shares,
        yes_fee=yes_fee,
        no_fee=no_fee,
        slippage_cost=slippage,
        safety_buffer=safety,
        roi=roi,
    ), yes_cap, no_cap


def calculate_vwap(asks: List[Tuple[float, float]], target_size: float) -> Optional[Tuple[float, float]]:
    """Return full-fill (cost, VWAP); a partial book is never a valid leg."""
    remaining = target_size
    cost = 0.0
    for price, available in sorted(asks, key=lambda item: item[0]):
        quantity = min(remaining, available)
        cost += quantity * price
        remaining -= quantity
        if remaining <= 1e-9:
            return cost, cost / target_size
    return None


def _best_size(yes_book: OrderBook, no_book: OrderBook, config: Config) -> Optional[Tuple[float, float, float, float, float, float, float]]:
    yes_asks, no_asks = yes_book.sorted_asks(), no_book.sorted_asks()
    candidates = _candidate_sizes(yes_asks, no_asks)
    best = None
    best_profit = float("-inf")
    for shares in candidates:
        yes = calculate_vwap(yes_asks, shares)
        no = calculate_vwap(no_asks, shares)
        if yes is None or no is None:
            continue
        yes_cost, yes_vwap = yes
        no_cost, no_vwap = no
        yes_fee = _fee_for_fill(yes_asks, shares, yes_book.fee_rate, yes_book.fee_exponent)
        no_fee = _fee_for_fill(no_asks, shares, no_book.fee_rate, no_book.fee_exponent)
        # Extra buffer from an old deployment remains an explicit safety cost,
        # while the actual fee is always taken from market metadata.
        safety = shares * max(0.0, config.safety_buffer_per_share + config.fee_buffer)
        slippage = max(0.0, yes_cost - shares * yes_asks[0][0]) + max(0.0, no_cost - shares * no_asks[0][0])
        profit = shares - yes_cost - no_cost - yes_fee - no_fee - safety
        if profit > best_profit + 1e-12:
            best_profit = profit
            best = (shares, yes_cost, no_cost, yes_fee, no_fee, slippage, safety)
    return best


def _candidate_sizes(yes_asks: List[Tuple[float, float]], no_asks: List[Tuple[float, float]]) -> List[float]:
    """All cumulative depth breakpoints on either leg; profit is piecewise linear."""
    points = set()
    for asks in (yes_asks, no_asks):
        cumulative = 0.0
        for _price, size in asks:
            cumulative += size
            if cumulative > 0:
                points.add(round(cumulative, 10))
    maximum = min(sum(size for _price, size in yes_asks), sum(size for _price, size in no_asks))
    return sorted(point for point in points if point <= maximum + 1e-9)


def _fee_for_fill(asks: List[Tuple[float, float]], shares: float, fee_rate: float, fee_exponent: float) -> float:
    remaining, fee = shares, 0.0
    for price, available in sorted(asks, key=lambda item: item[0]):
        quantity = min(remaining, available)
        fee += quantity * max(0.0, fee_rate) * ((price * (1.0 - price)) ** max(0.0, fee_exponent))
        remaining -= quantity
        if remaining <= 1e-9:
            break
    return fee


def _last_fill_price(asks: List[Tuple[float, float]], shares: float) -> Optional[float]:
    remaining = shares
    for price, available in sorted(asks, key=lambda item: item[0]):
        remaining -= min(remaining, available)
        if remaining <= 1e-9:
            return price
    return None


def _books_are_fresh(yes_book: OrderBook, no_book: OrderBook, config: Config) -> bool:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # Exchange and host clocks may differ by a small amount.  Future data far
    # beyond that tolerance is not trustworthy, but a 1s skew must not reject
    # a just-arrived WebSocket update.
    return all(-1_000 <= now_ms - book.timestamp_ms <= config.stale_book_ms for book in (yes_book, no_book))


def _decision_reason(profit: float, roi: float, config: Config) -> str:
    if profit < config.min_profit_usd:
        return f"net profit ${profit:.4f} below ${config.min_profit_usd:g}"
    return f"ROI {roi:.4%} below {config.min_roi:.2%}"


def _implies(a: Predicate, b: Predicate) -> bool:
    if a.kind != b.kind:
        return False
    if a.kind == "updown":
        return a.key == b.key
    if a.threshold is None or b.threshold is None:
        return False
    if a.start < b.start or a.end > b.end:
        return False
    if a.kind == "reach":
        return a.threshold >= b.threshold
    if a.kind == "dip":
        return a.threshold <= b.threshold
    return False
