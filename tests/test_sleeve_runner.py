"""SleeveRunner 실시간 엔진 단위·통합 테스트.

- 심볼 라우팅 (올바른 sleeve 에 bar 전달)
- 자본 격리 (한 sleeve 매매가 다른 sleeve 잔고 영향 없음)
- 계좌 CB 발동 시 모든 sleeve halt
- Notifier 이벤트 발행
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd

from tradingbot.broker.paper import PaperBroker
from tradingbot.engine.sleeve import Sleeve, SleeveOrchestrator
from tradingbot.engine.sleeve_runner import SleeveRunner
from tradingbot.notifier.base import Notifier, NotifyEvent
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies import buy_and_hold  # noqa: F401 registry
from tradingbot.strategies.base import Bar
from tradingbot.strategies.registry import get as get_strategy


class CaptureNotifier(Notifier):
    name = "capture"

    def __init__(self) -> None:
        self.events: list[tuple[NotifyEvent, str]] = []

    def notify(self, event: NotifyEvent, message: str, **context) -> None:
        self.events.append((event, message))


def _make_sleeve(name: str, symbol: str, cash: float) -> Sleeve:
    strat_cls = get_strategy("buy_and_hold")
    return Sleeve(
        name=name,
        symbol=symbol,
        strategy=strat_cls(params={}, symbol=symbol, timeframe="1h"),
        portfolio=Portfolio(starting_cash=cash),
        risk=RiskManager(max_position_pct=0.30, max_daily_loss_pct=1.0),
        broker=PaperBroker(fee_bps=10.0, slippage_bps=5.0),
        allocation_pct=cash / 10_000.0,
    )


def _bar(symbol_price: float, ts: datetime) -> Bar:
    return Bar(
        timestamp=ts,
        open=symbol_price,
        high=symbol_price * 1.002,
        low=symbol_price * 0.998,
        close=symbol_price,
        volume=10.0,
    )


def _build_stream(bars: list[tuple[str, Bar]]) -> Iterator[tuple[str, Bar]]:
    return iter(bars)


# ---------- 기본 라우팅 ----------


def test_runner_routes_bars_to_correct_sleeve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s_btc = _make_sleeve("BTC", "BTC/USDT", 4000.0)
    s_eth = _make_sleeve("ETH", "ETH/USDT", 6000.0)
    orch = SleeveOrchestrator([s_btc, s_eth])

    ts = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    bars = [
        ("BTC/USDT", _bar(50000.0, ts)),
        ("ETH/USDT", _bar(3000.0, ts + timedelta(hours=1))),
        ("BTC/USDT", _bar(50100.0, ts + timedelta(hours=2))),
    ]
    runner = SleeveRunner(orchestrator=orch, bar_stream=_build_stream(bars))
    runner.run()

    # buy_and_hold 는 첫 봉에서 BUY. 두 sleeve 모두 포지션 있어야.
    assert s_btc.position_amount() > 0
    assert s_eth.position_amount() > 0


def test_runner_ignores_unknown_symbol(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s_btc = _make_sleeve("BTC", "BTC/USDT", 10_000.0)
    orch = SleeveOrchestrator([s_btc])

    ts = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    bars = [
        ("BTC/USDT", _bar(50000.0, ts)),
        ("UNKNOWN/USDT", _bar(1000.0, ts + timedelta(hours=1))),  # 무시돼야
        ("BTC/USDT", _bar(50100.0, ts + timedelta(hours=2))),
    ]
    runner = SleeveRunner(orchestrator=orch, bar_stream=_build_stream(bars))
    runner.run()

    assert s_btc.position_amount() > 0


# ---------- 자본 격리 ----------


def test_runner_preserves_capital_isolation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s_btc = _make_sleeve("BTC", "BTC/USDT", 4000.0)
    s_eth = _make_sleeve("ETH", "ETH/USDT", 6000.0)
    orch = SleeveOrchestrator([s_btc, s_eth])

    ts = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    # BTC 만 거래, ETH 는 bar 없음
    bars = [
        ("BTC/USDT", _bar(50000.0, ts)),
        ("BTC/USDT", _bar(50100.0, ts + timedelta(hours=1))),
    ]
    runner = SleeveRunner(orchestrator=orch, bar_stream=_build_stream(bars))
    runner.run()

    # ETH sleeve 는 한 번도 건드리지 않아야
    assert s_eth.cash() == 6000.0
    assert s_eth.position_amount() == 0.0


# ---------- Notifier ----------


def test_runner_emits_fill_event(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s_btc = _make_sleeve("BTC", "BTC/USDT", 10_000.0)
    orch = SleeveOrchestrator([s_btc])
    cap = CaptureNotifier()

    ts = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    bars = [("BTC/USDT", _bar(50000.0, ts))]
    runner = SleeveRunner(
        orchestrator=orch, bar_stream=_build_stream(bars), notifiers=[cap]
    )
    runner.run()

    fill_events = [m for ev, m in cap.events if ev == NotifyEvent.ORDER_FILLED]
    assert len(fill_events) == 1
    assert "[BTC]" in fill_events[0]


# ---------- Heartbeat ----------


def test_runner_heartbeat_fires_at_configured_hour(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s_btc = _make_sleeve("BTC", "BTC/USDT", 10_000.0)
    orch = SleeveOrchestrator([s_btc])
    cap = CaptureNotifier()

    ts = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    bars = [("BTC/USDT", _bar(50000.0, ts))]
    runner = SleeveRunner(
        orchestrator=orch,
        bar_stream=_build_stream(bars),
        notifiers=[cap],
        heartbeat_enabled=True,
        heartbeat_hours_utc=[12],
    )
    fake_now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    with patch("tradingbot.engine.sleeve_runner.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        runner.run()

    hb_events = [m for ev, m in cap.events if ev == NotifyEvent.HEARTBEAT]
    assert len(hb_events) == 1
    assert "BTC" in hb_events[0]


def test_runner_heartbeat_disabled_no_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s_btc = _make_sleeve("BTC", "BTC/USDT", 10_000.0)
    orch = SleeveOrchestrator([s_btc])
    cap = CaptureNotifier()

    ts = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    bars = [("BTC/USDT", _bar(50000.0, ts))]
    runner = SleeveRunner(
        orchestrator=orch,
        bar_stream=_build_stream(bars),
        notifiers=[cap],
        heartbeat_enabled=False,
    )
    runner.run()

    assert not any(ev == NotifyEvent.HEARTBEAT for ev, _ in cap.events)


# ---------- 일일 리포트 ----------


def test_runner_emits_daily_report_on_rollover(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s_btc = _make_sleeve("BTC", "BTC/USDT", 10_000.0)
    orch = SleeveOrchestrator([s_btc])
    cap = CaptureNotifier()

    ts1 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    ts2 = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)  # 다음 날
    bars = [
        ("BTC/USDT", _bar(50000.0, ts1)),
        ("BTC/USDT", _bar(50100.0, ts2)),
    ]
    runner = SleeveRunner(
        orchestrator=orch, bar_stream=_build_stream(bars), notifiers=[cap]
    )
    runner.run()

    daily_events = [m for ev, m in cap.events if ev == NotifyEvent.DAILY_REPORT]
    assert len(daily_events) >= 1
    assert "일일 리포트" in daily_events[0]
