"""CLI 엔트리 포인트."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    name="tradingbot",
    help="코인 자동매매 봇 (규칙 기반 알고리즘 트레이딩)",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def paper(
    config: Path = typer.Option(
        Path("config/settings.yaml"),
        "--config",
        "-c",
        help="설정 YAML 경로",
    ),
    max_bars: int = typer.Option(
        0,
        "--max-bars",
        help="지정 시 해당 개수의 봉 처리 후 종료 (0 = 무제한)",
    ),
) -> None:
    """페이퍼 트레이딩 모드 (실시간 시세 + 가상 잔고)."""
    # 지연 import: CLI --help 만 실행할 때 의존성 로드를 피하기 위함
    from tradingbot.config import load_settings
    from tradingbot.data.feed import LiveDataFeed
    from tradingbot.engine.runner import Runner
    from tradingbot.exchange.ccxt_adapter import CCXTAdapter
    from tradingbot.logging_setup import setup_logging
    from tradingbot.portfolio.portfolio import Portfolio
    from tradingbot.portfolio.risk import RiskManager
    from tradingbot.strategies import buy_and_hold  # noqa: F401 registry 등록
    from tradingbot.strategies.registry import get as get_strategy

    setup_logging()
    settings = load_settings(config)

    from loguru import logger

    logger.info("페이퍼 모드 시작: {s} {tf}", s=settings.symbol, tf=settings.timeframe)

    exchange = CCXTAdapter(
        exchange_id=settings.exchange.id,
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        sandbox=settings.exchange.sandbox,
    )

    strategy_cls = get_strategy(settings.strategy.name)
    strategy = strategy_cls(
        params=settings.strategy.params,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
    )

    portfolio = Portfolio(starting_cash=settings.starting_cash)
    risk = RiskManager(max_position_pct=settings.risk.max_position_pct)

    from tradingbot.broker.paper import PaperBroker

    broker = PaperBroker(fee_bps=settings.fee_bps, slippage_bps=settings.slippage_bps)

    warmup = max(strategy.warmup_bars(), 5)
    feed = LiveDataFeed(
        exchange=exchange,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
        warmup_bars=warmup,
        max_bars=max_bars if max_bars > 0 else None,
    )

    runner = Runner(
        symbol=settings.symbol,
        strategy=strategy,
        broker=broker,
        portfolio=portfolio,
        risk=risk,
        bar_stream=feed.stream_bars(),
    )
    runner.run()


@app.command()
def backtest() -> None:
    """백테스트 모드 (과거 데이터 시뮬레이션)."""
    typer.echo("[backtest] 아직 구현되지 않음. Phase 2에서 추가 예정.")
    raise typer.Exit(code=1)


@app.command()
def live() -> None:
    """실전 모드 (실제 자산 주문). 이중 게이트 필요."""
    typer.echo("[live] 아직 구현되지 않음. Phase 4에서 추가 예정.")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
