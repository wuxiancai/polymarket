from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

PUSD_DECIMALS = 1_000_000
REDEEM_RETRY_SECONDS = 300
MAX_REDEMPTION_LOG = 100


class LiveTradingError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveCredentials:
    private_key: str
    wallet: str
    relayer_api_key: str = ""
    relayer_api_key_address: str = ""

    def __repr__(self) -> str:
        return (
            "LiveCredentials("
            f"private_key=<redacted>, wallet={self.wallet!r}, "
            f"has_relayer={bool(self.relayer_api_key)!r})"
        )


class LiveTradingClient:
    def __init__(self, credentials: LiveCredentials, sdk_client: Any = None) -> None:
        self.credentials = credentials
        self._sdk_client = sdk_client

    def _ensure_sdk_client(self) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        if self.credentials.relayer_api_key and not self.credentials.relayer_api_key_address:
            raise LiveTradingError("Relayer API 密钥需要同时提供 Relayer API 地址。")
        try:
            from polymarket import RelayerApiKey, SecureClient
        except ImportError as exc:
            raise LiveTradingError(
                "未安装 polymarket-client。真实交易需要 Python 3.11+，请重新执行 bash deploy.sh。"
            ) from exc
        kwargs = {
            "private_key": self.credentials.private_key,
            "wallet": self.credentials.wallet,
        }
        if self.credentials.relayer_api_key:
            kwargs["api_key"] = RelayerApiKey(
                key=self.credentials.relayer_api_key,
                address=self.credentials.relayer_api_key_address,
            )
        self._sdk_client = SecureClient.create(**kwargs)
        return self._sdk_client

    def close(self) -> None:
        client = self._sdk_client
        if client is not None and hasattr(client, "close"):
            client.close()
        self._sdk_client = None

    def snapshot(self) -> dict:
        client = self._ensure_sdk_client()
        balance_allowance = client.get_balance_allowance(asset_type="COLLATERAL")
        balance = _safe_float(getattr(balance_allowance, "balance", 0)) / PUSD_DECIMALS
        values = list(client.get_portfolio_values())
        portfolio_value = _sum_floats([_safe_float(getattr(item, "value", 0)) for item in values])
        positions = _items(client.list_positions(page_size=500, size_threshold=0))
        closed_positions = _items(client.list_closed_positions(page_size=50))
        open_orders = _items(client.list_open_orders())
        trades = _items(client.list_account_trades())
        unrealized_pnl = _sum_floats([_safe_float(getattr(item, "cash_pnl", 0)) for item in positions])
        realized_pnl = _sum_floats(
            [_safe_float(getattr(item, "realized_pnl", 0)) for item in closed_positions]
        )
        position_value = _sum_floats(
            [_safe_float(getattr(item, "current_value", 0)) for item in positions]
        )
        return {
            "logged_in": True,
            "account": {
                "wallet": _safe_text(getattr(client, "wallet", "")),
                "signer": _safe_text(getattr(client, "signer", "")),
                "wallet_type": _safe_text(getattr(client, "wallet_type", "")),
                "has_relayer": bool(self.credentials.relayer_api_key),
            },
            "balance_pusd": balance,
            "portfolio_value": portfolio_value,
            "position_value": position_value,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "positions": [_position_dict(item) for item in positions],
            "closed_positions": [_closed_position_dict(item) for item in closed_positions],
            "open_orders": [_order_dict(item) for item in open_orders],
            "trades": [_trade_dict(item) for item in trades],
        }

    def place_order(
        self,
        *,
        token_id: str,
        side: str,
        order_type: str,
        amount: str = "",
        shares: str = "",
        price: str = "",
        confirm: bool = False,
    ) -> dict:
        if not confirm:
            raise LiveTradingError("真实下单必须勾选确认。")
        client = self._ensure_sdk_client()
        normalized_side = str(side or "BUY").upper()
        if normalized_side not in {"BUY", "SELL"}:
            raise LiveTradingError("side 必须是 BUY 或 SELL。")
        normalized_type = str(order_type or "market").lower()
        if normalized_type == "limit":
            if not token_id or not price or shares in (None, ""):
                raise LiveTradingError("限价单需要 token_id、价格和份额。")
            response = client.place_limit_order(
                token_id=token_id,
                side=normalized_side,
                price=str(price),
                size=str(shares),
            )
        elif normalized_side == "BUY":
            if not token_id or amount in (None, ""):
                raise LiveTradingError("市价买单需要 token_id 和支出金额。")
            response = client.place_market_order(
                token_id=token_id,
                side="BUY",
                amount=str(amount),
            )
        else:
            if not token_id or shares in (None, ""):
                raise LiveTradingError("市价卖单需要 token_id 和卖出份额。")
            response = client.place_market_order(
                token_id=token_id,
                side="SELL",
                shares=str(shares),
            )
        return _order_response_dict(response)

    def place_market_buy(self, token_id: str, amount: float) -> dict:
        if not token_id or amount <= 0:
            raise LiveTradingError("自动买入需要 token_id 和正数金额。")
        client = self._ensure_sdk_client()
        response = client.place_market_order(
            token_id=token_id,
            side="BUY",
            amount=str(round(amount, 6)),
        )
        return _order_response_dict(response)

    def cancel_order(self, order_id: str) -> dict:
        if not order_id:
            raise LiveTradingError("order_id 不能为空。")
        client = self._ensure_sdk_client()
        response = client.cancel_order(order_id=order_id)
        canceled = list(getattr(response, "canceled", []) or [])
        not_canceled = getattr(response, "not_canceled", {}) or {}
        if order_id in canceled:
            return {"ok": True, "order_id": order_id, "message": "订单已取消。"}
        reason = not_canceled.get(order_id) if isinstance(not_canceled, dict) else None
        return {
            "ok": False,
            "order_id": order_id,
            "message": str(reason or "订单未能取消。"),
        }

    def redeem_positions(self, condition_id: str) -> dict:
        if not condition_id:
            raise LiveTradingError("condition_id 不能为空。")
        client = self._ensure_sdk_client()
        handle = client.redeem_positions(condition_id=condition_id)
        outcome = handle.wait()
        return {
            "ok": True,
            "condition_id": condition_id,
            "transaction_hash": _safe_text(getattr(outcome, "transaction_hash", "")),
        }


class LiveSession:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client: Optional[LiveTradingClient] = None
        self.last_error: Optional[str] = None
        self.auto_trading_enabled = False
        self.auto_trader_error: Optional[str] = None
        self.execution_log: List[dict] = []
        self._live_opportunities: Dict[str, dict] = {}
        self.redemption_log: List[dict] = []
        self._redeem_attempted: Dict[str, float] = {}

    def is_logged_in(self) -> bool:
        with self._lock:
            return self._client is not None

    def connect(self, credentials: LiveCredentials) -> dict:
        client = LiveTradingClient(credentials)
        snapshot = client.snapshot()
        snapshot["auto_trading_enabled"] = True
        snapshot["auto_trader_error"] = None
        snapshot["execution_log"] = []
        snapshot["live_opportunities"] = []
        with self._lock:
            old_client = self._client
            self._client = client
            self.last_error = None
            self.auto_trading_enabled = True
            self.auto_trader_error = None
            self._live_opportunities = {}
            self.redemption_log = []
            self._redeem_attempted = {}
        if old_client is not None:
            old_client.close()
        return snapshot

    def dashboard(self) -> dict:
        with self._lock:
            client = self._client
            if client is None:
                return {
                    "logged_in": False,
                    "error": None,
                    "live_opportunities": [],
                    "redemption_log": [],
                }
            try:
                data = client.snapshot()
                data["logged_in"] = True
            except Exception as exc:
                self.last_error = str(exc)
                return {
                    "logged_in": True,
                    "error": str(exc),
                    "auto_trading_enabled": self.auto_trading_enabled,
                    "auto_trader_error": self.last_error,
                    "execution_log": list(self.execution_log[-200:]),
                    "live_opportunities": self._opportunity_snapshot(),
                    "redemption_log": list(self.redemption_log[-MAX_REDEMPTION_LOG:]),
                }
            data["auto_trading_enabled"] = self.auto_trading_enabled
            data["auto_trader_error"] = self.auto_trader_error
            data["execution_log"] = list(self.execution_log[-200:])
            data["live_opportunities"] = self._opportunity_snapshot()
            self._auto_redeem(data.get("positions", []), client)
            data["redemption_log"] = list(self.redemption_log[-MAX_REDEMPTION_LOG:])
            return data

    def is_auto_trading_enabled(self) -> bool:
        with self._lock:
            return self.auto_trading_enabled

    def set_auto_trading(self, enabled: bool) -> bool:
        with self._lock:
            self.auto_trading_enabled = bool(enabled)
            if self.auto_trading_enabled:
                self.auto_trader_error = None
            return self.auto_trading_enabled

    def add_execution_log(self, entry: dict) -> None:
        with self._lock:
            self.execution_log.append(entry)
            self.execution_log = self.execution_log[-200:]

    def set_auto_trader_error(self, message: Optional[str]) -> None:
        with self._lock:
            self.auto_trader_error = message

    def _auto_redeem(self, positions: List[dict], client: LiveTradingClient) -> None:
        now = time.time()
        seen_conditions = set()
        for position in positions:
            if not bool(position.get("redeemable")):
                continue
            condition_id = str(position.get("condition_id") or "")
            if not condition_id or condition_id in seen_conditions:
                continue
            seen_conditions.add(condition_id)
            last_attempt = self._redeem_attempted.get(condition_id)
            if last_attempt is not None and now - last_attempt < REDEEM_RETRY_SECONDS:
                continue
            self._redeem_attempted[condition_id] = now
            title = str(position.get("title") or "")
            try:
                result = client.redeem_positions(condition_id)
            except Exception as exc:
                self._append_redemption_log(
                    {
                        "time": datetime.now(timezone.utc).isoformat(),
                        "condition_id": condition_id,
                        "title": title,
                        "transaction_hash": "",
                        "ok": False,
                        "detail": str(exc),
                    }
                )
                continue
            self._append_redemption_log(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "condition_id": condition_id,
                    "title": title,
                    "transaction_hash": str(result.get("transaction_hash") or ""),
                    "ok": bool(result.get("ok")),
                    "detail": "已自动兑换。" if result.get("ok") else "自动兑换失败。",
                }
            )

    def _append_redemption_log(self, entry: dict) -> None:
        self.redemption_log.append(entry)
        self.redemption_log = self.redemption_log[-MAX_REDEMPTION_LOG:]

    def auto_redeem_once(self) -> None:
        with self._lock:
            client = self._client
            if client is None:
                return
            try:
                data = client.snapshot()
            except Exception as exc:
                self.last_error = str(exc)
                return
            self._auto_redeem(data.get("positions", []), client)

    def upsert_live_opportunity(self, entry: dict) -> None:
        with self._lock:
            key = str(entry.get("pair_key") or entry.get("yes_token_id") or entry.get("time") or "")
            if key:
                self._live_opportunities[key] = entry

    def _opportunity_snapshot(self) -> List[dict]:
        return sorted(
            self._live_opportunities.values(),
            key=lambda item: str(item.get("time") or ""),
            reverse=True,
        )

    def place_market_buy(self, token_id: str, amount: float) -> dict:
        with self._lock:
            client = self._require_client()
            return client.place_market_buy(token_id=token_id, amount=amount)

    def place_order(
        self,
        *,
        token_id: str,
        side: str,
        order_type: str,
        amount: str = "",
        shares: str = "",
        price: str = "",
        confirm: bool = False,
    ) -> dict:
        with self._lock:
            client = self._require_client()
            return client.place_order(
                token_id=token_id,
                side=side,
                order_type=order_type,
                amount=amount,
                shares=shares,
                price=price,
                confirm=confirm,
            )

    def cancel_order(self, order_id: str) -> dict:
        with self._lock:
            client = self._require_client()
            return client.cancel_order(order_id=order_id)

    def logout(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
            self.last_error = None
            self.auto_trading_enabled = False
            self.auto_trader_error = None
            self.execution_log = []
            self._live_opportunities = {}
            self.redemption_log = []
            self._redeem_attempted = {}
        if client is not None:
            client.close()

    def _require_client(self) -> LiveTradingClient:
        if self._client is None:
            raise LiveTradingError("请先登录真实账户。")
        return self._client


def live_credentials_from_env() -> Optional[LiveCredentials]:
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY") or ""
    wallet = os.getenv("POLYMARKET_WALLET_ADDRESS") or ""
    if not private_key or not wallet:
        return None
    return LiveCredentials(
        private_key=private_key,
        wallet=wallet,
        relayer_api_key=os.getenv("POLYMARKET_RELAYER_API_KEY") or "",
        relayer_api_key_address=os.getenv("POLYMARKET_RELAYER_API_KEY_ADDRESS") or "",
    )


def _items(paginator: Any) -> List[Any]:
    if hasattr(paginator, "first_page"):
        page = paginator.first_page()
        return list(getattr(page, "items", []) or [])
    return list(paginator)


def _position_dict(item: Any) -> dict:
    return {
        "condition_id": _safe_text(getattr(item, "condition_id", "")),
        "token_id": _safe_text(getattr(item, "token_id", "")),
        "size": _safe_float(getattr(item, "size", 0)),
        "avg_price": _safe_float(getattr(item, "avg_price", 0)),
        "initial_value": _safe_float(getattr(item, "initial_value", 0)),
        "current_value": _safe_float(getattr(item, "current_value", 0)),
        "cash_pnl": _safe_float(getattr(item, "cash_pnl", 0)),
        "percent_pnl": _safe_float(getattr(item, "percent_pnl", 0)),
        "title": _safe_text(getattr(item, "title", "")),
        "slug": _safe_text(getattr(item, "slug", "")),
        "event_slug": _safe_text(getattr(item, "event_slug", "")),
        "outcome": _safe_text(getattr(item, "outcome", "")),
        "redeemable": bool(getattr(item, "redeemable", False)),
        "end_date": _safe_text(getattr(item, "end_date", "")),
    }


def _closed_position_dict(item: Any) -> dict:
    return {
        "condition_id": _safe_text(getattr(item, "condition_id", "")),
        "token_id": _safe_text(getattr(item, "token_id", "")),
        "realized_pnl": _safe_float(getattr(item, "realized_pnl", 0)),
        "total_bought": _safe_float(getattr(item, "total_bought", 0)),
        "title": _safe_text(getattr(item, "title", "")),
        "slug": _safe_text(getattr(item, "slug", "")),
        "event_slug": _safe_text(getattr(item, "event_slug", "")),
        "outcome": _safe_text(getattr(item, "outcome", "")),
        "timestamp": _safe_text(getattr(item, "timestamp", "")),
        "end_date": _safe_text(getattr(item, "end_date", "")),
    }


def _order_dict(item: Any) -> dict:
    return {
        "id": _safe_text(getattr(item, "id", "")),
        "condition_id": _safe_text(getattr(item, "condition_id", "")),
        "token_id": _safe_text(getattr(item, "token_id", "")),
        "side": _safe_text(getattr(item, "side", "")),
        "price": _safe_float(getattr(item, "price", 0)),
        "original_size": _safe_float(getattr(item, "original_size", 0)),
        "size_matched": _safe_float(getattr(item, "size_matched", 0)),
        "outcome": _safe_text(getattr(item, "outcome", "")),
        "order_type": _safe_text(getattr(item, "order_type", "")),
        "status": _safe_text(getattr(item, "status", "")),
        "created_at": _safe_text(getattr(item, "created_at", "")),
        "expires_at": _safe_text(getattr(item, "expires_at", "")),
    }


def _trade_dict(item: Any) -> dict:
    return {
        "id": _safe_text(getattr(item, "id", "")),
        "condition_id": _safe_text(getattr(item, "condition_id", "")),
        "token_id": _safe_text(getattr(item, "token_id", "")),
        "side": _safe_text(getattr(item, "side", "")),
        "price": _safe_float(getattr(item, "price", 0)),
        "size": _safe_float(getattr(item, "size", 0)),
        "outcome": _safe_text(getattr(item, "outcome", "")),
        "status": _safe_text(getattr(item, "status", "")),
        "transaction_hash": _safe_text(getattr(item, "transaction_hash", "")),
        "matched_at": _safe_text(getattr(item, "matched_at", "")),
    }


def _order_response_dict(response: Any) -> dict:
    if isinstance(response, dict):
        return response
    ok = bool(getattr(response, "ok", False))
    if ok:
        return {
            "ok": True,
            "order_id": _safe_text(getattr(response, "order_id", "")),
            "status": _safe_text(getattr(response, "status", "")),
            "trade_ids": list(getattr(response, "trade_ids", []) or []),
            "transactions_hashes": list(getattr(response, "transactions_hashes", []) or []),
            "message": "订单已提交。",
        }
    return {
        "ok": False,
        "code": _safe_text(getattr(response, "code", "unknown")),
        "message": _safe_text(getattr(response, "message", "订单被拒绝。")),
    }


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _sum_floats(values: List[float]) -> float:
    return sum(float(value or 0) for value in values)
