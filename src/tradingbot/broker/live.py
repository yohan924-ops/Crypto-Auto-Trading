"""LiveBroker: CCXT를 통해 실제 거래소에 주문 제출.

Testnet(sandbox=True) 와 실전(sandbox=False) 모두 이 브로커로 실행되며,
호출 측(CLI live)에서 이중 게이트로 보호된다.

네트워크 오류(NetworkError / RequestTimeout)는 tenacity 로 지수 백오프 재시도.
인증/잔고 부족 등 비네트워크 오류는 즉시 전파.
"""

from __future__ import annotations

from dataclasses import dataclass

import ccxt
from loguru import logger
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from tradingbot.exchange.ccxt_adapter import CCXTAdapter

from .base import Broker, Fill, Order, OrderSide, OrderType


@dataclass
class LiveBroker(Broker):
    exchange: CCXTAdapter

    def submit(self, order: Order, mark_price: float) -> Fill:
        if order.type != OrderType.MARKET:
            raise NotImplementedError("Phase 4 LiveBroker 는 시장가 주문만 지원")
        if order.amount <= 0:
            raise ValueError("주문 수량은 0보다 커야 함")
        # 재시도 시 중복 주문 방지를 위해 주문마다 고유 clientOrderId 를 전달.
        # CCXT unified 키를 쓰면 Binance(newClientOrderId)/Upbit(identifier) 로 매핑된다.
        # Binance 규격: 알파벳+숫자+'-' 최대 36자. order.id 는 12자 hex → 'bot-' 접두.
        client_order_id = f"bot-{order.id}"
        result = self._create_order_with_retry(
            symbol=order.symbol,
            side="buy" if order.side == OrderSide.BUY else "sell",
            amount=order.amount,
            client_order_id=client_order_id,
        )
        return self._to_fill(order, result, mark_price)

    @retry(
        retry=retry_if_exception_type((ccxt.NetworkError, ccxt.RequestTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
        before_sleep=before_sleep_log(logger, "WARNING"),  # type: ignore[arg-type]
    )
    def _create_order_with_retry(
        self, symbol: str, side: str, amount: float, client_order_id: str
    ) -> dict:
        return self.exchange.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=amount,
            params={"clientOrderId": client_order_id},
        )

    @staticmethod
    def _to_fill(order: Order, result: dict, mark_price: float) -> Fill:
        """ccxt 주문 응답을 Fill 로 변환.

        체결 수량(filled)은 **응답에 명시된 값만** 신뢰한다.
        - status == 'closed' + filled 누락: 전량 체결로 간주 (order.amount)
        - 그 외(open/partial/누락): filled 값이 있으면 그대로, 없으면 0
          → Portfolio 과대 기록 방지. 실제 체결 수량이 부족하면 다음 주문 사이징에
            반영되도록 보수적으로 처리.
        평균 체결가도 응답에 있으면 그 값, 없을 때만 mark_price 로 보완.
        """
        filled_raw = result.get("filled")
        status = (result.get("status") or "").lower()
        if filled_raw not in (None, ""):
            filled = float(filled_raw)
        elif status == "closed":
            filled = order.amount
        else:
            filled = 0.0
        avg_raw = result.get("average") or result.get("price")
        avg_price = float(avg_raw) if avg_raw not in (None, "") else mark_price

        fee_cost = 0.0
        fee_info = result.get("fee")
        if isinstance(fee_info, dict) and fee_info.get("cost") is not None:
            fee_cost = float(fee_info["cost"])
        elif isinstance(result.get("fees"), list) and result["fees"]:
            fee_cost = float(result["fees"][0].get("cost", 0.0) or 0.0)

        return Fill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            amount=filled,
            price=avg_price,
            fee=fee_cost,
            timestamp=order.created_at,
        )
