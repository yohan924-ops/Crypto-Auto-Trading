"""ATR 기반 동적 손절 테스트.

RiskManager.use_atr_stop=True 일 때 stop_loss_pct 대신
atr * atr_multiplier / avg_price 로 손절 임계 재계산 확인.
"""

from __future__ import annotations

from tradingbot.portfolio.portfolio import Position
from tradingbot.portfolio.risk import RiskManager


def _pos(avg_price: float = 100.0, amount: float = 1.0) -> Position:
    return Position(symbol="BTC/USDT", amount=amount, avg_price=avg_price)


def test_atr_stop_disabled_by_default_uses_fixed_stop():
    """기본값 use_atr_stop=False — 기존 stop_loss_pct 그대로 작동."""
    risk = RiskManager(stop_loss_pct=0.05)
    pos = _pos(100.0)
    # -5% 도달해야 트리거
    assert risk.check_stop_loss(pos, 95.1) is False
    assert risk.check_stop_loss(pos, 95.0) is True
    # ATR 을 줘도 use_atr_stop=False 면 무시
    assert risk.check_stop_loss(pos, 95.1, atr=10.0) is False


def test_atr_stop_uses_dynamic_threshold():
    """use_atr_stop=True + atr 전달 시 동적 임계 적용."""
    # atr=4.0, multiplier=2.0, avg=100 → effective_stop = 0.08 (8%)
    risk = RiskManager(
        stop_loss_pct=0.05,  # 기존 5% — 무시되어야 함
        use_atr_stop=True,
        atr_multiplier=2.0,
    )
    pos = _pos(100.0)
    # 5% 하락은 트리거 X (ATR 임계 8% 이므로)
    assert risk.check_stop_loss(pos, 95.0, atr=4.0) is False
    # 7.9% 하락: 아직 안 넘음
    assert risk.check_stop_loss(pos, 92.1, atr=4.0) is False
    # 8% 하락: 트리거
    assert risk.check_stop_loss(pos, 92.0, atr=4.0) is True


def test_atr_stop_with_low_volatility_tight_threshold():
    """변동성 작을 때 (atr=1.0) — 손절선이 2% 로 좁아짐."""
    risk = RiskManager(
        stop_loss_pct=0.05,
        use_atr_stop=True,
        atr_multiplier=2.0,
    )
    pos = _pos(100.0)
    # 1.9% 하락: 아직 안 넘음
    assert risk.check_stop_loss(pos, 98.1, atr=1.0) is False
    # 2% 하락: ATR 손절 트리거 (기존 5% 고정보다 빨리)
    assert risk.check_stop_loss(pos, 98.0, atr=1.0) is True


def test_atr_stop_with_high_volatility_wide_threshold():
    """변동성 클 때 (atr=8.0) — 손절선이 16% 로 넓어짐."""
    risk = RiskManager(
        stop_loss_pct=0.05,  # 기존 5% 는 무시
        use_atr_stop=True,
        atr_multiplier=2.0,
    )
    pos = _pos(100.0)
    # 10% 하락 — 기존 고정 5% 라면 트리거됐을 것. ATR 모드라 대기.
    assert risk.check_stop_loss(pos, 90.0, atr=8.0) is False
    # 16% 하락: ATR 트리거
    assert risk.check_stop_loss(pos, 84.0, atr=8.0) is True


def test_atr_stop_falls_back_to_fixed_when_atr_is_none():
    """use_atr_stop=True 여도 atr=None 이면 기존 stop_loss_pct 사용."""
    risk = RiskManager(
        stop_loss_pct=0.05,
        use_atr_stop=True,
        atr_multiplier=2.0,
    )
    pos = _pos(100.0)
    # atr 미전달 → 5% 고정 적용
    assert risk.check_stop_loss(pos, 95.1, atr=None) is False
    assert risk.check_stop_loss(pos, 95.0, atr=None) is True


def test_atr_stop_falls_back_when_atr_zero_or_negative():
    """잘못된 ATR 값 (0, 음수) → 고정 손절로 fallback."""
    risk = RiskManager(
        stop_loss_pct=0.05,
        use_atr_stop=True,
        atr_multiplier=2.0,
    )
    pos = _pos(100.0)
    # atr=0: 비정상, 고정 5% fallback
    assert risk.check_stop_loss(pos, 95.0, atr=0.0) is True
    # atr 음수도 마찬가지
    assert risk.check_stop_loss(pos, 95.0, atr=-1.0) is True


def test_atr_stop_different_multipliers():
    """atr_multiplier 조정 효과."""
    # mult=1.0, atr=4, avg=100 → 4% 손절
    risk_1x = RiskManager(use_atr_stop=True, atr_multiplier=1.0)
    pos = _pos(100.0)
    assert risk_1x.check_stop_loss(pos, 96.1, atr=4.0) is False
    assert risk_1x.check_stop_loss(pos, 96.0, atr=4.0) is True

    # mult=3.0, atr=4, avg=100 → 12% 손절 (더 넓게)
    risk_3x = RiskManager(use_atr_stop=True, atr_multiplier=3.0)
    assert risk_3x.check_stop_loss(pos, 88.1, atr=4.0) is False
    assert risk_3x.check_stop_loss(pos, 88.0, atr=4.0) is True


def test_atr_stop_combined_with_trailing():
    """ATR 고정 손절 + 트레일링 병행 작동."""
    risk = RiskManager(
        use_atr_stop=True,
        atr_multiplier=2.0,
        trailing_stop_pct=0.05,
        trailing_activate_pct=0.10,
    )
    pos = _pos(100.0)
    # 먼저 +15% 상승 → peak 115
    risk.update_peak("BTC/USDT", 115.0, pos.amount)
    # 트레일링 활성화 (peak_gain 15% > activate 10%)
    # peak 115 에서 5% 하락 = 109.25 가 트레일링 손절선
    # ATR 손절선: atr=3, mult=2 → 6% (= 94)
    # 현재가 108: peak 기준 -6.1% 하락 → 트레일링 트리거
    assert risk.check_stop_loss(pos, 108.0, symbol="BTC/USDT", atr=3.0) is True
