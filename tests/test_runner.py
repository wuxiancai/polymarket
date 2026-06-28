import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from polyarb.config import Config
from polyarb.models import BTC_ASSET
from polyarb.runner import RealtimePaperRunner


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
