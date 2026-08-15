from __future__ import annotations

import time
from dataclasses import replace
from typing import Iterable, List

from .models import Level, OrderBook


def websocket_supported() -> bool:
    try:
        import websockets  # noqa: F401
    except Exception:
        return False
    return True


def market_subscription_message(token_ids: Iterable[str]) -> dict:
    return {"type": "market", "assets_ids": list(token_ids)}


def parse_order_book_message(message: dict) -> OrderBook:
    return OrderBook(
        token_id=str(message.get("asset_id")),
        bids=_levels(message.get("bids") or []),
        asks=_levels(message.get("asks") or []),
        timestamp_ms=int(message.get("timestamp") or 0),
        hash=str(message.get("hash") or ""),
    )


def apply_price_change(book: OrderBook, change: dict) -> OrderBook:
    side = str(change.get("side") or "").upper()
    try:
        price = float(change["price"])
        size = float(change["size"])
    except (KeyError, TypeError, ValueError):
        return book

    if side == "BUY":
        bids = _upsert_level(book.bids, price, size)
        return replace(book, bids=bids, timestamp_ms=int(time.time() * 1000))
    if side == "SELL":
        asks = _upsert_level(book.asks, price, size)
        return replace(book, asks=asks, timestamp_ms=int(time.time() * 1000))
    return book


def apply_market_message(books: dict, message) -> int:
    messages = message if isinstance(message, list) else [message]
    updates = 0
    for item in messages:
        if not isinstance(item, dict):
            continue
        event_type = item.get("event_type") or item.get("type")
        if event_type == "book" and item.get("asset_id"):
            book = parse_order_book_message(item)
            current = books.get(book.token_id)
            if current is not None:
                book = replace(
                    book,
                    fee_rate=current.fee_rate,
                    fee_exponent=current.fee_exponent,
                    tick_size=current.tick_size,
                )
            books[book.token_id] = book
            updates += 1
        elif event_type == "price_change":
            for change in item.get("changes") or []:
                token_id = str(change.get("asset_id") or "")
                current = books.get(token_id)
                if current is None:
                    continue
                books[token_id] = apply_price_change(current, change)
                updates += 1
    return updates


def _levels(raw_levels: List[dict]) -> List[Level]:
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


def _upsert_level(levels: List[Level], price: float, size: float) -> List[Level]:
    updated = [(p, s) for p, s in levels if abs(p - price) > 1e-12]
    if size > 0:
        updated.append((price, size))
    return updated
