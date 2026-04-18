"""알림 채널 추상화.

모든 Notifier 는 ``notify(event, message, **context)`` 를 구현한다.
Runner 는 활성화된 Notifier 목록을 주입받아 이벤트마다 순회 호출한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class NotifyEvent(StrEnum):
    SIGNAL = "signal"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    STOP_LOSS = "stop_loss"
    CIRCUIT_BREAKER = "circuit_breaker"
    ERROR = "error"
    DAILY_REPORT = "daily_report"


class Notifier(ABC):
    """알림 채널 인터페이스."""

    name: str

    @abstractmethod
    def notify(self, event: NotifyEvent, message: str, **context) -> None:
        """이벤트를 채널로 전송. 구현체는 예외를 삼키고 로깅만 해야 함."""
