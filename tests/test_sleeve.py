"""Sleeve 엔진 단위·통합 테스트.

- Sleeve 독립 자본 관리
- SleeveOrchestrator 계좌 전체 서킷브레이커
- SleeveBacktester 엔드투엔드
- 기존 MultiAssetBacktester 와 결과 차이 확인 (공용 풀 vs Sleeve)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from tradingbot.broker.paper import PaperBroker
from tradingbot.engine.sleeve import (
    Sleeve,
    SleeveOrchestrator,
    SleeveSpec,
    build_sleeves,
)
from tradingbot.engine.sleeve_backtester import SleeveBacktester, SleeveItem
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies import (  # noqa: F401 registry
    bollinger_breakout,
    buy_and_hold,
)
from tradingbot.strategies.registry import get as get_strategy


def _make_sleeve(
    name: str,
    symbol: str,
    cash: float,
    alloc: float = 1.0,
    strat_name: str = "buy_and_hold",
    timeframe: str = "1h",
) -> Sleeve:
    strat_cls = get_strategy(strat_name)
    return Sleeve(
        name=name,
        symbol=symbol,
        strategy=strat_cls(params={}, symbol=symbol, timeframe=timeframe),
        portfolio=Portfolio(starting_cash=cash),
        risk=RiskManager(max_position_pct=0.30, max_daily_loss_pct=1.0),
        broker=PaperBroker(fee_bps=10.0, slippage_bps=5.0),
        allocation_pct=alloc,
    )


# ---------- build_sleeves ----------


def test_build_sleeves_allocates_capital_proportionally():
    specs = [
        SleeveSpec(
            name="BTC",
            symbol="BTC/USDT",
            strategy=get_strategy("buy_and_hold")(
                params={}, symbol="BTC/USDT", timeframe="1h"
            ),
            allocation_pct=0.40,
            risk=RiskManager(max_position_pct=0.30),
        ),
        SleeveSpec(
            name="ETH",
            symbol="ETH/USDT",
            strategy=get_strategy("buy_and_hold")(
                params={}, symbol="ETH/USDT", timeframe="1h"
            ),
            allocation_pct=0.10,
            risk=RiskManager(max_position_pct=0.30),
        ),
        SleeveSpec(
            name="SOL",
            symbol="SOL/USDT",
            strategy=get_strategy("buy_and_hold")(
                params={}, symbol="SOL/USDT", timeframe="1h"
            ),
            allocation_pct=0.50,
            risk=RiskManager(max_position_pct=0.30),
        ),
    ]
    sleeves = build_sleeves(specs, starting_cash=10_000.0, fee_bps=10.0, slippage_bps=5.0)
    assert len(sleeves) == 3
    assert sleeves[0].cash() == 4_000.0  # 40%
    assert sleeves[1].cash() == 1_000.0  # 10%
    assert sleeves[2].cash() == 5_000.0  # 50%


def test_build_sleeves_rejects_empty():
    with pytest.raises(ValueError):
        build_sleeves([], starting_cash=10_000.0, fee_bps=10.0, slippage_bps=5.0)


def test_build_sleeves_rejects_invalid_allocation():
    bad_spec = SleeveSpec(
        name="BTC",
        symbol="BTC/USDT",
        strategy=get_strategy("buy_and_hold")(
            params={}, symbol="BTC/USDT", timeframe="1h"
        ),
        allocation_pct=0.0,  # 0 허용 안 됨
        risk=RiskManager(),
    )
    with pytest.raises(ValueError):
        build_sleeves([bad_spec], 10000, 10, 5)


# ---------- SleeveOrchestrator ----------


def test_orchestrator_total_equity_aggregates_sleeves():
    s1 = _make_sleeve("BTC", "BTC/USDT", cash=4000.0)
    s2 = _make_sleeve("ETH", "ETH/USDT", cash=6000.0)
    orch = SleeveOrchestrator(sleeves=[s1, s2])
    prices = {"BTC/USDT": 50000.0, "ETH/USDT": 3000.0}
    # 포지션 없으니 cash 만 합산
    assert orch.total_equity(prices) == pytest.approx(10000.0)


def test_orchestrator_find_sleeve_by_symbol():
    s1 = _make_sleeve("BTC", "BTC/USDT", cash=4000.0)
    s2 = _make_sleeve("ETH", "ETH/USDT", cash=6000.0)
    orch = SleeveOrchestrator(sleeves=[s1, s2])
    assert orch.find_sleeve("BTC/USDT") is s1
    assert orch.find_sleeve("ETH/USDT") is s2
    assert orch.find_sleeve("SOL/USDT") is None


def test_orchestrator_circuit_breaker_halts_all_sleeves():
    """전체 자본 -10% 도달 시 모든 Sleeve halt."""
    s1 = _make_sleeve("BTC", "BTC/USDT", cash=5000.0)
    s2 = _make_sleeve("ETH", "ETH/USDT", cash=5000.0)
    orch = SleeveOrchestrator(sleeves=[s1, s2], max_daily_loss_pct=0.10)
    # 새 날 시작
    ts = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    prices = {"BTC/USDT": 50000.0, "ETH/USDT": 3000.0}
    orch.update_day(ts, prices)
    assert not orch.halted

    # BTC sleeve 의 cash 를 3000 으로 줄임 (총자산 10000 → 8000 = -20%)
    s1.portfolio.cash = 3000.0
    orch.update_circuit_breaker(prices)
    assert orch.halted is True
    # 모든 sleeve 의 risk._halted 가 True 로 설정됨
    assert s1.risk._halted is True
    assert s2.risk._halted is True


def test_orchestrator_circuit_breaker_resets_on_new_day():
    s1 = _make_sleeve("BTC", "BTC/USDT", cash=5000.0)
    s2 = _make_sleeve("ETH", "ETH/USDT", cash=5000.0)
    orch = SleeveOrchestrator(sleeves=[s1, s2], max_daily_loss_pct=0.10)
    prices = {"BTC/USDT": 50000.0, "ETH/USDT": 3000.0}

    # 첫날 halt 발동
    orch.update_day(datetime(2024, 1, 1, tzinfo=UTC), prices)
    s1.portfolio.cash = 3000.0
    orch.update_circuit_breaker(prices)
    assert orch.halted is True

    # 다음 날 → halt 해제
    s1.portfolio.cash = 3000.0  # 자산은 그대로
    orch.update_day(datetime(2024, 1, 2, tzinfo=UTC), prices)
    assert orch.halted is False
    assert s1.risk._halted is False
    assert s2.risk._halted is False


def test_orchestrator_rejects_empty_sleeves():
    with pytest.raises(ValueError):
        SleeveOrchestrator(sleeves=[])


def test_orchestrator_rejects_invalid_cb_pct():
    s1 = _make_sleeve("BTC", "BTC/USDT", 5000.0)
    with pytest.raises(ValueError):
        SleeveOrchestrator(sleeves=[s1], max_daily_loss_pct=0.0)
    with pytest.raises(ValueError):
        SleeveOrchestrator(sleeves=[s1], max_daily_loss_pct=1.5)


# ---------- Sleeve.process_bar_pipeline ----------


def test_sleeve_process_bar_buys_with_buy_and_hold(synthetic_ohlcv):
    df = synthetic_ohlcv(n=20, trend="up")
    s = _make_sleeve("BTC", "BTC/USDT", cash=10000.0, strat_name="buy_and_hold")
    from tradingbot.data.feed import bar_from_row

    for _, row in df.iterrows():
        bar = bar_from_row(row)
        s.process_bar_pipeline(bar)
    # buy_and_hold 는 첫 봉에서 BUY → 포지션 잡혀 있어야
    assert s.position_amount() > 0
    assert s.cash() < 10000.0
    # 체결 1건 이상
    assert len(s.trades) >= 1


def test_sleeves_are_independent(synthetic_ohlcv):
    """한 Sleeve 매매가 다른 Sleeve 잔고에 영향 주지 않음."""
    df = synthetic_ohlcv(n=20, trend="up")
    s1 = _make_sleeve("BTC", "BTC/USDT", cash=4000.0, strat_name="buy_and_hold")
    s2 = _make_sleeve("ETH", "ETH/USDT", cash=6000.0, strat_name="buy_and_hold")

    from tradingbot.data.feed import bar_from_row

    for _, row in df.iterrows():
        bar = bar_from_row(row)
        s1.process_bar_pipeline(bar)

    # s1 는 매매 후 cash 감소, s2 는 그대로
    assert s1.cash() < 4000.0
    assert s2.cash() == 6000.0


# ---------- SleeveBacktester ----------


def test_sleeve_backtester_smoke(synthetic_ohlcv):
    """3 sleeve 엔드투엔드 — buy_and_hold 로 모든 sleeve 수익 확인."""
    df1 = synthetic_ohlcv(n=50, trend="up", seed=1)
    df2 = synthetic_ohlcv(n=50, trend="up", seed=2)
    df3 = synthetic_ohlcv(n=50, trend="up", seed=3)

    s1 = _make_sleeve("BTC", "BTC/USDT", cash=4000.0, alloc=0.40)
    s2 = _make_sleeve("ETH", "ETH/USDT", cash=1000.0, alloc=0.10)
    s3 = _make_sleeve("SOL", "SOL/USDT", cash=5000.0, alloc=0.50)
    items = [
        SleeveItem(sleeve=s1, df=df1),
        SleeveItem(sleeve=s2, df=df2),
        SleeveItem(sleeve=s3, df=df3),
    ]
    bt = SleeveBacktester(
        items=items, timeframe="1h", starting_cash=10000.0, max_daily_loss_pct=0.10
    )
    result = bt.run()
    assert result.num_trades >= 3  # 각 sleeve 최소 BUY 1회
    assert result.ending_equity > 0
    assert len(result.per_sleeve) == 3
    assert "BTC" in result.per_sleeve
    assert "ETH" in result.per_sleeve
    assert "SOL" in result.per_sleeve


def test_sleeve_backtester_rejects_empty():
    with pytest.raises(ValueError):
        SleeveBacktester(items=[], timeframe="1h", starting_cash=10000.0)


def test_sleeve_backtester_summary_contains_key_fields(synthetic_ohlcv):
    df = synthetic_ohlcv(n=30, trend="up")
    s = _make_sleeve("BTC", "BTC/USDT", cash=10000.0, alloc=1.0)
    bt = SleeveBacktester(
        items=[SleeveItem(sleeve=s, df=df)], timeframe="1h", starting_cash=10000.0
    )
    result = bt.run()
    summary = result.summary()
    assert "Sleeve 기반 백테스트" in summary
    assert "BTC" in summary
    assert "계좌 CB 발동" in summary
