"""Swing Pullback — Gemini v2 크립토 스윙 전략 단일 TF 구현.

원안 (Gemini v2):
  1D EMA(50)      — 거시 추세 필터 (System_Enable)
  4H Supertrend   — 추세 지지선
  4H RSI 40~45    — 눌림목 포착
  4H MACD 양전환  — 반등 모멘텀 확인
  Supertrend 이탈 — 손절
  +10% 수익 후 트레일링 -5% — 익절

단일 TF 근사:
  우리 엔진은 단일 타임프레임이므로 "4H 단일" 로 동작하되,
  "1D EMA50" 은 4H × 300 = 50일 EMA(300) 로 수학적 동등 근사.
  (정확한 멀티 TF 데이터 피드 지원 시 1D 쪽으로 분리 가능)

철학:
  - 진입 조건 4개 AND (거시 EMA + Supertrend UP + RSI 눌림 + MACD 양전환)
  - SELL: Supertrend 하락 전환 → 즉시 청산 (동적 손절)
  - 트레일링·고정 손절은 RiskManager 가 외부 방어선으로 병렬 운용
"""

from __future__ import annotations

import pandas as pd

from tradingbot.utils.indicators import ema, macd, rsi, supertrend, volume_ma

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class SwingPullback(Strategy):
    name = "swing_pullback"

    def __init__(self, params: dict, symbol: str, timeframe: str, **kwargs) -> None:
        # 기본값을 super() 호출 전에 초기화: super() 내부의 _load_state_from_disk
        # → set_state 가 성공하면 기본값을 디스크 상태로 덮어쓴다.
        self._ready: bool = False
        super().__init__(params, symbol, timeframe, **kwargs)
        # 1D EMA50 을 4h 기준 EMA(300) 로 근사 (기본). 1D TF 에서 돌리면 50 을 권장.
        self.macro_ema_period = int(params.get("macro_ema_period", 300))
        self.st_period = int(params.get("st_period", 10))
        self.st_multiplier = float(params.get("st_multiplier", 3.0))
        self.rsi_period = int(params.get("rsi_period", 14))
        # Gemini 권장 40~45 "Bull market bias" 범위
        self.rsi_pullback_low = float(params.get("rsi_pullback_low", 40.0))
        self.rsi_pullback_high = float(params.get("rsi_pullback_high", 45.0))
        self.rsi_overbought = float(params.get("rsi_overbought", 70.0))
        self.macd_fast = int(params.get("macd_fast", 12))
        self.macd_slow = int(params.get("macd_slow", 26))
        self.macd_signal = int(params.get("macd_signal", 9))
        # 거짓 돌파 필터 (기본 비활성). True 일 때 BUY 시점의 volume > volume_ma × vol_mult 요구.
        self.require_volume = bool(params.get("require_volume", False))
        self.vol_period = int(params.get("vol_period", 20))
        self.vol_mult = float(params.get("vol_mult", 1.0))

        for p in (self.macro_ema_period, self.st_period, self.rsi_period,
                  self.macd_fast, self.macd_slow, self.macd_signal, self.vol_period):
            if p <= 0:
                raise ValueError(f"모든 period 는 양수여야 함: {p}")
        if self.st_multiplier <= 0:
            raise ValueError("st_multiplier 양수여야 함")
        if not 0 < self.rsi_pullback_low < self.rsi_pullback_high < self.rsi_overbought < 100:
            raise ValueError(
                "0 < rsi_pullback_low < rsi_pullback_high < rsi_overbought < 100 필요"
            )
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast 는 macd_slow 보다 작아야 함")

    # ---- 상태 영속화 훅 ----
    def get_state(self) -> dict:
        return {"ready": self._ready}

    def set_state(self, state: dict) -> None:
        self._ready = bool(state.get("ready", False))

    def warmup_bars(self) -> int:
        return max(
            self.macro_ema_period + 1,
            self.st_period + 2,
            self.macd_slow + self.macd_signal + 1,
            self.rsi_period + 2,
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
        highs = history["high"]
        lows = history["low"]

        macro_ema = ema(closes, self.macro_ema_period).iloc[-1]
        st_trend, _ = supertrend(highs, lows, closes, self.st_period, self.st_multiplier)
        curr_st = int(st_trend.iloc[-1])
        prev_st = int(st_trend.iloc[-2])
        curr_rsi = rsi(closes, self.rsi_period).iloc[-1]
        _, _, hist = macd(closes, self.macd_fast, self.macd_slow, self.macd_signal)
        curr_hist = hist.iloc[-1]
        prev_hist = hist.iloc[-2]

        if any(pd.isna(v) for v in (macro_ema, curr_rsi, curr_hist, prev_hist)):
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="지표 미준비",
            )

        # 2단계: RSI 가 pullback 구간 (40~45) 을 터치하면 ready
        if self.rsi_pullback_low <= curr_rsi <= self.rsi_pullback_high:
            self._ready = True

        # SELL #1: Supertrend 상→하 전환 (동적 손절/청산)
        if prev_st == 1 and curr_st == -1:
            self._ready = False
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="Supertrend 하락 전환 (청산)",
            )

        # SELL #2: RSI 과매수 익절
        if curr_rsi >= self.rsi_overbought:
            self._ready = False
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"RSI {curr_rsi:.1f} ≥ {self.rsi_overbought} (과매수 익절)",
            )

        # 1단계: 거시 추세 — 미달이면 BUY 차단
        if bar.close <= macro_ema:
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=f"거시 추세 미달 (close {bar.close:.2f} ≤ EMA{self.macro_ema_period} {macro_ema:.2f})",
            )

        # 3단계: 반등 모멘텀 — MACD 히스토그램 음→양 전환
        macd_flip_up = prev_hist <= 0 and curr_hist > 0

        # Supertrend 가 UP 상태 + ready + MACD 양전환 → BUY (옵션: 거래량 확인)
        if curr_st == 1 and self._ready and macd_flip_up:
            vol_ok = True
            vol_avg_str = ""
            if self.require_volume:
                vol_avg = volume_ma(history["volume"], self.vol_period).iloc[-1]
                if pd.isna(vol_avg) or bar.volume <= vol_avg * self.vol_mult:
                    vol_ok = False
                else:
                    vol_avg_str = f", vol={bar.volume:.1f}>{vol_avg:.1f}"
            if vol_ok:
                self._ready = False
                return Signal(
                    type=SignalType.BUY,
                    symbol=self.symbol,
                    timestamp=bar.timestamp,
                    price=bar.close,
                    reason=(
                        f"스윙 눌림 BUY (EMA{self.macro_ema_period}↑, ST=UP, "
                        f"RSI={curr_rsi:.1f}, MACDh {prev_hist:+.2f}→{curr_hist:+.2f}"
                        f"{vol_avg_str})"
                    ),
                )
            # 거래량 미달 — ready 는 유지해 다음 기회 대기
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="거래량 미달 (거짓 돌파 필터)",
            )

        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
            reason=f"대기 (ST={curr_st}, ready={self._ready}, flip={macd_flip_up})",
        )
