"""PaperBroker: 시세는 실시간이지만 주문은 내부에서 가상 체결."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from .base import Broker, Fill, Order, OrderSide, OrderType


@dataclass
class PaperBroker(Broker):
    """시장가 주문에 수수료와 슬리피지를 적용해 즉시 체결.

    fee_bps: 체결가 기준 수수료. 10 = 0.10%
    slippage_bps: 체결가 기울기. BUY는 mark * (1 + s), SELL은 mark * (1 - s)
    """

    fee_bps: float = 10.0
    slippage_bps: float = 5.0

    def submit(self, order: Order, mark_price: float) -> Fill:
        if order.type != OrderType.MARKET:
            raise NotImplementedError("Phase 1 페이퍼 브로커는 시장가 주문만 지원")
        if order.amount <= 0:
            raise ValueError("주문 수량은 0보다 커야 함")
        if mark_price <= 0:
            raise ValueError("mark_price 는 0보다 커야 함")

        slippage = self.slippage_bps / 10_000
        if order.side == OrderSide.BUY:
            fill_price = mark_price * (1 + slippage)
        else:
            fill_price = mark_price * (1 - slippage)

        notional = order.amount * fill_price
        fee = notional * (self.fee_bps / 10_000)

        return Fill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            amount=order.amount,
            price=fill_price,
            fee=fee,
            timestamp=order.created_at,
        )


def new_order_id() -> str:
    """짧은 주문 ID 생성기."""
    return uuid.uuid4().hex[:12]
