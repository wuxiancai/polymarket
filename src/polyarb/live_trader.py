from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Optional

from .config import Config
from .live import LiveSession
from .live_execution import LiveExecutionStore, WalletReservations
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


MAX_TOTAL_OPEN_COST = Decimal("0.97")


class LiveAutoTrader:
    def __init__(
        self,
        live_session: LiveSession,
        config: Config,
        asset: AssetSpec,
        execution_store: Optional[LiveExecutionStore] = None,
        reservations: Optional[WalletReservations] = None,
    ) -> None:
        self.live_session = live_session
        self.config = config
        self.asset = asset
        self.lock = threading.Lock()
        self.last_execution: Dict[str, float] = {}
        self.last_execution_status: Dict[str, str] = {}
        self.blocked_pairs: Dict[str, str] = {}
        self.last_scan_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self._snapshot_cache: Optional[dict] = None
        self._snapshot_at = 0.0
        self.execution_store = execution_store
        self.reservations = reservations or WalletReservations()
        self._restored = False
        self._confirmed_reservations: Dict[str, float] = {}

    def on_result(self, result: ScanResult) -> None:
        if not self.live_session.is_logged_in():
            return
        try:
            self._process_result(result)
        except Exception as exc:
            self._set_error(str(exc))

    def _process_result(self, result: ScanResult) -> None:
        with self.lock:
            self.last_scan_at = result.scanned_at
        for opportunity in sorted(result.opportunities, key=_settlement_at):
            status, detail = self._opportunity_status(opportunity)
            self.live_session.upsert_live_opportunity(
                self._opportunity_entry(opportunity, status, detail)
            )

    def _opportunity_status(self, opportunity: ArbOpportunity) -> tuple[str, str]:
        if not opportunity.executable:
            return "仅观察", ""
        spread_cents = _spread_cents(opportunity)
        if spread_cents < MIN_SPREAD_TO_OPEN_CENTS:
            return "仅观察", ""
        self._restore_and_reconcile()
        blocked_detail = self.blocked_pairs.get(opportunity.pair_key)
        if blocked_detail:
            return "平仓未完成", blocked_detail
        last_status = self.last_execution_status.get(opportunity.pair_key)
        last_time = self.last_execution.get(opportunity.pair_key)
        if last_time is not None and time.time() - last_time < self.config.cooldown_seconds:
            return last_status or "已成交", ""
        if not self.live_session.is_auto_trading_enabled():
            return last_status or "可成交", ""
        if self.live_session.is_trading_region_blocked():
            self._set_error(self.live_session.geoblock_error() or "真实交易区域受限。")
            return "区域受限", "服务器 IP 所在地区被 Polymarket 限制开仓，仅可平仓"
        sized, sizing_status = self._size_opportunity(opportunity)
        if sized is None:
            if sizing_status == "资金不足":
                return "已触发，未成功", "资金不足"
            return sizing_status or "仅观察", ""
        if not self._should_execute(opportunity):
            return last_status or "可成交", ""
        price_caps = _price_caps(sized)
        if price_caps is None:
            return "仅观察", "价格上限无法保留至少 3¢ 套利空间"
        status, execution_detail = self._execute_pair(sized, *price_caps)
        if status == "资金不足":
            display_status = "已触发，未成功"
            detail = "资金不足"
        elif status == "区域受限":
            display_status = "区域受限"
            detail = "服务器 IP 所在地区被 Polymarket 限制开仓，仅可平仓"
        else:
            display_status = status
            detail = execution_detail
        self.last_execution_status[opportunity.pair_key] = display_status
        if status in {"已成交", "部分成交"}:
            with self.lock:
                self.last_execution[opportunity.pair_key] = time.time()
        return display_status, detail

    def _opportunity_entry(self, opportunity: ArbOpportunity, status: str, detail: str) -> dict:
        return {
            "time": self.last_scan_at.isoformat() if self.last_scan_at else "",
            "asset": self.asset.symbol,
            "pair_key": opportunity.pair_key,
            "yes_question": opportunity.yes_question,
            "no_question": opportunity.no_question,
            "yes_token_id": opportunity.yes_token_id,
            "no_token_id": opportunity.no_token_id,
            "spread_cents": _spread_cents(opportunity),
            "guaranteed_profit": opportunity.guaranteed_profit,
            "status": status,
            "detail": detail,
        }

    def _should_execute(self, opportunity: ArbOpportunity) -> bool:
        if not opportunity.executable:
            return False
        last = self.last_execution.get(opportunity.pair_key)
        if last is None:
            return True
        return time.time() - last >= self.config.cooldown_seconds

    def _size_opportunity(self, opportunity: ArbOpportunity) -> tuple[Optional[ArbOpportunity], str]:
        if opportunity.total_cost <= 0:
            return None, "仅观察"
        spread_cents = _spread_cents(opportunity)
        if spread_cents < MIN_SPREAD_TO_OPEN_CENTS:
            return None, "仅观察"
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
        reserved_asset = self.reservations.total(self.asset.symbol)
        reserved_total = self.reservations.total()
        total_used = _all_used_capital(snapshot.get("positions", []))
        available = min(
            max(0.0, allocation - used - reserved_asset),
            max(0.0, balance - total_used - reserved_total),
        )
        target_budget = min(opportunity.total_cost, allocation * position_ratio)
        if available < target_budget:
            return None, "资金不足"
        scale = target_budget / opportunity.total_cost
        shares = opportunity.shares * scale
        total_cost = opportunity.total_cost * scale
        min_payout = opportunity.min_payout * scale
        guaranteed_profit = opportunity.guaranteed_profit * scale
        if shares < MIN_DISPLAYED_POSITION_VALUE or guaranteed_profit < MIN_DISPLAYED_POSITION_VALUE:
            # Low wallet budget can scale below the displayable minimum; treat it as insufficient funds.
            return None, "资金不足"
        return (
            replace(
                opportunity,
                shares=shares,
                total_cost=total_cost,
                min_payout=min_payout,
                guaranteed_profit=guaranteed_profit,
            ),
            "",
        )

    def _snapshot(self, force: bool = False) -> dict:
        now = time.time()
        if force or self._snapshot_cache is None or now - self._snapshot_at >= 30:
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
                for reservation_id, confirmed_at in list(self._confirmed_reservations.items()):
                    if now - confirmed_at >= 5:
                        self.reservations.release(reservation_id)
                        self._confirmed_reservations.pop(reservation_id, None)
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

    def _execute_pair(
        self,
        sized: ArbOpportunity,
        yes_max_price: float,
        no_max_price: float,
    ) -> tuple[str, str]:
        baseline = self._snapshot(force=True)
        reservation_id = ""
        intent = None
        if self.execution_store is not None:
            intent = self.execution_store.create(
                asset=self.asset.symbol,
                pair_key=sized.pair_key,
                yes_token_id=sized.yes_token_id,
                no_token_id=sized.no_token_id,
                shares=sized.shares,
                reserved_capital=sized.total_cost,
                baseline_yes_shares=_token_shares(baseline.get("positions", []), sized.yes_token_id),
                baseline_no_shares=_token_shares(baseline.get("positions", []), sized.no_token_id),
            )
            reservation_id = str(intent["id"])
        else:
            reservation_id = f"memory:{sized.pair_key}:{time.time_ns()}"
        if not self.reservations.reserve(reservation_id, self.asset.symbol, sized.total_cost, _to_float(baseline.get("balance_pusd"))):
            if intent is not None:
                self.execution_store.update(reservation_id, state="failed", detail="提交前资金预留失败。")
            return "资金不足", ""
        yes_result, no_result = self._safe_pair_buy(
            sized,
            yes_max_price=yes_max_price,
            no_max_price=no_max_price,
        )
        if intent is not None:
            self.execution_store.update(
                reservation_id,
                yes_order_id=str(yes_result.get("order_id") or ""),
                no_order_id=str(no_result.get("order_id") or ""),
            )
        successes = int(_is_confirmed_full_buy(yes_result, sized.shares)) + int(_is_confirmed_full_buy(no_result, sized.shares))
        # A delayed or response-lost leg may still fill after this method returns.  Do not
        # liquidate the confirmed leg until the uncertain leg is reconciled; doing so can
        # create the very one-leg exposure this safeguard is intended to prevent.
        if _is_ambiguous_submission(yes_result) or _is_ambiguous_submission(no_result):
            detail = "订单提交或成交仍不确定，已冻结交易对并等待持仓对账，禁止重复开仓。"
            self.blocked_pairs[sized.pair_key] = detail
            self._update_intent(reservation_id, "unknown_submission", detail)
            self._set_error(detail)
            self._log_execution(sized, yes_result, no_result, 0)
            return "成交确认中", detail
        if successes == 2:
            # Keep the reservation until a fresh account snapshot includes the new position.
            # Otherwise another opportunity in this same scan can spend the same cached balance.
            self._complete_intent(reservation_id, "confirmed", "YES/NO 两腿均已确认完整成交。", release=False)
            self._confirmed_reservations[reservation_id] = time.time()
            self._log_execution(sized, yes_result, no_result, successes)
            return "已成交", ""
        if successes == 1:
            successful_is_yes = _is_confirmed_full_buy(yes_result, sized.shares)
            successful_token = sized.yes_token_id if successful_is_yes else sized.no_token_id
            exit_result = self._safe_emergency_exit(
                token_id=successful_token,
                shares=sized.shares,
            )
            filled_shares = _filled_sell_shares(exit_result, sized.shares)
            remaining_shares = max(0.0, sized.shares - filled_shares)
            if remaining_shares <= 1e-6:
                self._complete_intent(reservation_id, "closed", "单腿成交已确认，紧急平仓已确认完成。")
                self._log_execution(sized, yes_result, no_result, 0, exit_result)
                return "已平仓", "初始一腿未成交，已全部平仓并释放资金。"
            detail = (
                f"初始订单 YES={yes_result.get('message')}; NO={no_result.get('message')}; "
                f"立即平仓未完成，剩余 {remaining_shares:g} 份：{exit_result.get('message')}"
            )
            self._log_execution(sized, yes_result, no_result, 0, exit_result)
            self._set_error(detail)
            self.blocked_pairs[sized.pair_key] = detail
            self._update_intent(reservation_id, "exit_pending", detail)
            return "平仓未完成", detail
        self._complete_intent(reservation_id, "failed", "两腿均未确认成交。")
        self._log_execution(sized, yes_result, no_result, successes)
        detail = (
            f"YES={yes_result.get('message')}; "
            f"NO={no_result.get('message')}"
        )
        self._set_error(detail)
        if _is_region_restricted(detail):
            self.live_session.mark_region_blocked()
            self._set_error(self.live_session.geoblock_error() or "真实交易区域受限。")
            return "区域受限", ""
        if _is_insufficient_funds(detail):
            return "资金不足", ""
        return "交易失败", detail

    def _update_intent(self, reservation_id: str, state: str, detail: str) -> None:
        if self.execution_store is not None and not reservation_id.startswith("memory:"):
            self.execution_store.update(reservation_id, state=state, detail=detail)

    def _complete_intent(self, reservation_id: str, state: str, detail: str, *, release: bool = True) -> None:
        self._update_intent(reservation_id, state, detail)
        if release:
            self.reservations.release(reservation_id)

    def _restore_and_reconcile(self) -> None:
        if self.execution_store is None:
            return
        active = self.execution_store.active(self.asset.symbol)
        for intent in active:
            intent_id = str(intent["id"])
            if not self._restored:
                self.reservations.reserve(intent_id, self.asset.symbol, _to_float(intent["reserved_capital"]), float("inf"))
            snapshot = self._snapshot(force=True)
            yes_delta = _token_shares(snapshot.get("positions", []), str(intent["yes_token_id"])) - _to_float(intent["baseline_yes_shares"])
            no_delta = _token_shares(snapshot.get("positions", []), str(intent["no_token_id"])) - _to_float(intent["baseline_no_shares"])
            shares = _to_float(intent["shares"])
            if yes_delta >= shares - 1e-6 and no_delta >= shares - 1e-6:
                self._complete_intent(intent_id, "confirmed", "服务恢复后已对账确认两腿完整成交。")
                self.blocked_pairs.pop(str(intent["pair_key"]), None)
            elif yes_delta <= 1e-6 and no_delta <= 1e-6:
                detail = "订单/成交状态尚未可确认；已保持冻结，等待下一次真实持仓对账。"
                self.blocked_pairs[str(intent["pair_key"])] = detail
            else:
                token_id = str(intent["yes_token_id"] if yes_delta > no_delta else intent["no_token_id"])
                exposed = max(yes_delta, no_delta)
                exit_result = self._safe_emergency_exit(token_id=token_id, shares=exposed)
                if _filled_sell_shares(exit_result, exposed) >= exposed - 1e-6:
                    self._complete_intent(intent_id, "closed", "服务恢复后发现单腿仓位，已紧急平仓。")
                    self.blocked_pairs.pop(str(intent["pair_key"]), None)
                else:
                    detail = "服务恢复后发现单腿仓位，但紧急平仓尚未完成；该交易对已冻结。"
                    self._update_intent(intent_id, "exit_pending", detail)
                    self.blocked_pairs[str(intent["pair_key"])] = detail
        self._restored = True

    def _safe_pair_buy(
        self,
        sized: ArbOpportunity,
        *,
        yes_max_price: float,
        no_max_price: float,
    ) -> tuple[dict, dict]:
        try:
            results = self.live_session.place_protected_pair_buy(
                yes_token_id=sized.yes_token_id,
                no_token_id=sized.no_token_id,
                shares=sized.shares,
                yes_max_price=yes_max_price,
                no_max_price=no_max_price,
            )
            if len(results) == 2:
                return results[0], results[1]
            failure = {"ok": False, "message": "套利批量订单返回不完整。"}
            return failure, failure
        except Exception as exc:
            failure = {"ok": False, "message": str(exc)}
            return failure, failure

    def _safe_emergency_exit(self, *, token_id: str, shares: float) -> dict:
        try:
            return self.live_session.place_emergency_market_sell(
                token_id=token_id,
                shares=shares,
            )
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def _log_execution(
        self,
        sized: ArbOpportunity,
        yes_result: dict,
        no_result: dict,
        successes: int,
        exit_result: Optional[dict] = None,
    ) -> None:
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
                    + (f"; 平仓={exit_result.get('message')}" if exit_result else "")
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


def _is_insufficient_funds(message: str) -> bool:
    lowered = message.lower()
    return any(
        keyword in lowered
        for keyword in ("not enough balance", "insufficient", "资金不足", "allowance")
    )


def _is_region_restricted(message: str) -> bool:
    return "trading restricted in your region" in message.lower()


def _filled_sell_shares(result: dict, requested_shares: float) -> float:
    if not result.get("ok"):
        return 0.0
    try:
        filled = float(result.get("making_amount"))
    except (TypeError, ValueError):
        return 0.0
    return min(max(0.0, filled), requested_shares)


def _is_confirmed_full_buy(result: dict, requested_shares: float) -> bool:
    if not result.get("ok") or str(result.get("status") or "").lower() != "matched":
        return False
    try:
        filled = float(result.get("taking_amount"))
    except (TypeError, ValueError):
        return False
    return filled >= requested_shares - 1e-6 and bool(result.get("trade_ids"))


def _is_ambiguous_submission(result: dict) -> bool:
    if not result.get("ok"):
        return bool(result.get("unknown_submission"))
    return str(result.get("status") or "").lower() in {"delayed", "live", "unmatched", ""}


def _token_shares(positions: List[dict], token_id: str) -> float:
    return sum(
        _to_float(position.get("size"))
        for position in positions
        if str(position.get("token_id") or "") == token_id
    )


def _all_used_capital(positions: List[dict]) -> float:
    return sum(_to_float(position.get("initial_value") or position.get("current_value")) for position in positions)


def _price_caps(opportunity: ArbOpportunity) -> Optional[tuple[float, float]]:
    """Split the observed edge across both legs without crossing the 97¢ ceiling."""
    yes_price = Decimal(str(opportunity.yes_avg_price))
    no_price = Decimal(str(opportunity.no_avg_price))
    observed_total = yes_price + no_price
    if observed_total > MAX_TOTAL_OPEN_COST:
        return None
    half_headroom = (MAX_TOTAL_OPEN_COST - observed_total) / Decimal("2")
    cents = Decimal("0.01")
    yes_cap = (yes_price + half_headroom).quantize(cents, rounding=ROUND_DOWN)
    no_cap = (no_price + half_headroom).quantize(cents, rounding=ROUND_DOWN)
    if yes_cap <= 0 or no_cap <= 0 or yes_cap + no_cap > MAX_TOTAL_OPEN_COST:
        return None
    return float(yes_cap), float(no_cap)
