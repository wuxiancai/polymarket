from pathlib import Path
from datetime import datetime, timezone

from polyarb.config import Config
from polyarb.runner import PaperRunner
from polyarb.store import PaperStore
from polyarb.web import WebState, format_standard_time, render_dashboard


def test_dashboard_renders_chinese_status(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, runner=PaperRunner(config))

    html = render_dashboard(state)

    assert "Polyarb BTC 套利模拟系统" in html
    assert "触发扫描" in html
    assert "暂无纸面成交" in html


def test_standard_time_is_precise_to_seconds():
    value = datetime(2026, 6, 27, 12, 39, 35, 953435, tzinfo=timezone.utc)

    assert format_standard_time(value) == "2026-06-27 20:39:35"
