"""Swing Pullback 전략 최소 검증."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tradingbot.strategies import swing_pullback  # noqa: F401
from tradingbot.strategies.base import Bar, SignalType
from tradingbot.strategies.registry import get as get_strategy


def _make_history(closes, highs=None, lows=None):
    n = len(closes)
    if highs is None:
        highs = [c * 1.002 for c in closes]
    if lows is None:
        lows = [c * 0.998 for c in closes]
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        rows.append(
            {
                "timestamp": start + timedelta(hours=4 * i),
                "open": closes[i - 1] if i > 0 else closes[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": 100.0,
            }
        )
    return pd.DataFrame(rows)


def _bar(row) -> Bar:
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


def _new(**overrides):
    cls = get_strategy("swing_pullback")
    params = {
        "macro_ema_period": 40,  # 테스트 빠르게
        "st_period": 10,
        "st_multiplier": 3.0,
        "rsi_period": 14,
        "rsi_pullback_low": 40.0,
        "rsi_pullback_high": 45.0,
        "rsi_overbought": 70.0,
        "macd_fast": 6,
        "macd_slow": 13,
        "macd_signal": 5,
    }
    params.update(overrides)
    return cls(params=params, symbol="BTC/USDT", timeframe="4h")


def test_registered():
    assert get_strategy("swing_pullback").name == "swing_pullback"


def test_warmup_hold():
    strat = _new()
    h = _make_history([100.0] * 10)
    sig = strat.on_bar(_bar(h.iloc[-1]), h)
    assert sig.type == SignalType.HOLD and "warmup" in sig.reason


def test_rejects_invalid_params():
    cls = get_strategy("swing_pullback")
    with pytest.raises(ValueError):
        cls(params={"rsi_pullback_low": 50, "rsi_pullback_high": 40},
            symbol="BTC/USDT", timeframe="4h")
    with pytest.raises(ValueError):
        cls(params={"st_multiplier": 0}, symbol="BTC/USDT", timeframe="4h")


def test_downtrend_no_buy():
    strat = _new()
    closes = np.linspace(200.0, 100.0, 120).tolist()
    h = _make_history(closes)
    buys = 0
    for i in range(strat.warmup_bars(), len(h)):
        sub = h.iloc[: i + 1].reset_index(drop=True)
        sig = strat.on_bar(_bar(sub.iloc[-1]), sub)
        if sig.type == SignalType.BUY:
            buys += 1
    assert buys == 0


def test_supertrend_flip_triggers_sell():
    strat = _new()
    # 강한 상승 후 가파른 하락 → Supertrend 반전
    closes = np.linspace(100.0, 200.0, 100).tolist() + np.linspace(200.0, 140.0, 40).tolist()
    h = _make_history(closes)
    found_sell = False
    for i in range(strat.warmup_bars(), len(h)):
        sub = h.iloc[: i + 1].reset_index(drop=True)
        sig = strat.on_bar(_bar(sub.iloc[-1]), sub)
        if sig.type == SignalType.SELL and "Supertrend" in sig.reason:
            found_sell = True
            break
    assert found_sell


# NOTE: BUY 발생 시나리오는 합성 데이터로 정확히 재현하기 까다로워
# (RSI pullback 구간·MACD 양전환·Supertrend UP 이 한 봉에 정렬돼야 함),
# 실제 BTC OHLCV 백테스트(bt_swing_pullback.yaml) 로 검증한다.
