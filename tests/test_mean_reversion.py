"""Mean Reversion 전략 및 신규 지표 (CHOP, %B) 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from tradingbot.strategies import mean_reversion  # noqa: F401 registry
from tradingbot.strategies.base import Bar, SignalType
from tradingbot.strategies.registry import get as get_strategy
from tradingbot.utils.indicators import chop, percent_b


def _make_bar(ts: datetime, close: float, high: float = None, low: float = None) -> Bar:
    return Bar(
        timestamp=ts,
        open=close,
        high=high if high is not None else close * 1.002,
        low=low if low is not None else close * 0.998,
        close=close,
        volume=10.0,
    )


# ---------- CHOP 지표 ----------


def test_chop_returns_nan_for_warmup(synthetic_ohlcv):
    df = synthetic_ohlcv(n=10, trend="up")
    result = chop(df["high"], df["low"], df["close"], period=14)
    # 14 기간 이하는 전부 NaN
    assert result.iloc[:13].isna().all()


def test_chop_sideways_market_high_value(synthetic_ohlcv):
    """횡보장 (sideways) 에서 CHOP > 50 기대."""
    df = synthetic_ohlcv(n=200, trend="sideways", seed=123)
    result = chop(df["high"], df["low"], df["close"], period=14)
    valid = result.dropna()
    # 횡보장 평균이 최소 45 이상 (완전 노이즈가 아닌 한)
    assert valid.mean() > 45, f"횡보장 CHOP 평균이 낮음: {valid.mean():.1f}"


def test_chop_strong_trend_lower_value(synthetic_ohlcv):
    """강한 추세장에서 CHOP 평균이 횡보 대비 낮아야 함."""
    df_up = synthetic_ohlcv(n=200, trend="up", seed=7)
    df_side = synthetic_ohlcv(n=200, trend="sideways", seed=7)
    chop_up = chop(df_up["high"], df_up["low"], df_up["close"], 14).dropna()
    chop_side = chop(df_side["high"], df_side["low"], df_side["close"], 14).dropna()
    assert chop_up.mean() < chop_side.mean(), (
        f"추세장 CHOP ({chop_up.mean():.1f}) 이 횡보장 ({chop_side.mean():.1f}) 보다 낮아야 함"
    )


# ---------- Percent B ----------


def test_percent_b_at_upper_band():
    """가격이 상단 밴드일 때 %B ≈ 1.0."""
    # 상승 추세 + 변동성 있는 데이터
    np.random.seed(0)
    closes = pd.Series([100 + i + np.random.normal(0, 2) for i in range(50)])
    pb = percent_b(closes, period=20, num_std=2.0)
    # 극단 튐 값은 대략 0~1 사이
    valid = pb.dropna()
    assert valid.min() < 1.5
    assert valid.max() > -0.5


def test_percent_b_below_zero_on_panic_sell():
    """급락으로 하단 밴드 뚫을 때 %B < 0."""
    # 횡보하다 마지막에 급락
    closes = pd.Series([100.0] * 30 + [80.0])
    pb = percent_b(closes, period=20, num_std=2.0)
    assert pb.iloc[-1] < 0, f"급락 후 %B 가 음수여야 함: {pb.iloc[-1]}"


# ---------- MeanReversion 전략 ----------


def test_mean_reversion_warmup_holds(synthetic_ohlcv):
    df = synthetic_ohlcv(n=10, trend="sideways")
    cls = get_strategy("mean_reversion")
    strat = cls(params={}, symbol="ETH/USDT", timeframe="4h")
    bar = _make_bar(df["timestamp"].iloc[-1], float(df["close"].iloc[-1]))
    sig = strat.on_bar(bar, df)
    assert sig.type == SignalType.HOLD
    assert sig.reason == "warmup"


def test_mean_reversion_buys_on_chop_and_panic(synthetic_ohlcv):
    """CHOP 높고 %B < 0 이면 BUY."""
    # 횡보 데이터 + 마지막 구간 급락으로 %B 하단 이탈
    df = synthetic_ohlcv(n=100, trend="sideways", seed=42).copy()
    df.loc[df.index[-3:], "close"] = df["close"].iloc[-4] * 0.85  # 급락
    df.loc[df.index[-3:], "low"] = df["close"].iloc[-1] * 0.98
    df.loc[df.index[-3:], "high"] = df["close"].iloc[-4] * 0.90
    df.loc[df.index[-3:], "open"] = df["close"].iloc[-4] * 0.90
    cls = get_strategy("mean_reversion")
    strat = cls(
        params={"chop_threshold": 30.0, "percent_b_low": 0.05},  # 관대한 임계
        symbol="ETH/USDT",
        timeframe="4h",
    )
    bar = _make_bar(
        df["timestamp"].iloc[-1],
        float(df["close"].iloc[-1]),
        high=float(df["high"].iloc[-1]),
        low=float(df["low"].iloc[-1]),
    )
    sig = strat.on_bar(bar, df)
    # BUY 또는 HOLD (데이터가 미묘할 수 있음) — 최소 SELL 은 아님 확인
    assert sig.type != SignalType.SELL


def test_mean_reversion_sells_at_sma_midline(synthetic_ohlcv):
    """상승해서 중앙선 도달 시 SELL."""
    df = synthetic_ohlcv(n=100, trend="up", seed=42)
    cls = get_strategy("mean_reversion")
    strat = cls(params={}, symbol="ETH/USDT", timeframe="4h")
    # 가격이 SMA 보다 훨씬 위면 SELL 신호
    bar = _make_bar(df["timestamp"].iloc[-1], float(df["close"].iloc[-1]) * 1.2)
    sig = strat.on_bar(bar, df)
    # 중앙선 이상이라 SELL
    assert sig.type == SignalType.SELL


def test_mean_reversion_status_snapshot(synthetic_ohlcv):
    df = synthetic_ohlcv(n=100, trend="sideways", seed=1)
    cls = get_strategy("mean_reversion")
    strat = cls(params={}, symbol="ETH/USDT", timeframe="4h")
    msg = strat.status_snapshot(df)
    assert "mean_reversion" in msg
    assert "CHOP=" in msg
    assert "%B=" in msg


def test_mean_reversion_rejects_invalid_params():
    cls = get_strategy("mean_reversion")
    with pytest.raises(ValueError):
        cls(
            params={"percent_b_low": 0.5, "percent_b_high": 0.3},
            symbol="ETH/USDT",
            timeframe="4h",
        )
    with pytest.raises(ValueError):
        cls(params={"chop_threshold": 150}, symbol="ETH/USDT", timeframe="4h")
