from __future__ import annotations

import calendar
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from .models import ArbOpportunity

ET = ZoneInfo("America/New_York")
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MIN_DISPLAYED_TRADE_VALUE = 0.01


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
                    yes_event_slug text not null default '',
                    yes_end_date text not null default '',
                    no_market_id text not null,
                    no_token_id text not null,
                    no_question text not null,
                    no_event_slug text not null default '',
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
                    yes_event_slug text not null default '',
                    yes_end_date text not null default '',
                    yes_avg_price real not null default 0,
                    no_market_id text not null,
                    no_token_id text not null default '',
                    no_question text not null default '',
                    no_event_slug text not null default '',
                    no_end_date text not null default '',
                    no_avg_price real not null default 0,
                    shares real not null,
                    total_cost real not null,
                    min_payout real not null,
                    guaranteed_profit real not null,
                    is_virtual integer not null default 0,
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
                    pair_key, kind, yes_market_id, yes_token_id, yes_question, yes_event_slug, yes_end_date,
                    no_market_id, no_token_id, no_question, no_event_slug, no_end_date, shares, yes_avg_price,
                    no_avg_price, total_cost, min_payout, guaranteed_profit,
                    edge_per_share, executable, reason, detected_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.pair_key,
                    opportunity.kind,
                    opportunity.yes_market_id,
                    opportunity.yes_token_id,
                    opportunity.yes_question,
                    opportunity.yes_event_slug,
                    opportunity.yes_end_date,
                    opportunity.no_market_id,
                    opportunity.no_token_id,
                    opportunity.no_question,
                    opportunity.no_event_slug,
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
        self._record_trade(opportunity, is_virtual=False)

    def record_virtual_trade(self, opportunity: ArbOpportunity) -> None:
        self._record_trade(opportunity, is_virtual=True)

    def _record_trade(self, opportunity: ArbOpportunity, is_virtual: bool) -> None:
        if not opportunity.executable:
            return
        if opportunity.shares < MIN_DISPLAYED_TRADE_VALUE or opportunity.guaranteed_profit < MIN_DISPLAYED_TRADE_VALUE:
            return
        with self._connect() as conn:
            conn.execute(
                """
                insert into paper_trades (
                    pair_key, yes_market_id, yes_token_id, yes_question, yes_event_slug, yes_end_date, yes_avg_price,
                    no_market_id, no_token_id, no_question, no_event_slug, no_end_date, no_avg_price, shares,
                    total_cost, min_payout, guaranteed_profit, is_virtual, detected_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.pair_key,
                    opportunity.yes_market_id,
                    opportunity.yes_token_id,
                    opportunity.yes_question,
                    opportunity.yes_event_slug,
                    opportunity.yes_end_date,
                    opportunity.yes_avg_price,
                    opportunity.no_market_id,
                    opportunity.no_token_id,
                    opportunity.no_question,
                    opportunity.no_event_slug,
                    opportunity.no_end_date,
                    opportunity.no_avg_price,
                    opportunity.shares,
                    opportunity.total_cost,
                    opportunity.min_payout,
                    opportunity.guaranteed_profit,
                    1 if is_virtual else 0,
                    opportunity.detected_at.isoformat(),
                ),
            )

    def latest_trades(self, limit: int = 20) -> List[Dict[str, object]]:
        return self._latest_trades(limit=limit, is_virtual=False)

    def latest_virtual_trades(self, limit: int = 20) -> List[Dict[str, object]]:
        return self._latest_trades(limit=limit, is_virtual=True)

    def _latest_trades(self, limit: int, is_virtual: bool) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from paper_trades
                where shares >= ?
                  and guaranteed_profit >= ?
                  and coalesce(is_virtual, 0) = ?
                order by detected_at desc, id desc
                limit ?
                """,
                (MIN_DISPLAYED_TRADE_VALUE, MIN_DISPLAYED_TRADE_VALUE, 1 if is_virtual else 0, limit),
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

    def latest_settled_trades(self, limit: int = 100, now: Optional[datetime] = None) -> List[Dict[str, object]]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        rows = []
        for row in self.latest_trades(limit=limit * 2):
            if _is_settled(row, current):
                rows.append(row)
            if len(rows) >= limit:
                break
        return rows

    def latest_virtual_positions(self, limit: int = 50, now: Optional[datetime] = None) -> List[Dict[str, object]]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        rows = []
        for row in self.latest_virtual_trades(limit=limit * 2):
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
            "yes_event_slug": "text not null default ''",
            "yes_end_date": "text not null default ''",
            "yes_avg_price": "real not null default 0",
            "no_token_id": "text not null default ''",
            "no_question": "text not null default ''",
            "no_event_slug": "text not null default ''",
            "no_end_date": "text not null default ''",
            "no_avg_price": "real not null default 0",
            "is_virtual": "integer not null default 0",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"alter table paper_trades add column {name} {definition}")
        existing_opportunity = {row["name"] for row in conn.execute("pragma table_info(opportunities)").fetchall()}
        for name in ("yes_event_slug", "no_event_slug", "yes_end_date", "no_end_date"):
            if name not in existing_opportunity:
                conn.execute(f"alter table opportunities add column {name} text not null default ''")
        self._backfill_paper_trade_prices(conn)
        self._backfill_paper_trade_end_dates(conn)

    def _backfill_paper_trade_prices(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            update paper_trades
            set yes_avg_price = coalesce(
                    (
                        select opportunities.yes_avg_price
                        from opportunities
                        where opportunities.pair_key = paper_trades.pair_key
                          and opportunities.detected_at = paper_trades.detected_at
                        order by opportunities.id desc
                        limit 1
                    ),
                    yes_avg_price
                ),
                no_avg_price = coalesce(
                    (
                        select opportunities.no_avg_price
                        from opportunities
                        where opportunities.pair_key = paper_trades.pair_key
                          and opportunities.detected_at = paper_trades.detected_at
                        order by opportunities.id desc
                        limit 1
                    ),
                    no_avg_price
                )
            where (yes_avg_price = 0 or no_avg_price = 0)
              and exists (
                  select 1
                  from opportunities
                  where opportunities.pair_key = paper_trades.pair_key
                    and opportunities.detected_at = paper_trades.detected_at
              )
            """
        )

    def _backfill_paper_trade_end_dates(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            update paper_trades
            set yes_end_date = coalesce(
                    nullif(yes_end_date, ''),
                    nullif((
                        select opportunities.yes_end_date
                        from opportunities
                        where opportunities.pair_key = paper_trades.pair_key
                          and opportunities.detected_at = paper_trades.detected_at
                        order by opportunities.id desc
                        limit 1
                    ), ''),
                    yes_end_date
                ),
                no_end_date = coalesce(
                    nullif(no_end_date, ''),
                    nullif((
                        select opportunities.no_end_date
                        from opportunities
                        where opportunities.pair_key = paper_trades.pair_key
                          and opportunities.detected_at = paper_trades.detected_at
                        order by opportunities.id desc
                        limit 1
                    ), ''),
                    no_end_date
                )
            where yes_end_date = '' or no_end_date = ''
            """
        )
        rows = conn.execute(
            """
            select id, yes_question, no_question, yes_end_date, no_end_date, detected_at
            from paper_trades
            where yes_end_date = '' or no_end_date = ''
            """
        ).fetchall()
        for row in rows:
            yes_end = row["yes_end_date"] or _infer_end_date(row["yes_question"], row["detected_at"])
            no_end = row["no_end_date"] or _infer_end_date(row["no_question"], row["detected_at"])
            if yes_end or no_end:
                conn.execute(
                    """
                    update paper_trades
                    set yes_end_date = ?, no_end_date = ?
                    where id = ?
                    """,
                    (yes_end or row["yes_end_date"], no_end or row["no_end_date"], row["id"]),
                )


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


def _infer_end_date(question: object, detected_at: object) -> str:
    detected = _parse_datetime(detected_at)
    if detected is None:
        return ""
    text = str(question or "")
    weekly = re.search(r"\b([A-Za-z]+) (\d{1,2})-(\d{1,2})\?", text)
    if weekly:
        month_name, _start_day, end_day = weekly.groups()
        month = MONTHS.get(month_name.lower())
        if month is None:
            return ""
        year = detected.astimezone(ET).year
        end_et = datetime(year, month, int(end_day), tzinfo=ET) + timedelta(days=1)
        return end_et.astimezone(timezone.utc).isoformat()
    monthly = re.search(r"\bin ([A-Za-z]+)\?", text)
    if monthly:
        month = MONTHS.get(monthly.group(1).lower())
        if month is None:
            return ""
        year = detected.astimezone(ET).year
        if month == 12:
            end_et = datetime(year + 1, 1, 1, tzinfo=ET)
        else:
            end_et = datetime(year, month + 1, 1, tzinfo=ET)
        return end_et.astimezone(timezone.utc).isoformat()
    return ""
