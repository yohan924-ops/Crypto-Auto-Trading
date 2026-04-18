"""Triple Screen (트리플 스크린) 전략 — 알렉산더 엘더 교과서 변형.

원전은 주/일/장중 3단 필터이지만, 크립토 단일 timeframe 구조에 맞춰 단순화.
**한 타임프레임 내에서 4개 조건 AND** 로 진입 판정:

  1) 추세 확인    — MACD 히스토그램 > 0  (상승 모멘텀)
  2) 극단 회피    — RSI 가 oversold~overbought 구간 안  (과매수/과매도 X)
  3) 진입 타이밍  — 종가 > 볼린저 중앙선(SMA) (중앙선 돌파)
  4) 거래 동반    — 현재 볼륨 > 볼륨 MA(20)     (확신 있는 움직임)

모두 ✅ 인 순간 BUY (포지션 없을 때만).
보유 중 MACD 히스토그램 < 0 으로 돌아서면 SELL (추세 약화 신호).

철학:
- "조건 많을수록 좋다" 가 아니라 **서로 다른 축을 봐야** 오버피팅 덜함.
  추세(MACD) / 모멘텀(RSI) / 위치(BB) / 확신(Volume) — 4개 축 모두 서로 다른 정보.
- RiskManager 의 손절/서킷브레이커가 여전히 최상위 방어선.
"""

from __future__ import annotations

import pandas as pd

from tradingbot.utils.indicators import macd, rsi, sma, volume_ma

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class TripleScreen(Strategy):
    name = "triple_screen"

    def __init__(self, params: dict, symbol: str, timeframe: str, **kwargs) -> None:
        super().__init__(params, symbol, timeframe, **kwargs)
        self.macd_fast = int(params.get("macd_fast", 12))
        self.macd_slow = int(params.get("macd_slow", 26))
        self.macd_signal = int(params.get("macd_signal", 9))
        self.rsi_period = int(params.get("rsi_period", 14))
        self.rsi_low = float(params.get("rsi_low", 40.0))
        self.rsi_high = float(params.get("rsi_high", 70.0))
        self.bb_period = int(params.get("bb_period", 20))
        self.vol_period = int(params.get("vol_period", 20))

        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast 는 macd_slow 보다 작아야 함")
        if not 0 < self.rsi_low < self.rsi_high < 100:
            raise ValueError("0 < rsi_low < rsi_high < 100 이어야 함")
        for p in (self.macd_fast, self.macd_slow, self.macd_signal,
                  self.rsi_period, self.bb_period, self.vol_period):
            if p <= 0:
                raise ValueError(f"모든 period 는 양수여야 함: {p}")

    def warmup_bars(self) -> int:
        # MACD signal 은 slow+signal 만큼, 볼린저·RSI 는 각 period+2 만큼 필요
        macd_warmup = self.macd_slow + self.macd_signal + 1
        return max(
            macd_warmup,
            self.rsi_period + 2,
            self.bb_period + 1,
            self.vol_period + 1,
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
        volumes = history["volume"]

        _, _, hist = macd(closes, self.macd_fast, self.macd_slow, self.macd_signal)
        rsi_vals = rsi(closes, self.rsi_period)
        bb_mid = sma(closes, self.bb_period)
        vol_avg = volume_ma(volumes, self.vol_period)

        curr_hist = hist.iloc[-1]
        prev_hist = hist.iloc[-2]
        curr_rsi = rsi_vals.iloc[-1]
        curr_mid = bb_mid.iloc[-1]
        curr_vol_avg = vol_avg.iloc[-1]

        # 각 조건이 하나라도 NaN 이면 판단 보류
        if any(pd.isna(v) for v in (curr_hist, prev_hist, curr_rsi, curr_mid, curr_vol_avg)):
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="지표 미준비",
            )

        cond_trend = curr_hist > 0
        cond_momentum = self.rsi_low <= curr_rsi <= self.rsi_high
        cond_entry = bar.close > curr_mid
        cond_volume = bar.volume > curr_vol_avg

        # SELL: 추세 약화 — 히스토그램이 양→음 으로 전환된 봉
        if prev_hist > 0 and curr_hist <= 0:
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"MACD 히스토그램 음전환 ({prev_hist:.2f}→{curr_hist:.2f})",
            )

        if cond_trend and cond_momentum and cond_entry and cond_volume:
            return Signal(
                type=SignalType.BUY,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=(
                    f"4개 조건 ✅ (MACDh={curr_hist:.2f}, RSI={curr_rsi:.1f}, "
                    f"close>{curr_mid:.2f}, vol={bar.volume:.1f}>{curr_vol_avg:.1f})"
                ),
            )

        missing = []
        if not cond_trend:
            missing.append("추세")
        if not cond_momentum:
            missing.append(f"RSI={curr_rsi:.1f}")
        if not cond_entry:
            missing.append("중앙선")
        if not cond_volume:
            missing.append("거래량")
        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
            reason=f"조건 미충족: {','.join(missing)}",
        )
