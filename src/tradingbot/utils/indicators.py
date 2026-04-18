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


def bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """볼린저 밴드. 반환: (middle, upper, lower).

    - middle = SMA(period)
    - upper = middle + num_std * std
    - lower = middle - num_std * std
    """
    if period <= 0:
        raise ValueError(f"period must be positive: {period}")
    if num_std <= 0:
        raise ValueError(f"num_std must be positive: {num_std}")
    middle = series.rolling(window=period, min_periods=period).mean()
    std = series.rolling(window=period, min_periods=period).std(ddof=0)
    return middle, middle + num_std * std, middle - num_std * std


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Average True Range — 변동성 지표, 손절 폭 계산 등에 사용."""
    if period <= 0:
        raise ValueError(f"period must be positive: {period}")
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


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
