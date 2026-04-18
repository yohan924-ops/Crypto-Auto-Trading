"""PaperBroker 테스트: 체결가, 수수료, 슬리피지."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tradingbot.broker.base import Order, OrderSide, OrderType
from tradingbot.broker.paper import PaperBroker, new_order_id


def _order(side: OrderSide = OrderSide.BUY, amount: float = 1.0) -> Order:
    return Order(
        id=new_order_id(),
        symbol="BTC/USDT",
        side=side,
        type=OrderType.MARKET,
        amount=amount,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_market_buy_applies_slippage_up():
    broker = PaperBroker(fee_bps=10, slippage_bps=5)
    fill = broker.submit(_order(side=OrderSide.BUY, amount=1.0), mark_price=100.0)
    # 슬리피지 0.05% → 체결가 100 * 1.0005
    assert fill.price == pytest.approx(100.05)


def test_market_sell_applies_slippage_down():
    broker = PaperBroker(fee_bps=10, slippage_bps=5)
    fill = broker.submit(_order(side=OrderSide.SELL, amount=1.0), mark_price=100.0)
    assert fill.price == pytest.approx(99.95)


def test_fee_is_bps_of_notional():
    broker = PaperBroker(fee_bps=10, slippage_bps=0)
    fill = broker.submit(_order(amount=2.0), mark_price=100.0)
    # notional = 2 * 100 = 200, fee = 200 * 0.001 = 0.2
    assert fill.fee == pytest.approx(0.2)


def test_zero_amount_rejected():
    broker = PaperBroker()
    with pytest.raises(ValueError):
        broker.submit(_order(amount=0.0), mark_price=100.0)


def test_negative_mark_price_rejected():
    broker = PaperBroker()
    with pytest.raises(ValueError):
        broker.submit(_order(), mark_price=-1.0)


def test_limit_order_not_supported_phase1():
    broker = PaperBroker()
    order = _order()
    order.type = OrderType.LIMIT
    with pytest.raises(NotImplementedError):
        broker.submit(order, mark_price=100.0)
