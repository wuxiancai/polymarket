from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .models import ArbOpportunity


class PaperStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists opportunities (
                    id integer primary key autoincrement,
                    pair_key text not null,
                    kind text not null,
                    yes_market_id text not null,
                    yes_token_id text not null,
                    yes_question text not null,
                    yes_end_date text not null default '',
                    no_market_id text not null,
                    no_token_id text not null,
                    no_question text not null,
                    no_end_date text not null default '',
                    shares real not null,
                    yes_avg_price real not null,
                    no_avg_price real not null,
                    total_cost real not null,
                    min_payout real not null,
                    guaranteed_profit real not null,
                    edge_per_share real not null,
                    executable integer not null,
                    reason text not null,
                    detected_at text not null
                );
                create table if not exists paper_trades (
                    id integer primary key autoincrement,
                    pair_key text not null,
                    yes_market_id text not null,
                    yes_token_id text not null default '',
                    yes_question text not null default '',
                    yes_end_date text not null default '',
                    yes_avg_price real not null default 0,
                    no_market_id text not null,
                    no_token_id text not null default '',
                    no_question text not null default '',
                    no_end_date text not null default '',
                    no_avg_price real not null default 0,
                    shares real not null,
                    total_cost real not null,
                    min_payout real not null,
                    guaranteed_profit real not null,
                    detected_at text not null
                );
                create index if not exists idx_opportunities_detected_at on opportunities(detected_at);
                create index if not exists idx_trades_detected_at on paper_trades(detected_at);
                """
            )
            self._ensure_paper_trade_columns(conn)

    def record_opportunity(self, opportunity: ArbOpportunity) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into opportunities (
                    pair_key, kind, yes_market_id, yes_token_id, yes_question, yes_end_date,
                    no_market_id, no_token_id, no_question, no_end_date, shares, yes_avg_price,
                    no_avg_price, total_cost, min_payout, guaranteed_profit,
                    edge_per_share, executable, reason, detected_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.pair_key,
                    opportunity.kind,
                    opportunity.yes_market_id,
                    opportunity.yes_token_id,
                    opportunity.yes_question,
                    opportunity.yes_end_date,
                    opportunity.no_market_id,
                    opportunity.no_token_id,
                    opportunity.no_question,
                    opportunity.no_end_date,
                    opportunity.shares,
                    opportunity.yes_avg_price,
                    opportunity.no_avg_price,
                    opportunity.total_cost,
                    opportunity.min_payout,
                    opportunity.guaranteed_profit,
                    opportunity.edge_per_share,
                    1 if opportunity.executable else 0,
                    opportunity.reason,
                    opportunity.detected_at.isoformat(),
                ),
            )

    def record_paper_trade(self, opportunity: ArbOpportunity) -> None:
        if not opportunity.executable:
            return
        with self._connect() as conn:
            conn.execute(
                """
                insert into paper_trades (
                    pair_key, yes_market_id, yes_token_id, yes_question, yes_end_date, yes_avg_price,
                    no_market_id, no_token_id, no_question, no_end_date, no_avg_price, shares,
                    total_cost, min_payout, guaranteed_profit, detected_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.pair_key,
                    opportunity.yes_market_id,
                    opportunity.yes_token_id,
                    opportunity.yes_question,
                    opportunity.yes_end_date,
                    opportunity.yes_avg_price,
                    opportunity.no_market_id,
                    opportunity.no_token_id,
                    opportunity.no_question,
                    opportunity.no_end_date,
                    opportunity.no_avg_price,
                    opportunity.shares,
                    opportunity.total_cost,
                    opportunity.min_payout,
                    opportunity.guaranteed_profit,
                    opportunity.detected_at.isoformat(),
                ),
            )

    def latest_trades(self, limit: int = 20) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from paper_trades
                order by detected_at desc, id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_positions(self, limit: int = 50, now: Optional[datetime] = None) -> List[Dict[str, object]]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        rows = []
        for row in self.latest_trades(limit=limit * 2):
            if not _is_settled(row, current):
                rows.append(row)
            if len(rows) >= limit:
                break
        return rows

    def latest_opportunities(self, limit: int = 20) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from opportunities
                order by detected_at desc, id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_paper_trade_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("pragma table_info(paper_trades)").fetchall()}
        columns = {
            "yes_token_id": "text not null default ''",
            "yes_question": "text not null default ''",
            "yes_end_date": "text not null default ''",
            "yes_avg_price": "real not null default 0",
            "no_token_id": "text not null default ''",
            "no_question": "text not null default ''",
            "no_end_date": "text not null default ''",
            "no_avg_price": "real not null default 0",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"alter table paper_trades add column {name} {definition}")
        existing_opportunity = {row["name"] for row in conn.execute("pragma table_info(opportunities)").fetchall()}
        for name in ("yes_end_date", "no_end_date"):
            if name not in existing_opportunity:
                conn.execute(f"alter table opportunities add column {name} text not null default ''")


def _is_settled(row: Dict[str, object], now: datetime) -> bool:
    dates = [_parse_datetime(row.get("yes_end_date")), _parse_datetime(row.get("no_end_date"))]
    known_dates = [value for value in dates if value is not None]
    return bool(known_dates) and all(value <= now for value in known_dates)


def _parse_datetime(value: object) -> Optional[datetime]:
    text = str(value or "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
