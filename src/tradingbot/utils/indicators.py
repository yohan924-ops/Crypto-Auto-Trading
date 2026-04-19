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


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD (Moving Average Convergence Divergence).

    표준 파라미터(12/26/9) 는 일봉 기준 제럴드 아펠 1979 원본.
    크립토 1h/4h 에서도 관습적으로 그대로 사용.

    반환: (macd_line, signal_line, histogram)
      - macd_line   = EMA(fast) - EMA(slow)
      - signal_line = EMA(signal) of macd_line
      - histogram   = macd_line - signal_line  (양수=상승 모멘텀)
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("fast/slow/signal 모두 양수여야 함")
    if fast >= slow:
        raise ValueError(f"fast({fast}) 는 slow({slow}) 보다 작아야 함")
    ema_fast = series.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = series.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def volume_ma(volume: pd.Series, period: int = 20) -> pd.Series:
    """거래량 이동평균. 현재 봉 volume 을 이 값과 비교해 "거래 동반" 판정."""
    if period <= 0:
        raise ValueError(f"period must be positive: {period}")
    return volume.rolling(window=period, min_periods=period).mean()


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 10,
    multiplier: float = 3.0,
) -> tuple[pd.Series, pd.Series]:
    """Supertrend (Olivier Seban 2007) — ATR 기반 동적 추세선.

    반환: (trend, line)
      - trend: +1 = 상승 추세 (close 가 밴드 하단을 지지로), -1 = 하락 추세
      - line : 현재 추세선 가격 (up 일 때는 lower band, down 일 때는 upper band)

    표준 파라미터 (10, 3). ATR multiplier 가 커질수록 민감도↓/노이즈↓.
    크립토 4h~1d 스윙 매매에 표준적으로 인용.
    """
    if period <= 0:
        raise ValueError(f"period must be positive: {period}")
    if multiplier <= 0:
        raise ValueError(f"multiplier must be positive: {multiplier}")

    atr_series = atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr_series
    basic_lower = hl2 - multiplier * atr_series

    n = len(close)
    final_upper = pd.Series([float("nan")] * n, index=close.index)
    final_lower = pd.Series([float("nan")] * n, index=close.index)
    trend = pd.Series([0] * n, index=close.index, dtype=int)
    line = pd.Series([float("nan")] * n, index=close.index)

    for i in range(n):
        if pd.isna(basic_upper.iloc[i]) or pd.isna(basic_lower.iloc[i]):
            continue
        if i == 0 or pd.isna(final_upper.iloc[i - 1]):
            final_upper.iloc[i] = basic_upper.iloc[i]
            final_lower.iloc[i] = basic_lower.iloc[i]
            trend.iloc[i] = 1 if close.iloc[i] > basic_upper.iloc[i] else -1
        else:
            # Upper band 는 하락 or close 가 이전 upper 를 뚫었을 때만 갱신
            if basic_upper.iloc[i] < final_upper.iloc[i - 1] or close.iloc[i - 1] > final_upper.iloc[i - 1]:
                final_upper.iloc[i] = basic_upper.iloc[i]
            else:
                final_upper.iloc[i] = final_upper.iloc[i - 1]
            # Lower band 는 상승 or close 가 이전 lower 를 뚫었을 때만 갱신
            if basic_lower.iloc[i] > final_lower.iloc[i - 1] or close.iloc[i - 1] < final_lower.iloc[i - 1]:
                final_lower.iloc[i] = basic_lower.iloc[i]
            else:
                final_lower.iloc[i] = final_lower.iloc[i - 1]
            # 추세 전환 판정
            prev_trend = trend.iloc[i - 1]
            if prev_trend == 1 and close.iloc[i] < final_lower.iloc[i]:
                trend.iloc[i] = -1
            elif prev_trend == -1 and close.iloc[i] > final_upper.iloc[i]:
                trend.iloc[i] = 1
            else:
                trend.iloc[i] = prev_trend if prev_trend != 0 else (1 if close.iloc[i] > basic_upper.iloc[i] else -1)
        line.iloc[i] = (
            final_lower.iloc[i] if trend.iloc[i] == 1 else final_upper.iloc[i]
        )
    return trend, line


def chop(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Choppiness Index (1991, Dreiss) — 시장의 횡보/추세 여부 판별.

    해석:
      - 61.8 이상: 횡보장 (chop, mean-reversion 에 유리)
      - 38.2 이하: 추세장 (trend-following 에 유리)
      - 그 사이: 애매

    반환: 0~100 범위 Series. 초기 period 구간은 NaN.
    수식: 100 × log10(Σ ATR(1) / (Max(High) - Min(Low))) / log10(period)
    """
    import numpy as np

    if period <= 0:
        raise ValueError(f"period must be positive: {period}")
    # True Range (period=1) 누적합
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    tr_sum = tr.rolling(window=period, min_periods=period).sum()
    high_max = high.rolling(window=period, min_periods=period).max()
    low_min = low.rolling(window=period, min_periods=period).min()
    range_ = high_max - low_min
    # 분모 0 방지
    safe_range = range_.replace(0, np.nan)
    return 100.0 * np.log10(tr_sum / safe_range) / np.log10(period)


def percent_b(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.Series:
    """볼린저 %B — 가격이 밴드 내 어느 위치에 있는지 0~1 스케일로 표현.

    해석:
      - %B < 0: 가격이 하단 밴드 아래 (패닉셀)
      - %B = 0: 가격이 하단 밴드
      - %B = 0.5: 가격이 중앙선
      - %B = 1: 가격이 상단 밴드
      - %B > 1: 가격이 상단 밴드 위 (과열)

    Mean Reversion 진입/청산 기준으로 사용.
    """
    middle, upper, lower = bollinger_bands(series, period, num_std)
    band_width = upper - lower
    # 분모 0 방지 (flat 구간)
    import numpy as np
    safe_width = band_width.replace(0, np.nan)
    return (series - lower) / safe_width


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
