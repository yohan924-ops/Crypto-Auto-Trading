"""페이퍼/실전 실시간 실행 루프.

데이터 피드에서 Bar 를 받아 ``process_bar`` 파이프라인에 통과시키고,
결과를 콘솔·파일 로그·JSONL·Notifier 로 전파한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import date

import pandas as pd
from loguru import logger

from tradingbot.broker.base import Broker
from tradingbot.logging_setup import log_order_event
from tradingbot.notifier.base import Notifier, NotifyEvent
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies.base import Bar, SignalType, Strategy

from .core import HISTORY_COLUMNS, BarOutcome, append_bar, process_bar


@dataclass
class _DailyStats:
    day: date
    start_equity: float
    num_fills: int = 0
    realized_trades: list[str] = field(default_factory=list)


class Runner:
    def __init__(
        self,
        symbol: str,
        strategy: Strategy,
        broker: Broker,
        portfolio: Portfolio,
        risk: RiskManager,
        bar_stream: Iterator[Bar],
        notifiers: list[Notifier] | None = None,
        dry_run: bool = False,
    ) -> None:
        self.symbol = symbol
        self.strategy = strategy
        self.broker = broker
        self.portfolio = portfolio
        self.risk = risk
        self.bar_stream = bar_stream
        self.notifiers = notifiers or []
        self.dry_run = dry_run
        self._daily: _DailyStats | None = None

    def run(self) -> None:
        self.strategy.on_start()
        history = pd.DataFrame(columns=HISTORY_COLUMNS)
        if self.dry_run:
            logger.warning("DRY-RUN 모드: 실제 주문은 제출되지 않고 결정만 로그됨")
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
                    dry_run=self.dry_run,
                )
                self._handle_day_rollover(outcome)
                self._handle_outcome(outcome)
                self._log_bar(outcome)
                # 매 봉 처리가 끝날 때마다 전략 내부 상태(예: _ready 플래그) 영속화
                self.strategy.save_state()
        finally:
            # 종료 시에도 최신 상태를 한 번 더 저장 (중간 상태 보존)
            try:
                self.strategy.save_state()
            except Exception as exc:  # noqa: BLE001
                logger.warning("종료 시 전략 상태 저장 실패: {}", exc)
            self.strategy.on_stop()

    # ----- 알림 전송 -----
    def _notify(self, event: NotifyEvent, message: str, **context) -> None:
        for n in self.notifiers:
            try:
                n.notify(event, message, **context)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Notifier {} 실패: {}", n.name, exc)

    # ----- 일별 리포트 관리 -----
    def _handle_day_rollover(self, outcome: BarOutcome) -> None:
        if outcome.day_rolled_over:
            if self._daily is not None:
                delta_pct = (
                    (outcome.equity_after - self._daily.start_equity)
                    / self._daily.start_equity
                    * 100.0
                    if self._daily.start_equity
                    else 0.0
                )
                self._notify(
                    NotifyEvent.DAILY_REPORT,
                    (
                        f"{self._daily.day} 일일 리포트 — 거래 {self._daily.num_fills}건, "
                        f"손익 {delta_pct:+.2f}%, 종가기준 자산 {outcome.equity_after:,.2f}"
                    ),
                )
            # 새 날 시작
            self._daily = _DailyStats(
                day=outcome.bar.timestamp.date(),
                start_equity=outcome.equity_after,
            )
        elif self._daily is None:
            # 첫 봉
            self._daily = _DailyStats(
                day=outcome.bar.timestamp.date(),
                start_equity=outcome.equity_after,
            )

    # ----- 이벤트별 알림/JSONL -----
    def _handle_outcome(self, outcome: BarOutcome) -> None:
        signal = outcome.signal
        if signal is not None:
            log_order_event({"event": "signal", **asdict(signal)})
            if signal.type != SignalType.HOLD:
                self._notify(
                    NotifyEvent.SIGNAL,
                    f"{signal.type.value.upper()} {signal.symbol} @ {signal.price:.2f} — {signal.reason or ''}".strip(),
                )

        if outcome.order is not None:
            log_order_event({"event": "order_submitted", **asdict(outcome.order)})

        if outcome.stop_loss_triggered:
            self._notify(
                NotifyEvent.STOP_LOSS,
                f"손절 발동 {self.symbol} @ {outcome.bar.close:.2f}",
            )

        if outcome.circuit_breaker_triggered:
            self._notify(
                NotifyEvent.CIRCUIT_BREAKER,
                f"일일 손실 한도 도달 — {self.symbol} 신규 진입 차단",
            )

        if outcome.fill is not None:
            log_order_event({"event": "order_filled", **asdict(outcome.fill)})
            if self._daily is not None:
                self._daily.num_fills += 1
            self._notify(
                NotifyEvent.ORDER_FILLED,
                (
                    f"{outcome.fill.side.value.upper()} {outcome.fill.amount:.6f} "
                    f"{outcome.fill.symbol} @ {outcome.fill.price:.2f} "
                    f"(fee {outcome.fill.fee:.4f})"
                ),
            )

        if outcome.rejected_reason is not None:
            logger.exception("주문 실패: {}", outcome.rejected_reason)
            log_order_event(
                {
                    "event": "order_rejected",
                    "order_id": outcome.order.id if outcome.order else None,
                    "reason": outcome.rejected_reason,
                }
            )
            self._notify(NotifyEvent.ORDER_REJECTED, outcome.rejected_reason)

    # ----- 바 한 줄 요약 -----
    def _log_bar(self, outcome: BarOutcome) -> None:
        bar = outcome.bar
        signal = outcome.signal
        tag = signal.type.value if signal else "warmup"
        if outcome.stop_loss_triggered:
            tag = "SL"
        elif outcome.circuit_breaker_triggered:
            tag = "HALT"
        logger.info(
            "[{ts}] close={close:.2f} sig={sig:<6} pos={amt:.6f} eq={eq:.2f} cash={cash:.2f}",
            ts=bar.timestamp.isoformat(),
            close=bar.close,
            sig=tag,
            amt=outcome.position_amount_after,
            eq=outcome.equity_after,
            cash=outcome.cash_after,
        )
