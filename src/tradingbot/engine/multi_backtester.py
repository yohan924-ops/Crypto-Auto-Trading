"""멀티 자산 백테스터.

여러 심볼 + 각 심볼별 전략·비중으로 동시에 백테스트 실행.
공유 자원: Portfolio, RiskManager, PaperBroker, 알림 — 포트폴리오 수준의
손익·서킷브레이커가 전체 자산에 걸쳐 동작.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from loguru import logger

from tradingbot.broker.base import Fill
from tradingbot.broker.paper import PaperBroker
from tradingbot.data.feed import bar_from_row
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies.base import Strategy

from .backtester import _annualization_factor, _sharpe, _sortino, _win_rate
from .core import HISTORY_COLUMNS, append_bar, process_bar


@dataclass
class PortfolioItem:
    """포트폴리오 한 항목 (심볼 + 전략 인스턴스 + 비중 + 데이터)."""

    symbol: str
    strategy: Strategy
    weight: float
    df: pd.DataFrame


@dataclass
class MultiBacktestResult:
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
    per_symbol: dict[str, dict] = field(default_factory=dict)
    equity_curve: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    trades: list[Fill] = field(repr=False, default_factory=list)

    def summary(self) -> str:
        lines = [
            "===== 멀티 자산 백테스트 결과 =====",
            f"기간:        {self.start.isoformat()} ~ {self.end.isoformat()}",
            f"타임프레임:  {self.timeframe}",
            f"심볼 개수:   {len(self.per_symbol)}",
            f"시작 자금:   {self.starting_cash:,.2f}",
            f"최종 자산:   {self.ending_equity:,.2f}",
            f"총 수익률:   {self.total_return_pct:+.2f}%",
            f"최대 낙폭:   {self.max_drawdown_pct:.2f}%",
            f"Sharpe:      {self.sharpe:+.2f}  Sortino: {self.sortino:+.2f}",
            f"총 거래:     {self.num_trades}",
            "-- 심볼별 요약 --",
        ]
        for sym, s in self.per_symbol.items():
            lines.append(
                f"  {sym:<12} w={s['weight']:.2f}  trades={s['num_trades']}  "
                f"strategy={s['strategy_name']}"
            )
        lines.append("==================================")
        return "\n".join(lines)


class MultiAssetBacktester:
    def __init__(
        self,
        items: list[PortfolioItem],
        timeframe: str,
        starting_cash: float,
        fee_bps: float,
        slippage_bps: float,
        risk: RiskManager,
    ) -> None:
        if not items:
            raise ValueError("포트폴리오에 최소 1개 항목 필요")
        self.items = items
        self.timeframe = timeframe
        self.starting_cash = starting_cash
        self.broker = PaperBroker(fee_bps=fee_bps, slippage_bps=slippage_bps)
        self.portfolio = Portfolio(starting_cash=starting_cash)
        self.risk = risk

    def run(self) -> MultiBacktestResult:
        # 모든 심볼의 바를 timestamp 오름차순으로 병합
        events: list[tuple[pd.Timestamp, PortfolioItem, pd.Series]] = []
        for item in self.items:
            if item.df.empty:
                continue
            for _, row in item.df.iterrows():
                events.append((row["timestamp"], item, row))
        events.sort(key=lambda e: e[0])
        if not events:
            raise ValueError("병합된 이벤트가 비어 있음")

        histories = {item.symbol: pd.DataFrame(columns=HISTORY_COLUMNS) for item in self.items}
        equity_rows: list[dict] = []
        trades: list[Fill] = []
        per_symbol_trades: dict[str, int] = {item.symbol: 0 for item in self.items}
        latest_price: dict[str, float] = {}

        # 모든 전략에 on_start 통지
        for item in self.items:
            item.strategy.on_start()

        try:
            for ts, item, row in events:
                bar = bar_from_row(row)
                history = histories[item.symbol]
                append_bar(history, bar)
                latest_price[item.symbol] = bar.close

                outcome = process_bar(
                    bar,
                    history,
                    symbol=item.symbol,
                    strategy=item.strategy,
                    broker=self.broker,
                    portfolio=self.portfolio,
                    risk=self.risk,
                    weight=item.weight,
                    extra_marks=latest_price,
                )
                if outcome.fill is not None:
                    trades.append(outcome.fill)
                    per_symbol_trades[item.symbol] += 1

                # 전체 포트폴리오 관점의 에쿼티
                total_equity = self.portfolio.equity(latest_price)
                equity_rows.append(
                    {
                        "timestamp": ts,
                        "symbol": item.symbol,
                        "close": bar.close,
                        "equity": total_equity,
                        "cash": self.portfolio.cash,
                    }
                )
        finally:
            for item in self.items:
                item.strategy.on_stop()

        equity_curve = pd.DataFrame(equity_rows)
        ending_equity = (
            equity_curve["equity"].iloc[-1] if not equity_curve.empty else self.starting_cash
        )
        running_max = equity_curve["equity"].cummax()
        drawdown = (equity_curve["equity"] - running_max) / running_max * 100.0
        mdd = abs(float(drawdown.min())) if not drawdown.empty else 0.0

        bar_returns = equity_curve["equity"].pct_change().dropna() if not equity_curve.empty else pd.Series(dtype=float)
        ann = _annualization_factor(self.timeframe)

        per_symbol = {
            item.symbol: {
                "weight": item.weight,
                "strategy_name": item.strategy.name,
                "num_trades": per_symbol_trades[item.symbol],
            }
            for item in self.items
        }

        # 승률은 심볼별로 별도 계산하는 게 정확하지만, 전체 FIFO 기준으로 근사
        result = MultiBacktestResult(
            start=events[0][0].to_pydatetime() if hasattr(events[0][0], "to_pydatetime") else events[0][0],
            end=events[-1][0].to_pydatetime() if hasattr(events[-1][0], "to_pydatetime") else events[-1][0],
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
            per_symbol=per_symbol,
            equity_curve=equity_curve,
            trades=trades,
        )
        logger.info(
            "멀티 자산 백테스트 완료: return={:+.2f}% trades={} symbols={}",
            result.total_return_pct,
            result.num_trades,
            len(per_symbol),
        )
        return result
