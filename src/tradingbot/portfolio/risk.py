"""Risk Manager: 전략 신호를 받아 실제 주문 수량을 결정.

Phase 1 MVP 버전은 최대 포지션 비중(max_position_pct)만 구현.
Phase 3 에서 손절/일일 손실 서킷브레이커 추가 예정.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.strategies.base import Signal, SignalType


@dataclass
class RiskManager:
    max_position_pct: float = 0.10

    def size_order(
        self,
        signal: Signal,
        equity: float,
        price: float,
        position_amount: float,
    ) -> float:
        """주문 수량 결정. 0 반환 시 주문 스킵.

        - BUY: 이미 포지션 보유 중이면 0, 아니면 max_position_pct 만큼 매수
        - SELL: 보유 수량 전체 청산
        - HOLD: 0
        """
        if signal.type == SignalType.BUY:
            if position_amount > 0:
                return 0.0
            if price <= 0 or equity <= 0:
                return 0.0
            target_notional = equity * self.max_position_pct
            return target_notional / price
        if signal.type == SignalType.SELL:
            return max(position_amount, 0.0)
        return 0.0
