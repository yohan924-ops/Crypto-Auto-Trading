"""Sleeve 기반 멀티 자산 백테스터.

기존 ``MultiAssetBacktester`` 는 공용 자본 풀 방식.
본 백테스터는 Sleeve 엔진 (각 자산 독립 자본 + 계좌 수준 CB) 을 백테스트.

Event merge 방식: 모든 심볼의 bar 를 timestamp 오름차순으로 통합 스트림.
각 이벤트마다:
  1) latest_prices 갱신
  2) SleeveOrchestrator.update_day (일자 전환)
  3) 해당 sleeve.process_bar_pipeline 호출
  4) SleeveOrchestrator.update_circuit_breaker (halt 여부 재평가)
  5) 총 자산 기록 (equity curve)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from loguru import logger

from tradingbot.broker.base import Fill
from tradingbot.data.feed import bar_from_row

from .backtester import _annualization_factor, _sharpe, _sortino, _win_rate
from .sleeve import Sleeve, SleeveOrchestrator


@dataclass
class SleeveItem:
    """SleeveBacktester 입력용 — SleeveSpec + 해당 자산의 OHLCV 데이터."""

    sleeve: Sleeve
    df: pd.DataFrame


@dataclass
class SleeveBacktestResult:
    start: datetime
    end: datetime
    timeframe: str
    starting_cash: float
    ending_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    sortino: float
    num_trades: int
    num_events: int
    win_rate_pct: float = 0.0
    per_sleeve: dict[str, dict] = field(default_factory=dict)
    equity_curve: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    trades: list[Fill] = field(repr=False, default_factory=list)
    circuit_breaker_events: int = 0

    def summary(self) -> str:
        lines = [
            "===== Sleeve 기반 백테스트 결과 =====",
            f"기간:        {self.start.isoformat()} ~ {self.end.isoformat()}",
            f"타임프레임:  {self.timeframe}",
            f"Sleeve 수:   {len(self.per_sleeve)}",
            f"시작 자금:   {self.starting_cash:,.2f}",
            f"최종 자산:   {self.ending_equity:,.2f}",
            f"총 수익률:   {self.total_return_pct:+.2f}%",
            f"최대 낙폭:   {self.max_drawdown_pct:.2f}%",
            f"Sharpe:      {self.sharpe:+.2f}  Sortino: {self.sortino:+.2f}",
            f"총 거래:     {self.num_trades}  (승률 {self.win_rate_pct:.1f}%)",
            f"계좌 CB 발동: {self.circuit_breaker_events}일",
            "-- Sleeve 별 요약 --",
        ]
        for name, s in self.per_sleeve.items():
            lines.append(
                f"  {name:<6} {s['symbol']:<10} alloc={s['allocation_pct']:.2f}  "
                f"trades={s['num_trades']}  strat={s['strategy_name']}  "
                f"ending={s['ending_equity']:,.2f}  ret={s['return_pct']:+.2f}%"
            )
        lines.append("=====================================")
        return "\n".join(lines)


class SleeveBacktester:
    def __init__(
        self,
        items: list[SleeveItem],
        timeframe: str,
        starting_cash: float,
        max_daily_loss_pct: float = 0.10,
    ) -> None:
        if not items:
            raise ValueError("최소 1개 SleeveItem 필요")
        self.items = items
        self.timeframe = timeframe
        self.starting_cash = starting_cash
        sleeves = [item.sleeve for item in items]
        self.orchestrator = SleeveOrchestrator(
            sleeves=sleeves,
            max_daily_loss_pct=max_daily_loss_pct,
        )

    def run(self) -> SleeveBacktestResult:
        # 모든 bar 를 timestamp 오름차순으로 통합
        events: list[tuple[pd.Timestamp, SleeveItem, pd.Series]] = []
        for item in self.items:
            if item.df.empty:
                continue
            for _, row in item.df.iterrows():
                events.append((row["timestamp"], item, row))
        events.sort(key=lambda e: e[0])
        if not events:
            raise ValueError("병합된 이벤트가 비어 있음")

        latest_prices: dict[str, float] = {}
        equity_rows: list[dict] = []
        trades: list[Fill] = []
        cb_days: set = set()

        for item in self.items:
            item.sleeve.strategy.on_start()

        try:
            for ts, item, row in events:
                bar = bar_from_row(row)
                latest_prices[item.sleeve.symbol] = bar.close

                # 1. 일자 전환 감지 (전체 계좌 기준 day_start_equity 설정)
                self.orchestrator.update_day(bar.timestamp, latest_prices)

                # 2. 해당 sleeve 의 파이프라인 실행
                outcome = item.sleeve.process_bar_pipeline(bar)
                if outcome.fill is not None:
                    trades.append(outcome.fill)

                # 3. 계좌 전체 CB 재평가
                self.orchestrator.update_circuit_breaker(latest_prices)
                if self.orchestrator.halted:
                    cb_days.add(ts.date())

                # 4. 총자산 스냅샷
                total_eq = self.orchestrator.total_equity(latest_prices)
                equity_rows.append(
                    {
                        "timestamp": ts,
                        "symbol": item.sleeve.symbol,
                        "close": bar.close,
                        "total_equity": total_eq,
                    }
                )
        finally:
            for item in self.items:
                try:
                    item.sleeve.strategy.on_stop()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("on_stop 실패 {}: {}", item.sleeve.name, exc)

        equity_curve = pd.DataFrame(equity_rows)
        ending_equity = (
            float(equity_curve["total_equity"].iloc[-1])
            if not equity_curve.empty
            else self.starting_cash
        )
        running_max = equity_curve["total_equity"].cummax()
        drawdown = (equity_curve["total_equity"] - running_max) / running_max * 100.0
        mdd = abs(float(drawdown.min())) if not drawdown.empty else 0.0

        bar_returns = (
            equity_curve["total_equity"].pct_change().dropna()
            if not equity_curve.empty
            else pd.Series(dtype=float)
        )
        ann = _annualization_factor(self.timeframe)

        per_sleeve: dict[str, dict] = {}
        for item in self.items:
            s = item.sleeve
            mark = latest_prices.get(s.symbol, 0.0)
            s_equity = s.equity(mark) if mark > 0 else s.cash()
            s_start = self.starting_cash * s.allocation_pct
            per_sleeve[s.name] = {
                "symbol": s.symbol,
                "allocation_pct": s.allocation_pct,
                "strategy_name": s.strategy.name,
                "num_trades": len(s.trades),
                "starting_cash": s_start,
                "ending_equity": s_equity,
                "return_pct": (s_equity / s_start - 1) * 100.0 if s_start > 0 else 0.0,
            }

        result = SleeveBacktestResult(
            start=events[0][0].to_pydatetime()
            if hasattr(events[0][0], "to_pydatetime")
            else events[0][0],
            end=events[-1][0].to_pydatetime()
            if hasattr(events[-1][0], "to_pydatetime")
            else events[-1][0],
            timeframe=self.timeframe,
            starting_cash=self.starting_cash,
            ending_equity=ending_equity,
            total_return_pct=(ending_equity / self.starting_cash - 1) * 100.0,
            max_drawdown_pct=mdd,
            sharpe=_sharpe(bar_returns, ann),
            sortino=_sortino(bar_returns, ann),
            num_trades=len(trades),
            num_events=len(events),
            win_rate_pct=_win_rate(trades),
            per_sleeve=per_sleeve,
            equity_curve=equity_curve,
            trades=trades,
            circuit_breaker_events=len(cb_days),
        )
        logger.info(
            "Sleeve 백테스트 완료: return={:+.2f}% trades={} sleeves={} cb_days={}",
            result.total_return_pct,
            result.num_trades,
            len(per_sleeve),
            result.circuit_breaker_events,
        )
        return result
