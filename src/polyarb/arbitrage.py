from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from .config import Config
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
    fill = _take_profitable_depth(yes_book.sorted_asks(), no_book.sorted_asks(), config.total_buffer)
    if fill is None:
        return None

    shares, yes_cost, no_cost, yes_avg, no_avg = fill
    total_cost = yes_cost + no_cost
    min_payout = shares
    guaranteed_profit = min_payout - total_cost
    edge_per_share = guaranteed_profit / shares if shares else 0.0
    executable = True
    reason = "executable"
    min_volume = min(pair.yes_market.volume_24h, pair.no_market.volume_24h)
    if min_volume < config.min_24h_volume_usd:
        executable = False
        reason = f"24h volume below ${config.min_24h_volume_usd:g}"
    elif total_cost < config.min_arbitrage_depth_usd:
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
    )


def find_opportunities(markets: Iterable[Market], books: Dict[str, OrderBook], config: Config) -> List[ArbOpportunity]:
    opportunities = []
    for pair in build_pairs(markets):
        opportunity = evaluate_pair(pair, books, config)
        if opportunity is not None:
            opportunities.append(opportunity)
    return sorted(opportunities, key=lambda item: item.guaranteed_profit, reverse=True)


def _take_profitable_depth(
    yes_asks: List[Tuple[float, float]],
    no_asks: List[Tuple[float, float]],
    buffer: float,
) -> Optional[Tuple[float, float, float, float, float]]:
    i = 0
    j = 0
    yes_remaining = yes_asks[0][1] if yes_asks else 0.0
    no_remaining = no_asks[0][1] if no_asks else 0.0
    shares = 0.0
    yes_cost = 0.0
    no_cost = 0.0

    while i < len(yes_asks) and j < len(no_asks):
        yes_price, _ = yes_asks[i]
        no_price, _ = no_asks[j]
        if yes_price + no_price >= 1.0 - buffer:
            break
        quantity = min(yes_remaining, no_remaining)
        if quantity <= 0:
            break
        shares += quantity
        yes_cost += quantity * yes_price
        no_cost += quantity * no_price
        yes_remaining -= quantity
        no_remaining -= quantity
        if yes_remaining <= 1e-9:
            i += 1
            if i < len(yes_asks):
                yes_remaining = yes_asks[i][1]
        if no_remaining <= 1e-9:
            j += 1
            if j < len(no_asks):
                no_remaining = no_asks[j][1]

    if shares <= 0:
        return None
    return shares, yes_cost, no_cost, yes_cost / shares, no_cost / shares


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
