from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .execution_rules import pair_has_strict_coverage

PUSD_DECIMALS = 1_000_000
REDEEM_RETRY_SECONDS = 300
MAX_REDEMPTION_LOG = 100
GEOBLOCK_URL = "https://polymarket.com/api/geoblock"
GEOBLOCK_TTL_SECONDS = 60.0
GEOBLOCK_TIMEOUT_SECONDS = 4.0


def _same_address(a: str, b: str) -> bool:
    return bool(a and b and a.strip().lower() == b.strip().lower())


def _signer_address_from_private_key(private_key: str) -> str:
    if not private_key:
        return ""
    try:
        from eth_account import Account

        return Account.from_key(private_key).address
    except Exception:
        return ""


def _normalize_wallet_for_sdk(
    wallet: str,
    private_key: str,
    relayer_address: str = "",
) -> Optional[str]:
    wallet = (wallet or "").strip()
    if not wallet:
        return None
    signer = _signer_address_from_private_key(private_key)
    if signer and _same_address(wallet, signer):
        return None
    if relayer_address and _same_address(wallet, relayer_address):
        return None
    return wallet


def _fetch_geoblock() -> Optional[dict]:
    try:
        from urllib.request import Request, urlopen

        request = Request(
            GEOBLOCK_URL,
            headers={
                "User-Agent": "polyarb/live",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=GEOBLOCK_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        return {
            "blocked": bool(payload.get("blocked")),
            "ip": str(payload.get("ip") or ""),
            "country": str(payload.get("country") or ""),
            "region": str(payload.get("region") or ""),
        }
    except Exception:
        return None


def geoblock_message(geo: Optional[dict]) -> str:
    if not geo or not geo.get("blocked"):
        return ""
    ip = str(geo.get("ip") or "未知 IP")
    country = str(geo.get("country") or "未知地区")
    region = str(geo.get("region") or "")
    location = country if not region else f"{country}/{region}"
    return (
        f"真实交易区域受限：服务器出口 IP {ip}（{location}）被 Polymarket 限制开仓，仅可平仓。"
        "请将服务部署或代理迁移到允许地区（如 eu-west-1）后重启服务。"
    )


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
            "wallet": _normalize_wallet_for_sdk(
                self.credentials.wallet,
                self.credentials.private_key,
                self.credentials.relayer_api_key_address,
            ),
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

    def place_protected_pair_buy(
        self,
        *,
        yes_token_id: str,
        no_token_id: str,
        shares: float,
        yes_max_price: float,
        no_max_price: float,
        fee_buffer: float = 0.0,
        yes_fee_budget: float = 0.0,
        no_fee_budget: float = 0.0,
    ) -> List[dict]:
        """Submit both legs together as full-or-kill buys with hard price caps."""
        try:
            target_shares = Decimal(str(shares))
            yes_price = Decimal(str(yes_max_price))
            no_price = Decimal(str(no_max_price))
            fee = Decimal(str(fee_buffer))
        except (InvalidOperation, ValueError) as exc:
            raise LiveTradingError("套利订单的份额或价格上限无效。") from exc
        if not yes_token_id or not no_token_id or target_shares <= 0:
            raise LiveTradingError("套利订单需要两个 token 和正数份额。")
        if fee < 0 or yes_price <= 0 or no_price <= 0 or yes_price + no_price >= Decimal("1"):
            raise LiveTradingError("套利两腿价格上限无效，必须低于最终 $1 兑付。")
        client = self._ensure_sdk_client()
        try:
            yes_fee = max(Decimal("0"), Decimal(str(yes_fee_budget))) + target_shares * fee / Decimal("2")
            no_fee = max(Decimal("0"), Decimal(str(no_fee_budget))) + target_shares * fee / Decimal("2")
        except InvalidOperation as exc:
            raise LiveTradingError("套利订单手续费预算无效。") from exc
        signed_orders = [
            client.create_market_order(
                token_id=token_id,
                side="BUY",
                amount=str(target_shares * max_price),
                max_spend=str(target_shares * max_price + fee_budget),
                max_price=str(max_price),
                order_type="FOK",
            )
            for token_id, max_price, fee_budget in ((yes_token_id, yes_price, yes_fee), (no_token_id, no_price, no_fee))
        ]
        requested_shares = [_signed_buy_shares(order, target_shares) for order in signed_orders]
        max_spends = [float(target_shares * yes_price + yes_fee), float(target_shares * no_price + no_fee)]
        if not pair_has_strict_coverage(*requested_shares, *max_spends):
            raise LiveTradingError(
                "手续费导致两腿份额差异过大，较小份额的结算兑付扣除两腿最高总支出后不足 $0.001，订单未提交。"
            )
        try:
            results = [_order_response_dict(response) for response in client.post_orders(signed_orders)]
            for result, shares, max_spend in zip(results, requested_shares, max_spends):
                result["requested_shares"] = shares
                result["max_spend"] = max_spend
            return results
        except Exception as exc:
            # The CLOB may have received signed orders even when the HTTP response was lost.
            return [
                {"ok": False, "unknown_submission": True, "message": f"批量订单提交结果未知：{exc}"},
                {"ok": False, "unknown_submission": True, "message": f"批量订单提交结果未知：{exc}"},
            ]

    def place_emergency_market_sell(self, *, token_id: str, shares: float) -> dict:
        """Immediately release a one-leg position; partial fills are reported to the caller."""
        try:
            quantity = Decimal(str(shares))
        except (InvalidOperation, ValueError) as exc:
            raise LiveTradingError("平仓份额无效。") from exc
        if not token_id or quantity <= 0:
            raise LiveTradingError("平仓需要 token 和正数份额。")
        response = self._ensure_sdk_client().place_market_order(
            token_id=token_id,
            side="SELL",
            shares=str(quantity),
            order_type="FAK",
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
        self._lock = threading.RLock()
        self._client: Optional[LiveTradingClient] = None
        self.last_error: Optional[str] = None
        self.auto_trading_enabled = False
        self.auto_trader_error: Optional[str] = None
        self.execution_log: List[dict] = []
        self.system_error_log: List[dict] = []
        self._live_opportunities: Dict[str, dict] = {}
        self.redemption_log: List[dict] = []
        self._redeem_attempted: Dict[str, float] = {}
        self._geoblock: Optional[dict] = None
        self._geoblock_at = 0.0
        self._geoblock_last_attempt = 0.0

    def is_logged_in(self) -> bool:
        with self._lock:
            return self._client is not None

    def geoblock(self, force: bool = False) -> Optional[dict]:
        now = time.time()
        with self._lock:
            if (
                self._geoblock is not None
                and not force
                and now - self._geoblock_at < GEOBLOCK_TTL_SECONDS
            ):
                return dict(self._geoblock)
            if not force and now - self._geoblock_last_attempt < GEOBLOCK_TTL_SECONDS:
                return dict(self._geoblock) if self._geoblock is not None else None
            self._geoblock_last_attempt = now
        data = _fetch_geoblock()
        if data is None:
            with self._lock:
                return dict(self._geoblock) if self._geoblock is not None else None
        with self._lock:
            self._geoblock = data
            self._geoblock_at = now
        return dict(data)

    def is_trading_region_blocked(self, force: bool = False) -> bool:
        data = self.geoblock(force=force)
        return bool(data and data.get("blocked"))

    def geoblock_error(self) -> str:
        with self._lock:
            geo = dict(self._geoblock) if self._geoblock is not None else None
        return geoblock_message(geo)

    def mark_region_blocked(self) -> None:
        with self._lock:
            current = dict(self._geoblock or {})
            current["blocked"] = True
            self._geoblock = current
            self._geoblock_at = time.time()

    def connect(self, credentials: LiveCredentials) -> dict:
        client = LiveTradingClient(credentials)
        snapshot = client.snapshot()
        geo = self.geoblock(force=True)
        auto_trader_error = geoblock_message(geo) if geo and geo.get("blocked") else None
        snapshot["auto_trading_enabled"] = True
        snapshot["auto_trader_error"] = auto_trader_error
        snapshot["execution_log"] = []
        snapshot["system_error_log"] = self.system_errors()
        snapshot["live_opportunities"] = []
        with self._lock:
            old_client = self._client
            self._client = client
            self.last_error = None
            self.auto_trading_enabled = True
            self.auto_trader_error = auto_trader_error
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
                self.add_system_error("真实账户快照", exc)
                return {
                    "logged_in": True,
                    "error": str(exc),
                    "auto_trading_enabled": self.auto_trading_enabled,
                    "auto_trader_error": self.last_error,
                    "execution_log": list(self.execution_log[-200:]),
                    "system_error_log": self.system_errors(),
                    "live_opportunities": self._opportunity_snapshot(),
                    "redemption_log": list(self.redemption_log[-MAX_REDEMPTION_LOG:]),
                }
            data["auto_trading_enabled"] = self.auto_trading_enabled
            data["auto_trader_error"] = self.auto_trader_error
            data["execution_log"] = list(self.execution_log[-200:])
            data["system_error_log"] = self.system_errors()
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
            result = self.auto_trading_enabled
        if result:
            geo = self.geoblock(force=True)
            if geo and geo.get("blocked"):
                self.set_auto_trader_error(geoblock_message(geo))
        return result

    def add_execution_log(self, entry: dict) -> None:
        with self._lock:
            self.execution_log.append(entry)
            self.execution_log = self.execution_log[-200:]

    def set_auto_trader_error(self, message: Optional[str]) -> None:
        with self._lock:
            self.auto_trader_error = message

    def add_system_error(self, source: str, message: object) -> None:
        text = str(message or "").strip()
        if not text:
            return
        with self._lock:
            self.system_error_log.append(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "source": str(source or "系统"),
                    "message": text,
                }
            )

    def system_errors(self) -> List[dict]:
        with self._lock:
            return list(self.system_error_log)

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
                self.add_system_error("自动兑换", exc)
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
            if not result.get("ok"):
                self.add_system_error("自动兑换", result.get("message") or "自动兑换失败。")

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
                self.add_system_error("自动兑换检查", exc)
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

    def place_protected_pair_buy(self, **kwargs) -> List[dict]:
        with self._lock:
            client = self._require_client()
            return client.place_protected_pair_buy(**kwargs)

    def place_emergency_market_sell(self, **kwargs) -> dict:
        with self._lock:
            client = self._require_client()
            return client.place_emergency_market_sell(**kwargs)

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
            self._geoblock = None
            self._geoblock_at = 0.0
            self._geoblock_last_attempt = 0.0
        if client is not None:
            client.close()

    def _require_client(self) -> LiveTradingClient:
        if self._client is None:
            raise LiveTradingError("请先登录真实账户。")
        return self._client


def live_credentials_from_env() -> Optional[LiveCredentials]:
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY") or ""
    wallet = os.getenv("POLYMARKET_WALLET_ADDRESS") or ""
    if not private_key:
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
            "making_amount": _safe_float(getattr(response, "making_amount", 0)) / PUSD_DECIMALS,
            "taking_amount": _safe_float(getattr(response, "taking_amount", 0)) / PUSD_DECIMALS,
            "message": "订单已提交。",
        }
    return {
        "ok": False,
        "code": _safe_text(getattr(response, "code", "unknown")),
        "message": _safe_text(getattr(response, "message", "订单被拒绝。")),
    }


def _signed_buy_shares(signed_order: Any, target_shares: Decimal) -> float:
    """Read SDK's fee-adjusted requested shares; test doubles retain the target size."""
    raw_taker_amount = getattr(signed_order, "taker_amount", None)
    if raw_taker_amount is None:
        return float(target_shares)
    return float(Decimal(str(raw_taker_amount)) / Decimal(PUSD_DECIMALS))


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
