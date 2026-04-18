"""대시보드 헬퍼 함수 테스트 (Streamlit UI 는 불러오지 않고 순수 로직만)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _write_orders(dir_: Path, rows: list[dict]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    f = dir_ / "orders.jsonl"
    with open(f, "w", encoding="utf-8") as fp:
        for r in rows:
            fp.write(json.dumps(r) + "\n")


def test_load_events_parses_jsonl(tmp_path, monkeypatch):
    _write_orders(
        tmp_path / "logs",
        [
            {"event": "signal", "type": "buy", "symbol": "BTC/USDT", "price": 30000.0, "timestamp": "2024-01-01T00:00:00+00:00"},
            {"event": "order_filled", "symbol": "BTC/USDT", "side": "buy", "amount": 0.1, "price": 30050.0, "fee": 0.3, "timestamp": "2024-01-01T00:00:01+00:00"},
            {"event": "signal", "type": "hold", "symbol": "BTC/USDT", "price": 30100.0, "timestamp": "2024-01-01T01:00:00+00:00"},
        ],
    )
    monkeypatch.chdir(tmp_path)
    # 캐시를 피하려고 streamlit import 는 피하고 내부 함수만 재구현
    from tradingbot.dashboard import app as dash_app

    dash_app.load_events.clear()  # type: ignore[attr-defined]
    events = dash_app.load_events()
    assert len(events) == 3
    assert set(events["event"]) == {"signal", "order_filled"}


def test_fills_and_signals_filter(tmp_path, monkeypatch):
    _write_orders(
        tmp_path / "logs",
        [
            {"event": "signal", "type": "buy", "symbol": "BTC/USDT", "price": 100, "timestamp": "2024-01-01T00:00:00+00:00"},
            {"event": "signal", "type": "hold", "symbol": "BTC/USDT", "price": 101, "timestamp": "2024-01-01T01:00:00+00:00"},
            {"event": "order_filled", "symbol": "BTC/USDT", "side": "buy", "amount": 1.0, "price": 100, "fee": 0.1, "timestamp": "2024-01-01T00:00:01+00:00"},
            {"event": "backtest_fill", "symbol": "ETH/USDT", "side": "sell", "amount": 2.0, "price": 50, "fee": 0.05, "timestamp": "2024-01-01T02:00:00+00:00"},
        ],
    )
    monkeypatch.chdir(tmp_path)
    from tradingbot.dashboard import app as dash_app

    dash_app.load_events.clear()  # type: ignore[attr-defined]
    events = dash_app.load_events()
    fills = dash_app._fills(events)
    assert len(fills) == 2
    signals = dash_app._signals(events)
    # HOLD 는 제외
    assert len(signals) == 1
    assert signals.iloc[0]["type"] == "buy"


def test_load_events_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingbot.dashboard import app as dash_app

    dash_app.load_events.clear()  # type: ignore[attr-defined]
    events = dash_app.load_events()
    assert events.empty


def test_load_events_skips_malformed_lines(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    f = logs_dir / "orders.jsonl"
    f.write_text(
        'not json\n'
        '{"event": "signal", "type": "buy", "symbol": "X", "price": 1, "timestamp": "2024-01-01T00:00:00+00:00"}\n'
        '\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    from tradingbot.dashboard import app as dash_app

    dash_app.load_events.clear()  # type: ignore[attr-defined]
    events = dash_app.load_events()
    # 깨진 줄은 스킵, 정상 1건만 로드
    assert len(events) == 1


def test_dashboard_cli_registered():
    from typer.testing import CliRunner

    from tradingbot.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dashboard" in result.stdout


def test_fills_returns_empty_on_empty_events():
    from tradingbot.dashboard import app as dash_app

    assert dash_app._fills(pd.DataFrame()).empty
    assert dash_app._signals(pd.DataFrame()).empty
