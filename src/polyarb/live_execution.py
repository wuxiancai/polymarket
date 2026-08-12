from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


ACTIVE_STATES = {"pending_confirmation", "unknown_submission", "exit_pending"}


class WalletReservations:
    """Process-wide capital reservations shared by all asset traders."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: Dict[str, tuple[str, float]] = {}

    def reserve(self, reservation_id: str, asset: str, amount: float, balance_limit: float) -> bool:
        if amount <= 0 or balance_limit < amount:
            return False
        with self._lock:
            if reservation_id in self._items:
                return True
            total = sum(existing_amount for _asset, existing_amount in self._items.values())
            if total + amount > balance_limit + 1e-9:
                return False
            self._items[reservation_id] = (asset, amount)
            return True

    def release(self, reservation_id: str) -> None:
        with self._lock:
            self._items.pop(reservation_id, None)

    def total(self, asset: Optional[str] = None) -> float:
        with self._lock:
            return sum(amount for item_asset, amount in self._items.values() if asset is None or item_asset == asset)


class LiveExecutionStore:
    """Durable, secret-free execution intents used for restart reconciliation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists live_execution_intents (
                    id text primary key,
                    asset text not null,
                    pair_key text not null,
                    yes_token_id text not null,
                    no_token_id text not null,
                    shares real not null,
                    reserved_capital real not null,
                    baseline_yes_shares real not null,
                    baseline_no_shares real not null,
                    state text not null,
                    yes_order_id text not null default '',
                    no_order_id text not null default '',
                    detail text not null default '',
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute("create index if not exists idx_live_execution_active on live_execution_intents(asset, state)")

    def create(self, *, asset: str, pair_key: str, yes_token_id: str, no_token_id: str, shares: float,
               reserved_capital: float, baseline_yes_shares: float, baseline_no_shares: float) -> dict:
        now = _now()
        item = {
            "id": uuid.uuid4().hex,
            "asset": asset,
            "pair_key": pair_key,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id,
            "shares": shares,
            "reserved_capital": reserved_capital,
            "baseline_yes_shares": baseline_yes_shares,
            "baseline_no_shares": baseline_no_shares,
            "state": "pending_confirmation",
            "yes_order_id": "",
            "no_order_id": "",
            "detail": "订单已签名，等待交易所确认成交。",
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as conn:
            columns = ", ".join(item)
            conn.execute(f"insert into live_execution_intents ({columns}) values ({', '.join('?' for _ in item)})", tuple(item.values()))
        return item

    def update(self, intent_id: str, *, state: Optional[str] = None, detail: Optional[str] = None,
               yes_order_id: Optional[str] = None, no_order_id: Optional[str] = None) -> dict:
        fields = {"updated_at": _now()}
        if state is not None:
            fields["state"] = state
        if detail is not None:
            fields["detail"] = detail
        if yes_order_id is not None:
            fields["yes_order_id"] = yes_order_id
        if no_order_id is not None:
            fields["no_order_id"] = no_order_id
        with self._connect() as conn:
            assignments = ", ".join(f"{name} = ?" for name in fields)
            conn.execute(f"update live_execution_intents set {assignments} where id = ?", (*fields.values(), intent_id))
        item = self.get(intent_id)
        if item is None:
            raise KeyError(intent_id)
        return item

    def get(self, intent_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("select * from live_execution_intents where id = ?", (intent_id,)).fetchone()
        return dict(row) if row else None

    def active(self, asset: Optional[str] = None) -> List[dict]:
        sql = "select * from live_execution_intents where state in ({})".format(", ".join("?" for _ in ACTIVE_STATES))
        args: list[object] = list(ACTIVE_STATES)
        if asset is not None:
            sql += " and asset = ?"
            args.append(asset)
        sql += " order by created_at"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
