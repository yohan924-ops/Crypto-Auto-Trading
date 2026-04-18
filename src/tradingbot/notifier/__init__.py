"""알림 레이어: 채널 빌더 헬퍼."""

from __future__ import annotations

from loguru import logger

from .base import Notifier, NotifyEvent
from .console import ConsoleNotifier

__all__ = ["Notifier", "NotifyEvent", "ConsoleNotifier", "build_notifiers"]


def build_notifiers(
    names: list[str],
    *,
    telegram_token: str | None = None,
    telegram_chat_id: str | None = None,
) -> list[Notifier]:
    """settings.yaml 의 notifiers 목록을 실제 인스턴스 리스트로 변환.

    토큰이 비어있는 텔레그램 등은 경고만 남기고 조용히 스킵한다.
    """
    result: list[Notifier] = []
    for name in names:
        if name == "console":
            result.append(ConsoleNotifier())
        elif name == "telegram":
            if not telegram_token or not telegram_chat_id:
                logger.warning(
                    "telegram notifier 비활성화: TELEGRAM_BOT_TOKEN/CHAT_ID 미설정"
                )
                continue
            from .telegram import TelegramNotifier

            result.append(TelegramNotifier(telegram_token, telegram_chat_id))
        else:
            logger.warning("알 수 없는 notifier: {}", name)
    return result
