from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .arbitrage import build_pairs, find_opportunities
from .config import Config
from .models import ArbOpportunity, Market, OrderBook
from .polymarket import ClobClient, GammaClient
from .store import PaperStore
from .websocket import apply_market_message, market_subscription_message


@dataclass
class ScanResult:
    markets: List[Market]
    pairs: int
    opportunities: List[ArbOpportunity]
    scanned_at: datetime


def scan_once(config: Config) -> ScanResult:
    gamma = GammaClient(config)
    clob = ClobClient(config)
    markets = gamma.bitcoin_markets()
    pairs = build_pairs(markets)
    token_ids = [token_id for pair in pairs for token_id in pair.token_ids]
    books = clob.order_books(token_ids)
    opportunities = find_opportunities(markets, books, config)
    return ScanResult(
        markets=markets,
        pairs=len(pairs),
        opportunities=opportunities,
        scanned_at=datetime.now(timezone.utc),
    )


class PaperRunner:
    def __init__(self, config: Config):
        self.config = config
        self.store = PaperStore(config.database_path)
        self.last_execution: Dict[str, float] = {}

    def run_forever(self) -> None:
        self.store.initialize()
        while True:
            self.run_iteration()
            time.sleep(self.config.refresh_seconds)

    def run_iteration(self) -> ScanResult:
        result = scan_once(self.config)
        for opportunity in result.opportunities:
            self.store.record_opportunity(opportunity)
            if self._should_execute(opportunity):
                self.store.record_paper_trade(opportunity)
                self.last_execution[opportunity.pair_key] = time.time()
        return result

    def _should_execute(self, opportunity: ArbOpportunity) -> bool:
        if not opportunity.executable:
            return False
        last = self.last_execution.get(opportunity.pair_key)
        if last is None:
            return True
        return time.time() - last >= self.config.cooldown_seconds


class RealtimePaperRunner(PaperRunner):
    def __init__(self, config: Config):
        super().__init__(config)
        self.gamma = GammaClient(config)
        self.clob = ClobClient(config)
        self.markets: List[Market] = []
        self.books: Dict[str, OrderBook] = {}
        self.pairs = 0
        self.last_event_at: Optional[datetime] = None

    async def run_forever(
        self,
        on_result: Optional[Callable[[ScanResult], None]] = None,
        on_event: Optional[Callable[[datetime], None]] = None,
    ) -> None:
        import websockets

        self.store.initialize()
        while True:
            self._bootstrap()
            initial_result = self._evaluate_current_books()
            self._record_result(initial_result)
            if on_result:
                on_result(initial_result)

            token_ids = sorted(set(self.books))
            async with websockets.connect(self.config.websocket_url, ping_interval=10, ping_timeout=20) as websocket:
                await websocket.send(json.dumps(market_subscription_message(token_ids)))
                async for raw_message in websocket:
                    message = json.loads(raw_message)
                    updates = apply_market_message(self.books, message)
                    if updates == 0:
                        continue
                    self.last_event_at = datetime.now(timezone.utc)
                    result = self._evaluate_current_books()
                    self._record_result(result)
                    if on_event:
                        on_event(self.last_event_at)
                    if on_result:
                        on_result(result)

    def _bootstrap(self) -> None:
        self.markets = self.gamma.bitcoin_markets()
        pairs = build_pairs(self.markets)
        self.pairs = len(pairs)
        token_ids = [token_id for pair in pairs for token_id in pair.token_ids]
        self.books = self.clob.order_books(token_ids)

    def _evaluate_current_books(self) -> ScanResult:
        opportunities = find_opportunities(self.markets, self.books, self.config)
        return ScanResult(
            markets=self.markets,
            pairs=self.pairs,
            opportunities=opportunities,
            scanned_at=datetime.now(timezone.utc),
        )

    def _record_result(self, result: ScanResult) -> None:
        for opportunity in result.opportunities:
            self.store.record_opportunity(opportunity)
            if self._should_execute(opportunity):
                self.store.record_paper_trade(opportunity)
                self.last_execution[opportunity.pair_key] = time.time()


def format_opportunities(result: ScanResult, limit: int = 20) -> str:
    lines = [
        f"markets={len(result.markets)} pairs={result.pairs} opportunities={len(result.opportunities)} "
        f"at={result.scanned_at.isoformat()}"
    ]
    if not result.opportunities:
        lines.append("无套利机会：没有发现通过滑点/深度/成交量风控的正收益组合。")
        return "\n".join(lines)
    for item in result.opportunities[:limit]:
        status = "EXEC" if item.executable else "WATCH"
        lines.extend(
            [
                f"[{status}] {item.pair_key} profit=${item.guaranteed_profit:.4f} "
                f"shares={item.shares:.4f} edge={item.edge_per_share:.4f} reason={item.reason}",
                f"  BUY YES {item.yes_avg_price:.4f}: {item.yes_question}",
                f"  BUY NO  {item.no_avg_price:.4f}: {item.no_question}",
            ]
        )
    return "\n".join(lines)
