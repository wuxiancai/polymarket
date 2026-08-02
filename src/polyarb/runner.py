from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .arbitrage import build_pairs, find_opportunities
from .config import Config
from .models import BTC_ASSET, DEFAULT_ASSETS, AssetSpec, ArbOpportunity, Market, OrderBook
from .polymarket import ClobClient, GammaClient
from .store import PaperStore
from .websocket import apply_market_message, market_subscription_message

WEBSOCKET_RECONNECT_DELAY_SECONDS = 10
MIN_DISPLAYED_POSITION_VALUE = 0.01
MIN_SPREAD_TO_OPEN_CENTS = 2.5
THIRTY_PERCENT_MAX_SPREAD_CENTS = 3.5
SIXTY_PERCENT_MAX_SPREAD_CENTS = 4.3


def _settlement_at(opportunity: ArbOpportunity) -> datetime:
    parsed = []
    for value in (opportunity.yes_end_date, opportunity.no_end_date):
        try:
            parsed.append(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc))
        except ValueError:
            continue
    return max(parsed) if parsed else datetime.max.replace(tzinfo=timezone.utc)


@dataclass
class ScanResult:
    markets: List[Market]
    pairs: int
    opportunities: List[ArbOpportunity]
    scanned_at: datetime
    books: Dict[str, OrderBook] = field(default_factory=dict)


def scan_once(config: Config) -> ScanResult:
    markets: List[Market] = []
    pairs = 0
    opportunities: List[ArbOpportunity] = []
    books: Dict[str, OrderBook] = {}
    for asset in DEFAULT_ASSETS:
        result = scan_asset_once(config, asset)
        markets.extend(result.markets)
        pairs += result.pairs
        opportunities.extend(result.opportunities)
        books.update(result.books)
    opportunities.sort(key=lambda item: item.guaranteed_profit, reverse=True)
    return ScanResult(
        markets=markets,
        pairs=pairs,
        opportunities=opportunities,
        scanned_at=datetime.now(timezone.utc),
        books=books,
    )


def scan_asset_once(config: Config, asset: AssetSpec) -> ScanResult:
    gamma = GammaClient(config)
    clob = ClobClient(config)
    markets = gamma.markets_for_asset(asset)
    pairs = build_pairs(markets)
    token_ids = [token_id for pair in pairs for token_id in pair.token_ids]
    books = clob.order_books(token_ids)
    opportunities = find_opportunities(markets, books, config)
    return ScanResult(
        markets=markets,
        pairs=len(pairs),
        opportunities=opportunities,
        scanned_at=datetime.now(timezone.utc),
        books=books,
    )


class PaperRunner:
    def __init__(self, config: Config, asset: AssetSpec = BTC_ASSET):
        self.config = config
        self.asset = asset
        self.store = PaperStore(config.database_path)
        self.last_execution: Dict[str, float] = {}

    def run_forever(self) -> None:
        self.store.initialize()
        while True:
            self.run_iteration()
            time.sleep(self.config.refresh_seconds)

    def run_iteration(self) -> ScanResult:
        result = scan_asset_once(self.config, self.asset)
        self._record_result(result)
        return result

    def _record_result(self, result: ScanResult) -> None:
        for opportunity in result.opportunities:
            self.store.record_opportunity(opportunity)
        for opportunity in sorted((item for item in result.opportunities if item.executable), key=_settlement_at):
            if not self._should_execute(opportunity):
                continue
            sized = self._sized_opportunity(opportunity)
            if sized is None:
                continue
            self.store.record_paper_trade(sized)
            self.last_execution[opportunity.pair_key] = time.time()

    def _should_execute(self, opportunity: ArbOpportunity) -> bool:
        if not opportunity.executable:
            return False
        last = self.last_execution.get(opportunity.pair_key)
        if last is None:
            return True
        return time.time() - last >= self.config.cooldown_seconds

    def _sized_opportunity(self, opportunity: ArbOpportunity) -> Optional[ArbOpportunity]:
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

        allocation = self.config.initial_capital_usdt * self.asset.allocation_ratio
        used = self._used_capital()
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

    def _used_capital(self) -> float:
        total = 0.0
        needle = self.asset.title_name.lower()
        for row in self.store.latest_positions(500):
            yes_question = str(row.get("yes_question", "")).lower()
            no_question = str(row.get("no_question", "")).lower()
            if needle not in yes_question and needle not in no_question:
                continue
            try:
                total += float(row.get("total_cost") or 0)
            except (TypeError, ValueError):
                continue
        return total


def _spread_cents(opportunity: ArbOpportunity) -> float:
    return round((1 - opportunity.yes_avg_price - opportunity.no_avg_price) * 100, 10)


class RealtimePaperRunner(PaperRunner):
    def __init__(self, config: Config, asset: AssetSpec = BTC_ASSET):
        super().__init__(config, asset)
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
        on_log: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        import websockets

        self.store.initialize()
        while True:
            try:
                self._bootstrap(on_log=on_log)
                initial_result = self._evaluate_current_books()
                self._record_result(initial_result)
                if on_result:
                    on_result(initial_result)

                token_ids = sorted(set(self.books))
                self._log(on_log, "info", f"WebSocket 正在连接 {self.config.websocket_url}")
                async with websockets.connect(self.config.websocket_url, ping_interval=10, ping_timeout=20) as websocket:
                    await websocket.send(json.dumps(market_subscription_message(token_ids)))
                    self._log(on_log, "ok", f"WebSocket 已订阅 {len(token_ids)} 个 token")
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
            except Exception as exc:
                self._log(on_log, "error", f"Polymarket 连接失败：{exc}")
                self._log(on_log, "info", f"{WEBSOCKET_RECONNECT_DELAY_SECONDS} 秒后重新连接 Polymarket")
                await asyncio.sleep(WEBSOCKET_RECONNECT_DELAY_SECONDS)

    def _bootstrap(self, on_log: Optional[Callable[[str, str], None]] = None) -> None:
        self._log(on_log, "info", f"Gamma API 正在拉取 {self.asset.symbol} 市场")
        self.markets = self.gamma.markets_for_asset(self.asset)
        pairs = build_pairs(self.markets)
        self.pairs = len(pairs)
        token_ids = [token_id for pair in pairs for token_id in pair.token_ids]
        self._log(on_log, "info", f"CLOB REST 正在拉取 {len(set(token_ids))} 个 token 盘口")
        self.books = self.clob.order_books(token_ids)
        self._log(on_log, "ok", f"REST 引导完成：市场 {len(self.markets)}，交易对 {self.pairs}，盘口 {len(self.books)}")

    def _evaluate_current_books(self) -> ScanResult:
        opportunities = find_opportunities(self.markets, self.books, self.config)
        return ScanResult(
            markets=self.markets,
            pairs=self.pairs,
            opportunities=opportunities,
            scanned_at=datetime.now(timezone.utc),
            books=self.books,
        )

    def _log(self, callback: Optional[Callable[[str, str], None]], level: str, message: str) -> None:
        if callback:
            callback(level, message)


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
