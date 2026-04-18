"""RSI 역추세(Mean Reversion) 전략.

- RSI 가 oversold(기본 30) 아래로 하향 돌파 → BUY (반등 기대)
- RSI 가 overbought(기본 70) 위로 상향 돌파 → SELL (조정 기대)
- 그 외 → HOLD

'돌파' 시점에만 신호를 내므로 같은 구간에 머무는 동안 반복 신호가 나가지 않는다.
포지션 크기와 손절/서킷브레이커는 RiskManager 가 담당.

이 파일은 ``@register`` 한 줄로만 엔진에 등록되며, 엔진/브로커/러너 코드는
수정 없이 rsi_reversal 을 사용할 수 있다 — 플러그인 구조 증명.
"""

from __future__ import annotations

import pandas as pd

from tradingbot.utils.indicators import rsi

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class RSIReversal(Strategy):
    name = "rsi_reversal"

    def __init__(self, params: dict, symbol: str, timeframe: str) -> None:
        super().__init__(params, symbol, timeframe)
        self.period = int(params.get("period", 14))
        self.oversold = float(params.get("oversold", 30.0))
        self.overbought = float(params.get("overbought", 70.0))
        if self.period <= 0:
            raise ValueError("period 는 양수여야 함")
        if not 0 < self.oversold < self.overbought < 100:
            raise ValueError(
                f"임계값 오류: 0 < oversold({self.oversold}) < overbought({self.overbought}) < 100"
            )

    def warmup_bars(self) -> int:
        # RSI 는 period 봉 이후 유효, 교차 판정 위해 +2
        return self.period + 2

    def on_bar(self, bar: Bar, history: pd.DataFrame) -> Signal:
        if len(history) < self.warmup_bars():
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="warmup",
            )

        values = rsi(history["close"], self.period)
        prev_rsi = values.iloc[-2]
        curr_rsi = values.iloc[-1]
        if pd.isna(prev_rsi) or pd.isna(curr_rsi):
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="RSI 미준비",
            )

        # 과매도 하향 돌파 → BUY
        if prev_rsi >= self.oversold and curr_rsi < self.oversold:
            return Signal(
                type=SignalType.BUY,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"RSI {curr_rsi:.1f} < {self.oversold} (과매도)",
            )

        # 과매수 상향 돌파 → SELL
        if prev_rsi <= self.overbought and curr_rsi > self.overbought:
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"RSI {curr_rsi:.1f} > {self.overbought} (과매수)",
            )

        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
        )
