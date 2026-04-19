"""Heartbeat 시스템 테스트.

- NotifyEvent.HEARTBEAT 가 지정 시각에 발송되는지
- 같은 (date, hour) 중복 발송 방지
- disabled 시 미발송
- Strategy.status_snapshot 기본/오버라이드 동작
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd
import pytest

from tradingbot.broker.paper import PaperBroker
from tradingbot.data.feed import bar_from_row
from tradingbot.engine.runner import Runner
from tradingbot.notifier.base import Notifier, NotifyEvent
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies import buy_and_hold, swing_pullback  # noqa: F401 registry
from tradingbot.strategies.base import Bar, Strategy
from tradingbot.strategies.registry import get as get_strategy


class CapturingNotifier(Notifier):
    name = "capture"

    def __init__(self) -> None:
        self.events: list[tuple[NotifyEvent, str]] = []

    def notify(self, event: NotifyEvent, message: str, **context) -> None:
        self.events.append((event, message))


def _bars_from_df(df) -> Iterator[Bar]:
    for _, row in df.iterrows():
        yield bar_from_row(row)


def test_strategy_base_status_snapshot_default(synthetic_ohlcv):
    df = synthetic_ohlcv(n=30, trend="up")
    strategy_cls = get_strategy("buy_and_hold")
    strategy = strategy_cls(params={}, symbol="BTC/USDT", timeframe="1h")
    # buy_and_hold 는 warmup=1. 30봉 있으니 워밍업 통과
    msg = strategy.status_snapshot(df)
    assert "buy_and_hold" in msg


def test_strategy_base_status_snapshot_warmup(synthetic_ohlcv):
    """워밍업 미달 상황에서 워밍업 진행도 표시."""
    df = synthetic_ohlcv(n=5, trend="up")
    strategy_cls = get_strategy("swing_pullback")
    strategy = strategy_cls(
        params={"macro_ema_period": 50},  # warmup 은 macro_ema+1 이 최대
        symbol="BTC/USDT",
        timeframe="4h",
    )
    msg = strategy.status_snapshot(df.head(3))
    assert "워밍업" in msg
    assert "3" in msg


def test_swing_pullback_status_snapshot_rich(synthetic_ohlcv):
    df = synthetic_ohlcv(n=400, trend="up")
    strategy_cls = get_strategy("swing_pullback")
    strategy = strategy_cls(
        params={"macro_ema_period": 50},
        symbol="BTC/USDT",
        timeframe="4h",
    )
    msg = strategy.status_snapshot(df)
    # 상승 추세 합성 데이터이므로 EMA ABOVE / ST UP 근처
    assert "close=" in msg
    assert "RSI=" in msg
    assert "MACDh=" in msg
    assert "ST=" in msg


def test_heartbeat_disabled_no_events(synthetic_ohlcv, tmp_path, monkeypatch):
    """heartbeat_enabled=False 이면 HEARTBEAT 알림이 나오지 않아야 함."""
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=10, trend="up")
    strategy_cls = get_strategy("buy_and_hold")
    strategy = strategy_cls(params={}, symbol="BTC/USDT", timeframe="1h")
    cap = CapturingNotifier()

    runner = Runner(
        symbol="BTC/USDT",
        strategy=strategy,
        broker=PaperBroker(fee_bps=10.0, slippage_bps=5.0),
        portfolio=Portfolio(starting_cash=10_000.0),
        risk=RiskManager(max_position_pct=0.10),
        bar_stream=_bars_from_df(df),
        notifiers=[cap],
        heartbeat_enabled=False,
    )
    runner.run()

    assert not any(ev == NotifyEvent.HEARTBEAT for ev, _ in cap.events)


def test_heartbeat_fires_at_configured_hour(synthetic_ohlcv, tmp_path, monkeypatch):
    """현재 시각이 heartbeat_hours_utc 중 하나면 1회 발송."""
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=10, trend="up")
    strategy_cls = get_strategy("buy_and_hold")
    strategy = strategy_cls(params={}, symbol="BTC/USDT", timeframe="1h")
    cap = CapturingNotifier()

    runner = Runner(
        symbol="BTC/USDT",
        strategy=strategy,
        broker=PaperBroker(fee_bps=10.0, slippage_bps=5.0),
        portfolio=Portfolio(starting_cash=10_000.0),
        risk=RiskManager(max_position_pct=0.10),
        bar_stream=_bars_from_df(df),
        notifiers=[cap],
        heartbeat_enabled=True,
        heartbeat_hours_utc=[12],
    )
    # 모든 bar 처리 시 datetime.now 가 12:xx UTC 를 리턴하도록 패치
    fake_now = datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC)
    with patch("tradingbot.engine.runner.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        runner.run()

    hb_events = [m for ev, m in cap.events if ev == NotifyEvent.HEARTBEAT]
    assert len(hb_events) == 1, f"Heartbeat 은 1회만 발송돼야 함 (실제 {len(hb_events)})"
    assert "자산" in hb_events[0]
    assert "2026-04-19 12:00 UTC" in hb_events[0]


def test_heartbeat_no_fire_outside_hours(synthetic_ohlcv, tmp_path, monkeypatch):
    """현재 시각이 hours_utc 외라면 발송 안 함."""
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=10, trend="up")
    strategy_cls = get_strategy("buy_and_hold")
    strategy = strategy_cls(params={}, symbol="BTC/USDT", timeframe="1h")
    cap = CapturingNotifier()

    runner = Runner(
        symbol="BTC/USDT",
        strategy=strategy,
        broker=PaperBroker(fee_bps=10.0, slippage_bps=5.0),
        portfolio=Portfolio(starting_cash=10_000.0),
        risk=RiskManager(max_position_pct=0.10),
        bar_stream=_bars_from_df(df),
        notifiers=[cap],
        heartbeat_enabled=True,
        heartbeat_hours_utc=[0, 12],  # 지금 15시면 해당 없음
    )
    fake_now = datetime(2026, 4, 19, 15, 30, 0, tzinfo=UTC)
    with patch("tradingbot.engine.runner.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        runner.run()

    hb_events = [ev for ev, _ in cap.events if ev == NotifyEvent.HEARTBEAT]
    assert hb_events == []


def test_heartbeat_status_snapshot_failure_handled(synthetic_ohlcv, tmp_path, monkeypatch):
    """status_snapshot 에서 예외 터져도 heartbeat 메시지는 발송돼야 함."""
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=10, trend="up")

    class BrokenStrategy(Strategy):
        name = "broken"

        def warmup_bars(self) -> int:
            return 1

        def on_bar(self, bar, history):
            from tradingbot.strategies.base import Signal, SignalType
            return Signal(
                type=SignalType.HOLD,
                symbol=self.symbol,
                timestamp=bar.timestamp,
                price=bar.close,
            )

        def status_snapshot(self, history: pd.DataFrame) -> str:
            raise RuntimeError("지표 계산 실패")

    strategy = BrokenStrategy(params={}, symbol="BTC/USDT", timeframe="1h")
    cap = CapturingNotifier()

    runner = Runner(
        symbol="BTC/USDT",
        strategy=strategy,
        broker=PaperBroker(fee_bps=10.0, slippage_bps=5.0),
        portfolio=Portfolio(starting_cash=10_000.0),
        risk=RiskManager(max_position_pct=0.10),
        bar_stream=_bars_from_df(df),
        notifiers=[cap],
        heartbeat_enabled=True,
        heartbeat_hours_utc=[12],
    )
    fake_now = datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC)
    with patch("tradingbot.engine.runner.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        runner.run()

    hb_events = [m for ev, m in cap.events if ev == NotifyEvent.HEARTBEAT]
    assert len(hb_events) == 1
    assert "상태 스냅샷 실패" in hb_events[0]
