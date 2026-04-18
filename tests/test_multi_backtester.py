"""멀티 자산 백테스터 테스트."""

from __future__ import annotations

import pytest

from tradingbot.engine.multi_backtester import (
    MultiAssetBacktester,
    PortfolioItem,
)
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies import (
    buy_and_hold,  # noqa: F401
    ma_crossover,  # noqa: F401
)
from tradingbot.strategies.registry import get as get_strategy


def _make_items(synthetic_ohlcv, specs):
    """specs = [(symbol, strat_name, params, weight, trend, n, seed), ...]"""
    items = []
    for sym, name, params, weight, trend, n, seed in specs:
        cls = get_strategy(name)
        strat = cls(params=params, symbol=sym, timeframe="1h")
        df = synthetic_ohlcv(n=n, trend=trend, seed=seed)
        items.append(PortfolioItem(symbol=sym, strategy=strat, weight=weight, df=df))
    return items


def test_multi_backtester_runs_and_reports(synthetic_ohlcv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    items = _make_items(
        synthetic_ohlcv,
        [
            ("BTC/USDT", "buy_and_hold", {}, 0.5, "up", 100, 1),
            ("ETH/USDT", "buy_and_hold", {}, 0.5, "up", 100, 2),
        ],
    )
    mbt = MultiAssetBacktester(
        items=items,
        timeframe="1h",
        starting_cash=10_000.0,
        fee_bps=10.0,
        slippage_bps=5.0,
        risk=RiskManager(max_position_pct=0.3, stop_loss_pct=0.99, max_daily_loss_pct=0.99),
    )
    result = mbt.run()
    assert result.num_events == 200  # 100 x 2 symbols
    assert "BTC/USDT" in result.per_symbol
    assert "ETH/USDT" in result.per_symbol
    # 각 심볼에서 buy-and-hold 한 번씩 체결
    assert result.per_symbol["BTC/USDT"]["num_trades"] >= 1
    assert result.per_symbol["ETH/USDT"]["num_trades"] >= 1
    assert result.total_return_pct != 0  # 상승장이라 변화 있어야 함


def test_multi_backtester_summary_contains_sections(synthetic_ohlcv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    items = _make_items(
        synthetic_ohlcv,
        [
            ("BTC/USDT", "ma_crossover", {"fast": 10, "slow": 30}, 0.5, "up", 150, 7),
            ("ETH/USDT", "buy_and_hold", {}, 0.5, "down", 150, 7),
        ],
    )
    mbt = MultiAssetBacktester(
        items=items,
        timeframe="1h",
        starting_cash=10_000.0,
        fee_bps=10.0,
        slippage_bps=5.0,
        risk=RiskManager(max_position_pct=0.3, stop_loss_pct=0.99, max_daily_loss_pct=0.99),
    )
    result = mbt.run()
    summary = result.summary()
    assert "멀티 자산 백테스트" in summary
    assert "심볼별 요약" in summary
    assert "BTC/USDT" in summary
    assert "ETH/USDT" in summary


def test_weights_affect_position_size(synthetic_ohlcv, tmp_path, monkeypatch):
    """같은 전략·데이터에서 weight 가 크면 더 큰 포지션을 가진다."""
    monkeypatch.chdir(tmp_path)

    def _equity_and_trades(weight: float):
        items = _make_items(
            synthetic_ohlcv,
            [("BTC/USDT", "buy_and_hold", {}, weight, "up", 50, 42)],
        )
        mbt = MultiAssetBacktester(
            items=items,
            timeframe="1h",
            starting_cash=10_000.0,
            fee_bps=0.0,
            slippage_bps=0.0,
            risk=RiskManager(
                max_position_pct=0.5, stop_loss_pct=0.99, max_daily_loss_pct=0.99
            ),
        )
        return mbt.run()

    r_small = _equity_and_trades(weight=0.2)
    r_large = _equity_and_trades(weight=0.8)
    # weight 가 큰 쪽이 체결 명목액이 더 크다
    notional_small = sum(f.amount * f.price for f in r_small.trades)
    notional_large = sum(f.amount * f.price for f in r_large.trades)
    assert notional_large > notional_small


def test_empty_portfolio_rejected():
    with pytest.raises(ValueError):
        MultiAssetBacktester(
            items=[],
            timeframe="1h",
            starting_cash=10_000.0,
            fee_bps=0.0,
            slippage_bps=0.0,
            risk=RiskManager(),
        )
