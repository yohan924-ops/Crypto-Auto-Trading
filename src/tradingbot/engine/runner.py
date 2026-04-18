"""페이퍼/실전 실행 루프.

데이터 피드에서 Bar 를 받아 → 전략에 전달 → 신호 생성 → Risk 로 수량 결정 →
Broker 로 주문 → Portfolio 에 체결 반영 → 로그/알림 순으로 처리.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict

import pandas as pd
from loguru import logger

from tradingbot.broker.base import Broker, Order, OrderSide, OrderType
from tradingbot.broker.paper import new_order_id
from tradingbot.logging_setup import log_order_event
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies.base import Bar, SignalType, Strategy

_HISTORY_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class Runner:
    def __init__(
        self,
        symbol: str,
        strategy: Strategy,
        broker: Broker,
        portfolio: Portfolio,
        risk: RiskManager,
        bar_stream: Iterator[Bar],
    ) -> None:
        self.symbol = symbol
        self.strategy = strategy
        self.broker = broker
        self.portfolio = portfolio
        self.risk = risk
        self.bar_stream = bar_stream

    def run(self) -> None:
        self.strategy.on_start()
        history = pd.DataFrame(columns=_HISTORY_COLUMNS)
        try:
            for bar in self.bar_stream:
                self._process_bar(bar, history)
        finally:
            self.strategy.on_stop()

    def _process_bar(self, bar: Bar, history: pd.DataFrame) -> None:
        history.loc[len(history)] = {
            "timestamp": bar.timestamp,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }

        if len(history) < self.strategy.warmup_bars():
            logger.debug(
                "워밍업 중: {n}/{need}",
                n=len(history),
                need=self.strategy.warmup_bars(),
            )
            return

        signal = self.strategy.on_bar(bar, history)
        log_order_event({"event": "signal", **asdict(signal)})

        marks = {self.symbol: bar.close}
        equity = self.portfolio.equity(marks)
        position_amount = self.portfolio.get_position(self.symbol).amount

        amount = self.risk.size_order(
            signal=signal,
            equity=equity,
            price=bar.close,
            position_amount=position_amount,
        )

        fill = None
        if amount > 0 and signal.type in (SignalType.BUY, SignalType.SELL):
            side = OrderSide.BUY if signal.type == SignalType.BUY else OrderSide.SELL
            order = Order(
                id=new_order_id(),
                symbol=self.symbol,
                side=side,
                type=OrderType.MARKET,
                amount=amount,
                created_at=bar.timestamp,
            )
            log_order_event({"event": "order_submitted", **asdict(order)})
            try:
                fill = self.broker.submit(order, mark_price=bar.close)
                self.portfolio.apply_fill(fill)
                log_order_event({"event": "order_filled", **asdict(fill)})
            except Exception as exc:
                logger.exception("주문 체결 실패: {}", exc)
                log_order_event({"event": "order_rejected", "order_id": order.id, "reason": str(exc)})

        # 바 요약 출력
        new_equity = self.portfolio.equity(marks)
        pos = self.portfolio.get_position(self.symbol)
        logger.info(
            "[{ts}] close={close:.2f} signal={sig:<4} pos={amt:.6f} equity={eq:.2f} cash={cash:.2f}",
            ts=bar.timestamp.isoformat(),
            close=bar.close,
            sig=signal.type.value,
            amt=pos.amount,
            eq=new_equity,
            cash=self.portfolio.cash,
        )
