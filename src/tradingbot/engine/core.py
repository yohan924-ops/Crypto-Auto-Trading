"""엔진 공통 로직: 단일 바를 처리하는 파이프라인 함수.

Runner(실시간)와 Backtester(과거 리플레이)가 동일한 처리 로직을 공유하도록
한 곳에 추출. 로깅·메트릭은 각자 호출측에서 처리.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradingbot.broker.base import Broker, Fill, Order, OrderSide, OrderType
from tradingbot.broker.paper import new_order_id
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies.base import Bar, Signal, SignalType, Strategy

HISTORY_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


@dataclass
class BarOutcome:
    """단일 바 처리의 결과 스냅샷."""

    bar: Bar
    signal: Signal | None
    fill: Fill | None
    order: Order | None
    equity_after: float
    cash_after: float
    position_amount_after: float
    rejected_reason: str | None = None


def append_bar(history: pd.DataFrame, bar: Bar) -> None:
    """history DataFrame 에 bar 를 in-place 로 한 행 추가."""
    history.loc[len(history)] = {
        "timestamp": bar.timestamp,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def process_bar(
    bar: Bar,
    history: pd.DataFrame,
    *,
    symbol: str,
    strategy: Strategy,
    broker: Broker,
    portfolio: Portfolio,
    risk: RiskManager,
) -> BarOutcome:
    """새 바 하나를 파이프라인에 통과시키고 결과 스냅샷 반환.

    ``history`` 는 호출 전 현재 바가 이미 포함되어 있어야 함.
    """
    marks = {symbol: bar.close}

    if len(history) < strategy.warmup_bars():
        return BarOutcome(
            bar=bar,
            signal=None,
            fill=None,
            order=None,
            equity_after=portfolio.equity(marks) if portfolio.positions else portfolio.cash,
            cash_after=portfolio.cash,
            position_amount_after=portfolio.get_position(symbol).amount,
        )

    signal = strategy.on_bar(bar, history)
    equity = portfolio.equity(marks)
    position_amount = portfolio.get_position(symbol).amount
    amount = risk.size_order(
        signal=signal,
        equity=equity,
        price=bar.close,
        position_amount=position_amount,
    )

    order: Order | None = None
    fill: Fill | None = None
    rejected: str | None = None

    if amount > 0 and signal.type in (SignalType.BUY, SignalType.SELL):
        side = OrderSide.BUY if signal.type == SignalType.BUY else OrderSide.SELL
        order = Order(
            id=new_order_id(),
            symbol=symbol,
            side=side,
            type=OrderType.MARKET,
            amount=amount,
            created_at=bar.timestamp,
        )
        try:
            fill = broker.submit(order, mark_price=bar.close)
            portfolio.apply_fill(fill)
        except Exception as exc:  # noqa: BLE001
            rejected = str(exc)

    return BarOutcome(
        bar=bar,
        signal=signal,
        fill=fill,
        order=order,
        equity_after=portfolio.equity(marks),
        cash_after=portfolio.cash,
        position_amount_after=portfolio.get_position(symbol).amount,
        rejected_reason=rejected,
    )
