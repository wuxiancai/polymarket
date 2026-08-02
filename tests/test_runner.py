import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from polyarb.config import Config
from polyarb.models import BTC_ASSET, ArbOpportunity
from polyarb.runner import PaperRunner, RealtimePaperRunner, ScanResult


def paper_opportunity(pair_key: str, end_date: str) -> ArbOpportunity:
    return ArbOpportunity(
        pair_key=pair_key,
        kind="same_market",
        yes_market_id=f"{pair_key}-yes",
        yes_token_id=f"{pair_key}-y",
        yes_question="Will Bitcoin be above $60,000 on August 4?",
        no_market_id=f"{pair_key}-no",
        no_token_id=f"{pair_key}-n",
        no_question="Will Bitcoin be above $60,000 on August 4?",
        yes_event_slug="what-price-will-bitcoin-be-on-august-4",
        no_event_slug="what-price-will-bitcoin-be-on-august-4",
        yes_end_date=end_date,
        no_end_date=end_date,
        shares=10,
        yes_avg_price=0.40,
        no_avg_price=0.57,
        total_cost=10,
        min_payout=10.3,
        guaranteed_profit=0.3,
        edge_per_share=0.03,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )


def test_runner_executes_nearest_end_date_first(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    item = PaperRunner(config, BTC_ASSET)
    item.store.initialize()
    far = paper_opportunity("far", "2026-08-10T00:00:00+00:00")
    near = paper_opportunity("near", "2026-08-04T00:00:00+00:00")

    item._record_result(
        ScanResult(
            markets=[],
            pairs=0,
            opportunities=[far, near],
            scanned_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
        )
    )

    with item.store._connect() as conn:
        rows = conn.execute("select pair_key from paper_trades order by id asc").fetchall()
    assert [row["pair_key"] for row in rows] == ["near", "far"]


class StopAfterReconnect(BaseException):
    pass


class FailingWebSocketConnect:
    async def __aenter__(self):
        raise ConnectionError("keepalive ping timeout")

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def test_realtime_runner_reconnects_forever_after_websocket_error(monkeypatch, tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    runner = RealtimePaperRunner(config, BTC_ASSET)
    bootstrap_calls = 0
    sleep_delays = []
    logs = []

    def fake_connect(*args, **kwargs):
        return FailingWebSocketConnect()

    def fake_bootstrap(on_log=None):
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        runner.books = {"token-1": object()}
        if bootstrap_calls == 2:
            raise StopAfterReconnect()

    async def fake_sleep(delay):
        sleep_delays.append(delay)

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=fake_connect))
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(runner, "_bootstrap", fake_bootstrap)
    monkeypatch.setattr(runner, "_evaluate_current_books", lambda: None)
    monkeypatch.setattr(runner, "_record_result", lambda result: None)

    with pytest.raises(StopAfterReconnect):
        asyncio.run(runner.run_forever(on_log=lambda level, message: logs.append((level, message))))

    assert bootstrap_calls == 2
    assert sleep_delays == [10]
    assert ("error", "Polymarket 连接失败：keepalive ping timeout") in logs
    assert ("info", "10 秒后重新连接 Polymarket") in logs
