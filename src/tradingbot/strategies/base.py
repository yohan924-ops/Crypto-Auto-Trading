"""전략 ABC 및 관련 데이터 구조.

모든 전략은 Strategy ABC를 상속하고 ``on_bar`` 에서 ``Signal`` 을 반환한다.
엔진/브로커는 전략 구현체를 직접 import 하지 않으며, ``registry`` 경유로만 참조한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

import pandas as pd


class SignalType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Bar:
    """단일 OHLCV 캔들."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    """전략이 생성한 매매 신호.

    포지션 크기는 RiskManager가 결정하므로 size 정보는 포함하지 않는다.
    """

    type: SignalType
    symbol: str
    timestamp: datetime
    price: float
    reason: str = ""


class Strategy(ABC):
    """모든 전략의 공통 인터페이스.

    구현체는 ``name`` 클래스 변수를 정의하고 ``@register`` 데코레이터로 등록한다.
    """

    name: ClassVar[str]

    def __init__(self, params: dict, symbol: str, timeframe: str) -> None:
        self.params = params
        self.symbol = symbol
        self.timeframe = timeframe

    @abstractmethod
    def warmup_bars(self) -> int:
        """전략 계산에 필요한 최소 봉 개수."""

    @abstractmethod
    def on_bar(self, bar: Bar, history: pd.DataFrame) -> Signal:
        """새 봉마다 호출. ``history`` 는 현재 봉을 마지막 행으로 포함한다.

        컬럼: timestamp, open, high, low, close, volume.
        """

    def on_start(self) -> None:
        """선택적 훅. 전략 초기화 직후 한 번 호출."""

    def on_stop(self) -> None:
        """선택적 훅. 엔진 종료 시 호출."""
