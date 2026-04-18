"""기술적 지표 헬퍼."""

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


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index) — Wilder 방식.

    일반적 해석:
      - 30 이하: 과매도(oversold), 반등 기대
      - 70 이상: 과매수(overbought), 조정 기대

    반환: 0~100 범위의 Series. 초기 ``period`` 구간은 NaN.
    """
    if period <= 0:
        raise ValueError(f"period must be positive: {period}")
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder 의 이동평균 = EMA(alpha=1/period)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)
