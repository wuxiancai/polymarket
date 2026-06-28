from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple


Level = Tuple[float, float]


@dataclass(frozen=True)
class AssetSpec:
    symbol: str
    tag_slug: str
    title_name: str
    allocation_ratio: float


BTC_ASSET = AssetSpec(symbol="BTC", tag_slug="bitcoin", title_name="Bitcoin", allocation_ratio=0.70)
ETH_ASSET = AssetSpec(symbol="ETH", tag_slug="ethereum", title_name="Ethereum", allocation_ratio=0.30)
DEFAULT_ASSETS = (BTC_ASSET, ETH_ASSET)


@dataclass(frozen=True)
class Predicate:
    kind: str
    threshold: Optional[int]
    period: str
    start: datetime
    end: datetime
    duration_minutes: int

    @property
    def key(self) -> str:
        threshold = "" if self.threshold is None else str(self.threshold)
        return "|".join(
            [
                self.kind,
                threshold,
                self.start.isoformat(),
                self.end.isoformat(),
            ]
        )


@dataclass(frozen=True)
class Market:
    id: str
    question: str
    slug: str
    event_slug: str
    end_date: str
    yes_token_id: str
    no_token_id: str
    volume_24h: float
    liquidity: float
    predicate: Predicate


@dataclass(frozen=True)
class OrderBook:
    token_id: str
    bids: List[Level]
    asks: List[Level]
    timestamp_ms: int
    hash: str

    @property
    def best_ask(self) -> Optional[float]:
        return min((price for price, _ in self.asks), default=None)

    @property
    def best_bid(self) -> Optional[float]:
        return max((price for price, _ in self.bids), default=None)

    def sorted_asks(self) -> List[Level]:
        return sorted(self.asks, key=lambda level: level[0])


@dataclass(frozen=True)
class ArbPair:
    pair_key: str
    kind: str
    yes_market: Market
    yes_token_id: str
    no_market: Market
    no_token_id: str

    @property
    def token_ids(self) -> List[str]:
        return [self.yes_token_id, self.no_token_id]


@dataclass(frozen=True)
class ArbOpportunity:
    pair_key: str
    kind: str
    yes_market_id: str
    yes_token_id: str
    yes_question: str
    no_market_id: str
    no_token_id: str
    no_question: str
    yes_end_date: str
    no_end_date: str
    shares: float
    yes_avg_price: float
    no_avg_price: float
    total_cost: float
    min_payout: float
    guaranteed_profit: float
    edge_per_share: float
    executable: bool
    reason: str
    detected_at: datetime

    def as_dict(self) -> Dict[str, object]:
        return {
            "pair_key": self.pair_key,
            "kind": self.kind,
            "yes_market_id": self.yes_market_id,
            "yes_token_id": self.yes_token_id,
            "yes_question": self.yes_question,
            "no_market_id": self.no_market_id,
            "no_token_id": self.no_token_id,
            "no_question": self.no_question,
            "yes_end_date": self.yes_end_date,
            "no_end_date": self.no_end_date,
            "shares": self.shares,
            "yes_avg_price": self.yes_avg_price,
            "no_avg_price": self.no_avg_price,
            "total_cost": self.total_cost,
            "min_payout": self.min_payout,
            "guaranteed_profit": self.guaranteed_profit,
            "edge_per_share": self.edge_per_share,
            "executable": self.executable,
            "reason": self.reason,
            "detected_at": self.detected_at.isoformat(),
        }
