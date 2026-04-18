"""RiskManager 테스트 (Phase 1 최소 버전)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies.base import Signal, SignalType


def _signal(t: SignalType) -> Signal:
    return Signal(
        type=t,
        symbol="BTC/USDT",
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        price=100.0,
    )


def test_buy_sizes_to_max_position_pct():
    rm = RiskManager(max_position_pct=0.1)
    amount = rm.size_order(_signal(SignalType.BUY), equity=10_000.0, price=100.0, position_amount=0.0)
    # 10% of 10000 = 1000 → /100 price = 10 units
    assert amount == pytest.approx(10.0)


def test_buy_skipped_when_position_exists():
    rm = RiskManager(max_position_pct=0.1)
    amount = rm.size_order(_signal(SignalType.BUY), equity=10_000.0, price=100.0, position_amount=5.0)
    assert amount == 0.0


def test_sell_closes_entire_position():
    rm = RiskManager()
    amount = rm.size_order(_signal(SignalType.SELL), equity=10_000.0, price=100.0, position_amount=3.5)
    assert amount == pytest.approx(3.5)


def test_hold_returns_zero():
    rm = RiskManager()
    amount = rm.size_order(_signal(SignalType.HOLD), equity=10_000.0, price=100.0, position_amount=0.0)
    assert amount == 0.0
