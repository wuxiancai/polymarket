from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Config
from .models import BTC_ASSET, AssetSpec, Market, OrderBook
from .parser import parse_market


class PolymarketError(RuntimeError):
    pass


class GammaClient:
    def __init__(self, config: Config):
        self.config = config

    def markets_for_asset(self, asset: AssetSpec, now: Optional[datetime] = None) -> List[Market]:
        now_utc = now or datetime.now(timezone.utc)
        params = urlencode(
            {
                "tag_slug": asset.tag_slug,
                "closed": "false",
                "active": "true",
                "limit": "500",
            }
        )
        events = _get_json(f"{self.config.gamma_events_url}?{params}")
        markets: List[Market] = []
        for event in events:
            for raw_market in event.get("markets") or []:
                market = self._parse_market(event, raw_market, now_utc, asset)
                if market is not None:
                    markets.append(market)
        return markets

    def bitcoin_markets(self, now: Optional[datetime] = None) -> List[Market]:
        return self.markets_for_asset(BTC_ASSET, now)

    def _parse_market(self, event: dict, raw: dict, now: datetime, asset: AssetSpec) -> Optional[Market]:
        if not (raw.get("active") is True and raw.get("closed") is False and raw.get("acceptingOrders") is True):
            return None
        try:
            outcomes = json.loads(raw.get("outcomes") or "[]")
            token_ids = json.loads(raw.get("clobTokenIds") or "[]")
        except (TypeError, ValueError):
            return None
        if outcomes != ["Yes", "No"] or len(token_ids) != 2:
            return None
        parsed = parse_market(raw.get("question") or "", raw.get("endDate") or "", now, self.config, asset.title_name)
        if parsed is None:
            return None
        volume = raw.get("volume24hr")
        if volume is None:
            volume = event.get("volume24hr")
        return Market(
            id=str(raw.get("id")),
            question=raw.get("question") or "",
            slug=raw.get("slug") or "",
            event_slug=event.get("slug") or "",
            end_date=raw.get("endDate") or "",
            yes_token_id=str(token_ids[0]),
            no_token_id=str(token_ids[1]),
            volume_24h=float(volume or 0),
            liquidity=float(raw.get("liquidityClob") or raw.get("liquidity") or 0),
            predicate=parsed.to_predicate(),
        )


class ClobClient:
    def __init__(self, config: Config):
        self.config = config

    def order_book(self, token_id: str) -> OrderBook:
        data = _get_json(f"{self.config.clob_url}/book?{urlencode({'token_id': token_id})}")
        return OrderBook(
            token_id=str(data.get("asset_id") or token_id),
            bids=_levels(data.get("bids") or []),
            asks=_levels(data.get("asks") or []),
            timestamp_ms=int(data.get("timestamp") or int(time.time() * 1000)),
            hash=str(data.get("hash") or ""),
        )

    def order_books(self, token_ids: Iterable[str]) -> Dict[str, OrderBook]:
        books: Dict[str, OrderBook] = {}
        for token_id in sorted(set(token_ids)):
            try:
                book = self.order_book(token_id)
            except Exception:
                continue
            books[token_id] = book
        return books


def _get_json(url: str):
    request = Request(
        url,
        headers={
            "User-Agent": "polyarb/2.3.0 (+https://polymarket.com)",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise PolymarketError(f"request failed: {url}: {exc}") from exc


def _levels(raw_levels: List[dict]) -> List[tuple]:
    levels = []
    for level in raw_levels:
        try:
            price = float(level["price"])
            size = float(level["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0 and size > 0:
            levels.append((price, size))
    return levels
