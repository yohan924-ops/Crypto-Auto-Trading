"""페이퍼/실전 실시간 실행 루프.

데이터 피드에서 Bar 를 받아 ``process_bar`` 로 파이프라인을 돌린다.
결과를 콘솔·로그 파일·JSONL 에 기록.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict

import pandas as pd
from loguru import logger

from tradingbot.broker.base import Broker
from tradingbot.logging_setup import log_order_event
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies.base import Bar, Strategy

from .core import HISTORY_COLUMNS, append_bar, process_bar


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
        history = pd.DataFrame(columns=HISTORY_COLUMNS)
        try:
            for bar in self.bar_stream:
                append_bar(history, bar)
                outcome = process_bar(
                    bar,
                    history,
                    symbol=self.symbol,
                    strategy=self.strategy,
                    broker=self.broker,
                    portfolio=self.portfolio,
                    risk=self.risk,
                )
                self._log_outcome(outcome)
        finally:
            self.strategy.on_stop()

    def _log_outcome(self, outcome) -> None:
        bar = outcome.bar
        signal = outcome.signal
        signal_label = signal.type.value if signal else "warmup"

        if signal is not None:
            log_order_event({"event": "signal", **asdict(signal)})
        if outcome.order is not None:
            log_order_event({"event": "order_submitted", **asdict(outcome.order)})
        if outcome.fill is not None:
            log_order_event({"event": "order_filled", **asdict(outcome.fill)})
        if outcome.rejected_reason is not None:
            logger.exception("주문 체결 실패: {}", outcome.rejected_reason)
            log_order_event(
                {
                    "event": "order_rejected",
                    "order_id": outcome.order.id if outcome.order else None,
                    "reason": outcome.rejected_reason,
                }
            )

        logger.info(
            "[{ts}] close={close:.2f} signal={sig:<6} pos={amt:.6f} equity={eq:.2f} cash={cash:.2f}",
            ts=bar.timestamp.isoformat(),
            close=bar.close,
            sig=signal_label,
            amt=outcome.position_amount_after,
            eq=outcome.equity_after,
            cash=outcome.cash_after,
        )
