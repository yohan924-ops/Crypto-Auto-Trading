"""Sleeve 기반 실시간 운용 Runner.

기존 ``Runner`` (단일 자산) 를 확장한 멀티 sleeve 실시간 엔진.
``MultiSymbolFeed`` 로부터 (symbol, Bar) 튜플을 받아 해당 sleeve 에 라우팅.

주요 책임:
  - bar 를 올바른 Sleeve 로 라우팅
  - 각 Sleeve 의 process_bar_pipeline 호출
  - SleeveOrchestrator.update_day / update_circuit_breaker 관리
  - notifier 이벤트 발행 (매수·매도·손절·일일 리포트·heartbeat)
  - 심볼별 전략 상태 영속화 (save_state)

Gemini 요구사항 반영:
  - 자본 격리 (Virtual Ledger): Sleeve.Portfolio 가 이미 독립. assertion 으로 보강.
  - 주문 순차 실행: 단일 스레드 이벤트 루프라 자연스럽게 sequential.
    별도 OrderQueueManager 미구현 — 4h 타임프레임 + 매매 드물어 rate limit 비필수.
  - 상태 동기화: PaperBroker 는 전량 체결만. LiveBroker 는 Portfolio.apply_fill 이
    이미 부분 체결 방어 로직 있음 (오버셀 감지).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime

from loguru import logger

from tradingbot.logging_setup import log_order_event
from tradingbot.notifier.base import Notifier, NotifyEvent
from tradingbot.strategies.base import Bar, SignalType

from .core import BarOutcome
from .sleeve import Sleeve, SleeveOrchestrator


@dataclass
class _DailyStats:
    day: date
    start_equity: float
    num_fills: int = 0


class SleeveRunner:
    def __init__(
        self,
        orchestrator: SleeveOrchestrator,
        bar_stream: Iterator[tuple[str, Bar]],
        notifiers: list[Notifier] | None = None,
        heartbeat_enabled: bool = False,
        heartbeat_hours_utc: list[int] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.bar_stream = bar_stream
        self.notifiers = notifiers or []
        self.heartbeat_enabled = heartbeat_enabled
        self.heartbeat_hours_utc = sorted(set(heartbeat_hours_utc or [0, 12]))
        self._last_heartbeat_key: tuple[date, int] | None = None
        self._daily: _DailyStats | None = None
        self._latest_prices: dict[str, float] = {}

    def run(self) -> None:
        for sleeve in self.orchestrator.sleeves:
            sleeve.strategy.on_start()
        try:
            for symbol, bar in self.bar_stream:
                sleeve = self.orchestrator.find_sleeve(symbol)
                if sleeve is None:
                    logger.warning("알 수 없는 심볼 {} — bar 건너뜀", symbol)
                    continue
                self._process_bar(sleeve, bar)
                # 매 bar 처리 후 전략 상태 영속화
                try:
                    sleeve.strategy.save_state()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("{} 상태 저장 실패: {}", sleeve.name, exc)
        finally:
            for sleeve in self.orchestrator.sleeves:
                try:
                    sleeve.strategy.save_state()
                    sleeve.strategy.on_stop()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("{} 종료 처리 실패: {}", sleeve.name, exc)

    def _process_bar(self, sleeve: Sleeve, bar: Bar) -> None:
        """단일 bar 를 해당 Sleeve 파이프라인에 통과시키고 이벤트 전파."""
        self._latest_prices[sleeve.symbol] = bar.close

        # 1. 일자 전환 감지 (orchestrator) — day_start_equity 재설정
        rolled = self.orchestrator.update_day(bar.timestamp, self._latest_prices)
        if rolled:
            self._emit_daily_report(bar.timestamp)

        # 2. Sleeve 의 파이프라인 실행 (process_bar → 손절/서킷 체크 → 주문)
        outcome = sleeve.process_bar_pipeline(bar)

        # 3. 계좌 전체 CB 재평가
        self.orchestrator.update_circuit_breaker(self._latest_prices)

        # 4. 이벤트 전파
        self._handle_outcome(sleeve, outcome)
        self._log_bar(sleeve, outcome)

        # 5. Heartbeat
        self._maybe_send_heartbeat(sleeve, outcome)

        # 6. Virtual Ledger assertion (Gemini 요구사항)
        # 각 sleeve 의 cash 와 포지션은 독립. 계좌 총자산이 음수 아닌지 sanity check.
        total = self.orchestrator.total_equity(self._latest_prices)
        assert total > 0, f"총자산 음수 이상 상태: {total}"

    # ----- 이벤트 처리 (Runner 와 동일 구조) -----
    def _notify(self, event: NotifyEvent, message: str, **context) -> None:
        for n in self.notifiers:
            try:
                n.notify(event, message, **context)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Notifier {} 실패: {}", n.name, exc)

    def _handle_outcome(self, sleeve: Sleeve, outcome: BarOutcome) -> None:
        signal = outcome.signal
        if signal is not None:
            log_order_event({"event": "signal", "sleeve": sleeve.name, **asdict(signal)})
            if signal.type != SignalType.HOLD:
                self._notify(
                    NotifyEvent.SIGNAL,
                    f"[{sleeve.name}] {signal.type.value.upper()} "
                    f"{signal.symbol} @ {signal.price:.2f} — "
                    f"{signal.reason or ''}".strip(),
                )

        if outcome.order is not None:
            log_order_event(
                {"event": "order_submitted", "sleeve": sleeve.name, **asdict(outcome.order)}
            )

        if outcome.stop_loss_triggered:
            self._notify(
                NotifyEvent.STOP_LOSS,
                f"[{sleeve.name}] 손절 발동 {sleeve.symbol} @ {outcome.bar.close:.2f}",
            )

        if outcome.circuit_breaker_triggered:
            self._notify(
                NotifyEvent.CIRCUIT_BREAKER,
                f"[{sleeve.name}] 개별 sleeve halt — 신규 진입 차단",
            )
        if self.orchestrator.halted:
            self._notify(
                NotifyEvent.CIRCUIT_BREAKER,
                "계좌 전체 서킷브레이커 — 모든 sleeve halt",
            )

        if outcome.fill is not None:
            log_order_event(
                {"event": "order_filled", "sleeve": sleeve.name, **asdict(outcome.fill)}
            )
            if self._daily is not None:
                self._daily.num_fills += 1
            self._notify(
                NotifyEvent.ORDER_FILLED,
                f"[{sleeve.name}] {outcome.fill.side.value.upper()} "
                f"{outcome.fill.amount:.6f} {outcome.fill.symbol} "
                f"@ {outcome.fill.price:.2f} (fee {outcome.fill.fee:.4f})",
            )

        if outcome.rejected_reason is not None:
            logger.exception("[{}] 주문 실패: {}", sleeve.name, outcome.rejected_reason)
            log_order_event(
                {
                    "event": "order_rejected",
                    "sleeve": sleeve.name,
                    "reason": outcome.rejected_reason,
                }
            )
            self._notify(
                NotifyEvent.ORDER_REJECTED,
                f"[{sleeve.name}] {outcome.rejected_reason}",
            )

    def _emit_daily_report(self, ts: datetime) -> None:
        if self._daily is not None:
            prev_equity = self._daily.start_equity
            current_equity = self.orchestrator.total_equity(self._latest_prices)
            delta_pct = (
                (current_equity - prev_equity) / prev_equity * 100.0
                if prev_equity
                else 0.0
            )
            self._notify(
                NotifyEvent.DAILY_REPORT,
                f"{self._daily.day} 일일 리포트 — 거래 {self._daily.num_fills}건, "
                f"손익 {delta_pct:+.2f}%, 종가기준 자산 {current_equity:,.2f}",
            )
        self._daily = _DailyStats(
            day=ts.date(),
            start_equity=self.orchestrator.total_equity(self._latest_prices),
        )

    def _log_bar(self, sleeve: Sleeve, outcome: BarOutcome) -> None:
        bar = outcome.bar
        signal = outcome.signal
        tag = signal.type.value if signal else "warmup"
        if outcome.stop_loss_triggered:
            tag = "SL"
        elif outcome.circuit_breaker_triggered:
            tag = "HALT"
        logger.info(
            "[{name}] [{ts}] close={close:.2f} sig={sig:<6} "
            "pos={amt:.6f} eq={eq:.2f} cash={cash:.2f}",
            name=sleeve.name,
            ts=bar.timestamp.isoformat(),
            close=bar.close,
            sig=tag,
            amt=outcome.position_amount_after,
            eq=outcome.equity_after,
            cash=outcome.cash_after,
        )

    def _maybe_send_heartbeat(self, sleeve: Sleeve, outcome: BarOutcome) -> None:
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

        # 각 sleeve 의 상태 요약
        lines = [f"{now.strftime('%Y-%m-%d %H:%M UTC')} Sleeve Heartbeat"]
        total = self.orchestrator.total_equity(self._latest_prices)
        halt_tag = " [HALTED]" if self.orchestrator.halted else ""
        lines.append(f"계좌 총자산: {total:,.2f}{halt_tag}")
        for s in self.orchestrator.sleeves:
            mark = self._latest_prices.get(s.symbol, 0.0)
            eq = s.equity(mark) if mark > 0 else s.cash()
            pos = s.position_amount()
            pos_tag = f"{pos:.6f} @ {s.portfolio.get_position(s.symbol).avg_price:.2f}" if pos > 0 else "현금"
            try:
                strat_status = s.strategy.status_snapshot(s.history)
            except Exception as exc:  # noqa: BLE001
                strat_status = f"status_snapshot 실패: {type(exc).__name__}"
            lines.append(f"  [{s.name}] eq={eq:,.2f} pos={pos_tag}")
            lines.append(f"    {strat_status}")
        self._notify(NotifyEvent.HEARTBEAT, "\n".join(lines))
