"""기술적 지표 헬퍼.

Phase 2: SMA, EMA. Phase 5에서 RSI 등 추가 예정.
"""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """단순이동평균 (Simple Moving Average).

    최초 ``period - 1`` 개 값은 NaN. 길이가 부족하면 전부 NaN.
    """
    if period <= 0:
        raise ValueError(f"period must be positive: {period}")
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """지수이동평균 (Exponential Moving Average)."""
    if period <= 0:
        raise ValueError(f"period must be positive: {period}")
    return series.ewm(span=period, adjust=False, min_periods=period).mean()
