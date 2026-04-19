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
        bollinger_breakout,  # noqa: F401
        buy_and_hold,  # noqa: F401
        ma_crossover,  # noqa: F401
        mean_reversion,  # noqa: F401
        pullback,  # noqa: F401
        rsi_reversal,  # noqa: F401
        rsi_reversal_v2,  # noqa: F401
        swing_pullback,  # noqa: F401
        triple_screen,  # noqa: F401
        volatility_breakout,  # noqa: F401
        volatility_breakout_v2,  # noqa: F401
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
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="주문을 제출하지 않고 결정 로그만 출력",
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
    from tradingbot.notifier import build_notifiers
    from tradingbot.portfolio.portfolio import Portfolio
    from tradingbot.portfolio.risk import RiskManager
    from tradingbot.strategies.registry import get as get_strategy

    _register_strategies()
    setup_logging()
    settings = load_settings(config)

    logger.info("페이퍼 모드 시작: {s} {tf}", s=settings.symbol, tf=settings.timeframe)

    # paper 모드는 내부 PaperBroker 가 주문을 시뮬레이션하므로 거래소 주문 API
    # 경로를 전혀 밟지 않는다 → API 키 불필요.
    # 오히려 키를 넘기면 CCXT 가 public endpoint 에도 인증 헤더를 붙여
    # "Testnet 키 × Mainnet 접속" 같은 조합에서 AuthenticationError 발생.
    exchange = CCXTAdapter(
        exchange_id=settings.exchange.id,
        api_key=None,
        api_secret=None,
        sandbox=settings.exchange.sandbox,
    )

    strategy_cls = get_strategy(settings.strategy.name)
    strategy = strategy_cls(
        params=settings.strategy.params,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
        state_path=Path("logs/strategy_state_paper.json"),
    )

    portfolio = Portfolio(starting_cash=settings.starting_cash)
    risk = RiskManager(
        max_position_pct=settings.risk.max_position_pct,
        stop_loss_pct=settings.risk.stop_loss_pct,
        max_daily_loss_pct=settings.risk.max_daily_loss_pct,
        trailing_stop_pct=settings.risk.trailing_stop_pct,
        trailing_activate_pct=settings.risk.trailing_activate_pct,
        state_path=Path("logs/risk_state_paper.json"),
    )
    broker = PaperBroker(fee_bps=settings.fee_bps, slippage_bps=settings.slippage_bps)
    notifiers = build_notifiers(
        settings.notifiers,
        telegram_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
    )

    warmup = max(strategy.warmup_bars(), 5)

    # Testnet 은 과거 데이터 제한적(약 17일). 장기 지표(예: EMA 300) warmup 을
    # 즉시 달성하도록 Mainnet public API 에서 backfill 만 받아온다.
    # 주문·실시간 피드는 여전히 Testnet.
    backfill_exchange = None
    if settings.exchange.sandbox:
        try:
            backfill_exchange = CCXTAdapter(
                exchange_id=settings.exchange.id,
                api_key=None,  # public endpoint 만 쓰므로 키 불필요
                api_secret=None,
                sandbox=False,  # mainnet public API
            )
            logger.info(
                "backfill_exchange 활성: {} mainnet 에서 과거 봉만 받아옵니다.",
                settings.exchange.id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mainnet backfill_exchange 생성 실패 — Testnet 만 사용: {}", exc
            )

    if settings.use_websocket and settings.exchange.id != "binance":
        logger.warning(
            "use_websocket=true 이지만 현재 거래소({})는 WebSocket 지원이 Binance 전용이라 REST 폴링으로 동작합니다.",
            settings.exchange.id,
        )
    if settings.use_websocket and settings.exchange.id == "binance":
        from tradingbot.data.ws_feed import BinanceWebSocketFeed

        feed = BinanceWebSocketFeed(
            symbol=settings.symbol,
            timeframe=settings.timeframe,
            sandbox=settings.exchange.sandbox,
            warmup_bars=warmup,
            max_bars=max_bars if max_bars > 0 else None,
            backfill_exchange=exchange,
        )
    else:
        feed = LiveDataFeed(
            exchange=exchange,
            symbol=settings.symbol,
            timeframe=settings.timeframe,
            warmup_bars=warmup,
            max_bars=max_bars if max_bars > 0 else None,
            backfill_exchange=backfill_exchange,
        )

    runner = Runner(
        symbol=settings.symbol,
        strategy=strategy,
        broker=broker,
        portfolio=portfolio,
        risk=risk,
        bar_stream=feed.stream_bars(),
        notifiers=notifiers,
        dry_run=dry_run,
        heartbeat_enabled=settings.heartbeat.enabled,
        heartbeat_hours_utc=settings.heartbeat.hours_utc,
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
    save_report: Path | None = typer.Option(
        None,
        "--save-report",
        help="Plotly HTML 리포트 저장 경로 (지정 시 차트 포함)",
    ),
) -> None:
    """백테스트 모드 (과거 OHLCV 데이터로 전략 시뮬레이션)."""
    import pandas as pd
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

    exchange = CCXTAdapter(
        exchange_id=settings.exchange.id,
        api_key=settings.exchange_api_key,
        api_secret=settings.exchange_api_secret,
        sandbox=settings.exchange.sandbox,
    )

    risk = RiskManager(
        max_position_pct=settings.risk.max_position_pct,
        stop_loss_pct=settings.risk.stop_loss_pct,
        max_daily_loss_pct=settings.risk.max_daily_loss_pct,
        trailing_stop_pct=settings.risk.trailing_stop_pct,
        trailing_activate_pct=settings.risk.trailing_activate_pct,
        use_atr_stop=settings.risk.use_atr_stop,
        atr_multiplier=settings.risk.atr_multiplier,
    )

    # Sleeve 기반 모드 감지 (최우선)
    if settings.sleeves:
        from tradingbot.engine.sleeve import SleeveSpec, build_sleeves
        from tradingbot.engine.sleeve_backtester import (
            SleeveBacktester,
            SleeveItem,
        )

        logger.info(
            "Sleeve 백테스트: {n}개 sleeve {tf} {start}~{end}",
            n=len(settings.sleeves),
            tf=settings.timeframe,
            start=start_dt.date(),
            end=end_dt.date(),
        )

        specs: list[SleeveSpec] = []
        dfs: dict[str, pd.DataFrame] = {}
        for sv in settings.sleeves:
            df_sym = fetch_historical(
                exchange=exchange,
                symbol=sv.symbol,
                timeframe=settings.timeframe,
                start=start_dt,
                end=end_dt,
            )
            if df_sym.empty:
                typer.echo(f"{sv.symbol} 과거 데이터 없음. 스킵.")
                continue
            dfs[sv.symbol] = df_sym
            strat_cls = get_strategy(sv.strategy.name)
            strat = strat_cls(
                params=sv.strategy.params,
                symbol=sv.symbol,
                timeframe=settings.timeframe,
            )
            sleeve_risk = RiskManager(
                max_position_pct=sv.risk.max_position_pct,
                stop_loss_pct=sv.risk.stop_loss_pct,
                max_daily_loss_pct=sv.risk.max_daily_loss_pct,
                trailing_stop_pct=sv.risk.trailing_stop_pct,
                trailing_activate_pct=sv.risk.trailing_activate_pct,
                use_atr_stop=sv.risk.use_atr_stop,
                atr_multiplier=sv.risk.atr_multiplier,
            )
            specs.append(
                SleeveSpec(
                    name=sv.name,
                    symbol=sv.symbol,
                    strategy=strat,
                    allocation_pct=sv.allocation_pct,
                    risk=sleeve_risk,
                )
            )

        if not specs:
            typer.echo("유효한 Sleeve 가 없습니다.")
            raise typer.Exit(code=1)

        sleeves = build_sleeves(
            specs=specs,
            starting_cash=settings.starting_cash,
            fee_bps=settings.fee_bps,
            slippage_bps=settings.slippage_bps,
        )
        items = [SleeveItem(sleeve=s, df=dfs[s.symbol]) for s in sleeves]
        sbt = SleeveBacktester(
            items=items,
            timeframe=settings.timeframe,
            starting_cash=settings.starting_cash,
            max_daily_loss_pct=settings.sleeve_max_daily_loss_pct,
        )
        result = sbt.run()
        typer.echo(result.summary())
        if save_curve is not None:
            save_curve.parent.mkdir(parents=True, exist_ok=True)
            result.equity_curve.to_csv(save_curve, index=False)
            typer.echo(f"에쿼티 커브 저장: {save_curve}")
        return

    # 멀티 자산 포트폴리오 모드 감지 (공용 풀 방식, legacy)
    if settings.portfolio:
        from tradingbot.engine.multi_backtester import (
            MultiAssetBacktester,
            PortfolioItem,
        )

        logger.info(
            "멀티 자산 백테스트: {n}개 심볼 {tf} {start}~{end}",
            n=len(settings.portfolio),
            tf=settings.timeframe,
            start=start_dt.date(),
            end=end_dt.date(),
        )
        items: list[PortfolioItem] = []
        for p in settings.portfolio:
            df_sym = fetch_historical(
                exchange=exchange,
                symbol=p.symbol,
                timeframe=settings.timeframe,
                start=start_dt,
                end=end_dt,
            )
            if df_sym.empty:
                typer.echo(f"{p.symbol} 과거 데이터 없음. 스킵.")
                continue
            strat_cls = get_strategy(p.strategy.name)
            strat = strat_cls(
                params=p.strategy.params,
                symbol=p.symbol,
                timeframe=settings.timeframe,
            )
            items.append(PortfolioItem(symbol=p.symbol, strategy=strat, weight=p.weight, df=df_sym))

        if not items:
            typer.echo("유효한 심볼이 없습니다.")
            raise typer.Exit(code=1)

        mbt = MultiAssetBacktester(
            items=items,
            timeframe=settings.timeframe,
            starting_cash=settings.starting_cash,
            fee_bps=settings.fee_bps,
            slippage_bps=settings.slippage_bps,
            risk=risk,
        )
        result = mbt.run()
        typer.echo(result.summary())
        if save_curve is not None:
            save_curve.parent.mkdir(parents=True, exist_ok=True)
            result.equity_curve.to_csv(save_curve, index=False)
            typer.echo(f"에쿼티 커브 저장: {save_curve}")
        if save_report is not None:
            typer.echo("멀티 자산 HTML 리포트는 아직 미지원 (단일 자산 모드에서만 사용 가능).")
        return

    # 단일 자산 모드 (legacy)
    logger.info(
        "백테스트 시작: {s} {tf} {start}~{end} 전략={strat}",
        s=settings.symbol,
        tf=settings.timeframe,
        start=start_dt.date(),
        end=end_dt.date(),
        strat=settings.strategy.name,
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
        risk=risk,
    )
    result = backtester.run(df)
    typer.echo(result.summary())

    if save_curve is not None:
        save_curve.parent.mkdir(parents=True, exist_ok=True)
        result.equity_curve.to_csv(save_curve, index=False)
        typer.echo(f"에쿼티 커브 저장: {save_curve}")

    if save_report is not None:
        from tradingbot.reports import render_html_report

        render_html_report(result, settings.strategy.name, save_report)
        typer.echo(f"HTML 리포트 저장: {save_report}")


@app.command()
def live(
    config: Path = typer.Option(
        Path("config/settings.yaml"),
        "--config",
        "-c",
        help="설정 YAML 경로",
    ),
    i_understand_real_money: bool = typer.Option(
        False,
        "--i-understand-real-money",
        help="실제 자산 손실 가능성을 이해함을 명시적으로 확인 (이중 게이트)",
    ),
    max_bars: int = typer.Option(
        0,
        "--max-bars",
        help="지정 시 해당 개수의 봉 처리 후 종료 (0 = 무제한)",
    ),
    skip_countdown: bool = typer.Option(
        False,
        "--skip-countdown",
        help="5초 안전 카운트다운 건너뛰기 (테스트/운영 자동화용)",
    ),
) -> None:
    """실전 모드 (실제 자산 주문). 이중 게이트 + 5초 안전 카운트다운 필수."""
    import time

    from loguru import logger

    from tradingbot.broker.live import LiveBroker
    from tradingbot.config import load_settings
    from tradingbot.data.feed import LiveDataFeed
    from tradingbot.engine.runner import Runner
    from tradingbot.exchange.ccxt_adapter import CCXTAdapter
    from tradingbot.logging_setup import setup_logging
    from tradingbot.notifier import build_notifiers
    from tradingbot.portfolio.portfolio import Portfolio
    from tradingbot.portfolio.risk import RiskManager
    from tradingbot.strategies.registry import get as get_strategy

    _register_strategies()
    setup_logging()
    settings = load_settings(config)

    # ---- 이중 게이트 ----
    if not settings.live_confirmed:
        typer.secho(
            "❌ 실전 모드 거부: config/settings.yaml 의 live_confirmed 가 true 여야 합니다.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=2)
    if not i_understand_real_money:
        typer.secho(
            "❌ 실전 모드 거부: --i-understand-real-money 플래그가 필요합니다.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=2)
    if not settings.exchange_api_key or not settings.exchange_api_secret:
        typer.secho(
            "❌ 실전 모드 거부: .env 에 EXCHANGE_API_KEY / EXCHANGE_API_SECRET 가 필요합니다.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=2)

    env_label = (
        "TESTNET (가상 자산)"
        if settings.exchange.sandbox
        else "🚨 MAINNET (실제 자산) 🚨"
    )
    color = typer.colors.YELLOW if settings.exchange.sandbox else typer.colors.RED
    typer.secho("╔══════════════════════════════════════════════╗", fg=color, bold=True)
    typer.secho(f"║ 실전 모드 시작: {env_label}", fg=color, bold=True)
    typer.secho(f"║ 거래소: {settings.exchange.id}  심볼: {settings.symbol}", fg=color)
    typer.secho(f"║ 전략: {settings.strategy.name}  타임프레임: {settings.timeframe}", fg=color)
    if not settings.exchange.sandbox:
        typer.secho("║ ⚠️  실제 자산이 사용됩니다. Ctrl+C 로 취소 가능", fg=color, bold=True)
    typer.secho("╚══════════════════════════════════════════════╝", fg=color, bold=True)

    if not skip_countdown:
        for i in range(5, 0, -1):
            typer.echo(f"  {i}...")
            time.sleep(1)

    exchange = CCXTAdapter(
        exchange_id=settings.exchange.id,
        api_key=settings.exchange_api_key,
        api_secret=settings.exchange_api_secret,
        sandbox=settings.exchange.sandbox,
    )

    strategy_cls = get_strategy(settings.strategy.name)
    strategy = strategy_cls(
        params=settings.strategy.params,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
        state_path=Path("logs/strategy_state_live.json"),
    )

    portfolio = Portfolio(starting_cash=settings.starting_cash)
    # 실전 모드 startup 동기화: 거래소 실 잔고/포지션을 로컬 Portfolio 로 주입.
    # 봇 재시작 후 "거래소엔 있는데 봇은 모르는 미아 포지션" 발생 방지.
    try:
        balance = exchange.fetch_balance()
        current_price = None
        try:
            ticker = exchange.fetch_ticker(settings.symbol)
            current_price = float(ticker.get("last") or ticker.get("close") or 0.0) or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("ticker 조회 실패 (avg_price 초기화 스킵): {}", exc)
        portfolio.sync_from_exchange(
            balance=balance,
            symbol=settings.symbol,
            current_price=current_price,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("거래소 잔고 동기화 실패 — startup 중단: {}", exc)
        raise typer.Exit(code=3) from exc

    risk = RiskManager(
        max_position_pct=settings.risk.max_position_pct,
        stop_loss_pct=settings.risk.stop_loss_pct,
        max_daily_loss_pct=settings.risk.max_daily_loss_pct,
        trailing_stop_pct=settings.risk.trailing_stop_pct,
        trailing_activate_pct=settings.risk.trailing_activate_pct,
        state_path=Path("logs/risk_state_live.json"),
    )
    broker = LiveBroker(exchange=exchange)
    if settings.use_websocket:
        logger.warning(
            "use_websocket=true 는 live 모드에서 현재 지원되지 않아 REST 폴링으로 동작합니다."
        )
    notifiers = build_notifiers(
        settings.notifiers,
        telegram_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
    )

    warmup = max(strategy.warmup_bars(), 5)
    feed = LiveDataFeed(
        exchange=exchange,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
        warmup_bars=warmup,
        max_bars=max_bars if max_bars > 0 else None,
    )

    logger.info("LIVE 시작: {} {} ({})", settings.symbol, settings.timeframe, env_label)
    runner = Runner(
        symbol=settings.symbol,
        strategy=strategy,
        broker=broker,
        portfolio=portfolio,
        risk=risk,
        bar_stream=feed.stream_bars(),
        notifiers=notifiers,
        heartbeat_enabled=settings.heartbeat.enabled,
        heartbeat_hours_utc=settings.heartbeat.hours_utc,
    )
    runner.run()


@app.command()
def dashboard(
    port: int = typer.Option(8501, "--port", "-p", help="Streamlit 서버 포트"),
    headless: bool = typer.Option(
        True, "--headless/--open-browser", help="브라우저 자동 실행 여부"
    ),
) -> None:
    """Streamlit 기반 웹 대시보드를 실행 (logs/orders.jsonl 시각화)."""
    import subprocess
    import sys
    from importlib.resources import files

    app_path = str(files("tradingbot.dashboard").joinpath("app.py"))
    # 'streamlit' 실행 파일이 PATH 에 없을 수 있으므로 현재 파이썬의 -m 로 호출.
    args = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        app_path,
        "--server.port",
        str(port),
    ]
    if headless:
        args += ["--server.headless", "true"]
    typer.echo(f"대시보드 실행: http://localhost:{port}")
    subprocess.run(args, check=False)


if __name__ == "__main__":
    app()
