"""공용 테스트 픽스처: 합성 OHLCV 생성."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tradingbot.strategies.base import Bar


def _synthetic_ohlcv(
    n: int = 100,
    start: datetime | None = None,
    timeframe_minutes: int = 60,
    trend: str = "up",
    seed: int = 42,
) -> pd.DataFrame:
    """단위 테스트용 합성 OHLCV.

    trend: 'up' | 'down' | 'sideways'
    """
    rng = np.random.default_rng(seed)
    start = start or datetime(2024, 1, 1, tzinfo=UTC)

    if trend == "up":
        drift = 0.002
    elif trend == "down":
        drift = -0.002
    else:
        drift = 0.0

    noise = rng.normal(0, 0.005, size=n)
    log_returns = drift + noise
    close = 100.0 * np.exp(np.cumsum(log_returns))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.003, size=n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.003, size=n))
    volume = rng.uniform(10, 100, size=n)

    ts = [start + timedelta(minutes=timeframe_minutes * i) for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


@pytest.fixture
def synthetic_ohlcv():
    return _synthetic_ohlcv


@pytest.fixture
def sample_bar() -> Bar:
    return Bar(
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
    )
