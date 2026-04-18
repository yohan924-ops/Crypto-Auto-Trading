"""엔진 공통 로직: 단일 바를 처리하는 파이프라인 함수.

Runner(실시간)와 Backtester(과거 리플레이)가 동일한 처리 로직을 공유.
로깅·메트릭은 각자 호출측에서 처리.

처리 순서 (중요):
  1. 새 봉을 history 에 추가
  2. RiskManager.update_day 로 일자 전환 감지
  3. 보유 포지션이 있으면 손절 여부 체크 → 트리거 시 SELL 강제
  4. 순환 차단(서킷브레이커)이 켜져 있으면 신규 진입 차단
  5. 그 외엔 전략의 on_bar → RiskManager.size_order → Broker.submit
  6. 체결 후 잔고/자산 갱신 및 서킷브레이커 재평가
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
    stop_loss_triggered: bool = False
    circuit_breaker_triggered: bool = False
    day_rolled_over: bool = False
    dry_run: bool = False


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


def _snapshot(bar, signal, order, fill, portfolio, symbol, marks, **flags) -> BarOutcome:
    pos_amount = portfolio.get_position(symbol).amount
    equity = portfolio.equity(marks) if portfolio.positions else portfolio.cash
    return BarOutcome(
        bar=bar,
        signal=signal,
        fill=fill,
        order=order,
        equity_after=equity,
        cash_after=portfolio.cash,
        position_amount_after=pos_amount,
        **flags,
    )


def _make_order(
    symbol: str, side: OrderSide, amount: float, created_at
) -> Order:
    return Order(
        id=new_order_id(),
        symbol=symbol,
        side=side,
        type=OrderType.MARKET,
        amount=amount,
        created_at=created_at,
    )


def _execute(
    order: Order, bar: Bar, broker: Broker, portfolio: Portfolio, dry_run: bool
) -> tuple[Fill | None, str | None]:
    if dry_run:
        return None, None
    try:
        fill = broker.submit(order, mark_price=bar.close)
        portfolio.apply_fill(fill)
        return fill, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def process_bar(
    bar: Bar,
    history: pd.DataFrame,
    *,
    symbol: str,
    strategy: Strategy,
    broker: Broker,
    portfolio: Portfolio,
    risk: RiskManager,
    dry_run: bool = False,
    weight: float = 1.0,
    extra_marks: dict[str, float] | None = None,
) -> BarOutcome:
    """새 바 하나를 파이프라인에 통과시키고 결과 스냅샷 반환.

    ``history`` 는 호출 전 현재 바가 이미 포함되어 있어야 함.
    ``extra_marks`` 는 멀티 자산 모드에서 다른 심볼들의 최근 종가 (equity 계산용).
    """
    marks: dict[str, float] = dict(extra_marks or {})
    marks[symbol] = bar.close

    # 1) 일자 전환 감지 (해당 시점 자산 기준으로 day-start equity 기록)
    current_equity = portfolio.equity(marks) if portfolio.positions else portfolio.cash
    day_rolled = risk.update_day(bar.timestamp, current_equity)

    # 2) 워밍업 미완: 포지션 관리만, 신호 생성 X
    if len(history) < strategy.warmup_bars():
        return _snapshot(bar, None, None, None, portfolio, symbol, marks, day_rolled_over=day_rolled)

    # 3) 손절 체크 (포지션 있을 때만). 봉 내 저가 터치 포함.
    position = portfolio.get_position(symbol)
    if risk.check_stop_loss(position, bar.close, low_price=bar.low):
        forced_signal = Signal(
            type=SignalType.SELL,
            symbol=symbol,
            timestamp=bar.timestamp,
            price=bar.close,
            reason=f"손절 트리거 (avg={position.avg_price:.2f}, -{risk.stop_loss_pct * 100:.1f}%)",
        )
        order = _make_order(symbol, OrderSide.SELL, position.amount, bar.timestamp)
        fill, rejected = _execute(order, bar, broker, portfolio, dry_run)
        risk.update_circuit_breaker(portfolio.equity(marks))
        return _snapshot(
            bar,
            forced_signal,
            order,
            fill,
            portfolio,
            symbol,
            marks,
            rejected_reason=rejected,
            stop_loss_triggered=True,
            day_rolled_over=day_rolled,
            dry_run=dry_run,
        )

    # 4) 서킷브레이커: 켜져 있으면 신규 진입 차단 (SELL 만 허용)
    signal = strategy.on_bar(bar, history)
    if risk.halted and signal.type == SignalType.BUY:
        return _snapshot(
            bar,
            signal,
            None,
            None,
            portfolio,
            symbol,
            marks,
            circuit_breaker_triggered=True,
            day_rolled_over=day_rolled,
        )

    # 5) 정상 신호 처리
    position_amount = portfolio.get_position(symbol).amount
    amount = risk.size_order(
        signal=signal,
        equity=current_equity,
        price=bar.close,
        position_amount=position_amount,
        weight=weight,
    )

    order: Order | None = None
    fill: Fill | None = None
    rejected: str | None = None
    if amount > 0 and signal.type in (SignalType.BUY, SignalType.SELL):
        side = OrderSide.BUY if signal.type == SignalType.BUY else OrderSide.SELL
        order = _make_order(symbol, side, amount, bar.timestamp)
        fill, rejected = _execute(order, bar, broker, portfolio, dry_run)

    # 6) 서킷브레이커 재평가
    risk.update_circuit_breaker(portfolio.equity(marks))

    return _snapshot(
        bar,
        signal,
        order,
        fill,
        portfolio,
        symbol,
        marks,
        rejected_reason=rejected,
        day_rolled_over=day_rolled,
        dry_run=dry_run,
    )
