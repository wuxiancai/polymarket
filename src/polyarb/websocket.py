from __future__ import annotations

from typing import Iterable


def websocket_supported() -> bool:
    try:
        import websockets  # noqa: F401
    except Exception:
        return False
    return True


def market_subscription_message(token_ids: Iterable[str]) -> dict:
    return {"type": "market", "assets_ids": list(token_ids)}
