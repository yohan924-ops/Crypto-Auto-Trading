"""CLI 엔트리 포인트."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

app = typer.Typer(
    name="tradingbot",
    help="코인 자동매매 봇 (규칙 기반 알고리즘 트레이딩)",
    no_args_is_help=True,
    add_completion=False,
)


def _register_strategies() -> None:
    """레지스트리에 내장 전략들을 등록하기 위한 side-effect import."""
    from tradingbot.strategies import (
        buy_and_hold,  # noqa: F401
        ma_crossover,  # noqa: F401
    )


def _parse_date(value: str) -> datetime:
    """YYYY-MM-DD 또는 ISO8601 문자열을 UTC datetime 으로 변환."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError as exc:
        raise typer.BadParameter(f"날짜 형식이 올바르지 않음: {value!r}") from exc


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
    from loguru import logger

    from tradingbot.broker.paper import PaperBroker
    from tradingbot.config import load_settings
    from tradingbot.data.feed import LiveDataFeed
    from tradingbot.engine.runner import Runner
    from tradingbot.exchange.ccxt_adapter import CCXTAdapter
    from tradingbot.logging_setup import setup_logging
    from tradingbot.portfolio.portfolio import Portfolio
    from tradingbot.portfolio.risk import RiskManager
    from tradingbot.strategies.registry import get as get_strategy

    _register_strategies()
    setup_logging()
    settings = load_settings(config)

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
def backtest(
    config: Path = typer.Option(
        Path("config/settings.yaml"),
        "--config",
        "-c",
        help="설정 YAML 경로",
    ),
    start: str = typer.Option(..., "--start", help="시작 날짜 (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--end", help="종료 날짜 (YYYY-MM-DD, 미포함)"),
    save_curve: Path | None = typer.Option(
        None,
        "--save-curve",
        help="에쿼티 커브 CSV 저장 경로 (지정 시만 저장)",
    ),
) -> None:
    """백테스트 모드 (과거 OHLCV 데이터로 전략 시뮬레이션)."""
    from loguru import logger

    from tradingbot.config import load_settings
    from tradingbot.data.historical import fetch_historical
    from tradingbot.engine.backtester import Backtester
    from tradingbot.exchange.ccxt_adapter import CCXTAdapter
    from tradingbot.logging_setup import setup_logging
    from tradingbot.portfolio.risk import RiskManager
    from tradingbot.strategies.registry import get as get_strategy

    _register_strategies()
    setup_logging()
    settings = load_settings(config)
    start_dt = _parse_date(start)
    end_dt = _parse_date(end)

    logger.info(
        "백테스트 시작: {s} {tf} {start}~{end} 전략={strat}",
        s=settings.symbol,
        tf=settings.timeframe,
        start=start_dt.date(),
        end=end_dt.date(),
        strat=settings.strategy.name,
    )

    exchange = CCXTAdapter(
        exchange_id=settings.exchange.id,
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        sandbox=settings.exchange.sandbox,
    )

    df = fetch_historical(
        exchange=exchange,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
        start=start_dt,
        end=end_dt,
    )
    if df.empty:
        typer.echo("해당 구간의 과거 데이터가 없습니다.")
        raise typer.Exit(code=1)

    strategy_cls = get_strategy(settings.strategy.name)
    strategy = strategy_cls(
        params=settings.strategy.params,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
    )

    backtester = Backtester(
        symbol=settings.symbol,
        timeframe=settings.timeframe,
        strategy=strategy,
        starting_cash=settings.starting_cash,
        fee_bps=settings.fee_bps,
        slippage_bps=settings.slippage_bps,
        risk=RiskManager(max_position_pct=settings.risk.max_position_pct),
    )
    result = backtester.run(df)
    typer.echo(result.summary())

    if save_curve is not None:
        save_curve.parent.mkdir(parents=True, exist_ok=True)
        result.equity_curve.to_csv(save_curve, index=False)
        typer.echo(f"에쿼티 커브 저장: {save_curve}")


@app.command()
def live() -> None:
    """실전 모드 (실제 자산 주문). 이중 게이트 필요."""
    typer.echo("[live] 아직 구현되지 않음. Phase 4에서 추가 예정.")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
