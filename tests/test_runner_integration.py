"""Runner 통합 테스트: 합성 데이터 + buy_and_hold 로 엔드투엔드 동작 확인."""

from __future__ import annotations

from collections.abc import Iterator

from tradingbot.broker.paper import PaperBroker
from tradingbot.data.feed import bar_from_row
from tradingbot.engine.runner import Runner
from tradingbot.portfolio.portfolio import Portfolio
from tradingbot.portfolio.risk import RiskManager
from tradingbot.strategies import buy_and_hold  # noqa: F401  registry 등록
from tradingbot.strategies.base import Bar
from tradingbot.strategies.registry import get as get_strategy


def _bars_from_df(df) -> Iterator[Bar]:
    for _, row in df.iterrows():
        yield bar_from_row(row)


def test_runner_executes_buy_and_hold_end_to_end(synthetic_ohlcv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # logs/ 가 테스트 디렉터리에 생성되도록
    df = synthetic_ohlcv(n=20, trend="up")
    strategy_cls = get_strategy("buy_and_hold")
    strategy = strategy_cls(params={}, symbol="BTC/USDT", timeframe="1h")
    broker = PaperBroker(fee_bps=10.0, slippage_bps=5.0)
    portfolio = Portfolio(starting_cash=10_000.0)
    risk = RiskManager(max_position_pct=0.10)

    runner = Runner(
        symbol="BTC/USDT",
        strategy=strategy,
        broker=broker,
        portfolio=portfolio,
        risk=risk,
        bar_stream=_bars_from_df(df),
    )
    runner.run()

    # buy_and_hold 이므로 첫 봉에서 BUY, 이후 HOLD. 포지션이 잡혀 있어야 함.
    pos = portfolio.get_position("BTC/USDT")
    assert pos.amount > 0, "buy-and-hold 실행 후 포지션이 존재해야 함"
    # 현금이 시작 자금보다 작아져야 함 (매수 차감)
    assert portfolio.cash < 10_000.0
    # logs/orders.jsonl 이 생성되어 있어야 함
    assert (tmp_path / "logs" / "orders.jsonl").exists()
