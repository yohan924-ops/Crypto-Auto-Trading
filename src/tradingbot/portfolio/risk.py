"""Risk Manager: 포지션 사이징 + 손절 + 일일 손실 서킷브레이커.

- max_position_pct: 신규 진입 시 자산의 몇 % 까지 할당할지
- stop_loss_pct: 포지션 평가손이 이 비율을 넘으면 강제 청산 신호
- max_daily_loss_pct: 일일 손실이 이 비율에 도달하면 당일 추가 거래 차단
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from tradingbot.portfolio.portfolio import Position
from tradingbot.strategies.base import Signal, SignalType


@dataclass
class RiskManager:
    max_position_pct: float = 0.10
    stop_loss_pct: float = 0.05
    max_daily_loss_pct: float = 0.05

    # 내부 상태 (일자별 리셋)
    _current_day: date | None = field(default=None, repr=False)
    _day_start_equity: float | None = field(default=None, repr=False)
    _halted: bool = field(default=False, repr=False)

    def size_order(
        self,
        signal: Signal,
        equity: float,
        price: float,
        position_amount: float,
        weight: float = 1.0,
    ) -> float:
        """주문 수량 결정. 0 반환 시 주문 스킵.

        - BUY: 이미 포지션 보유 중이면 0, 아니면 max_position_pct*weight 만큼 매수
        - SELL: 보유 수량 전체 청산
        - HOLD: 0

        ``weight`` 는 멀티 자산 포트폴리오에서 심볼별 할당 비중. 단일 자산은 1.0.
        """
        if signal.type == SignalType.BUY:
            if position_amount > 0:
                return 0.0
            if price <= 0 or equity <= 0 or weight <= 0:
                return 0.0
            target_notional = equity * self.max_position_pct * weight
            return target_notional / price
        if signal.type == SignalType.SELL:
            return max(position_amount, 0.0)
        return 0.0

    def check_stop_loss(self, position: Position, current_price: float) -> bool:
        """보유 포지션이 손절선(-stop_loss_pct) 이하로 내려갔는지 여부."""
        if position.amount <= 0 or position.avg_price <= 0 or current_price <= 0:
            return False
        pnl_pct = (current_price - position.avg_price) / position.avg_price
        return pnl_pct <= -self.stop_loss_pct

    def update_day(self, now: datetime, equity: float) -> bool:
        """일자 경계를 관리. 날짜가 바뀌면 True 반환하고 상태 리셋.

        새로운 날 시작 → 손실 한도도 초기화.
        """
        today = now.date()
        if self._current_day != today:
            self._current_day = today
            self._day_start_equity = equity
            self._halted = False
            return True
        return False

    def update_circuit_breaker(self, equity: float) -> None:
        """현재 자산이 일일 손실 한도를 초과하면 halted 플래그 설정."""
        if self._day_start_equity is None or self._day_start_equity <= 0:
            return
        daily_pnl_pct = (equity - self._day_start_equity) / self._day_start_equity
        if daily_pnl_pct <= -self.max_daily_loss_pct:
            self._halted = True

    @property
    def halted(self) -> bool:
        return self._halted

    def daily_pnl_pct(self, equity: float) -> float:
        if self._day_start_equity is None or self._day_start_equity <= 0:
            return 0.0
        return (equity - self._day_start_equity) / self._day_start_equity * 100.0
