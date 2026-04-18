"""가장 단순한 전략: 첫 신호로 BUY 후 계속 HOLD.

엔드투엔드 파이프라인 검증용. Phase 2에서 MA Crossover 등 실전략으로 교체.
"""

from __future__ import annotations

import pandas as pd

from .base import Bar, Signal, SignalType, Strategy
from .registry import register


@register
class BuyAndHold(Strategy):
    name = "buy_and_hold"

    def __init__(self, params: dict, symbol: str, timeframe: str, **kwargs) -> None:
        self._bought = False
        super().__init__(params, symbol, timeframe, **kwargs)

    # ---- 상태 영속화 훅 ----
    def get_state(self) -> dict:
        return {"bought": self._bought}

    def set_state(self, state: dict) -> None:
        self._bought = bool(state.get("bought", False))

    def warmup_bars(self) -> int:
        return 0

    def on_bar(self, bar: Bar, history: pd.DataFrame) -> Signal:
        if not self._bought:
            self._bought = True
            return Signal(
                type=SignalType.BUY,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
                reason="buy-and-hold 초기 진입",
            )
        return Signal(
            type=SignalType.HOLD,
            symbol=self.symbol,
            timestamp=bar.timestamp,
            price=bar.close,
        )
