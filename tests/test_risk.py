"""RiskManager 테스트: 사이징, 손절, 일일 손실 서킷브레이커."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tradingbot.portfolio.portfolio import Position
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies.base import Signal, SignalType


def _signal(t: SignalType) -> Signal:
    return Signal(
        type=t,
        symbol="BTC/USDT",
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        price=100.0,
    )


# ------- 사이징 -------


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


# ------- 손절 -------


def test_stop_loss_triggers_when_price_drops_below_threshold():
    rm = RiskManager(stop_loss_pct=0.05)
    pos = Position(symbol="BTC/USDT", amount=1.0, avg_price=100.0)
    # 95 는 정확히 -5% 경계, 94 는 초과 → 트리거
    assert rm.check_stop_loss(pos, 95.0) is True  # -5% 정확 도달
    assert rm.check_stop_loss(pos, 94.0) is True
    assert rm.check_stop_loss(pos, 95.5) is False  # -4.5% 아직 아님


def test_stop_loss_skips_empty_position():
    rm = RiskManager(stop_loss_pct=0.05)
    pos = Position(symbol="BTC/USDT", amount=0.0, avg_price=0.0)
    assert rm.check_stop_loss(pos, 1.0) is False


# ------- 서킷브레이커 -------


def test_new_day_resets_halt_and_tracks_equity():
    rm = RiskManager(max_daily_loss_pct=0.05)
    t0 = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    rolled = rm.update_day(t0, equity=10_000.0)
    assert rolled is True
    assert rm.halted is False

    # 같은 날 다른 시각 → 롤오버 없음
    t1 = t0 + timedelta(hours=5)
    rolled2 = rm.update_day(t1, equity=9_800.0)
    assert rolled2 is False


def test_circuit_breaker_halts_after_daily_loss_limit():
    rm = RiskManager(max_daily_loss_pct=0.05)
    t0 = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    rm.update_day(t0, equity=10_000.0)
    assert rm.halted is False

    # -3% → 아직 halt 아님
    rm.update_circuit_breaker(9_700.0)
    assert rm.halted is False

    # -5.1% → halt 발동
    rm.update_circuit_breaker(9_490.0)
    assert rm.halted is True


def test_new_day_clears_previous_halt():
    rm = RiskManager(max_daily_loss_pct=0.05)
    t0 = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    rm.update_day(t0, equity=10_000.0)
    rm.update_circuit_breaker(9_400.0)  # halt 발동
    assert rm.halted is True

    next_day = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
    rolled = rm.update_day(next_day, equity=9_400.0)
    assert rolled is True
    assert rm.halted is False


def test_daily_pnl_pct_matches():
    rm = RiskManager()
    rm.update_day(datetime(2024, 1, 1, tzinfo=UTC), equity=10_000.0)
    assert rm.daily_pnl_pct(10_100.0) == pytest.approx(1.0)
    assert rm.daily_pnl_pct(9_800.0) == pytest.approx(-2.0)
