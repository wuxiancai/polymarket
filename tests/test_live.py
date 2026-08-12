import sys
from types import SimpleNamespace

import pytest

from polyarb.live import (
    LiveCredentials,
    LiveSession,
    LiveTradingClient,
    LiveTradingError,
    _normalize_wallet_for_sdk,
    live_credentials_from_env,
)


TEST_PRIVATE_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


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
        self.created_market_orders = []
        self.post_orders_calls = []
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

    def create_market_order(self, **kwargs):
        self.created_market_orders.append(kwargs)
        return {"signed": kwargs}

    def post_orders(self, orders):
        self.post_orders_calls.append(list(orders))
        return (
            {"ok": True, "order_id": "yes-order", "message": "订单已提交。"},
            {"ok": True, "order_id": "no-order", "message": "订单已提交。"},
        )

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


def test_live_client_places_protected_fok_pair_as_one_batch():
    item, fake = client()

    results = item.place_protected_pair_buy(
        yes_token_id="token-yes",
        no_token_id="token-no",
        shares=10,
        yes_max_price=0.40,
        no_max_price=0.57,
    )

    assert [call["order_type"] for call in fake.created_market_orders] == ["FOK", "FOK"]
    assert [call["max_price"] for call in fake.created_market_orders] == ["0.4", "0.57"]
    assert [float(call["amount"]) for call in fake.created_market_orders] == [4.0, 5.7]
    assert len(fake.post_orders_calls) == 1
    assert len(fake.post_orders_calls[0]) == 2
    assert all(result["ok"] for result in results)


def test_live_client_places_single_missing_leg_hedge_as_protected_fok():
    item, fake = client()

    result = item.place_protected_market_buy(
        token_id="token-no",
        shares=10,
        max_price=0.57,
    )

    assert result["ok"] is True
    assert fake.market_order_calls == [{
        "token_id": "token-no",
        "side": "BUY",
        "amount": "5.70",
        "max_price": "0.57",
        "order_type": "FOK",
    }]


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


def test_live_session_marks_region_blocked_without_network():
    session = LiveSession()

    session.mark_region_blocked()

    assert session.is_trading_region_blocked() is True
    assert "Polymarket" in session.geoblock_error()


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


def test_normalize_wallet_for_sdk_uses_default_deposit_wallet_when_blank_or_signer():
    from eth_account import Account

    signer = Account.from_key(TEST_PRIVATE_KEY).address

    assert _normalize_wallet_for_sdk("", TEST_PRIVATE_KEY) is None
    assert _normalize_wallet_for_sdk("  ", TEST_PRIVATE_KEY) is None
    assert _normalize_wallet_for_sdk(signer, TEST_PRIVATE_KEY) is None
    assert _normalize_wallet_for_sdk(
        signer, TEST_PRIVATE_KEY, relayer_address=signer
    ) is None
    assert (
        _normalize_wallet_for_sdk("0xactualPolymarketWallet", TEST_PRIVATE_KEY)
        == "0xactualPolymarketWallet"
    )


def test_live_client_omits_signer_wallet_when_creating_sdk(monkeypatch):
    from eth_account import Account

    signer = Account.from_key(TEST_PRIVATE_KEY).address
    created = []

    class FakeSecureClient:
        @classmethod
        def create(cls, **kwargs):
            created.append(kwargs)
            return object()

    monkeypatch.setitem(
        sys.modules,
        "polymarket",
        SimpleNamespace(RelayerApiKey=object, SecureClient=FakeSecureClient),
    )

    item = LiveTradingClient(
        LiveCredentials(private_key=TEST_PRIVATE_KEY, wallet=signer)
    )
    item._ensure_sdk_client()

    assert created[0]["wallet"] is None
    assert created[0]["private_key"] == TEST_PRIVATE_KEY


def test_live_credentials_from_env_accepts_private_key_without_wallet(monkeypatch):
    monkeypatch.delenv("POLYMARKET_WALLET_ADDRESS", raising=False)
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xsecret")

    value = live_credentials_from_env()

    assert value is not None
    assert value.wallet == ""
    assert "0xsecret" not in repr(value)
