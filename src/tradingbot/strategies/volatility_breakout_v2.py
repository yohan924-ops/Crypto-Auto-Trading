"""변동성 돌파 v2 — 래리 윌리엄스 + 동적 K + 거시 추세 필터.

기존 `volatility_breakout` 이 6구간 평균 -0.25% 로 실패한 이유를 보완:
  - 하락장에서도 돌파 신호가 떠 진입 → 데드캣 바운스에 속음
  - 고정 k=0.5 는 노이즈 많은 장에서 휩쏘에 취약

본 구현 (Gemini/Claude 합의안):
  1) 주봉 추세 인터락 — 일봉 기준 35일 MA (≈ 5주 MA) 아래면 진입 전면 차단
  2) 동적 K — 최근 5봉 평균 노이즈 비율을 [k_min, k_max] 범위로 선형 매핑
     노이즈 비율 = 1 - |close - open| / (high - low)
     꼬리 긴 박스권 장세(노이즈 ↑) → K ↑ (문턱 높여 거짓 돌파 차단)
     몸통 큰 추세 장세(노이즈 ↓) → K ↓ (민감하게 반응)
  3) 익일 청산 — 다음 봉에서 무조건 SELL (오버나잇 리스크 0, 포지션 누적 버그 방지)

일봉 전용 권장. 4h 등 하위 TF 도 동작은 하되 의도된 설계 아님.
"""

from __future__ import annotations

import pandas as pd

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class VolatilityBreakoutV2(Strategy):
    name = "volatility_breakout_v2"

    def __init__(self, params: dict, symbol: str, timeframe: str, **kwargs) -> None:
        # 기본값을 super() 호출 전에 초기화 (상태 복원 순서 보장).
        self._entered_bar: int | None = None
        super().__init__(params, symbol, timeframe, **kwargs)

        self.use_dynamic_k = bool(params.get("use_dynamic_k", True))
        self.k_static = float(params.get("k", 0.5))
        self.k_min = float(params.get("k_min", 0.3))
        self.k_max = float(params.get("k_max", 0.8))
        self.noise_period = int(params.get("noise_period", 5))

        self.use_macro_filter = bool(params.get("use_macro_filter", True))
        self.macro_ma_period = int(params.get("macro_ma_period", 35))

        if not (0 < self.k_static < 2):
            raise ValueError(f"k 는 0~2 범위여야 함: {self.k_static}")
        if not (0 < self.k_min < self.k_max < 2):
            raise ValueError(
                f"0 < k_min < k_max < 2 필요: min={self.k_min}, max={self.k_max}"
            )
        if self.noise_period <= 0 or self.macro_ma_period <= 0:
            raise ValueError("noise_period, macro_ma_period 는 양수")

    # ---- 상태 영속화 훅 ----
    def get_state(self) -> dict:
        return {"had_position": self._entered_bar is not None}

    def set_state(self, state: dict) -> None:
        self._entered_bar = -1 if state.get("had_position") else None

    def warmup_bars(self) -> int:
        base = max(self.noise_period + 1, 2)
        if self.use_macro_filter:
            base = max(base, self.macro_ma_period + 1)
        return base

    def status_snapshot(self, history: pd.DataFrame) -> str:
        if len(history) < self.warmup_bars():
            return f"{self.name} 워밍업 {len(history)}/{self.warmup_bars()}봉"
        close = float(history["close"].iloc[-1])
        prev = history.iloc[-2]
        prev_range = float(prev["high"]) - float(prev["low"])
        k = self._compute_dynamic_k(history) if self.use_dynamic_k else self.k_static
        last_open = float(history["open"].iloc[-1])
        target = last_open + k * prev_range
        gap = (close - target) / target * 100 if target else 0.0
        macro_ok = True
        macro_tag = "-"
        if self.use_macro_filter:
            ma = history["close"].rolling(self.macro_ma_period).mean().iloc[-1]
            if pd.isna(ma):
                macro_ok = False
                macro_tag = f"MA{self.macro_ma_period} NaN"
            else:
                macro_ok = close > ma
                macro_tag = (
                    f"MA{self.macro_ma_period} "
                    f"{'ABOVE' if macro_ok else 'BELOW'}"
                )
        pos_tag = "보유 중" if self._entered_bar is not None else "無포지션"
        return (
            f"{self.name} | close={close:.2f} | target={target:.2f} "
            f"({gap:+.2f}%) | k={k:.3f} | {macro_tag} | {pos_tag}"
        )

    def _compute_dynamic_k(self, history: pd.DataFrame) -> float:
        """최근 noise_period 봉의 평균 노이즈 비율로 K 를 선형 매핑."""
        recent = history.iloc[-self.noise_period - 1 : -1]  # 현재 봉 제외
        highs = recent["high"].astype(float)
        lows = recent["low"].astype(float)
        closes = recent["close"].astype(float)
        opens = recent["open"].astype(float)
        ranges = (highs - lows).replace(0, 1e-9)
        bodies = (closes - opens).abs()
        noise_ratios = 1.0 - (bodies / ranges)
        avg_noise = float(noise_ratios.clip(0, 1).mean())
        k = self.k_min + (self.k_max - self.k_min) * avg_noise
        return max(self.k_min, min(self.k_max, k))

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

        # 익일 청산 (포지션 누적 방지, 오버나잇 리스크 0)
        if self._entered_bar is not None and current_idx > self._entered_bar:
            self._entered_bar = None
            return Signal(
                type=SignalType.SELL,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="변동성 돌파 v2 익일 청산",
            )

        # 주봉 추세 인터락 — 거시 하락장 진입 원천 차단
        if self.use_macro_filter:
            ma = history["close"].rolling(self.macro_ma_period).mean().iloc[-1]
            if pd.isna(ma) or bar.close <= ma:
                return Signal(
                    type=SignalType.HOLD,
                    symbol=self.symbol,
                    timestamp=bar.timestamp,
                    price=bar.close,
                    reason=(
                        f"거시 추세 미달 (close={bar.close:.2f} ≤ "
                        f"MA{self.macro_ma_period}={ma:.2f})"
                        if not pd.isna(ma)
                        else "MA 미준비"
                    ),
                )

        # K 결정 — 동적 or 고정
        if self.use_dynamic_k:
            k = self._compute_dynamic_k(history)
        else:
            k = self.k_static

        prev = history.iloc[-2]
        prev_range = float(prev["high"]) - float(prev["low"])
        target = bar.open + k * prev_range

        if bar.close > target and self._entered_bar is None:
            self._entered_bar = current_idx
            return Signal(
                type=SignalType.BUY,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason=(
                    f"변동성 돌파 v2 (close={bar.close:.2f} > target={target:.2f}, "
                    f"k={k:.3f})"
                ),
            )

        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
            reason=f"대기 (target={target:.2f}, k={k:.3f})",
        )
