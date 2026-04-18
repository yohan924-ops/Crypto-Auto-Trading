"""기본 콘솔 알림 채널 (loguru 로 stderr 출력)."""

from __future__ import annotations

from loguru import logger

from .base import Notifier, NotifyEvent


class ConsoleNotifier(Notifier):
    name = "console"

    _EMOJI = {
        NotifyEvent.SIGNAL: "📡",
        NotifyEvent.ORDER_FILLED: "✅",
        NotifyEvent.ORDER_REJECTED: "⚠️",
        NotifyEvent.STOP_LOSS: "🛑",
        NotifyEvent.CIRCUIT_BREAKER: "🚨",
        NotifyEvent.ERROR: "❌",
        NotifyEvent.DAILY_REPORT: "📊",
    }

    def notify(self, event: NotifyEvent, message: str, **context) -> None:
        emoji = self._EMOJI.get(event, "")
        logger.info("{} [{}] {}", emoji, event.value, message)
