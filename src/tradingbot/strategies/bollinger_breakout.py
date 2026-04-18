"""볼린저 밴드 돌파 전략.

- 종가가 상단 밴드(SMA + num_std·σ) 를 상향 돌파 → BUY (변동성 확장 추종)
- 종가가 하단 밴드를 하향 돌파 → SELL
- 그 외 → HOLD
"""

from __future__ import annotations

import pandas as pd

from tradingbot.utils.indicators import bollinger_bands

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class BollingerBreakout(Strategy):
    name = "bollinger_breakout"

    def __init__(self, params: dict, symbol: str, timeframe: str, **kwargs) -> None:
        super().__init__(params, symbol, timeframe, **kwargs)
        self.period = int(params.get("period", 20))
        self.num_std = float(params.get("num_std", 2.0))
        if self.period <= 0 or self.num_std <= 0:
            raise ValueError("period/num_std 는 양수여야 함")

    def warmup_bars(self) -> int:
        return self.period + 1

    def on_bar(self, bar: Bar, history: pd.DataFrame) -> Signal:
        if len(history) < self.warmup_bars():
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="warmup",
            )
        # 현재 바를 제외한 과거 종가로만 밴드 계산 → 밴드는 "고정선" 역할
        prev_closes = history["close"].iloc[:-1]
        _, upper, lower = bollinger_bands(prev_closes, self.period, self.num_std)
        if upper.dropna().empty:
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="warmup",
            )
        band_upper = upper.iloc[-1]
        band_lower = lower.iloc[-1]
        prev_close = history["close"].iloc[-2]
        curr_close = bar.close

        if (
            not pd.isna(band_upper)
            and prev_close <= band_upper
            and curr_close > band_upper
        ):
            return Signal(
                type=SignalType.BUY,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"상단 돌파 (close={curr_close:.2f} > {band_upper:.2f})",
            )
        if (
            not pd.isna(band_lower)
            and prev_close >= band_lower
            and curr_close < band_lower
        ):
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"하단 돌파 (close={curr_close:.2f} < {band_lower:.2f})",
            )
        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
        )
