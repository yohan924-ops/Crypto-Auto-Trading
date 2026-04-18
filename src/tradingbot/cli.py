"""CLI 엔트리 포인트.

Phase 0 스캐폴딩 단계에서는 명령어 골격만 제공하며,
각 모드의 실제 동작은 이후 페이즈에서 구현된다.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="tradingbot",
    help="코인 자동매매 봇 (규칙 기반 알고리즘 트레이딩)",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def paper() -> None:
    """페이퍼 트레이딩 모드 (실시간 시세 + 가상 잔고)."""
    typer.echo("[paper] 아직 구현되지 않음. Phase 1에서 추가 예정.")
    raise typer.Exit(code=1)


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
