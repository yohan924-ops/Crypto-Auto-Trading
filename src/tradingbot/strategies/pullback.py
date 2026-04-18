"""상승장 눌림목(Pullback) 전략 — 3단 논리 회로.

핵심 철학:
  현물 단방향 시장에서 가장 치명적인 건 "하락장에서도 매수를 시도하는 것".
  → 1단계에서 **장기 추세 필터** 로 매수 로직 자체를 차단.
  → 2단계에서 **과매도(RSI)** 로 단기 눌림목 포착.
  → 3단계에서 **MACD 히스토그램 양전환** 으로 반등 모멘텀 확인 후에만 진입.

triple_screen 과의 결정적 차이:
  triple_screen = "모든 조건 충족 중인 동안 매번 매수 가능" (상태 유지 기반)
                 → 상승장에서 자주 진입 → 수수료 누적
  pullback      = "조건 조합의 '전환 순간' 에만 매수" (상태 머신 기반)
                 → 드문 진입, 높은 승률 지향

SELL:
  - 전략 자체: RSI > rsi_overbought (과매수 익절)
  - 외부: RiskManager 의 손절 + 트레일링 스탑 (전략 밖에서 처리)
"""

from __future__ import annotations

import pandas as pd

from tradingbot.utils.indicators import bollinger_bands, ema, macd, rsi, volume_ma

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class Pullback(Strategy):
    name = "pullback"

    def __init__(self, params: dict, symbol: str, timeframe: str, **kwargs) -> None:
        # super() 내부 _load_state_from_disk 가 set_state 를 호출하며 이 값을 덮어쓸 수 있음.
        self._ready: bool = False
        super().__init__(params, symbol, timeframe, **kwargs)
        # 1단계: 장기 추세 필터
        self.ema_period = int(params.get("ema_period", 120))
        # 2단계: 진입 준비 (RSI + 선택적 BB 하단)
        self.rsi_period = int(params.get("rsi_period", 14))
        self.rsi_oversold = float(params.get("rsi_oversold", 30.0))
        self.rsi_overbought = float(params.get("rsi_overbought", 70.0))
        self.use_bb_lower = bool(params.get("use_bb_lower", True))
        self.bb_period = int(params.get("bb_period", 20))
        self.bb_num_std = float(params.get("bb_num_std", 2.0))
        # 3단계: 확인 필터
        self.macd_fast = int(params.get("macd_fast", 12))
        self.macd_slow = int(params.get("macd_slow", 26))
        self.macd_signal = int(params.get("macd_signal", 9))
        self.require_volume = bool(params.get("require_volume", True))
        self.vol_period = int(params.get("vol_period", 20))
        self.vol_mult = float(params.get("vol_mult", 1.0))

        for p in (self.ema_period, self.rsi_period, self.bb_period,
                  self.macd_fast, self.macd_slow, self.macd_signal, self.vol_period):
            if p <= 0:
                raise ValueError(f"모든 period 는 양수여야 함: {p}")
        if not 0 < self.rsi_oversold < self.rsi_overbought < 100:
            raise ValueError("0 < rsi_oversold < rsi_overbought < 100 이어야 함")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast 는 macd_slow 보다 작아야 함")

    # ---- 상태 영속화 훅 ----
    def get_state(self) -> dict:
        return {"ready": self._ready}

    def set_state(self, state: dict) -> None:
        self._ready = bool(state.get("ready", False))

    def warmup_bars(self) -> int:
        return max(
            self.ema_period + 1,
            self.macd_slow + self.macd_signal + 1,
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

        ema_long = ema(closes, self.ema_period).iloc[-1]
        _, _, hist = macd(closes, self.macd_fast, self.macd_slow, self.macd_signal)
        curr_hist = hist.iloc[-1]
        prev_hist = hist.iloc[-2]
        curr_rsi = rsi(closes, self.rsi_period).iloc[-1]
        vol_avg = volume_ma(volumes, self.vol_period).iloc[-1]

        if any(pd.isna(v) for v in (ema_long, curr_hist, prev_hist, curr_rsi, vol_avg)):
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="지표 미준비",
            )

        # 2단계를 먼저 평가 — 눌림목은 보통 '잠깐 EMA 아래로 내려갔다 오는' 구간에서
        # 발생하므로 추세 필터보다 앞서 ready 상태를 기록해야 한다.
        rsi_oversold_hit = curr_rsi <= self.rsi_oversold
        bb_lower_hit = False
        if self.use_bb_lower:
            _, _, bb_lower = bollinger_bands(closes, self.bb_period, self.bb_num_std)
            if not pd.isna(bb_lower.iloc[-1]) and bar.close <= bb_lower.iloc[-1]:
                bb_lower_hit = True
        if rsi_oversold_hit or bb_lower_hit:
            self._ready = True

        # 1단계: 거시 추세 — 하락장이면 BUY 차단 (ready 는 유지해 반등 시점에 발화)
        trend_up = bar.close > ema_long
        if not trend_up:
            if curr_rsi >= self.rsi_overbought:
                return Signal(
                    type=SignalType.SELL,
                    symbol=self.symbol,
                    timestamp=bar.timestamp,
                    price=bar.close,
                    reason=f"RSI {curr_rsi:.1f} ≥ {self.rsi_overbought} (과매수)",
                )
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"추세 이탈 (close {bar.close:.2f} < EMA{self.ema_period} {ema_long:.2f})",
            )

        # 3단계: 반등 모멘텀 확인 — MACD 히스토그램 음→양 전환
        macd_flip_up = prev_hist <= 0 and curr_hist > 0

        # 익절: 과매수 도달 (진입 후 상승 피크)
        if curr_rsi >= self.rsi_overbought:
            self._ready = False
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"RSI {curr_rsi:.1f} ≥ {self.rsi_overbought} (과매수 익절)",
            )

        if self._ready and macd_flip_up:
            vol_ok = (not self.require_volume) or (bar.volume > vol_avg * self.vol_mult)
            if vol_ok:
                self._ready = False  # 트리거 소비 — 다음 눌림목 대기
                return Signal(
                    type=SignalType.BUY,
                    symbol=self.symbol,
                    timestamp=bar.timestamp,
                    price=bar.close,
                    reason=(
                        f"눌림목 반등 BUY (close>{ema_long:.0f} EMA, RSI={curr_rsi:.1f}, "
                        f"MACD {prev_hist:+.2f}→{curr_hist:+.2f}, vol={bar.volume:.1f})"
                    ),
                )

        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
            reason=f"대기 (ready={self._ready}, flip={macd_flip_up})",
        )
