"""Pullback 전략 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tradingbot.strategies import pullback  # noqa: F401  registry 등록
from tradingbot.strategies.base import Bar, SignalType
from tradingbot.strategies.registry import get as get_strategy


def _make_history(closes, volumes=None, highs=None, lows=None):
    n = len(closes)
    if volumes is None:
        volumes = [100.0] * n
    if highs is None:
        highs = [c * 1.001 for c in closes]
    if lows is None:
        lows = [c * 0.999 for c in closes]
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        rows.append(
            {
                "timestamp": start + timedelta(hours=i),
                "open": closes[i - 1] if i > 0 else closes[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i],
            }
        )
    return pd.DataFrame(rows)


def _bar_from_row(row) -> Bar:
    return Bar(
        timestamp=row["timestamp"].to_pydatetime()
        if hasattr(row["timestamp"], "to_pydatetime")
        else row["timestamp"],
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
    )


def _new_strategy(**overrides):
    cls = get_strategy("pullback")
    params = {
        "ema_period": 15,  # 테스트 빠르게
        "rsi_period": 14,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "use_bb_lower": True,
        "bb_period": 20,
        "bb_num_std": 2.0,
        "macd_fast": 6,
        "macd_slow": 13,
        "macd_signal": 5,
        "require_volume": True,
        "vol_period": 10,
        "vol_mult": 1.0,
    }
    params.update(overrides)
    return cls(params=params, symbol="BTC/USDT", timeframe="1h")


def test_registered():
    cls = get_strategy("pullback")
    assert cls.name == "pullback"


def test_rejects_invalid_params():
    cls = get_strategy("pullback")
    with pytest.raises(ValueError):
        cls(params={"ema_period": 0}, symbol="BTC/USDT", timeframe="1h")
    with pytest.raises(ValueError):
        cls(params={"rsi_oversold": 70, "rsi_overbought": 30}, symbol="BTC/USDT", timeframe="1h")
    with pytest.raises(ValueError):
        cls(params={"macd_fast": 20, "macd_slow": 10}, symbol="BTC/USDT", timeframe="1h")


def test_warmup_hold():
    strat = _new_strategy()
    history = _make_history([100.0] * 10)
    bar = _bar_from_row(history.iloc[-1])
    sig = strat.on_bar(bar, history)
    assert sig.type == SignalType.HOLD
    assert "warmup" in sig.reason


def test_downtrend_blocks_buy():
    """거시 하락 추세(close < EMA) 에서는 어떤 조건에서도 BUY 안 나와야 함."""
    strat = _new_strategy()
    # 계속 하락
    closes = np.linspace(200.0, 100.0, 80).tolist()
    history = _make_history(closes)
    # 모든 봉 순회하며 BUY 가 한 번이라도 나오면 실패
    buys = 0
    for i in range(strat.warmup_bars(), len(history)):
        sub = history.iloc[: i + 1].reset_index(drop=True)
        bar = _bar_from_row(sub.iloc[-1])
        sig = strat.on_bar(bar, sub)
        if sig.type == SignalType.BUY:
            buys += 1
    assert buys == 0, f"하락장에서 BUY 발생 {buys}회 — 추세 필터 실패"


def test_uptrend_with_pullback_then_rebound_triggers_buy():
    """현실적 노이즈 섞인 상승 → 눌림 → 반등 시 BUY 한 번은 나와야 함."""
    strat = _new_strategy(rsi_oversold=40.0, require_volume=False)
    rng = np.random.RandomState(42)
    # 80봉 노이즈 상승 (drift +0.3%, 변동성 1.5%)
    closes = [100.0]
    for _ in range(80):
        r = 0.003 + rng.normal(0, 0.015)
        closes.append(closes[-1] * (1 + r))
    # 15봉 급락 (-2%/봉) → RSI 과매도 + BB 하단 돌파 유도
    for _ in range(15):
        closes.append(closes[-1] * 0.980)
    # 30봉 반등 (+1.5%/봉) → MACD 양전환
    for _ in range(30):
        closes.append(closes[-1] * 1.015)
    history = _make_history(closes)

    found_buy = False
    for i in range(strat.warmup_bars(), len(history)):
        sub = history.iloc[: i + 1].reset_index(drop=True)
        bar = _bar_from_row(sub.iloc[-1])
        sig = strat.on_bar(bar, sub)
        if sig.type == SignalType.BUY:
            found_buy = True
            assert "눌림목 반등" in sig.reason
            break
    assert found_buy, "상승 눌림목 시나리오에서 BUY 가 한 번은 나와야 함"


def test_overbought_emits_sell():
    """RSI 과매수 영역 돌파 시 SELL 발생."""
    strat = _new_strategy(rsi_overbought=70.0)
    # 꾸준한 강한 상승 → RSI 결국 70 돌파
    closes = np.linspace(100.0, 300.0, 100).tolist()
    history = _make_history(closes)
    found_sell = False
    for i in range(strat.warmup_bars(), len(history)):
        sub = history.iloc[: i + 1].reset_index(drop=True)
        bar = _bar_from_row(sub.iloc[-1])
        sig = strat.on_bar(bar, sub)
        if sig.type == SignalType.SELL:
            found_sell = True
            assert "과매수" in sig.reason
            break
    assert found_sell


def test_macd_flip_without_pullback_does_not_buy():
    """눌림목(RSI 과매도 또는 BB 하단) 없이 MACD만 양전환 된다고 BUY 안 됨."""
    strat = _new_strategy(use_bb_lower=False)  # BB 하단 경로 차단
    # 완만 상승만 (RSI 30 깨지는 구간 없음)
    closes = np.linspace(100.0, 130.0, 80).tolist()
    history = _make_history(closes, volumes=[200.0] * 80)
    buys = 0
    for i in range(strat.warmup_bars(), len(history)):
        sub = history.iloc[: i + 1].reset_index(drop=True)
        bar = _bar_from_row(sub.iloc[-1])
        sig = strat.on_bar(bar, sub)
        if sig.type == SignalType.BUY:
            buys += 1
    assert buys == 0, "눌림목 없는 상승장에서 BUY 안 나와야 함"
