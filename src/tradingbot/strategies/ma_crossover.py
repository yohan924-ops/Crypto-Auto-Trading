"""이동평균 교차 전략.

- 단기 이평선(fast)이 장기 이평선(slow)을 상향 돌파 → 골든크로스 → BUY
- 단기 이평선이 장기 이평선을 하향 돌파 → 데드크로스 → SELL
- 그 외 → HOLD

전략은 신호만 생성하며 포지션 크기는 RiskManager가 결정.
"""

from __future__ import annotations

import pandas as pd

from tradingbot.utils.indicators import sma

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class MACrossover(Strategy):
    name = "ma_crossover"

    def __init__(self, params: dict, symbol: str, timeframe: str, **kwargs) -> None:
        super().__init__(params, symbol, timeframe, **kwargs)
        self.fast = int(params.get("fast", 20))
        self.slow = int(params.get("slow", 50))
        if self.fast <= 0 or self.slow <= 0:
            raise ValueError("fast/slow 기간은 양수여야 함")
        if self.fast >= self.slow:
            raise ValueError(
                f"fast({self.fast})는 slow({self.slow})보다 작아야 함"
            )

    def warmup_bars(self) -> int:
        # 교차 판정에는 최소 slow + 1 봉이 필요
        return self.slow + 1

    def on_bar(self, bar: Bar, history: pd.DataFrame) -> Signal:
        if len(history) < self.warmup_bars():
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="warmup",
            )

        close = history["close"]
        fast_ma = sma(close, self.fast)
        slow_ma = sma(close, self.slow)

        prev_fast, curr_fast = fast_ma.iloc[-2], fast_ma.iloc[-1]
        prev_slow, curr_slow = slow_ma.iloc[-2], slow_ma.iloc[-1]

        # 골든크로스: 직전 봉에 fast<=slow 였다가 현재 봉에서 fast>slow 로 전환
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return Signal(
                type=SignalType.BUY,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"골든크로스 (SMA{self.fast}>{self.slow})",
            )

        # 데드크로스
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"데드크로스 (SMA{self.fast}<{self.slow})",
            )

        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
        )
