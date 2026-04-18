"""텔레그램 봇 알림 채널.

python-telegram-bot (async) 대신 stdlib urllib 로 간단히 HTTP POST.
이벤트 유실보다 프로그램 중단 방지가 우선이므로 모든 예외는 삼키고 로그만 남김.

봇 설정:
  1. Telegram 에서 @BotFather 검색 → /newbot → 이름 입력 → 토큰 발급
  2. 봇과 대화 시작 (아무 메시지)
  3. https://api.telegram.org/bot<TOKEN>/getUpdates 에서 chat_id 확인
  4. .env 에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 저장
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from loguru import logger

from .base import Notifier, NotifyEvent

_API_BASE = "https://api.telegram.org"


class TelegramNotifier(Notifier):
    name = "telegram"

    _EMOJI = {
        NotifyEvent.SIGNAL: "📡",
        NotifyEvent.ORDER_FILLED: "✅",
        NotifyEvent.ORDER_REJECTED: "⚠️",
        NotifyEvent.STOP_LOSS: "🛑",
        NotifyEvent.CIRCUIT_BREAKER: "🚨",
        NotifyEvent.ERROR: "❌",
        NotifyEvent.DAILY_REPORT: "📊",
    }

    def __init__(self, bot_token: str, chat_id: str, timeout: float = 5.0) -> None:
        if not bot_token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN 과 TELEGRAM_CHAT_ID 모두 필요함")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    def notify(self, event: NotifyEvent, message: str, **context) -> None:
        emoji = self._EMOJI.get(event, "")
        text = f"{emoji} [{event.value}] {message}".strip()
        try:
            self._send(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("텔레그램 전송 실패 ({}): {}", event.value, exc)

    def _send(self, text: str) -> None:
        url = f"{_API_BASE}/bot{self.bot_token}/sendMessage"
        body = urllib.parse.urlencode(
            {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
            if not payload.get("ok"):
                raise RuntimeError(f"Telegram API error: {payload}")
