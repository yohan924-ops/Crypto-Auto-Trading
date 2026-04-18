"""RSI Reversal 전략 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from tradingbot.strategies.base import Bar, SignalType
from tradingbot.strategies.rsi_reversal import RSIReversal


def _closes_to_df(closes: list[float]) -> tuple[list[Bar], pd.DataFrame]:
    bars: list[Bar] = []
    rows = []
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for i, c in enumerate(closes):
        ts = start + timedelta(hours=i)
        bars.append(Bar(timestamp=ts, open=c, high=c, low=c, close=c, volume=1.0))
        rows.append({"timestamp": ts, "open": c, "high": c, "low": c, "close": c, "volume": 1.0})
    return bars, pd.DataFrame(rows)


def _run_strategy(strat, closes: list[float]):
    bars, df = _closes_to_df(closes)
    sigs = []
    for i, bar in enumerate(bars):
        history = df.iloc[: i + 1].reset_index(drop=True)
        sigs.append(strat.on_bar(bar, history))
    return sigs


def test_rejects_invalid_thresholds():
    with pytest.raises(ValueError):
        RSIReversal(params={"oversold": 70, "overbought": 30}, symbol="X", timeframe="1h")
    with pytest.raises(ValueError):
        RSIReversal(params={"oversold": -1}, symbol="X", timeframe="1h")


def test_hold_during_warmup():
    strat = RSIReversal(
        params={"period": 5, "oversold": 30, "overbought": 70},
        symbol="X",
        timeframe="1h",
    )
    # warmup_bars = period + 2 = 7
    bars, df = _closes_to_df([100.0] * 6)  # 6 바 → warmup 미달
    for i, bar in enumerate(bars):
        history = df.iloc[: i + 1].reset_index(drop=True)
        assert strat.on_bar(bar, history).type == SignalType.HOLD


def test_buy_signal_on_oversold_cross():
    strat = RSIReversal(
        params={"period": 5, "oversold": 30, "overbought": 70},
        symbol="X",
        timeframe="1h",
    )
    # 초반 상승 → RSI 높게 유지 → 급락으로 RSI 30 아래로 돌파
    closes = [100, 101, 102, 103, 104, 105, 106, 107, 90, 80, 75, 70, 65]
    signals = _run_strategy(strat, closes)
    assert any(s.type == SignalType.BUY for s in signals)


def test_sell_signal_on_overbought_cross():
    strat = RSIReversal(
        params={"period": 5, "oversold": 30, "overbought": 70},
        symbol="X",
        timeframe="1h",
    )
    # 초반 하락 → RSI 낮게 → 급등으로 RSI 70 위로 돌파
    closes = [100, 99, 98, 97, 96, 95, 94, 93, 110, 120, 130, 140, 150]
    signals = _run_strategy(strat, closes)
    assert any(s.type == SignalType.SELL for s in signals)


def test_warmup_bars_is_period_plus_two():
    strat = RSIReversal(params={"period": 14}, symbol="X", timeframe="1h")
    assert strat.warmup_bars() == 16


def test_strategy_registered():
    from tradingbot.strategies.registry import get

    cls = get("rsi_reversal")
    assert cls is RSIReversal
