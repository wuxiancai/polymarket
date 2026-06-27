from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List

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
                    no_market_id text not null,
                    no_token_id text not null,
                    no_question text not null,
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
                    no_market_id text not null,
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

    def record_opportunity(self, opportunity: ArbOpportunity) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into opportunities (
                    pair_key, kind, yes_market_id, yes_token_id, yes_question,
                    no_market_id, no_token_id, no_question, shares, yes_avg_price,
                    no_avg_price, total_cost, min_payout, guaranteed_profit,
                    edge_per_share, executable, reason, detected_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.pair_key,
                    opportunity.kind,
                    opportunity.yes_market_id,
                    opportunity.yes_token_id,
                    opportunity.yes_question,
                    opportunity.no_market_id,
                    opportunity.no_token_id,
                    opportunity.no_question,
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
                    pair_key, yes_market_id, no_market_id, shares, total_cost,
                    min_payout, guaranteed_profit, detected_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.pair_key,
                    opportunity.yes_market_id,
                    opportunity.no_market_id,
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
