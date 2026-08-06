from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .config import Config
from .live import LiveSession
from .models import ArbOpportunity, AssetSpec
from .runner import (
    MIN_DISPLAYED_POSITION_VALUE,
    MIN_SPREAD_TO_OPEN_CENTS,
    SIXTY_PERCENT_MAX_SPREAD_CENTS,
    THIRTY_PERCENT_MAX_SPREAD_CENTS,
    ScanResult,
    _settlement_at,
    _spread_cents,
)


class LiveAutoTrader:
    def __init__(self, live_session: LiveSession, config: Config, asset: AssetSpec) -> None:
        self.live_session = live_session
        self.config = config
        self.asset = asset
        self.lock = threading.Lock()
        self.last_execution: Dict[str, float] = {}
        self.last_scan_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self._snapshot_cache: Optional[dict] = None
        self._snapshot_at = 0.0

    def on_result(self, result: ScanResult) -> None:
        if not self.live_session.is_logged_in():
            return
        if not self.live_session.is_auto_trading_enabled():
            return
        try:
            self._process_result(result)
        except Exception as exc:
            self._set_error(str(exc))

    def _process_result(self, result: ScanResult) -> None:
        with self.lock:
            self.last_scan_at = result.scanned_at
        executable = sorted(
            (item for item in result.opportunities if item.executable),
            key=_settlement_at,
        )
        for opportunity in executable:
            if not self._should_execute(opportunity):
                continue
            sized = self._size_opportunity(opportunity)
            if sized is None:
                continue
            successes = self._execute_pair(sized)
            if successes > 0:
                with self.lock:
                    self.last_execution[opportunity.pair_key] = time.time()

    def _should_execute(self, opportunity: ArbOpportunity) -> bool:
        if not opportunity.executable:
            return False
        last = self.last_execution.get(opportunity.pair_key)
        if last is None:
            return True
        return time.time() - last >= self.config.cooldown_seconds

    def _size_opportunity(self, opportunity: ArbOpportunity) -> Optional[ArbOpportunity]:
        if opportunity.total_cost <= 0:
            return None
        spread_cents = _spread_cents(opportunity)
        if spread_cents <= MIN_SPREAD_TO_OPEN_CENTS:
            return None
        if spread_cents <= THIRTY_PERCENT_MAX_SPREAD_CENTS:
            position_ratio = 0.3
        elif spread_cents <= SIXTY_PERCENT_MAX_SPREAD_CENTS:
            position_ratio = 0.6
        else:
            position_ratio = 1.0

        snapshot = self._snapshot()
        balance = _to_float(snapshot.get("balance_pusd"))
        allocation = balance * self._allocation_ratio()
        used = self._used_capital(snapshot.get("positions", []))
        available = max(0.0, allocation - used)
        target_budget = min(opportunity.total_cost, allocation * position_ratio)
        if available < target_budget:
            return None
        scale = target_budget / opportunity.total_cost
        shares = opportunity.shares * scale
        total_cost = opportunity.total_cost * scale
        min_payout = opportunity.min_payout * scale
        guaranteed_profit = opportunity.guaranteed_profit * scale
        if shares < MIN_DISPLAYED_POSITION_VALUE or guaranteed_profit < MIN_DISPLAYED_POSITION_VALUE:
            return None
        return replace(
            opportunity,
            shares=shares,
            total_cost=total_cost,
            min_payout=min_payout,
            guaranteed_profit=guaranteed_profit,
        )

    def _snapshot(self) -> dict:
        now = time.time()
        if self._snapshot_cache is None or now - self._snapshot_at >= 30:
            try:
                data = self.live_session.dashboard()
            except Exception as exc:
                self._set_error(str(exc))
                return {}
            if not data.get("logged_in"):
                return {}
            if data.get("error"):
                self._set_error(str(data["error"]))
            if "balance_pusd" in data:
                self._snapshot_cache = data
                self._snapshot_at = now
        return self._snapshot_cache or {}

    def _allocation_ratio(self) -> float:
        ratios = self.config.allocation_ratios or {}
        try:
            return float(ratios.get(self.asset.symbol, self.asset.allocation_ratio))
        except (TypeError, ValueError):
            return self.asset.allocation_ratio

    def _used_capital(self, positions: List[dict]) -> float:
        needle = self.asset.title_name.lower()
        total = 0.0
        for position in positions:
            title = str(position.get("title") or "").lower()
            if needle not in title:
                continue
            total += _to_float(position.get("initial_value") or position.get("current_value"))
        return total

    def _execute_pair(self, sized: ArbOpportunity) -> int:
        yes_amount = sized.shares * sized.yes_avg_price
        no_amount = sized.shares * sized.no_avg_price
        yes_result = self._safe_buy(sized.yes_token_id, yes_amount)
        no_result = self._safe_buy(sized.no_token_id, no_amount)
        successes = int(bool(yes_result.get("ok"))) + int(bool(no_result.get("ok")))
        self._log_execution(sized, yes_result, no_result, successes)
        if successes < 2:
            detail = (
                f"YES={yes_result.get('message')}; "
                f"NO={no_result.get('message')}"
            )
            self._set_error(detail)
        return successes

    def _safe_buy(self, token_id: str, amount: float) -> dict:
        try:
            return self.live_session.place_market_buy(token_id=token_id, amount=amount)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def _log_execution(self, sized: ArbOpportunity, yes_result: dict, no_result: dict, successes: int) -> None:
        self.live_session.add_execution_log(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "asset": self.asset.symbol,
                "pair_key": sized.pair_key,
                "yes_question": sized.yes_question,
                "no_question": sized.no_question,
                "shares": sized.shares,
                "yes_order_id": yes_result.get("order_id"),
                "no_order_id": no_result.get("order_id"),
                "ok": successes == 2,
                "detail": (
                    f"YES={yes_result.get('message')}; "
                    f"NO={no_result.get('message')}"
                ),
            }
        )

    def _set_error(self, message: Optional[str]) -> None:
        with self.lock:
            self.last_error = message
        self.live_session.set_auto_trader_error(message)


def _to_float(value: object) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
