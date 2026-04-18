"""Bollinger Breakout + Volatility Breakout 전략 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from tradingbot.strategies.base import Bar, SignalType
from tradingbot.strategies.bollinger_breakout import BollingerBreakout
from tradingbot.strategies.volatility_breakout import VolatilityBreakout


def _bars_from_ohlc(rows: list[tuple[float, float, float, float]]):
    """rows = [(open, high, low, close), ...]"""
    bars: list[Bar] = []
    records = []
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for i, (o, h, lo, c) in enumerate(rows):
        ts = start + timedelta(hours=i)
        bars.append(Bar(timestamp=ts, open=o, high=h, low=lo, close=c, volume=1.0))
        records.append(
            {"timestamp": ts, "open": o, "high": h, "low": lo, "close": c, "volume": 1.0}
        )
    return bars, pd.DataFrame(records)


def _closes_to_bars(closes: list[float]):
    rows = [(c, c, c, c) for c in closes]
    return _bars_from_ohlc(rows)


def _run(strategy, bars, df):
    sigs = []
    for i, bar in enumerate(bars):
        history = df.iloc[: i + 1].reset_index(drop=True)
        sigs.append(strategy.on_bar(bar, history))
    return sigs


# ------- Bollinger Breakout -------


def test_bollinger_rejects_invalid_params():
    with pytest.raises(ValueError):
        BollingerBreakout(params={"period": 0}, symbol="X", timeframe="1h")
    with pytest.raises(ValueError):
        BollingerBreakout(params={"num_std": 0}, symbol="X", timeframe="1h")


def test_bollinger_hold_during_warmup():
    strat = BollingerBreakout(
        params={"period": 5, "num_std": 2.0}, symbol="X", timeframe="1h"
    )
    bars, df = _closes_to_bars([100.0] * 5)  # 5 < period+1=6
    for s in _run(strat, bars, df):
        assert s.type == SignalType.HOLD


def test_bollinger_upper_break_emits_buy():
    strat = BollingerBreakout(
        params={"period": 5, "num_std": 2.0}, symbol="X", timeframe="1h"
    )
    # 낮은 변동성 이후 급등 → 상단 돌파
    closes = [100, 100, 100, 100, 100, 100, 100, 130]
    bars, df = _closes_to_bars(closes)
    signals = _run(strat, bars, df)
    assert SignalType.BUY in [s.type for s in signals]


def test_bollinger_lower_break_emits_sell():
    strat = BollingerBreakout(
        params={"period": 5, "num_std": 2.0}, symbol="X", timeframe="1h"
    )
    closes = [100, 100, 100, 100, 100, 100, 100, 70]
    bars, df = _closes_to_bars(closes)
    signals = _run(strat, bars, df)
    assert SignalType.SELL in [s.type for s in signals]


# ------- Volatility Breakout -------


def test_vbo_rejects_invalid_k():
    with pytest.raises(ValueError):
        VolatilityBreakout(params={"k": 0}, symbol="X", timeframe="1d")
    with pytest.raises(ValueError):
        VolatilityBreakout(params={"k": 3.0}, symbol="X", timeframe="1d")


def test_vbo_buy_then_exit_next_bar():
    strat = VolatilityBreakout(params={"k": 0.5}, symbol="X", timeframe="1d")
    # 봉0 (warmup): open=100, high=110, low=90, close=105 → range=20
    # 봉1: open=105, close=120 → target = 105 + 0.5*20 = 115. close>target → BUY
    # 봉2: 진입 익일 → 무조건 SELL
    rows = [
        (100, 110, 90, 105),
        (105, 125, 104, 120),
        (120, 125, 118, 122),
    ]
    bars, df = _bars_from_ohlc(rows)
    signals = _run(strat, bars, df)
    types = [s.type for s in signals]
    assert types[0] == SignalType.HOLD  # warmup
    assert types[1] == SignalType.BUY
    assert types[2] == SignalType.SELL


def test_vbo_no_trigger_below_target():
    strat = VolatilityBreakout(params={"k": 0.5}, symbol="X", timeframe="1d")
    # 봉1: target = 105+10=115, close=110 (미돌파)
    rows = [
        (100, 110, 90, 105),
        (105, 115, 100, 110),
    ]
    bars, df = _bars_from_ohlc(rows)
    signals = _run(strat, bars, df)
    assert signals[1].type == SignalType.HOLD


def test_new_strategies_registered():
    from tradingbot.strategies.registry import get

    assert get("bollinger_breakout").name == "bollinger_breakout"
    assert get("volatility_breakout").name == "volatility_breakout"
