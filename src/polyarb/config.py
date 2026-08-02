from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    min_24h_volume_usd: float = 1000.0
    min_arbitrage_depth_usd: float = 100.0
    slippage_buffer_cents: int = 2
    fee_buffer: float = 0.0
    allow_near_expiry_long_periods: bool = True
    near_expiry_days: int = 30
    gamma_events_url: str = "https://gamma-api.polymarket.com/events"
    clob_url: str = "https://clob.polymarket.com"
    database_path: Path = Path("data/paper.sqlite3")
    refresh_seconds: int = 30
    cooldown_seconds: int = 30
    websocket_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    initial_capital_usdt: float = 10000.0

    @property
    def slippage_buffer(self) -> float:
        cents = min(3, max(1, int(self.slippage_buffer_cents)))
        return cents / 100.0

    @property
    def total_buffer(self) -> float:
        return self.slippage_buffer + self.fee_buffer

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            min_24h_volume_usd=_float_env("MIN_24H_VOLUME_USD", 1000.0),
            min_arbitrage_depth_usd=_float_env("MIN_ARBITRAGE_DEPTH_USD", 100.0),
            slippage_buffer_cents=_int_env("SLIPPAGE_BUFFER_CENTS", 2),
            fee_buffer=_float_env("FEE_BUFFER", 0.0),
            allow_near_expiry_long_periods=_bool_env("ALLOW_NEAR_EXPIRY_LONG_PERIODS", True),
            near_expiry_days=_int_env("NEAR_EXPIRY_DAYS", 30),
            database_path=Path(os.getenv("POLYARB_DB", "data/paper.sqlite3")),
            refresh_seconds=_int_env("REFRESH_SECONDS", 30),
            cooldown_seconds=_int_env("COOLDOWN_SECONDS", 30),
            websocket_url=os.getenv("POLYMARKET_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market"),
            initial_capital_usdt=_float_env("PAPER_INITIAL_CAPITAL_USDT", 10000.0),
        )


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value in (None, "") else float(value)


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value in (None, "") else int(value)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.lower() in {"1", "true", "yes", "on"}
