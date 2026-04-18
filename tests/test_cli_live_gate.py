"""CLI live 명령 이중 게이트 테스트.

실제 거래소 호출 없이 CliRunner 로 게이트 동작만 검증.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tradingbot.cli import app

runner = CliRunner()


def _combined(result) -> str:
    """stdout + stderr 합쳐서 반환 (Click 버전 호환)."""
    out = getattr(result, "stdout", "") or ""
    err = getattr(result, "stderr", "") or ""
    return out + err


def _write_settings(tmp: Path, live_confirmed: bool) -> Path:
    cfg = tmp / "settings.yaml"
    cfg.write_text(
        f"""
mode: live
live_confirmed: {"true" if live_confirmed else "false"}
symbol: "BTC/USDT"
timeframe: "1h"
starting_cash: 1000.0
fee_bps: 10.0
slippage_bps: 5.0
exchange:
  id: binance
  sandbox: true
strategy:
  name: buy_and_hold
  params: {{}}
risk:
  max_position_pct: 0.10
  stop_loss_pct: 0.05
  max_daily_loss_pct: 0.05
notifiers: []
""".strip(),
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def clean_env(monkeypatch):
    for k in (
        "EXCHANGE_API_KEY",
        "EXCHANGE_API_SECRET",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def test_live_rejected_when_config_live_confirmed_false(tmp_path, clean_env):
    cfg = _write_settings(tmp_path, live_confirmed=False)
    result = runner.invoke(
        app,
        ["live", "--config", str(cfg), "--i-understand-real-money", "--skip-countdown"],
    )
    assert result.exit_code == 2
    assert "live_confirmed" in _combined(result)


def test_live_rejected_when_flag_missing(tmp_path, clean_env):
    cfg = _write_settings(tmp_path, live_confirmed=True)
    result = runner.invoke(app, ["live", "--config", str(cfg), "--skip-countdown"])
    assert result.exit_code == 2
    assert "i-understand-real-money" in _combined(result)


def test_live_rejected_when_api_key_missing(tmp_path, clean_env):
    cfg = _write_settings(tmp_path, live_confirmed=True)
    result = runner.invoke(
        app,
        [
            "live",
            "--config",
            str(cfg),
            "--i-understand-real-money",
            "--skip-countdown",
        ],
    )
    assert result.exit_code == 2
    assert "EXCHANGE_API_KEY" in _combined(result)


def test_live_help_works():
    result = runner.invoke(app, ["live", "--help"])
    assert result.exit_code == 0
    combined = _combined(result)
    assert "--i-understand-real-money" in combined
    assert "--skip-countdown" in combined
