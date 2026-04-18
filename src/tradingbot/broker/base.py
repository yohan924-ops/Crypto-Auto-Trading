"""브로커 ABC 및 Order/Fill 데이터 구조."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class Order:
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    amount: float
    price: float | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Fill:
    """브로커가 주문을 체결했을 때 생성되는 이벤트."""

    order_id: str
    symbol: str
    side: OrderSide
    amount: float
    price: float
    fee: float
    timestamp: datetime


class Broker(ABC):
    """페이퍼/실전 공통 인터페이스.

    Runner는 주문 가능 여부(현금/포지션 충분성)를 자체 판단 후 ``submit`` 호출한다.
    """

    @abstractmethod
    def submit(self, order: Order, mark_price: float) -> Fill:
        """주문을 체결하고 Fill 이벤트를 반환. 거부 시 예외 발생."""
