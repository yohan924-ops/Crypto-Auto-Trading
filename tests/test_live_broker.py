"""LiveBroker 테스트 (CCXT 모의 객체).

실제 네트워크 호출 없이 submit 이 create_order 를 올바르게 부르고,
응답을 Fill 로 변환하는지 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import ccxt
import pytest

from tradingbot.broker.base import Order, OrderSide, OrderType
from tradingbot.broker.live import LiveBroker


def _order(side: OrderSide = OrderSide.BUY, amount: float = 0.001) -> Order:
    return Order(
        id="test-123",
        symbol="BTC/USDT",
        side=side,
        type=OrderType.MARKET,
        amount=amount,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _ok_response(
    filled: float = 0.001, avg: float = 30_000.0, fee: float = 0.03
) -> dict:
    return {
        "id": "binance-999",
        "symbol": "BTC/USDT",
        "status": "closed",
        "filled": filled,
        "average": avg,
        "fee": {"cost": fee, "currency": "USDT"},
    }


def test_submit_calls_create_order_with_market_params():
    exchange = MagicMock()
    exchange.create_order.return_value = _ok_response()
    broker = LiveBroker(exchange=exchange)

    fill = broker.submit(_order(amount=0.001), mark_price=30_000.0)

    exchange.create_order.assert_called_once()
    args, kwargs = exchange.create_order.call_args
    # create_order(symbol, type, side, amount, price, params) — CCXTAdapter 인터페이스
    assert kwargs["symbol"] == "BTC/USDT"
    assert kwargs["type"] == "market"
    assert kwargs["side"] == "buy"
    assert kwargs["amount"] == pytest.approx(0.001)
    assert fill.price == pytest.approx(30_000.0)
    assert fill.amount == pytest.approx(0.001)
    assert fill.fee == pytest.approx(0.03)
    assert fill.order_id == "test-123"


def test_submit_sell_converts_side():
    exchange = MagicMock()
    exchange.create_order.return_value = _ok_response()
    broker = LiveBroker(exchange=exchange)
    broker.submit(_order(side=OrderSide.SELL), mark_price=30_000.0)
    assert exchange.create_order.call_args.kwargs["side"] == "sell"


def test_missing_fields_fallback_to_mark_and_amount():
    """거래소 응답이 얇은 경우 mark_price / order.amount 로 보완."""
    exchange = MagicMock()
    exchange.create_order.return_value = {"status": "closed"}
    broker = LiveBroker(exchange=exchange)
    fill = broker.submit(_order(amount=0.005), mark_price=29_000.0)
    assert fill.amount == pytest.approx(0.005)
    assert fill.price == pytest.approx(29_000.0)
    assert fill.fee == 0.0


def test_limit_order_not_supported():
    exchange = MagicMock()
    broker = LiveBroker(exchange=exchange)
    order = _order()
    order.type = OrderType.LIMIT
    with pytest.raises(NotImplementedError):
        broker.submit(order, mark_price=30_000.0)


def test_zero_amount_rejected():
    exchange = MagicMock()
    broker = LiveBroker(exchange=exchange)
    with pytest.raises(ValueError):
        broker.submit(_order(amount=0.0), mark_price=30_000.0)


def test_network_error_retries_then_succeeds():
    exchange = MagicMock()
    # 첫 두 번은 NetworkError, 세 번째 성공
    exchange.create_order.side_effect = [
        ccxt.NetworkError("temp"),
        ccxt.NetworkError("temp"),
        _ok_response(),
    ]
    broker = LiveBroker(exchange=exchange)
    fill = broker.submit(_order(), mark_price=30_000.0)
    assert exchange.create_order.call_count == 3
    assert fill.price == pytest.approx(30_000.0)


def test_network_error_exhausts_retries_and_reraises():
    exchange = MagicMock()
    exchange.create_order.side_effect = ccxt.NetworkError("persistent outage")
    broker = LiveBroker(exchange=exchange)
    with pytest.raises(ccxt.NetworkError):
        broker.submit(_order(), mark_price=30_000.0)
    # stop_after_attempt(3) → 총 3번 시도
    assert exchange.create_order.call_count == 3


def test_non_network_error_propagates_without_retry():
    exchange = MagicMock()
    exchange.create_order.side_effect = ccxt.InsufficientFunds("잔고 부족")
    broker = LiveBroker(exchange=exchange)
    with pytest.raises(ccxt.InsufficientFunds):
        broker.submit(_order(), mark_price=30_000.0)
    # 재시도 없이 즉시 전파
    assert exchange.create_order.call_count == 1
