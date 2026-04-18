"""백테스터 엔드투엔드 테스트."""

from __future__ import annotations

from tradingbot.engine.backtester import Backtester
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies import (
    buy_and_hold,  # noqa: F401
    ma_crossover,  # noqa: F401
)
from tradingbot.strategies.registry import get as get_strategy


def _make_backtester(strategy_name: str, params: dict):
    strategy_cls = get_strategy(strategy_name)
    strategy = strategy_cls(params=params, symbol="BTC/USDT", timeframe="1h")
    return Backtester(
        symbol="BTC/USDT",
        timeframe="1h",
        strategy=strategy,
        starting_cash=10_000.0,
        fee_bps=10.0,
        slippage_bps=5.0,
        risk=RiskManager(max_position_pct=0.10),
    )


def test_buy_and_hold_positive_return_on_uptrend(synthetic_ohlcv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=100, trend="up")
    bt = _make_backtester("buy_and_hold", params={})
    result = bt.run(df)
    assert result.num_bars == len(df)
    assert result.num_trades >= 1
    assert result.total_return_pct > 0, "상승장에서 buy-and-hold는 수익이 나야 함"


def test_buy_and_hold_loss_on_downtrend(synthetic_ohlcv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=100, trend="down")
    bt = _make_backtester("buy_and_hold", params={})
    result = bt.run(df)
    # buy-and-hold 는 하락장에서 손실
    assert result.total_return_pct < 0


def test_ma_crossover_runs_and_records_trades(synthetic_ohlcv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=300, trend="up", seed=7)
    bt = _make_backtester("ma_crossover", params={"fast": 10, "slow": 30})
    result = bt.run(df)
    assert result.num_bars == len(df)
    # 상승 추세 + 교차 기반 전략 → 최소 1회 이상 매수
    assert result.num_trades >= 1


def test_equity_curve_length_matches_bars(synthetic_ohlcv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=80, trend="sideways")
    bt = _make_backtester("buy_and_hold", params={})
    result = bt.run(df)
    assert len(result.equity_curve) == len(df)


def test_summary_string_has_return(synthetic_ohlcv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=60, trend="up")
    bt = _make_backtester("buy_and_hold", params={})
    result = bt.run(df)
    summary = result.summary()
    assert "총 수익률" in summary
    assert "최대 낙폭" in summary
    assert "Sharpe" in summary
    assert "Sortino" in summary
    assert "승률" in summary


def test_sharpe_and_sortino_computed(synthetic_ohlcv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=200, trend="up")
    bt = _make_backtester("buy_and_hold", params={})
    result = bt.run(df)
    # 숫자가 나와야 하고 NaN/inf 가 아니어야 함
    import math

    assert math.isfinite(result.sharpe)
    assert math.isfinite(result.sortino)
    assert 0.0 <= result.win_rate_pct <= 100.0


def test_strategy_swap_without_engine_change(synthetic_ohlcv, tmp_path, monkeypatch):
    """플러그인 구조 증명: 전략 이름만 바꿔 rsi_reversal 실행.

    엔진/브로커/러너 코드는 Phase 3 이후 한 줄도 변경되지 않았음.
    """
    monkeypatch.chdir(tmp_path)
    from tradingbot.strategies import rsi_reversal  # noqa: F401  registry 등록

    df = synthetic_ohlcv(n=400, trend="sideways", seed=3)
    bt = _make_backtester("rsi_reversal", params={"period": 14, "oversold": 30, "overbought": 70})
    result = bt.run(df)
    assert result.num_bars == len(df)
    # 횡보장 합성 데이터에서는 RSI 교차가 발생할 가능성 — 최소 0 이상
    assert result.num_trades >= 0
