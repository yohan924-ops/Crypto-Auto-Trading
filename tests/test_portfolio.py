"""Portfolio 테스트: Fill 적용과 equity 계산."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tradingbot.broker.base import Fill, OrderSide
from tradingbot.portfolio.portfolio import Portfolio


def _fill(
    symbol: str = "BTC/USDT",
    side: OrderSide = OrderSide.BUY,
    amount: float = 1.0,
    price: float = 100.0,
    fee: float = 0.1,
) -> Fill:
    return Fill(
        order_id="test",
        symbol=symbol,
        side=side,
        amount=amount,
        price=price,
        fee=fee,
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_initial_cash():
    p = Portfolio(starting_cash=1000.0)
    assert p.cash == 1000.0
    assert p.positions == {}
    assert p.equity({}) == 1000.0


def test_buy_fill_reduces_cash_and_adds_position():
    p = Portfolio(starting_cash=1000.0)
    p.apply_fill(_fill(amount=2.0, price=50.0, fee=1.0))
    # 현금: 1000 - (2*50) - 1 = 899
    assert p.cash == pytest.approx(899.0)
    pos = p.get_position("BTC/USDT")
    assert pos.amount == pytest.approx(2.0)
    assert pos.avg_price == pytest.approx(50.0)


def test_sell_fill_increases_cash_and_reduces_position():
    p = Portfolio(starting_cash=1000.0)
    p.apply_fill(_fill(side=OrderSide.BUY, amount=2.0, price=50.0, fee=1.0))
    p.apply_fill(_fill(side=OrderSide.SELL, amount=1.0, price=60.0, fee=0.6))
    # 매도 후 현금: 899 + 60 - 0.6 = 958.4
    assert p.cash == pytest.approx(958.4)
    pos = p.get_position("BTC/USDT")
    assert pos.amount == pytest.approx(1.0)


def test_full_sell_resets_avg_price():
    p = Portfolio(starting_cash=1000.0)
    p.apply_fill(_fill(side=OrderSide.BUY, amount=2.0, price=50.0, fee=0.0))
    p.apply_fill(_fill(side=OrderSide.SELL, amount=2.0, price=60.0, fee=0.0))
    pos = p.get_position("BTC/USDT")
    assert pos.amount == 0.0
    assert pos.avg_price == 0.0


def test_avg_price_weighted_on_additional_buy():
    p = Portfolio(starting_cash=10_000.0)
    p.apply_fill(_fill(amount=1.0, price=100.0, fee=0.0))
    p.apply_fill(_fill(amount=1.0, price=200.0, fee=0.0))
    pos = p.get_position("BTC/USDT")
    assert pos.amount == pytest.approx(2.0)
    assert pos.avg_price == pytest.approx(150.0)


def test_equity_includes_position_mark():
    p = Portfolio(starting_cash=1000.0)
    p.apply_fill(_fill(amount=2.0, price=50.0, fee=0.0))
    # 현재가 70 에 마크: 현금 900 + 2*70 = 1040
    assert p.equity({"BTC/USDT": 70.0}) == pytest.approx(1040.0)


def test_equity_missing_mark_raises():
    p = Portfolio(starting_cash=1000.0)
    p.apply_fill(_fill(amount=2.0, price=50.0, fee=0.0))
    with pytest.raises(KeyError):
        p.equity({})
