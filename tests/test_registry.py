"""전략 레지스트리 테스트."""

from __future__ import annotations

import pytest

from tradingbot.strategies import buy_and_hold  # noqa: F401  등록 트리거
from tradingbot.strategies.registry import available, get


def test_buy_and_hold_registered():
    assert "buy_and_hold" in available()


def test_get_returns_class():
    cls = get("buy_and_hold")
    assert cls.name == "buy_and_hold"


def test_unknown_raises():
    with pytest.raises(KeyError):
        get("does_not_exist")
