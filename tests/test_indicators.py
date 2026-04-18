"""지표 테스트 (SMA / EMA / RSI / Bollinger / ATR)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.utils.indicators import (
    atr,
    bollinger_bands,
    ema,
    macd,
    rsi,
    sma,
    supertrend,
    volume_ma,
)


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = sma(s, period=3)
    # 첫 두 값은 NaN, 이후 (1+2+3)/3=2, (2+3+4)/3=3, (3+4+5)/3=4
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[3] == pytest.approx(3.0)
    assert result.iloc[4] == pytest.approx(4.0)


def test_sma_invalid_period():
    s = pd.Series([1.0, 2.0])
    with pytest.raises(ValueError):
        sma(s, period=0)


def test_ema_converges_to_value():
    # 일정한 값에 대해 EMA 는 결국 그 값에 수렴
    s = pd.Series([10.0] * 50)
    result = ema(s, period=5)
    assert result.iloc[-1] == pytest.approx(10.0)


def test_ema_reacts_faster_than_sma():
    # 같은 period 에서 마지막 값 변화에 EMA 가 SMA 보다 더 민감
    data = [10.0] * 20 + [20.0]
    s = pd.Series(data)
    e = ema(s, period=5).iloc[-1]
    m = sma(s, period=5).iloc[-1]
    # EMA 가 최근 값 20 에 SMA 보다 가까움
    assert abs(e - 20.0) < abs(m - 20.0)


# ------- RSI -------


def test_rsi_range_is_0_to_100():
    s = pd.Series(np.linspace(100, 200, 50) + np.random.RandomState(0).normal(0, 1, 50))
    r = rsi(s, period=14).dropna()
    assert (r >= 0).all()
    assert (r <= 100).all()


def test_rsi_pure_uptrend_is_100():
    # 계속 상승만 하면 모든 loss 가 0, RSI 가 100 에 수렴
    s = pd.Series(np.arange(1.0, 50.0))
    r = rsi(s, period=14).dropna()
    assert r.iloc[-1] == pytest.approx(100.0)


def test_rsi_pure_downtrend_is_0():
    # 계속 하락만 하면 RSI 가 0 에 수렴
    s = pd.Series(np.arange(50.0, 1.0, -1.0))
    r = rsi(s, period=14).dropna()
    assert r.iloc[-1] == pytest.approx(0.0)


def test_rsi_warmup_nan():
    s = pd.Series([100.0] * 10)
    r = rsi(s, period=14)
    # 길이 10 < period 14 → 모두 NaN
    assert r.isna().all()


def test_rsi_invalid_period():
    with pytest.raises(ValueError):
        rsi(pd.Series([1.0, 2.0]), period=0)


# ------- Bollinger -------


def test_bollinger_middle_equals_sma():
    s = pd.Series(np.linspace(1, 100, 50))
    middle, upper, lower = bollinger_bands(s, period=20, num_std=2.0)
    # middle 은 SMA 와 동일
    assert middle.iloc[-1] == pytest.approx(sma(s, 20).iloc[-1])
    # upper > middle > lower 항상 성립
    assert upper.iloc[-1] > middle.iloc[-1] > lower.iloc[-1]


def test_bollinger_constant_series_has_zero_width():
    # 모든 값이 같으면 std=0 → upper == middle == lower
    s = pd.Series([10.0] * 30)
    middle, upper, lower = bollinger_bands(s, period=10, num_std=2.0)
    assert upper.iloc[-1] == pytest.approx(middle.iloc[-1])
    assert lower.iloc[-1] == pytest.approx(middle.iloc[-1])


def test_bollinger_invalid_params():
    s = pd.Series([1.0, 2.0])
    with pytest.raises(ValueError):
        bollinger_bands(s, period=0)
    with pytest.raises(ValueError):
        bollinger_bands(s, period=10, num_std=0.0)


# ------- ATR -------


def test_atr_positive_for_ranging_market():
    # 등락이 있으면 ATR > 0
    high = pd.Series([10.0, 12.0, 11.0, 13.0, 14.0, 12.0] * 5)
    low = pd.Series([9.0, 10.0, 9.5, 11.0, 12.0, 10.0] * 5)
    close = pd.Series([9.5, 11.0, 10.0, 12.0, 13.0, 11.0] * 5)
    result = atr(high, low, close, period=14).dropna()
    assert (result > 0).all()


def test_atr_zero_for_flat_market():
    flat = pd.Series([100.0] * 30)
    result = atr(flat, flat, flat, period=14).dropna()
    # 가격 변동 없으면 ATR 은 0
    assert result.iloc[-1] == pytest.approx(0.0, abs=1e-9)


# ------- MACD -------


def test_macd_histogram_positive_on_uptrend():
    # 꾸준한 상승: EMA(12) > EMA(26) → macd_line > 0 → 히스토그램 양수로 수렴
    s = pd.Series(np.linspace(100.0, 200.0, 100))
    line, sig, hist = macd(s)
    assert line.iloc[-1] > 0
    assert hist.iloc[-1] > 0


def test_macd_histogram_negative_on_downtrend():
    s = pd.Series(np.linspace(200.0, 100.0, 100))
    line, _, hist = macd(s)
    assert line.iloc[-1] < 0
    assert hist.iloc[-1] < 0


def test_macd_warmup_nan():
    # slow=26 + signal=9 = 34 봉 이하에서는 signal/hist 가 NaN
    s = pd.Series(np.arange(1.0, 20.0))
    _, sig, hist = macd(s)
    assert sig.isna().all()
    assert hist.isna().all()


def test_macd_rejects_invalid_params():
    s = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        macd(s, fast=0)
    with pytest.raises(ValueError):
        macd(s, fast=20, slow=10)  # fast >= slow


# ------- Volume MA -------


def test_volume_ma_matches_simple_mean():
    v = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    result = volume_ma(v, period=3)
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(20.0)
    assert result.iloc[4] == pytest.approx(40.0)


def test_volume_ma_invalid_period():
    with pytest.raises(ValueError):
        volume_ma(pd.Series([1.0]), period=0)


# ------- Supertrend -------


def test_supertrend_follows_uptrend():
    # 꾸준한 상승 → trend 최종값 +1
    high = pd.Series(np.linspace(101.0, 201.0, 80))
    low = pd.Series(np.linspace(99.0, 199.0, 80))
    close = pd.Series(np.linspace(100.0, 200.0, 80))
    trend, line = supertrend(high, low, close, period=10, multiplier=3.0)
    # 최종 상태는 상승 추세
    assert trend.iloc[-1] == 1
    # 상승 추세일 때 line 은 lower band (종가 아래)
    assert line.iloc[-1] < close.iloc[-1]


def test_supertrend_follows_downtrend():
    high = pd.Series(np.linspace(201.0, 101.0, 80))
    low = pd.Series(np.linspace(199.0, 99.0, 80))
    close = pd.Series(np.linspace(200.0, 100.0, 80))
    trend, line = supertrend(high, low, close, period=10, multiplier=3.0)
    assert trend.iloc[-1] == -1
    # 하락 추세일 때 line 은 upper band (종가 위)
    assert line.iloc[-1] > close.iloc[-1]


def test_supertrend_invalid_params():
    s = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        supertrend(s, s, s, period=0)
    with pytest.raises(ValueError):
        supertrend(s, s, s, multiplier=0)
