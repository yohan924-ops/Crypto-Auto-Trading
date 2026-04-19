"""Mean Reversion (역추세 매매) — Gemini 설계.

ETH 처럼 박스권 L자 횡보가 고착화된 자산 대상. 추세 추종 (swing_pullback 등)
이 실패하는 구간에서 "하단 패닉셀 → 중앙선 회귀" 패턴을 핀포인트 타격.

진입 조건 (동시 충족):
  1) CHOP(14) > chop_threshold (기본 61.8) — 횡보장 확인
  2) %B < percent_b_low (기본 0.0) — 가격이 볼린저 하단 뚫음 (패닉셀)
  → BUY

청산 조건 (하나라도 충족):
  1) 가격이 SMA(bb_period) 중앙선 도달 → SELL (회귀 익절)
  2) %B > percent_b_high (기본 1.0) — 상단 돌파 (욕심 방어)
  3) RiskManager stop_loss / trailing 은 외부 방어선

주의:
  - 추세장 (CHOP < 38.2) 에서는 진입 자체 차단 → 추세 돌파 놓침
  - 하지만 이게 Mean Reversion 의 본질. "박스권 전용 사이드킥" 으로 설계
"""

from __future__ import annotations

import pandas as pd

from tradingbot.utils.indicators import chop, percent_b, sma

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class MeanReversion(Strategy):
    name = "mean_reversion"

    def __init__(self, params: dict, symbol: str, timeframe: str, **kwargs) -> None:
        super().__init__(params, symbol, timeframe, **kwargs)
        self.chop_period = int(params.get("chop_period", 14))
        self.chop_threshold = float(params.get("chop_threshold", 61.8))
        self.bb_period = int(params.get("bb_period", 20))
        self.bb_std = float(params.get("bb_std", 2.0))
        self.percent_b_low = float(params.get("percent_b_low", 0.0))
        self.percent_b_high = float(params.get("percent_b_high", 1.0))

        if self.chop_period <= 0 or self.bb_period <= 0:
            raise ValueError("chop_period, bb_period 는 양수")
        if not 0 < self.chop_threshold < 100:
            raise ValueError(f"chop_threshold 는 0~100: {self.chop_threshold}")
        if self.bb_std <= 0:
            raise ValueError(f"bb_std 양수: {self.bb_std}")
        if self.percent_b_low >= self.percent_b_high:
            raise ValueError("percent_b_low < percent_b_high 필요")

    def warmup_bars(self) -> int:
        return max(self.chop_period + 1, self.bb_period + 1)

    def status_snapshot(self, history: pd.DataFrame) -> str:
        need = self.warmup_bars()
        if len(history) < need:
            return f"{self.name} 워밍업 {len(history)}/{need}봉"
        curr_chop = float(
            chop(history["high"], history["low"], history["close"], self.chop_period).iloc[-1]
        )
        curr_pb = float(percent_b(history["close"], self.bb_period, self.bb_std).iloc[-1])
        curr_sma = float(sma(history["close"], self.bb_period).iloc[-1])
        close = float(history["close"].iloc[-1])
        chop_tag = "횡보" if curr_chop > self.chop_threshold else "추세"
        pb_tag = (
            "하단↓" if curr_pb < self.percent_b_low
            else "상단↑" if curr_pb > self.percent_b_high
            else "밴드내"
        )
        return (
            f"{self.name} | close={close:.2f} | SMA{self.bb_period}={curr_sma:.2f} | "
            f"CHOP={curr_chop:.1f}({chop_tag}) | %B={curr_pb:+.3f}({pb_tag})"
        )

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
        highs = history["high"]
        lows = history["low"]

        curr_chop = chop(highs, lows, closes, self.chop_period).iloc[-1]
        curr_pb = percent_b(closes, self.bb_period, self.bb_std).iloc[-1]
        curr_sma = sma(closes, self.bb_period).iloc[-1]

        if any(pd.isna(v) for v in (curr_chop, curr_pb, curr_sma)):
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="지표 미준비",
            )

        # 청산: 중앙선 도달 또는 상단 돌파
        # (진입 시점부터 SMA/%B 기준 감시. 포지션 보유 여부는 엔진이 관리)
        if bar.close >= curr_sma or curr_pb >= self.percent_b_high:
            reason = (
                f"중앙선 회귀 (close {bar.close:.2f} ≥ SMA{self.bb_period} {curr_sma:.2f})"
                if bar.close >= curr_sma
                else f"상단 돌파 (%B {curr_pb:.3f} ≥ {self.percent_b_high})"
            )
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=reason,
            )

        # 진입: CHOP 횡보 + %B 하단 뚫음
        if curr_chop > self.chop_threshold and curr_pb < self.percent_b_low:
            return Signal(
                type=SignalType.BUY,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=(
                    f"Mean Reversion BUY (CHOP {curr_chop:.1f}>{self.chop_threshold} + "
                    f"%B {curr_pb:.3f}<{self.percent_b_low})"
                ),
            )

        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
            reason=f"대기 (CHOP={curr_chop:.1f}, %B={curr_pb:.3f})",
        )
