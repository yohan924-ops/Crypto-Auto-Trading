"""Notifier 레이어 테스트 (콘솔 + 팩토리 + 텔레그램 HTTP mock)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingbot.notifier import build_notifiers
from tradingbot.notifier.base import Notifier, NotifyEvent
from tradingbot.notifier.console import ConsoleNotifier
from tradingbot.notifier.telegram import TelegramNotifier


def test_console_notifier_does_not_raise():
    n = ConsoleNotifier()
    # 단순히 예외가 안 나는지 확인
    n.notify(NotifyEvent.SIGNAL, "BUY BTC/USDT @ 100.00")
    n.notify(NotifyEvent.STOP_LOSS, "손절 발동")


def test_build_notifiers_console_only():
    notifiers = build_notifiers(["console"])
    assert len(notifiers) == 1
    assert notifiers[0].name == "console"


def test_build_notifiers_telegram_without_token_is_skipped():
    notifiers = build_notifiers(["telegram"])
    assert notifiers == []


def test_build_notifiers_telegram_with_token_included():
    notifiers = build_notifiers(
        ["console", "telegram"], telegram_token="abc", telegram_chat_id="123"
    )
    names = [n.name for n in notifiers]
    assert names == ["console", "telegram"]


def test_build_notifiers_unknown_name_skipped():
    notifiers = build_notifiers(["does_not_exist"])
    assert notifiers == []


def test_telegram_notifier_requires_both_creds():
    with pytest.raises(ValueError):
        TelegramNotifier(bot_token="", chat_id="")
    with pytest.raises(ValueError):
        TelegramNotifier(bot_token="x", chat_id="")


def test_telegram_notifier_sends_http_post():
    t = TelegramNotifier(bot_token="TOKEN", chat_id="CHAT")
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value.read.return_value = b'{"ok": true}'
    with patch(
        "tradingbot.notifier.telegram.urllib.request.urlopen",
        return_value=mock_ctx,
    ) as urlopen:
        t.notify(NotifyEvent.SIGNAL, "BUY BTC @ 100")

    assert urlopen.called
    call_args = urlopen.call_args
    req = call_args[0][0]
    assert req.full_url.startswith("https://api.telegram.org/botTOKEN/sendMessage")
    # body 에 chat_id 와 text 가 포함되어야 함
    body = req.data.decode("utf-8")
    assert "chat_id=CHAT" in body
    assert "BUY+BTC" in body or "BUY%20BTC" in body


def test_telegram_swallows_exceptions():
    """네트워크 실패가 매매 루프를 멈추지 않아야 함."""
    t = TelegramNotifier(bot_token="x", chat_id="y")
    with patch(
        "tradingbot.notifier.telegram.urllib.request.urlopen",
        side_effect=OSError("network down"),
    ):
        t.notify(NotifyEvent.ERROR, "x")  # 예외 전파 안 됨
    # no assertion needed; if exception propagated, test fails


def test_notifier_abc_cannot_instantiate():
    with pytest.raises(TypeError):
        Notifier()  # type: ignore[abstract]
