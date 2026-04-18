"""지표 테스트 (SMA / EMA / RSI)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.utils.indicators import ema, rsi, sma


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
