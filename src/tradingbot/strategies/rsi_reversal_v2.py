"""RSI Reversal v2 — 장기 추세 필터(EMA) 추가 버전.

원본(rsi_reversal) 의 치명적 약점:
  하락 추세 중에도 RSI 30 하향 돌파 시마다 BUY → "떨어지는 칼날 잡기".
  2022 H2 같은 장기 하락장에선 반복 진입·손절로 자산 침식.

v2 수정:
  [1단계] 거시 추세 필터 — close > EMA(ema_period, 기본 200)
  [2단계] 기존 RSI 30 하향 돌파 트리거
  둘 다 충족할 때만 BUY. SELL (과매수 상향 돌파) 은 추세와 무관하게 청산 신호로 유지.

철학:
  - 추가된 조건은 단 하나 (EMA) — 복잡도 증가 최소
  - 상승장·횡보장에서는 원본과 거의 동일 동작
  - 하락장에서만 BUY 차단 → 하방 방어
"""

from __future__ import annotations

import pandas as pd

from tradingbot.utils.indicators import ema, rsi

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class RSIReversalV2(Strategy):
    name = "rsi_reversal_v2"

    def __init__(self, params: dict, symbol: str, timeframe: str) -> None:
        super().__init__(params, symbol, timeframe)
        self.period = int(params.get("period", 14))
        self.oversold = float(params.get("oversold", 30.0))
        self.overbought = float(params.get("overbought", 70.0))
        self.ema_period = int(params.get("ema_period", 200))
        if self.period <= 0 or self.ema_period <= 0:
            raise ValueError("period / ema_period 는 양수여야 함")
        if not 0 < self.oversold < self.overbought < 100:
            raise ValueError(
                f"임계값: 0 < oversold({self.oversold}) < overbought({self.overbought}) < 100"
            )

    def warmup_bars(self) -> int:
        return max(self.period + 2, self.ema_period + 1)

    def on_bar(self, bar: Bar, history: pd.DataFrame) -> Signal:
        if len(history) < self.warmup_bars():
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="warmup",
            )

        closes = history["close"]
        rsi_vals = rsi(closes, self.period)
        prev_rsi = rsi_vals.iloc[-2]
        curr_rsi = rsi_vals.iloc[-1]
        ema_long = ema(closes, self.ema_period).iloc[-1]
        if pd.isna(prev_rsi) or pd.isna(curr_rsi) or pd.isna(ema_long):
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="지표 미준비",
            )

        # 과매수 상향 돌파 → SELL (추세 무관, 청산 신호)
        if prev_rsi <= self.overbought and curr_rsi > self.overbought:
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"RSI {curr_rsi:.1f} > {self.overbought} (과매수)",
            )

        # 과매도 하향 돌파: **추세 필터 통과 시에만** BUY
        if prev_rsi >= self.oversold and curr_rsi < self.oversold:
            if bar.close > ema_long:
                return Signal(
                    type=SignalType.BUY,
                    symbol=self.symbol,
                    timestamp=bar.timestamp,
                    price=bar.close,
                    reason=(
                        f"RSI {curr_rsi:.1f} < {self.oversold} + close>EMA{self.ema_period}"
                        f"({bar.close:.2f}>{ema_long:.2f})"
                    ),
                )
            # 추세 이탈 — BUY 차단 (떨어지는 칼날 방어)
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=(
                    f"RSI 과매도이지만 추세 이탈 차단 "
                    f"(close {bar.close:.2f} ≤ EMA{self.ema_period} {ema_long:.2f})"
                ),
            )

        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
        )
