"""MA Crossover 전략 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from tradingbot.strategies.base import Bar, SignalType
from tradingbot.strategies.ma_crossover import MACrossover


def _bars_from_closes(closes: list[float]) -> tuple[list[Bar], pd.DataFrame]:
    bars: list[Bar] = []
    rows = []
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for i, c in enumerate(closes):
        ts = start + timedelta(hours=i)
        bars.append(Bar(timestamp=ts, open=c, high=c, low=c, close=c, volume=1.0))
        rows.append(
            {
                "timestamp": ts,
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 1.0,
            }
        )
    return bars, pd.DataFrame(rows)


def _run(strategy, closes: list[float]):
    bars, df = _bars_from_closes(closes)
    signals = []
    for i, bar in enumerate(bars):
        history = df.iloc[: i + 1].reset_index(drop=True)
        signals.append(strategy.on_bar(bar, history))
    return signals


def test_rejects_fast_ge_slow():
    with pytest.raises(ValueError):
        MACrossover(params={"fast": 10, "slow": 10}, symbol="X", timeframe="1h")
    with pytest.raises(ValueError):
        MACrossover(params={"fast": 20, "slow": 10}, symbol="X", timeframe="1h")


def test_hold_during_warmup():
    strat = MACrossover(params={"fast": 3, "slow": 5}, symbol="X", timeframe="1h")
    # warmup_bars = slow + 1 = 6. 5개까지는 HOLD
    bars, df = _bars_from_closes([1, 2, 3, 4, 5])
    for i, bar in enumerate(bars):
        history = df.iloc[: i + 1].reset_index(drop=True)
        sig = strat.on_bar(bar, history)
        assert sig.type == SignalType.HOLD


def test_golden_cross_emits_buy():
    strat = MACrossover(params={"fast": 3, "slow": 5}, symbol="X", timeframe="1h")
    # 평탄 구간 이후 급등 → fast 가 slow 를 상향 돌파
    closes = [5, 5, 5, 5, 5, 5, 5, 20, 30, 40]
    signals = _run(strat, closes)
    types = [s.type for s in signals]
    assert SignalType.BUY in types


def test_dead_cross_emits_sell_after_buy():
    strat = MACrossover(params={"fast": 3, "slow": 5}, symbol="X", timeframe="1h")
    # 평탄 → 급등(골든크로스) → 급락(데드크로스)
    closes = [5, 5, 5, 5, 5, 5, 5, 20, 30, 40, 5, 5, 5]
    signals = _run(strat, closes)
    types = [s.type for s in signals]
    assert SignalType.BUY in types
    assert SignalType.SELL in types


def test_warmup_bars_is_slow_plus_one():
    strat = MACrossover(params={"fast": 20, "slow": 50}, symbol="X", timeframe="1h")
    assert strat.warmup_bars() == 51
