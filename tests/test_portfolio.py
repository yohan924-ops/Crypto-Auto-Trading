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
    # 평단가 = (2*50 + 1) / 2 = 50.5 (수수료 포함 실효 본전가, 2026-04-21~)
    assert pos.avg_price == pytest.approx(50.5)


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


# ---------- sync_from_exchange ----------


def test_sync_sets_cash_and_position_from_balance():
    p = Portfolio(starting_cash=0.0)
    balance = {
        "USDT": {"free": 8123.45, "used": 0.0, "total": 8123.45},
        "BTC": {"free": 0.025, "used": 0.0, "total": 0.025},
    }
    p.sync_from_exchange(balance, symbol="BTC/USDT", current_price=30000.0)
    assert p.cash == pytest.approx(8123.45)
    pos = p.get_position("BTC/USDT")
    assert pos.amount == pytest.approx(0.025)
    # avg_price 가 0 이었으므로 current_price 로 초기화
    assert pos.avg_price == pytest.approx(30000.0)


def test_sync_preserves_existing_avg_price():
    """이미 진입가가 기록돼 있다면 동기화가 그걸 덮어쓰지 않아야 함."""
    p = Portfolio(starting_cash=0.0)
    p.apply_fill(_fill(amount=0.02, price=25000.0, fee=0.0))
    balance = {
        "USDT": {"free": 500.0, "used": 0.0, "total": 500.0},
        "BTC": {"free": 0.03, "used": 0.0, "total": 0.03},
    }
    p.sync_from_exchange(balance, symbol="BTC/USDT", current_price=30000.0)
    pos = p.get_position("BTC/USDT")
    assert pos.amount == pytest.approx(0.03)
    # 기존 avg_price 25000 유지 (0 이 아니라 덮어쓰지 않음)
    assert pos.avg_price == pytest.approx(25000.0)


def test_sync_zero_balance_resets_position():
    p = Portfolio(starting_cash=0.0)
    p.apply_fill(_fill(amount=0.02, price=25000.0, fee=0.0))
    # 거래소엔 BTC 0 이라 하면 로컬도 0 으로 정리
    balance = {"USDT": {"free": 1000.0, "used": 0.0, "total": 1000.0}}
    p.sync_from_exchange(balance, symbol="BTC/USDT", current_price=30000.0)
    pos = p.get_position("BTC/USDT")
    assert pos.amount == 0.0
    assert pos.avg_price == 0.0


def test_sync_missing_asset_keys_defaults_to_zero():
    """API 가 특정 자산 키를 빼먹어도 예외 없이 0 으로 처리."""
    p = Portfolio(starting_cash=5000.0)
    p.sync_from_exchange({}, symbol="BTC/USDT", current_price=None)
    assert p.cash == 0.0
    pos = p.get_position("BTC/USDT")
    assert pos.amount == 0.0
