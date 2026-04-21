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
import pytest

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
    # 새 메시지 포맷: "✅ 매수 체결\nBTC ...\n거래금..."
    assert "매수 체결" in fill_events[0]
    assert "BTC" in fill_events[0]
    # 평단가 표시 확인 (수수료 포함 실효가)
    assert "평단가" in fill_events[0] or "평단" in fill_events[0]


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
    # 새 포맷: "📊 YYYY-MM-DD 일일 결산"
    assert "일일 결산" in daily_events[0]
    assert "매매" in daily_events[0]
    assert "총자산" in daily_events[0]


# ---------- 통화 포맷 헬퍼 ----------


def test_currency_symbol_usdt_is_dollar():
    from tradingbot.engine.sleeve_runner import _currency_symbol

    assert _currency_symbol("BTC/USDT") == "$"
    assert _currency_symbol("ETH/USDC") == "$"
    assert _currency_symbol("BTC/USD") == "$"


def test_currency_symbol_krw_is_won():
    from tradingbot.engine.sleeve_runner import _currency_symbol

    assert _currency_symbol("BTC/KRW") == "₩"
    assert _currency_symbol("ETH/KRW") == "₩"


def test_currency_symbol_unknown_quote_fallback():
    from tradingbot.engine.sleeve_runner import _currency_symbol

    # 미지 quote 는 "코드 " 형태로 fallback
    assert _currency_symbol("BTC/XYZ") == "XYZ "


def test_fmt_money_krw_no_decimal():
    from tradingbot.engine.sleeve_runner import _fmt_money

    # KRW 는 소수점 없음
    assert _fmt_money(1234567.89, "BTC/KRW") == "₩1,234,568"


def test_fmt_money_usdt_two_decimals():
    from tradingbot.engine.sleeve_runner import _fmt_money

    assert _fmt_money(1234.567, "BTC/USDT") == "$1,234.57"


def test_fmt_money_negative_value():
    from tradingbot.engine.sleeve_runner import _fmt_money

    # 손실 금액 표시
    assert "-" in _fmt_money(-123.45, "BTC/USDT")


# ---------- 평단가 수수료 포함 ----------


def test_fill_message_shows_effective_avg_price_with_fee(tmp_path, monkeypatch):
    """매수 체결 시 메시지에 수수료 포함 평단가가 표시돼야."""
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

    # 포지션 평단가 확인 — 수수료 반영됐는지
    pos = s_btc.portfolio.get_position("BTC/USDT")
    # fill.price 는 슬리피지 5bps 포함됨. 평단은 여기에 수수료 10bps 더 더해진 실효가.
    # PaperBroker: actual_fill_price = 50000 * 1.0005 = 50025 (slippage)
    # fee = 50025 * amount * 0.001
    # avg_price = 50025 * amount + fee) / amount = 50025 * 1.001 ≈ 50075
    assert pos.avg_price > 50000.0
    # 실효가 = slip+fee 합쳐 약 0.15% 위
    assert pos.avg_price == pytest.approx(50000.0 * 1.0015, rel=0.001)


# ---------- Heartbeat 상세 ----------


def test_heartbeat_shows_pnl_percent_per_sleeve(tmp_path, monkeypatch):
    """Heartbeat 메시지에 자산별 수익률(%) 표시."""
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
    fake_now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    with patch("tradingbot.engine.sleeve_runner.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        runner.run()

    hb = [m for ev, m in cap.events if ev == NotifyEvent.HEARTBEAT][0]
    # 수익률 퍼센트 포맷 확인 (+0.00% 또는 -X.XX%)
    import re
    assert re.search(r"[+-]\d+\.\d{2}%", hb), f"수익률 % 표시 없음: {hb}"
    assert "총자산" in hb
    assert "BTC" in hb
    # 보유 중이면 평단 표시, 현금 대기면 "현금 대기"
    assert "평단" in hb or "현금 대기" in hb
