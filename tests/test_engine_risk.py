"""엔진 + 리스크 통합: 손절·서킷브레이커 트리거가 실제로 동작하는지 확인."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from tradingbot.broker.paper import PaperBroker
from tradingbot.engine.backtester import Backtester
from tradingbot.engine.core import append_bar, process_bar
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies import buy_and_hold  # noqa: F401 registry
from tradingbot.strategies.base import Bar, SignalType
from tradingbot.strategies.registry import get as get_strategy


def _make_df(closes: list[float]) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "timestamp": start + timedelta(hours=i),
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(rows)


def test_stop_loss_liquidates_position(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # buy_and_hold → 첫 봉에서 매수. 이후 가격이 -10% 떨어지면 손절 트리거.
    closes = [100.0, 100.0, 95.0, 92.0, 88.0]  # -12% down from entry
    df = _make_df(closes)

    strategy_cls = get_strategy("buy_and_hold")
    strategy = strategy_cls(params={}, symbol="BTC/USDT", timeframe="1h")
    backtester = Backtester(
        symbol="BTC/USDT",
        timeframe="1h",
        strategy=strategy,
        starting_cash=10_000.0,
        fee_bps=0.0,
        slippage_bps=0.0,
        risk=RiskManager(
            max_position_pct=0.50, stop_loss_pct=0.05, max_daily_loss_pct=0.50
        ),
    )
    result = backtester.run(df)
    # 매수 1회 + 손절 매도 1회 = 2 trades
    assert result.num_trades == 2
    # 마지막 봉에서 포지션이 0 이어야 함 (손절 청산 후)
    last = result.equity_curve.iloc[-1]
    assert last["position"] == 0.0


def test_circuit_breaker_blocks_new_buy():
    """서킷브레이커가 켜진 상태에서는 새 BUY 시그널이 차단되어야 함."""
    rm = RiskManager(
        max_position_pct=0.5,
        stop_loss_pct=0.99,  # 손절 비활성화 수준
        max_daily_loss_pct=0.01,  # 1% 넘기면 halt
    )
    portfolio = Portfolio(starting_cash=10_000.0)
    broker = PaperBroker(fee_bps=0.0, slippage_bps=0.0)
    strategy_cls = get_strategy("buy_and_hold")
    strategy = strategy_cls(params={}, symbol="BTC/USDT", timeframe="1h")

    history = pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )

    # 첫 봉: 자산 10000 기준 day 시작, 매수 수행
    t0 = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    bar0 = Bar(timestamp=t0, open=100.0, high=100.0, low=100.0, close=100.0, volume=1.0)
    append_bar(history, bar0)
    out0 = process_bar(
        bar0,
        history,
        symbol="BTC/USDT",
        strategy=strategy,
        broker=broker,
        portfolio=portfolio,
        risk=rm,
    )
    assert out0.fill is not None
    assert out0.signal.type == SignalType.BUY

    # 둘째 봉: 가격 급락 → equity 감소 → 서킷브레이커 발동
    t1 = t0 + timedelta(hours=1)
    bar1 = Bar(timestamp=t1, open=90.0, high=90.0, low=90.0, close=90.0, volume=1.0)
    append_bar(history, bar1)
    process_bar(
        bar1,
        history,
        symbol="BTC/USDT",
        strategy=strategy,
        broker=broker,
        portfolio=portfolio,
        risk=rm,
    )
    # halted 상태여야 함
    assert rm.halted is True


def test_dry_run_does_not_submit_order():
    rm = RiskManager(max_position_pct=0.1, stop_loss_pct=0.99, max_daily_loss_pct=0.99)
    portfolio = Portfolio(starting_cash=10_000.0)
    broker = PaperBroker(fee_bps=0.0, slippage_bps=0.0)
    strategy_cls = get_strategy("buy_and_hold")
    strategy = strategy_cls(params={}, symbol="BTC/USDT", timeframe="1h")

    history = pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    t0 = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    bar0 = Bar(timestamp=t0, open=100.0, high=100.0, low=100.0, close=100.0, volume=1.0)
    append_bar(history, bar0)
    out = process_bar(
        bar0,
        history,
        symbol="BTC/USDT",
        strategy=strategy,
        broker=broker,
        portfolio=portfolio,
        risk=rm,
        dry_run=True,
    )
    # 시그널은 나오고 주문도 만들어지지만 체결은 없음
    assert out.signal is not None
    assert out.order is not None
    assert out.fill is None
    assert out.dry_run is True
    # 현금은 변하지 않아야 함
    assert portfolio.cash == 10_000.0
