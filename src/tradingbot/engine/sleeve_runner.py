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

# ---------- 통화 표시 헬퍼 ----------

_CURRENCY_SYMBOLS = {
    "USDT": "$",
    "USDC": "$",
    "USD": "$",
    "KRW": "₩",
    "EUR": "€",
    "JPY": "¥",
}


def _currency_symbol(symbol: str) -> str:
    """'BTC/USDT' → '$', 'BTC/KRW' → '₩'. 미지 quote 는 '<code> '."""
    quote = symbol.split("/")[-1] if "/" in symbol else symbol
    return _CURRENCY_SYMBOLS.get(quote, quote + " ")


def _fmt_money(value: float, symbol: str) -> str:
    """통화 기호 + 천단위 콤마 포맷. KRW 는 소수점 없음."""
    sym = _currency_symbol(symbol)
    quote = symbol.split("/")[-1] if "/" in symbol else symbol
    if quote == "KRW":
        return f"{sym}{value:,.0f}"
    return f"{sym}{value:,.2f}"


def _fmt_pct(value: float) -> str:
    """+/- 붙은 퍼센트 포맷."""
    return f"{value:+.2f}%"


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
                action = "매수" if signal.type == SignalType.BUY else "매도"
                self._notify(
                    NotifyEvent.SIGNAL,
                    f"🎯 {action} 신호\n"
                    f"{sleeve.name} {_fmt_money(signal.price, sleeve.symbol)}\n"
                    f"사유: {signal.reason or '-'}",
                )

        if outcome.order is not None:
            log_order_event(
                {"event": "order_submitted", "sleeve": sleeve.name, **asdict(outcome.order)}
            )

        if outcome.stop_loss_triggered:
            # 손실률 계산: (현재가 - 평단가) / 평단가
            pos = sleeve.portfolio.get_position(sleeve.symbol)
            loss_pct = 0.0
            if pos.avg_price > 0:
                loss_pct = (outcome.bar.close - pos.avg_price) / pos.avg_price * 100
            self._notify(
                NotifyEvent.STOP_LOSS,
                f"🛑 손절 발동\n"
                f"{sleeve.name} {_fmt_money(outcome.bar.close, sleeve.symbol)} "
                f"({_fmt_pct(loss_pct)})",
            )

        if outcome.circuit_breaker_triggered:
            self._notify(
                NotifyEvent.CIRCUIT_BREAKER,
                f"🚨 {sleeve.name} 개별 중지\n신규 진입 차단",
            )
        if self.orchestrator.halted:
            self._notify(
                NotifyEvent.CIRCUIT_BREAKER,
                "🚨 계좌 전체 서킷브레이커 발동\n일일 손실 한도 도달 — 모든 매매 중단",
            )

        if outcome.fill is not None:
            log_order_event(
                {"event": "order_filled", "sleeve": sleeve.name, **asdict(outcome.fill)}
            )
            if self._daily is not None:
                self._daily.num_fills += 1

            fill = outcome.fill
            pos = sleeve.portfolio.get_position(sleeve.symbol)
            action = "매수" if fill.side.value == "buy" else "매도"
            notional = fill.amount * fill.price

            lines = [
                f"✅ {action} 체결",
                f"{sleeve.name} {fill.amount:.6f}개 "
                f"@ {_fmt_money(fill.price, sleeve.symbol)}",
                f"거래금: {_fmt_money(notional, sleeve.symbol)} "
                f"(수수료 {_fmt_money(fill.fee, sleeve.symbol)})",
            ]
            # 체결 후 평단가 (수수료 포함) 표시
            if pos.amount > 0 and pos.avg_price > 0:
                lines.append(
                    f"보유: {pos.amount:.6f}개 · 평단가 "
                    f"{_fmt_money(pos.avg_price, sleeve.symbol)}"
                )
            else:
                lines.append(f"현금: {_fmt_money(sleeve.cash(), sleeve.symbol)}")
            self._notify(NotifyEvent.ORDER_FILLED, "\n".join(lines))

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
                f"⚠️ {sleeve.name} 주문 거부\n{outcome.rejected_reason}",
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
            delta_abs = current_equity - prev_equity
            # 대표 통화 (첫 sleeve 기준)
            repr_symbol = self.orchestrator.sleeves[0].symbol
            self._notify(
                NotifyEvent.DAILY_REPORT,
                f"📊 {self._daily.day} 일일 결산\n"
                f"매매 {self._daily.num_fills}건 · "
                f"손익 {_fmt_money(delta_abs, repr_symbol)} "
                f"({_fmt_pct(delta_pct)})\n"
                f"총자산 {_fmt_money(current_equity, repr_symbol)}",
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

        # 계좌 총자산 + 초기 자본 대비 수익률
        total_eq = self.orchestrator.total_equity(self._latest_prices)
        total_initial = sum(s.initial_cash for s in self.orchestrator.sleeves)
        total_pnl_pct = (
            (total_eq - total_initial) / total_initial * 100.0 if total_initial > 0 else 0.0
        )
        repr_symbol = self.orchestrator.sleeves[0].symbol
        halt_tag = " [긴급정지]" if self.orchestrator.halted else ""

        lines = [
            f"💓 봇 상태 ({now.strftime('%m/%d %H:%M UTC')}){halt_tag}",
            f"총자산: {_fmt_money(total_eq, repr_symbol)} "
            f"({_fmt_pct(total_pnl_pct)})",
            "",
        ]
        # 각 sleeve 상세
        for s in self.orchestrator.sleeves:
            mark = self._latest_prices.get(s.symbol, 0.0)
            eq = s.equity(mark) if mark > 0 else s.cash()
            s_pnl_pct = (
                (eq - s.initial_cash) / s.initial_cash * 100.0
                if s.initial_cash > 0
                else 0.0
            )
            pos_amount = s.position_amount()
            pos_line = ""
            if pos_amount > 0:
                avg = s.portfolio.get_position(s.symbol).avg_price
                # 현재가 대비 평단 손익
                pos_pnl_pct = (
                    (mark - avg) / avg * 100.0 if avg > 0 and mark > 0 else 0.0
                )
                pos_line = (
                    f"  보유: {pos_amount:.6f}개 · "
                    f"평단 {_fmt_money(avg, s.symbol)} "
                    f"({_fmt_pct(pos_pnl_pct)})"
                )
            else:
                pos_line = "  보유: 없음 (현금 대기)"

            lines.append(
                f"[{s.name}] {_fmt_money(eq, s.symbol)} ({_fmt_pct(s_pnl_pct)})"
            )
            if mark > 0:
                lines.append(f"  현재가: {_fmt_money(mark, s.symbol)}")
            lines.append(pos_line)

            # 전략 간단 요약
            try:
                strat_status = s.strategy.status_snapshot(s.history)
            except Exception as exc:  # noqa: BLE001
                strat_status = f"상태 스냅샷 실패: {type(exc).__name__}"
            lines.append(f"  상태: {strat_status}")
            lines.append("")

        self._notify(NotifyEvent.HEARTBEAT, "\n".join(lines).rstrip())
