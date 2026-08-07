from types import SimpleNamespace

import pytest

from polyarb.live import (
    LiveCredentials,
    LiveSession,
    LiveTradingClient,
    LiveTradingError,
    live_credentials_from_env,
)


class FakePage:
    def __init__(self, items):
        self.items = items


class FakePaginator:
    def __init__(self, items):
        self.items = items

    def first_page(self):
        return FakePage(self.items)


class FakeTransactionHandle:
    def wait(self):
        return SimpleNamespace(transaction_hash="0xredeemed")


class FakeSdkClient:
    wallet = "0xwallet"
    signer = "0xsigner"
    wallet_type = "DEPOSIT_WALLET"

    def __init__(self):
        self.market_order_calls = []
        self.limit_order_calls = []
        self.redeem_calls = []

    def get_balance_allowance(self, **kwargs):
        return SimpleNamespace(balance=1_000_000, allowances={})

    def get_portfolio_values(self, **kwargs):
        return (SimpleNamespace(value="123.45"),)

    def list_positions(self, **kwargs):
        return FakePaginator(
            [
                SimpleNamespace(
                    condition_id="0xcondition",
                    token_id="token-yes",
                    size=10,
                    avg_price="0.42",
                    current_value="5.00",
                    cash_pnl="0.80",
                    percent_pnl=16.68,
                    title="Will Bitcoin be above $60,000?",
                    slug="bitcoin",
                    event_slug="bitcoin-event",
                    outcome="YES",
                    redeemable=False,
                    end_date="2026-08-10",
                )
            ]
        )

    def list_closed_positions(self, **kwargs):
        return FakePaginator(
            [
                SimpleNamespace(
                    condition_id="0xclosed",
                    token_id="token-no",
                    realized_pnl="3.25",
                    total_bought="20.00",
                    title="Will Ethereum dip?",
                    slug="ethereum",
                    event_slug="ethereum-event",
                    outcome="NO",
                    timestamp=1782752879,
                    end_date="2026-08-09",
                )
            ]
        )

    def list_open_orders(self, **kwargs):
        return FakePaginator(
            [
                SimpleNamespace(
                    id="order-1",
                    condition_id="0xcondition",
                    token_id="token-yes",
                    side="BUY",
                    price="0.42",
                    original_size="10",
                    size_matched="0",
                    outcome="YES",
                    order_type="GTC",
                    status="LIVE",
                    created_at=1782752879,
                    expires_at=None,
                )
            ]
        )

    def list_account_trades(self, **kwargs):
        return FakePaginator(
            [
                SimpleNamespace(
                    id="trade-1",
                    condition_id="0xcondition",
                    token_id="token-yes",
                    side="BUY",
                    price="0.42",
                    size="10",
                    outcome="YES",
                    status="CONFIRMED",
                    transaction_hash="0xhash",
                    matched_at=1782752879,
                )
            ]
        )

    def place_market_order(self, **kwargs):
        self.market_order_calls.append(kwargs)
        return {"ok": True, "order_id": "market-order", "message": "订单已提交。"}

    def place_limit_order(self, **kwargs):
        self.limit_order_calls.append(kwargs)
        return {"ok": True, "order_id": "limit-order", "message": "订单已提交。"}

    def cancel_order(self, **kwargs):
        self.cancel_call = kwargs

    def redeem_positions(self, **kwargs):
        self.redeem_calls.append(kwargs)
        return FakeTransactionHandle()


def credentials():
    return LiveCredentials(
        private_key="0xsecret",
        wallet="0xwallet",
        relayer_api_key="relayer",
        relayer_api_key_address="0xrelayer",
    )


def client(fake=None):
    fake = fake or FakeSdkClient()
    return LiveTradingClient(credentials(), sdk_client=fake), fake


def test_live_snapshot_returns_account_balance_positions_and_orders():
    item, _fake = client()

    data = item.snapshot()

    assert data["logged_in"] is True
    assert data["balance_pusd"] == 1.0
    assert data["portfolio_value"] == 123.45
    assert data["account"]["wallet"] == "0xwallet"
    assert data["account"]["has_relayer"] is True
    assert data["positions"][0]["outcome"] == "YES"
    assert data["positions"][0]["redeemable"] is False
    assert data["closed_positions"][0]["realized_pnl"] == 3.25
    assert data["open_orders"][0]["id"] == "order-1"
    assert data["trades"][0]["id"] == "trade-1"
    assert "0xsecret" not in repr(data)


def test_live_order_requires_confirmation():
    item, _fake = client()

    with pytest.raises(LiveTradingError):
        item.place_order(
            token_id="token-yes",
            side="BUY",
            order_type="market",
            amount="10",
            confirm=False,
        )


def test_live_order_places_market_buy_sell_and_limit():
    item, fake = client()

    item.place_order(
        token_id="token-yes",
        side="BUY",
        order_type="market",
        amount="10",
        confirm=True,
    )
    assert fake.market_order_calls[0]["side"] == "BUY"
    assert fake.market_order_calls[0]["amount"] == "10"

    item.place_order(
        token_id="token-no",
        side="SELL",
        order_type="market",
        shares="5",
        confirm=True,
    )
    assert fake.market_order_calls[1]["side"] == "SELL"
    assert fake.market_order_calls[1]["shares"] == "5"

    item.place_order(
        token_id="token-yes",
        side="BUY",
        order_type="limit",
        price="0.42",
        shares="7",
        confirm=True,
    )
    assert fake.limit_order_calls[0]["side"] == "BUY"
    assert fake.limit_order_calls[0]["size"] == "7"


def test_live_client_redeems_position():
    item, fake = client()

    result = item.redeem_positions("0xcondition")

    assert result["ok"] is True
    assert result["transaction_hash"] == "0xredeemed"
    assert fake.redeem_calls == [{"condition_id": "0xcondition"}]


def test_live_session_auto_redeems_redeemable_positions_once_per_condition():
    session = LiveSession()
    fake = FakeSdkClient()
    item = LiveTradingClient(credentials(), sdk_client=fake)
    positions = [
        {"condition_id": "0xa", "title": "Market A", "redeemable": True},
        {"condition_id": "0xa", "title": "Market A", "redeemable": True},
        {"condition_id": "0xb", "title": "Market B", "redeemable": True},
        {"condition_id": "0xc", "title": "Market C", "redeemable": False},
    ]

    session._auto_redeem(positions, item)

    assert [call["condition_id"] for call in fake.redeem_calls] == ["0xa", "0xb"]
    assert len(session.redemption_log) == 2
    assert all(row["ok"] for row in session.redemption_log)


def test_live_credentials_from_env(monkeypatch):
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xsecret")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_RELAYER_API_KEY", "relayer")
    monkeypatch.setenv("POLYMARKET_RELAYER_API_KEY_ADDRESS", "0xrelayer")

    value = live_credentials_from_env()

    assert value is not None
    assert value.private_key == "0xsecret"
    assert value.relayer_api_key == "relayer"
    assert "0xsecret" not in repr(value)
