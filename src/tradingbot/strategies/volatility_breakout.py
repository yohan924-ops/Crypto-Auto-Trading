"""변동성 돌파 (래리 윌리엄스 스타일) 전략.

고전 로직:
  - 오늘 시가 + k * (전일 고가 - 전일 저가) = 목표가
  - 장중 목표가를 상향 돌파하면 진입, 다음 봉에서 청산

본 구현 (바 단위 단순화):
  - 현재 봉의 close 가 (현재 open + k * 전일 range) 보다 크면 BUY
  - 다음 봉에서는 포지션을 청산하는 SELL 을 내보냄 (하루 이상 보유 방지)

일봉(1d) 에 가장 적합하지만 다른 타임프레임에서도 동작은 한다.
"""

from __future__ import annotations

import pandas as pd

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class VolatilityBreakout(Strategy):
    name = "volatility_breakout"

    def __init__(self, params: dict, symbol: str, timeframe: str) -> None:
        super().__init__(params, symbol, timeframe)
        self.k = float(params.get("k", 0.5))
        if not 0 < self.k < 2:
            raise ValueError(f"k 는 0~2 범위여야 함: {self.k}")
        self._entered_bar: int | None = None

    def warmup_bars(self) -> int:
        # 전일 고/저가 필요 → 최소 2봉
        return 2

    def on_bar(self, bar: Bar, history: pd.DataFrame) -> Signal:
        if len(history) < self.warmup_bars():
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="warmup",
            )

        current_idx = len(history) - 1

        # 이전 바에서 진입했다면 이번 바에서 청산
        if self._entered_bar is not None and current_idx > self._entered_bar:
            self._entered_bar = None
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="변동성 돌파 익일 청산",
            )

        prev = history.iloc[-2]
        prev_range = float(prev["high"]) - float(prev["low"])
        target = bar.open + self.k * prev_range
        if bar.close > target and self._entered_bar is None:
            self._entered_bar = current_idx
            return Signal(
                type=SignalType.BUY,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"변동성 돌파 (close={bar.close:.2f} > target={target:.2f})",
            )

        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
        )
