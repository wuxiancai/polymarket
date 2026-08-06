from datetime import datetime, timezone

from polyarb.config import Config
from polyarb.live_trader import LiveAutoTrader
from polyarb.models import BTC_ASSET, ArbOpportunity
from polyarb.runner import ScanResult


class FakeLiveSession:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.buys = []
        self.logs = []
        self.errors = []

    def is_logged_in(self):
        return True

    def is_auto_trading_enabled(self):
        return self.enabled

    def dashboard(self):
        return {"logged_in": True, "balance_pusd": 1000.0, "positions": []}

    def place_market_buy(self, token_id, amount):
        self.buys.append((token_id, amount))
        return {"ok": True, "order_id": f"order-{len(self.buys)}"}

    def add_execution_log(self, entry):
        self.logs.append(entry)

    def set_auto_trader_error(self, message):
        self.errors.append(message)


def opportunity() -> ArbOpportunity:
    return ArbOpportunity(
        pair_key="pair-1",
        kind="same_market",
        yes_market_id="m1",
        yes_token_id="yes-token",
        yes_question="Will Bitcoin be above $60,000 on August 10?",
        no_market_id="m1",
        no_token_id="no-token",
        no_question="Will Bitcoin be above $60,000 on August 10?",
        yes_event_slug="bitcoin-event",
        no_event_slug="bitcoin-event",
        yes_end_date="2026-08-11T00:00:00+00:00",
        no_end_date="2026-08-11T00:00:00+00:00",
        shares=1000.0,
        yes_avg_price=0.40,
        no_avg_price=0.556,
        total_cost=956.0,
        min_payout=1000.0,
        guaranteed_profit=44.0,
        edge_per_share=0.044,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
    )


def trader(session=None):
    session = session or FakeLiveSession()
    config = Config(
        database_path="data/paper.sqlite3",
        initial_capital_usdt=1000.0,
        allocation_ratios={"BTC": 1.0, "ETH": 0.0, "XRP": 0.0, "SOL": 0.0},
        cooldown_seconds=30,
    )
    return LiveAutoTrader(session, config, BTC_ASSET), session


def test_live_auto_trader_places_yes_and_no_market_buys():
    item, session = trader()

    item.on_result(
        ScanResult(
            markets=[],
            pairs=1,
            opportunities=[opportunity()],
            scanned_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert len(session.buys) == 2
    assert session.buys[0][0] == "yes-token"
    assert round(session.buys[0][1], 2) == 400.0
    assert session.buys[1][0] == "no-token"
    assert round(session.buys[1][1], 2) == 556.0
    assert len(session.logs) == 1
    assert session.logs[0]["ok"] is True
    assert item.last_execution["pair-1"] > 0


def test_live_auto_trader_skips_when_disabled():
    item, session = trader(FakeLiveSession(enabled=False))

    item.on_result(
        ScanResult(
            markets=[],
            pairs=1,
            opportunities=[opportunity()],
            scanned_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert session.buys == []
    assert session.logs == []
