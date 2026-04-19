"""페이퍼/실전 실시간 실행 루프.

데이터 피드에서 Bar 를 받아 ``process_bar`` 파이프라인에 통과시키고,
결과를 콘솔·파일 로그·JSONL·Notifier 로 전파한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime

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
        heartbeat_enabled: bool = False,
        heartbeat_hours_utc: list[int] | None = None,
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
        self.heartbeat_enabled = heartbeat_enabled
        self.heartbeat_hours_utc = sorted(set(heartbeat_hours_utc or [0, 12]))
        # 마지막으로 heartbeat 를 발송한 (date, hour) 기록. 같은 시간 중복 발송 방지.
        self._last_heartbeat_key: tuple[date, int] | None = None

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
                self._maybe_send_heartbeat(history, outcome)
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

    # ----- Heartbeat (정기 상태 보고) -----
    def _maybe_send_heartbeat(self, history: pd.DataFrame, outcome: BarOutcome) -> None:
        """현재 시각이 지정된 heartbeat UTC 시각을 넘겼으면 1회 상태 보고.

        - 실제 '지금' 시각 (datetime.now(UTC)) 기준으로 판단. 백테스트에서는
          heartbeat_enabled 가 False 로 주입되므로 영향 없음.
        - (date, hour) 키로 중복 방지.
        """
        if not self.heartbeat_enabled or not self.heartbeat_hours_utc:
            return
        now = datetime.now(UTC)
        current_hour = now.hour
        if current_hour not in self.heartbeat_hours_utc:
            return
        key = (now.date(), current_hour)
        if self._last_heartbeat_key == key:
            return
        self._last_heartbeat_key = key

        try:
            strategy_status = self.strategy.status_snapshot(history)
        except Exception as exc:  # noqa: BLE001
            strategy_status = f"상태 스냅샷 실패: {type(exc).__name__}"

        pos = self.portfolio.get_position(self.symbol)
        pos_line = (
            f"{pos.amount:.6f} @ 평단 {pos.avg_price:.2f}"
            if pos.amount > 0
            else "0 (현금 100%)"
        )
        daily_pnl = self.risk.daily_pnl_pct(outcome.equity_after)
        halt_tag = " [HALTED]" if self.risk.halted else ""

        message = (
            f"{now.strftime('%Y-%m-%d %H:%M UTC')} | "
            f"자산 {outcome.equity_after:,.2f} | "
            f"일손익 {daily_pnl:+.2f}%{halt_tag} | "
            f"포지션 {pos_line}\n"
            f"{strategy_status}"
        )
        self._notify(NotifyEvent.HEARTBEAT, message)

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
