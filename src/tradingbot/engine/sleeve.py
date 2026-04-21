"""Sleeve 기반 멀티 자산 운용 엔진.

기존 ``MultiAssetBacktester`` 와 달리:
  - 각 자산(Sleeve)이 **완전 독립 자본** 보유. 공용 풀 없음.
  - 자산별 독립 Portfolio + RiskManager + Strategy.
  - 계좌 전체 수준 서킷브레이커 (일일 손실 -pct% 도달 시 모든 Sleeve BUY 차단).
  - 자산별 max_daily_loss 개별 서킷 브레이커는 비활성 (orchestrator 가 전담).

설계 이유 (2026-04-19 Gemini + Claude 합의):
  1. ETH sleeve 손실이 BTC sleeve 자본을 침식하지 않게 (sleeve 격리)
  2. 생존자 편향이 의심되는 SOL 에 자본 집중할 때 전체 계좌 방어선 유지
  3. 전략별 엣지 훼손 없이 단순 자본 배분으로 알파 극대화
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
from loguru import logger

from tradingbot.broker.base import Broker, Fill
from tradingbot.broker.paper import PaperBroker
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies.base import Bar, Strategy

from .core import HISTORY_COLUMNS, BarOutcome, append_bar, process_bar


@dataclass
class Sleeve:
    """단일 자산의 독립 자본 컨테이너.

    각 필드는 해당 자산만의 상태. 다른 Sleeve 와 자본·포지션·전략 상태 공유 X.
    """

    name: str  # 표시용 이름 (예: "BTC")
    symbol: str  # 실제 거래 심볼 (예: "BTC/USDT")
    strategy: Strategy
    portfolio: Portfolio
    risk: RiskManager
    broker: Broker
    allocation_pct: float  # 0.0 ~ 1.0, 전체 자본 중 배분 비율 (기록 목적)
    initial_cash: float = 0.0  # 수익률 계산용 시작 자본 (build_sleeves 에서 설정)
    history: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=HISTORY_COLUMNS)
    )
    trades: list[Fill] = field(default_factory=list, repr=False)

    def cash(self) -> float:
        return self.portfolio.cash

    def position_amount(self) -> float:
        return self.portfolio.get_position(self.symbol).amount

    def equity(self, mark_price: float) -> float:
        """현 시점 sleeve 평가액 (현금 + 포지션 × mark)."""
        if self.portfolio.get_position(self.symbol).amount > 0:
            return self.portfolio.equity({self.symbol: mark_price})
        return self.portfolio.cash

    def process_bar_pipeline(self, bar: Bar, dry_run: bool = False) -> BarOutcome:
        """이 Sleeve 의 파이프라인에 bar 를 통과시킨다.

        ``core.process_bar`` 에 자기 자산의 state 를 주입하여 호출.
        결과 fill 은 self.trades 에 누적.
        """
        append_bar(self.history, bar)
        outcome = process_bar(
            bar,
            self.history,
            symbol=self.symbol,
            strategy=self.strategy,
            broker=self.broker,
            portfolio=self.portfolio,
            risk=self.risk,
            dry_run=dry_run,
        )
        if outcome.fill is not None:
            self.trades.append(outcome.fill)
        return outcome


@dataclass
class SleeveSpec:
    """Sleeve 구성용 스펙 (Orchestrator/Backtester 생성 시 입력)."""

    name: str
    symbol: str
    strategy: Strategy
    allocation_pct: float
    risk: RiskManager


class SleeveOrchestrator:
    """여러 Sleeve 를 감독하는 마스터 컨트롤러.

    책임:
      - 각 Sleeve 의 시가 평가 합산 (total_equity)
      - 계좌 전체 일일 손실 서킷브레이커 — 한계 도달 시 모든 Sleeve halt
      - Sleeve 찾기 (symbol 로 라우팅)
      - 일자 전환 시 day_start_equity 갱신

    설계 원칙:
      - orchestrator 는 "전체 계좌 방어선" 역할만. 개별 sleeve 내부 손절/트레일링은
        각 RiskManager 에 위임.
      - halt 발동 시 sleeve 의 risk._halted 플래그 조작으로 BUY 차단 (기존
        ``process_bar`` 가 이미 risk.halted 를 검사함).
    """

    def __init__(
        self,
        sleeves: list[Sleeve],
        max_daily_loss_pct: float = 0.10,
    ) -> None:
        if not sleeves:
            raise ValueError("최소 1개 Sleeve 필요")
        if not 0 < max_daily_loss_pct <= 1.0:
            raise ValueError(
                f"max_daily_loss_pct 는 0~1 범위: {max_daily_loss_pct}"
            )
        self.sleeves = sleeves
        self.max_daily_loss_pct = max_daily_loss_pct
        # 상태
        self._current_day: date | None = None
        self._day_start_equity: float | None = None
        self._halted: bool = False

    @property
    def halted(self) -> bool:
        return self._halted

    def find_sleeve(self, symbol: str) -> Sleeve | None:
        for s in self.sleeves:
            if s.symbol == symbol:
                return s
        return None

    def total_equity(self, latest_prices: dict[str, float]) -> float:
        total = 0.0
        for sleeve in self.sleeves:
            mark = latest_prices.get(sleeve.symbol)
            if mark is None or mark <= 0:
                total += sleeve.cash()
            else:
                total += sleeve.equity(mark)
        return total

    def update_day(self, ts: datetime, latest_prices: dict[str, float]) -> bool:
        today = ts.date()
        if self._current_day == today:
            return False
        self._current_day = today
        self._day_start_equity = self.total_equity(latest_prices)
        # 새 날: halt 해제 + 모든 sleeve 의 halt 도 해제
        self._halted = False
        for sleeve in self.sleeves:
            sleeve.risk._halted = False
        logger.debug(
            "SleeveOrchestrator 새 날 시작: {}, day_start_equity={:.2f}",
            today,
            self._day_start_equity,
        )
        return True

    def update_circuit_breaker(self, latest_prices: dict[str, float]) -> None:
        """계좌 전체 일일 손실 체크. 한계 도달 시 halt 발동."""
        if self._day_start_equity is None or self._day_start_equity <= 0:
            return
        current = self.total_equity(latest_prices)
        daily_pnl = (current - self._day_start_equity) / self._day_start_equity
        if daily_pnl <= -self.max_daily_loss_pct and not self._halted:
            self._halted = True
            # 모든 sleeve 에 halt 전파 — 기존 process_bar 가 risk.halted 체크
            for sleeve in self.sleeves:
                sleeve.risk._halted = True
            logger.warning(
                "계좌 전체 서킷브레이커 발동: daily_pnl={:.2%} <= -{:.2%}, "
                "{} Sleeve 전부 halt",
                daily_pnl,
                self.max_daily_loss_pct,
                len(self.sleeves),
            )


def build_sleeves(
    specs: list[SleeveSpec],
    starting_cash: float,
    fee_bps: float,
    slippage_bps: float,
    quote_ccy: str = "USDT",
) -> list[Sleeve]:
    """SleeveSpec 목록으로부터 Sleeve 인스턴스 생성.

    각 Sleeve 는:
      - cash = starting_cash * allocation_pct
      - 독립 Portfolio, 독립 PaperBroker (fee/slippage 동일)
      - 제공된 RiskManager 그대로 사용

    allocation_pct 합이 1.0 과 크게 차이 나면 경고.
    """
    if not specs:
        raise ValueError("최소 1개 SleeveSpec 필요")
    total_alloc = sum(s.allocation_pct for s in specs)
    if abs(total_alloc - 1.0) > 0.01:
        logger.warning(
            "allocation_pct 합 {:.3f} — 1.0 에서 벗어남. 의도한 경우가 아니면 설정 확인",
            total_alloc,
        )
    sleeves: list[Sleeve] = []
    for spec in specs:
        if not 0 < spec.allocation_pct <= 1.0:
            raise ValueError(
                f"allocation_pct 는 0 < x <= 1.0: {spec.name}={spec.allocation_pct}"
            )
        sleeve_cash = starting_cash * spec.allocation_pct
        portfolio = Portfolio(starting_cash=sleeve_cash, quote_ccy=quote_ccy)
        broker = PaperBroker(fee_bps=fee_bps, slippage_bps=slippage_bps)
        sleeves.append(
            Sleeve(
                name=spec.name,
                symbol=spec.symbol,
                strategy=spec.strategy,
                portfolio=portfolio,
                risk=spec.risk,
                broker=broker,
                allocation_pct=spec.allocation_pct,
                initial_cash=sleeve_cash,
            )
        )
    return sleeves
