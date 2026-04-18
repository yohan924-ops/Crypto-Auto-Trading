"""백테스터: 과거 OHLCV 데이터로 전략을 바 단위로 리플레이."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

import pandas as pd
from loguru import logger

from tradingbot.broker.base import Fill
from tradingbot.broker.paper import PaperBroker
from tradingbot.data.feed import bar_from_row
from tradingbot.logging_setup import log_order_event
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies.base import Strategy

from .core import HISTORY_COLUMNS, append_bar, process_bar


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    starting_cash: float
    ending_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    num_trades: int
    num_bars: int
    equity_curve: pd.DataFrame = field(repr=False)
    trades: list[Fill] = field(repr=False)

    def summary(self) -> str:
        lines = [
            "===== 백테스트 결과 =====",
            f"심볼:        {self.symbol}  타임프레임: {self.timeframe}",
            f"기간:        {self.start.isoformat()} ~ {self.end.isoformat()}",
            f"봉 개수:     {self.num_bars}",
            f"시작 자금:   {self.starting_cash:,.2f}",
            f"최종 자산:   {self.ending_equity:,.2f}",
            f"총 수익률:   {self.total_return_pct:+.2f}%",
            f"최대 낙폭:   {self.max_drawdown_pct:.2f}%",
            f"거래 횟수:   {self.num_trades}",
            "========================",
        ]
        return "\n".join(lines)


class Backtester:
    def __init__(
        self,
        symbol: str,
        timeframe: str,
        strategy: Strategy,
        starting_cash: float,
        fee_bps: float,
        slippage_bps: float,
        risk: RiskManager,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.strategy = strategy
        self.starting_cash = starting_cash
        self.broker = PaperBroker(fee_bps=fee_bps, slippage_bps=slippage_bps)
        self.portfolio = Portfolio(starting_cash=starting_cash)
        self.risk = risk

    def run(self, df: pd.DataFrame) -> BacktestResult:
        if df.empty:
            raise ValueError("백테스트 데이터가 비어 있음")

        history = pd.DataFrame(columns=HISTORY_COLUMNS)
        equity_rows: list[dict] = []
        trades: list[Fill] = []

        self.strategy.on_start()
        try:
            for _, row in df.iterrows():
                bar = bar_from_row(row)
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
                equity_rows.append(
                    {
                        "timestamp": bar.timestamp,
                        "close": bar.close,
                        "cash": outcome.cash_after,
                        "position": outcome.position_amount_after,
                        "equity": outcome.equity_after,
                    }
                )
                if outcome.fill is not None:
                    trades.append(outcome.fill)
                    log_order_event({"event": "backtest_fill", **asdict(outcome.fill)})
        finally:
            self.strategy.on_stop()

        equity_curve = pd.DataFrame(equity_rows)
        ending_equity = (
            equity_curve["equity"].iloc[-1] if not equity_curve.empty else self.starting_cash
        )

        if not equity_curve.empty:
            running_max = equity_curve["equity"].cummax()
            drawdown = (equity_curve["equity"] - running_max) / running_max * 100.0
            mdd = float(drawdown.min()) if not drawdown.empty else 0.0
        else:
            mdd = 0.0

        total_return_pct = (ending_equity / self.starting_cash - 1) * 100.0
        start_ts = df["timestamp"].iloc[0]
        end_ts = df["timestamp"].iloc[-1]

        result = BacktestResult(
            symbol=self.symbol,
            timeframe=self.timeframe,
            start=(start_ts.to_pydatetime() if hasattr(start_ts, "to_pydatetime") else start_ts),
            end=(end_ts.to_pydatetime() if hasattr(end_ts, "to_pydatetime") else end_ts),
            starting_cash=self.starting_cash,
            ending_equity=ending_equity,
            total_return_pct=total_return_pct,
            max_drawdown_pct=abs(mdd),
            num_trades=len(trades),
            num_bars=len(equity_curve),
            equity_curve=equity_curve,
            trades=trades,
        )
        logger.info(
            "백테스트 완료: return={:+.2f}% trades={} mdd={:.2f}%",
            result.total_return_pct,
            result.num_trades,
            result.max_drawdown_pct,
        )
        return result
