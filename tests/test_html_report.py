"""HTML 리포트 생성 테스트 (파일 생성 + 필수 콘텐츠 포함)."""

from __future__ import annotations

from tradingbot.engine.backtester import Backtester
from tradingbot.portfolio.risk import RiskManager
from tradingbot.reports import render_html_report
from tradingbot.strategies import (
    buy_and_hold,  # noqa: F401
    ma_crossover,  # noqa: F401
)
from tradingbot.strategies.registry import get as get_strategy


def _make_result(synthetic_ohlcv, trend: str = "up"):
    df = synthetic_ohlcv(n=150, trend=trend)
    strategy_cls = get_strategy("ma_crossover")
    strategy = strategy_cls(
        params={"fast": 5, "slow": 20},
        symbol="BTC/USDT",
        timeframe="1h",
    )
    bt = Backtester(
        symbol="BTC/USDT",
        timeframe="1h",
        strategy=strategy,
        starting_cash=10_000.0,
        fee_bps=10.0,
        slippage_bps=5.0,
        risk=RiskManager(max_position_pct=0.30, stop_loss_pct=0.99, max_daily_loss_pct=0.99),
    )
    return bt.run(df)


def test_html_report_creates_file(tmp_path, synthetic_ohlcv, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _make_result(synthetic_ohlcv, trend="up")
    out = tmp_path / "report.html"
    render_html_report(result, strategy_name="ma_crossover", output=out)
    assert out.exists()
    assert out.stat().st_size > 5_000  # 간단한 최소 크기 체크 (Plotly CDN + 내용)


def test_html_report_contains_key_sections(tmp_path, synthetic_ohlcv, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _make_result(synthetic_ohlcv, trend="up")
    out = tmp_path / "report.html"
    render_html_report(result, strategy_name="ma_crossover", output=out)
    html = out.read_text(encoding="utf-8")
    # 주요 섹션 타이틀 포함 여부
    assert "백테스트 리포트" in html
    assert "자산 곡선" in html or "Equity" in html
    assert "월별 수익률" in html
    assert "거래 내역" in html
    # 지표 카드
    assert "총 수익률" in html
    assert "Sharpe" in html
    # Plotly div 존재
    assert "plotly" in html.lower()


def test_html_report_handles_empty_trades(tmp_path, synthetic_ohlcv, monkeypatch):
    """신호가 없을 정도로 타이트한 설정에서도 리포트가 생성되어야 함."""
    monkeypatch.chdir(tmp_path)
    df = synthetic_ohlcv(n=30, trend="sideways")
    strategy_cls = get_strategy("ma_crossover")
    strategy = strategy_cls(
        params={"fast": 5, "slow": 25},  # 거의 교차 안 나옴
        symbol="BTC/USDT",
        timeframe="1h",
    )
    bt = Backtester(
        symbol="BTC/USDT",
        timeframe="1h",
        strategy=strategy,
        starting_cash=10_000.0,
        fee_bps=10.0,
        slippage_bps=5.0,
        risk=RiskManager(max_position_pct=0.1, stop_loss_pct=0.99, max_daily_loss_pct=0.99),
    )
    result = bt.run(df)
    out = tmp_path / "empty.html"
    render_html_report(result, strategy_name="ma_crossover", output=out)
    assert out.exists()
