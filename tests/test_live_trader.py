from datetime import datetime, timezone

from polyarb.config import Config
from polyarb.live_trader import LiveAutoTrader, _pair_is_covered, _price_caps
from polyarb.live_execution import LiveExecutionStore, WalletReservations
from polyarb.models import BTC_ASSET, ArbOpportunity
from polyarb.runner import ScanResult


class FakeLiveSession:
    def __init__(self, enabled=True, balance=1000.0, positions=None, buy_result=None, exit_result=None, geo_blocked=False):
        self.enabled = enabled
        self.balance = balance
        self.positions = positions or []
        self.buy_result = buy_result
        self.exit_result = exit_result
        self.geo_blocked = geo_blocked
        self.geoblock_info = {"blocked": geo_blocked, "ip": "1.2.3.4", "country": "SG", "region": ""}
        self.buys = []
        self.exits = []
        self.logs = []
        self.errors = []
        self.system_errors = []
        self.opportunities = []

    def is_logged_in(self):
        return True

    def is_auto_trading_enabled(self):
        return self.enabled

    def geoblock(self):
        return dict(self.geoblock_info)

    def is_trading_region_blocked(self):
        return self.geo_blocked

    def mark_region_blocked(self):
        self.geo_blocked = True
        self.geoblock_info["blocked"] = True

    def geoblock_error(self):
        if not self.geo_blocked:
            return ""
        return "真实交易区域受限：服务器出口 IP 1.2.3.4（SG）被 Polymarket 限制开仓，仅可平仓。"

    def dashboard(self):
        return {"logged_in": True, "balance_pusd": self.balance, "positions": self.positions}

    def place_protected_pair_buy(self, *, yes_token_id, no_token_id, shares, yes_max_price, no_max_price, fee_buffer=0.0):
        self.buys.append((yes_token_id, shares, yes_max_price))
        self.buys.append((no_token_id, shares, no_max_price))
        if self.buy_result is not None:
            if isinstance(self.buy_result, (list, tuple)):
                results = [dict(item) for item in self.buy_result]
            else:
                results = [dict(self.buy_result), dict(self.buy_result)]
            for result, cap in zip(results, (yes_max_price, no_max_price)):
                result.setdefault("max_spend", shares * cap + (shares * fee_buffer / 2))
            return results
        return [
            {"ok": True, "order_id": f"order-{len(self.buys) - 1}", "status": "matched", "taking_amount": shares, "trade_ids": ["yes-trade"], "max_spend": shares * yes_max_price + (shares * fee_buffer / 2)},
            {"ok": True, "order_id": f"order-{len(self.buys)}", "status": "matched", "taking_amount": shares, "trade_ids": ["no-trade"], "max_spend": shares * no_max_price + (shares * fee_buffer / 2)},
        ]

    def place_emergency_market_sell(self, *, token_id, shares):
        self.exits.append((token_id, shares))
        if self.exit_result is not None:
            return dict(self.exit_result)
        return {"ok": True, "order_id": "exit-order", "making_amount": shares}

    def add_execution_log(self, entry):
        self.logs.append(entry)

    def set_auto_trader_error(self, message):
        self.errors.append(message)

    def add_system_error(self, source, message):
        self.system_errors.append({"source": source, "message": str(message)})

    def upsert_live_opportunity(self, entry):
        self.opportunities.append(entry)


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
        no_avg_price=0.546,
        total_cost=946.0,
        min_payout=1000.0,
        guaranteed_profit=54.0,
        edge_per_share=0.054,
        executable=True,
        reason="executable",
        detected_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
    )


def trader(session=None, **kwargs):
    session = session or FakeLiveSession()
    config = Config(
        database_path="data/paper.sqlite3",
        initial_capital_usdt=1000.0,
        allocation_ratios={"BTC": 1.0, "ETH": 0.0, "XRP": 0.0, "SOL": 0.0},
        cooldown_seconds=30,
    )
    return LiveAutoTrader(session, config, BTC_ASSET, **kwargs), session


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
    assert round(session.buys[0][1], 2) == round(session.buys[1][1], 2)
    assert session.buys[1][0] == "no-token"
    assert round(session.buys[0][2] + session.buys[1][2], 2) <= 0.97
    assert len(session.logs) == 1
    assert session.logs[0]["ok"] is True
    assert session.opportunities[-1]["status"] == "已成交"
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
    assert session.opportunities[-1]["status"] == "可成交"


def test_live_auto_trader_marks_insufficient_funds():
    item, session = trader(
        FakeLiveSession(
            balance=1.0,
                positions=[{"title": "Will Bitcoin be above $60,000 on August 10?", "initial_value": 0.8}],
        )
    )

    item.on_result(
        ScanResult(
            markets=[],
            pairs=1,
            opportunities=[opportunity()],
            scanned_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert session.buys == []
    assert session.opportunities[-1]["status"] == "已触发，未成功"
    assert session.opportunities[-1]["detail"] == "资金不足"


def test_live_auto_trader_never_executes_when_spread_is_under_three_cents():
    item, session = trader()
    unsafe = opportunity()
    unsafe = unsafe.__class__(**{**unsafe.__dict__, "yes_avg_price": 0.40, "no_avg_price": 0.571, "total_cost": 971.0, "guaranteed_profit": 29.0})

    item.on_result(
        ScanResult(
            markets=[],
            pairs=1,
            opportunities=[unsafe],
            scanned_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert session.buys == []
    assert session.opportunities[-1]["status"] == "仅观察"


def test_live_price_caps_reserve_configured_fee_buffer_inside_97_cents():
    safe = opportunity().__class__(**{**opportunity().__dict__, "yes_avg_price": 0.40, "no_avg_price": 0.54})
    caps = _price_caps(safe, fee_buffer=0.01)

    assert caps is not None
    assert caps[0] + caps[1] + 0.01 < 0.96


def test_live_accepts_small_fee_adjusted_share_difference_when_pair_is_covered():
    assert _pair_is_covered(
        {"taking_amount": 10.0, "max_spend": 4.0},
        {"taking_amount": 9.9, "max_spend": 5.4},
    )


def test_live_auto_trader_cools_down_after_single_leg_exit():
    item, session = trader(
        FakeLiveSession(
            buy_result=[
                {"ok": True, "order_id": "yes-order", "status": "matched", "taking_amount": 1000.0, "trade_ids": ["yes-trade"]},
                {"ok": False, "message": "order couldn't be fully filled"},
            ],
            exit_result={"ok": True, "order_id": "yes-exit", "making_amount": 1000.0},
        )
    )
    result = ScanResult(markets=[], pairs=1, opportunities=[opportunity()], scanned_at=datetime.now(timezone.utc))

    item.on_result(result)
    item.on_result(result)

    assert len(session.buys) == 2
    assert session.opportunities[-1]["status"] == "已平仓"


def test_live_auto_trader_marks_zero_budget_as_insufficient_funds():
    item, session = trader(FakeLiveSession(balance=0.0))

    item.on_result(
        ScanResult(
            markets=[],
            pairs=1,
            opportunities=[opportunity()],
            scanned_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert session.buys == []
    assert session.opportunities[-1]["status"] == "已触发，未成功"
    assert session.opportunities[-1]["detail"] == "资金不足"


def test_live_auto_trader_marks_order_failure_as_triggered_insufficient_funds():
    item, session = trader(
        FakeLiveSession(
            balance=1000.0,
            buy_result={"ok": False, "message": "not enough balance"},
        )
    )

    item.on_result(
        ScanResult(
            markets=[],
            pairs=1,
            opportunities=[opportunity()],
            scanned_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert len(session.buys) == 2
    assert len(session.logs) == 1
    assert session.logs[0]["ok"] is False
    assert session.opportunities[-1]["status"] == "已触发，未成功"
    assert session.opportunities[-1]["detail"] == "资金不足"


def test_live_auto_trader_immediately_exits_a_single_filled_leg():
    item, session = trader(
        FakeLiveSession(
            balance=1000.0,
            buy_result=[
                {"ok": True, "order_id": "yes-order", "status": "matched", "taking_amount": 1000.0, "trade_ids": ["yes-trade"], "message": "订单已成交。"},
                {"ok": False, "message": "order couldn't be fully filled"},
            ],
            exit_result={"ok": True, "order_id": "yes-exit", "making_amount": 1000.0},
        )
    )

    item.on_result(
        ScanResult(
            markets=[],
            pairs=1,
            opportunities=[opportunity()],
            scanned_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert session.exits == [("yes-token", session.buys[0][1])]
    assert session.opportunities[-1]["status"] == "已平仓"
    assert "已全部平仓" in session.opportunities[-1]["detail"]


def test_live_auto_trader_freezes_pair_when_emergency_exit_cannot_fully_fill():
    item, session = trader(
        FakeLiveSession(
            balance=1000.0,
            buy_result=[
                {"ok": True, "order_id": "yes-order", "status": "matched", "taking_amount": 1000.0, "trade_ids": ["yes-trade"], "message": "订单已成交。"},
                {"ok": False, "message": "order couldn't be fully filled"},
            ],
            exit_result={"ok": True, "order_id": "partial-exit", "making_amount": 400.0},
        )
    )

    item.on_result(
        ScanResult(
            markets=[],
            pairs=1,
            opportunities=[opportunity()],
            scanned_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert len(session.exits) == 1
    assert session.opportunities[-1]["status"] == "平仓未完成"
    assert "剩余 600" in session.opportunities[-1]["detail"]

    item.on_result(
        ScanResult(
            markets=[],
            pairs=1,
            opportunities=[opportunity()],
            scanned_at=datetime(2026, 8, 7, 12, 1, tzinfo=timezone.utc),
        )
    )
    assert len(session.buys) == 2
    assert len(session.exits) == 1


def test_live_auto_trader_does_not_mark_delayed_orders_as_filled():
    item, session = trader(
        FakeLiveSession(
            buy_result=[
                {"ok": True, "order_id": "yes-order", "status": "delayed", "taking_amount": 0, "trade_ids": []},
                {"ok": True, "order_id": "no-order", "status": "delayed", "taking_amount": 0, "trade_ids": []},
            ]
        )
    )

    item.on_result(ScanResult(markets=[], pairs=1, opportunities=[opportunity()], scanned_at=datetime.now(timezone.utc)))

    assert session.opportunities[-1]["status"] == "成交确认中"
    assert session.exits == []
    assert "等待持仓对账" in session.opportunities[-1]["detail"]


def test_live_auto_trader_does_not_exit_a_matched_leg_while_other_leg_is_delayed():
    item, session = trader(
        FakeLiveSession(
            buy_result=[
                {"ok": True, "order_id": "yes-order", "status": "matched", "taking_amount": 1000, "trade_ids": ["yes-trade"]},
                {"ok": True, "order_id": "no-order", "status": "delayed", "taking_amount": 0, "trade_ids": []},
            ]
        )
    )

    item.on_result(ScanResult(markets=[], pairs=1, opportunities=[opportunity()], scanned_at=datetime.now(timezone.utc)))

    assert session.opportunities[-1]["status"] == "成交确认中"
    assert session.exits == []


def test_live_auto_trader_reserves_wallet_capital_between_opportunities():
    item, session = trader(FakeLiveSession(balance=1000.0))
    first = opportunity()
    second = first.__class__(**{**first.__dict__, "pair_key": "pair-2"})
    item.on_result(ScanResult(markets=[], pairs=2, opportunities=[first, second], scanned_at=datetime.now(timezone.utc)))

    assert len(session.buys) == 2
    assert session.opportunities[-1]["status"] == "已触发，未成功"
    assert session.opportunities[-1]["detail"] == "资金不足"


def test_live_auto_trader_restores_pending_intent_and_blocks_before_reconciliation(tmp_path):
    store = LiveExecutionStore(tmp_path / "paper.sqlite3")
    saved = store.create(
        asset="BTC",
        pair_key="pair-1",
        yes_token_id="yes-token",
        no_token_id="no-token",
        shares=10.0,
        reserved_capital=9.7,
        baseline_yes_shares=0.0,
        baseline_no_shares=0.0,
    )
    item, session = trader(FakeLiveSession(balance=1000.0), execution_store=store, reservations=WalletReservations())

    item.on_result(ScanResult(markets=[], pairs=1, opportunities=[opportunity()], scanned_at=datetime.now(timezone.utc)))

    assert session.buys == []
    assert session.opportunities[-1]["status"] == "平仓未完成"
    assert store.get(saved["id"])["state"] == "pending_confirmation"


def test_live_auto_trader_skips_when_region_blocked():
    item, session = trader(FakeLiveSession(geo_blocked=True))

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
    assert session.opportunities[-1]["status"] == "区域受限"
    assert "Polymarket" in session.errors[-1]


def test_live_auto_trader_marks_region_restricted_from_order_error():
    restricted = (
        "Trading restricted in your region - "
        "https://docs.polymarket.com/developers/CLOB/geoblock"
    )
    item, session = trader(
        FakeLiveSession(
            balance=1000.0,
            buy_result={"ok": False, "message": restricted},
        )
    )
    result = ScanResult(
        markets=[],
        pairs=1,
        opportunities=[opportunity()],
        scanned_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
    )

    item.on_result(result)

    assert len(session.buys) == 2
    assert len(session.logs) == 1
    assert session.opportunities[-1]["status"] == "区域受限"
    assert session.geo_blocked is True
    assert "Polymarket" in session.errors[-1]

    item.on_result(result)

    assert len(session.buys) == 2
    assert len(session.logs) == 1
    assert session.opportunities[-1]["status"] == "区域受限"
