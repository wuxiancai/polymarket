from polyarb.models import OrderBook
from polyarb.websocket import apply_market_message, market_subscription_message


def test_market_subscription_message_uses_market_assets():
    assert market_subscription_message(["a", "b"]) == {"type": "market", "assets_ids": ["a", "b"]}


def test_price_change_updates_ask_depth():
    books = {
        "token-1": OrderBook(
            token_id="token-1",
            bids=[(0.4, 10.0)],
            asks=[(0.6, 10.0)],
            timestamp_ms=1,
            hash="h",
        )
    }
    message = {
        "event_type": "price_change",
        "changes": [
            {"asset_id": "token-1", "side": "SELL", "price": "0.59", "size": "25"},
            {"asset_id": "token-1", "side": "SELL", "price": "0.6", "size": "0"},
        ],
    }

    updates = apply_market_message(books, message)

    assert updates == 2
    assert books["token-1"].asks == [(0.59, 25.0)]
