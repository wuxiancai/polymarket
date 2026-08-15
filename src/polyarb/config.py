from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from .models import DEFAULT_ALLOCATION_RATIOS


@dataclass(frozen=True)
class Config:
    min_24h_volume_usd: float = 1000.0
    min_arbitrage_depth_usd: float = 100.0
    # Retained as a compatibility input for existing deployments.  It is no
    # longer an execution threshold: depth VWAP and the live fee model decide
    # whether a pair is profitable.
    slippage_buffer_cents: int = 3
    fee_buffer: float = 0.0
    min_profit_usd: float = 1.0
    min_roi: float = 0.01
    safety_buffer_per_share: float = 0.002
    stale_book_ms: int = 5_000
    max_single_trade_usd: float = 100.0
    max_open_exposure_usd: float = 500.0
    max_consecutive_failures: int = 3
    dry_run: bool = False
    allow_near_expiry_long_periods: bool = True
    near_expiry_days: int = 30
    gamma_events_url: str = "https://gamma-api.polymarket.com/events"
    clob_url: str = "https://clob.polymarket.com"
    database_path: Path = Path("data/paper.sqlite3")
    refresh_seconds: int = 30
    cooldown_seconds: int = 30
    websocket_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    initial_capital_usdt: float = 10000.0
    allocation_ratios: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ALLOCATION_RATIOS))

    @property
    def slippage_buffer(self) -> float:
        return max(0, int(self.slippage_buffer_cents)) / 100.0

    @property
    def total_buffer(self) -> float:
        # Kept for callers outside the opportunity engine.  Fee and safety
        # must be evaluated from the actual order-book levels, not as a fixed
        # spread threshold.
        return self.fee_buffer + self.safety_buffer_per_share

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            min_24h_volume_usd=_float_env("MIN_24H_VOLUME_USD", 1000.0),
            min_arbitrage_depth_usd=_float_env("MIN_ARBITRAGE_DEPTH_USD", 100.0),
            slippage_buffer_cents=_int_env("SLIPPAGE_BUFFER_CENTS", 3),
            fee_buffer=_float_env("FEE_BUFFER", 0.0),
            min_profit_usd=_float_env("MIN_PROFIT_USD", 1.0),
            min_roi=_float_env("MIN_ROI", 0.01),
            safety_buffer_per_share=_float_env("SAFETY_BUFFER_PER_SHARE", 0.002),
            stale_book_ms=_int_env("STALE_BOOK_MS", 5_000),
            max_single_trade_usd=_float_env("MAX_SINGLE_TRADE_USD", 100.0),
            max_open_exposure_usd=_float_env("MAX_OPEN_EXPOSURE_USD", 500.0),
            max_consecutive_failures=_int_env("MAX_CONSECUTIVE_FAILURES", 3),
            dry_run=_bool_env("DRY_RUN", False),
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
