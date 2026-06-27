from pathlib import Path

from polyarb.config import Config
from polyarb.runner import PaperRunner
from polyarb.store import PaperStore
from polyarb.web import WebState, render_dashboard


def test_dashboard_renders_chinese_status(tmp_path):
    config = Config(database_path=Path(tmp_path) / "paper.sqlite3")
    store = PaperStore(config.database_path)
    store.initialize()
    state = WebState(config=config, store=store, runner=PaperRunner(config))

    html = render_dashboard(state)

    assert "Polyarb BTC 套利模拟系统" in html
    assert "触发扫描" in html
    assert "暂无纸面成交" in html
