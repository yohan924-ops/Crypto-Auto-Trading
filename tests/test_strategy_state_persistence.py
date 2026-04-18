"""전략 상태 영속화 테스트 — 재시작 후 내부 플래그 복원 검증."""

from __future__ import annotations

import json

import pytest

from tradingbot.strategies import (
    bollinger_breakout,  # noqa: F401
    buy_and_hold,  # noqa: F401
    ma_crossover,  # noqa: F401
    pullback,  # noqa: F401
    rsi_reversal,  # noqa: F401
    swing_pullback,  # noqa: F401
    volatility_breakout,  # noqa: F401
)
from tradingbot.strategies.registry import get as get_strategy


def _make(name: str, symbol: str, timeframe: str, state_path=None, **extra_params):
    cls = get_strategy(name)
    return cls(
        params=extra_params,
        symbol=symbol,
        timeframe=timeframe,
        state_path=state_path,
    )


# ---------- swing_pullback ----------


def test_swing_pullback_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    s1 = _make("swing_pullback", "BTC/USDT", "4h", state_path=path)
    assert s1._ready is False

    # 상태 변경 후 저장
    s1._ready = True
    s1.save_state()
    assert path.exists()

    # 새 인스턴스에서 복원
    s2 = _make("swing_pullback", "BTC/USDT", "4h", state_path=path)
    assert s2._ready is True


def test_swing_pullback_state_file_contents(tmp_path):
    path = tmp_path / "state.json"
    s = _make("swing_pullback", "BTC/USDT", "4h", state_path=path)
    s._ready = True
    s.save_state()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["name"] == "swing_pullback"
    assert data["symbol"] == "BTC/USDT"
    assert data["timeframe"] == "4h"
    assert data["state"]["ready"] is True


# ---------- 컨텍스트 불일치 안전성 ----------


def test_state_ignored_when_symbol_changed(tmp_path):
    """다른 심볼로 만든 상태 파일은 무시해야 함 (오염 방지)."""
    path = tmp_path / "state.json"
    s1 = _make("swing_pullback", "BTC/USDT", "4h", state_path=path)
    s1._ready = True
    s1.save_state()

    # 같은 이름·같은 타임프레임이지만 다른 심볼 → 복원 건너뜀
    s2 = _make("swing_pullback", "ETH/USDT", "4h", state_path=path)
    assert s2._ready is False


def test_state_ignored_when_timeframe_changed(tmp_path):
    path = tmp_path / "state.json"
    s1 = _make("swing_pullback", "BTC/USDT", "4h", state_path=path)
    s1._ready = True
    s1.save_state()

    s2 = _make("swing_pullback", "BTC/USDT", "1h", state_path=path)
    assert s2._ready is False


def test_state_ignored_when_strategy_name_changed(tmp_path):
    """다른 전략 클래스가 같은 파일 경로로 읽어도 오염되지 않아야 함."""
    path = tmp_path / "state.json"
    s = _make("swing_pullback", "BTC/USDT", "4h", state_path=path)
    s._ready = True
    s.save_state()

    p = _make("pullback", "BTC/USDT", "4h", state_path=path)
    # pullback 의 기본 _ready 그대로 (swing_pullback 파일이라 무시)
    assert p._ready is False


# ---------- 손상된 파일 ----------


def test_corrupt_state_file_does_not_raise(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("this is not json {", encoding="utf-8")
    s = _make("swing_pullback", "BTC/USDT", "4h", state_path=path)
    # 예외 없이 기본값 유지
    assert s._ready is False


# ---------- state_path 미지정: no-op ----------


def test_no_state_path_means_no_persistence(tmp_path, monkeypatch):
    """Backtester 경로처럼 state_path=None 이면 파일 I/O 가 아예 발생하지 않음."""
    s = _make("swing_pullback", "BTC/USDT", "4h", state_path=None)
    s._ready = True
    # save_state 호출해도 어디에도 쓰지 않음 (no-op)
    s.save_state()
    # 현재 디렉토리에 원하지 않는 파일이 생기지 않아야 함
    assert not (tmp_path / "state.json").exists()


# ---------- buy_and_hold ----------


def test_buy_and_hold_bought_flag_persists(tmp_path):
    path = tmp_path / "state.json"
    s1 = _make("buy_and_hold", "BTC/USDT", "1h", state_path=path)
    s1._bought = True
    s1.save_state()

    s2 = _make("buy_and_hold", "BTC/USDT", "1h", state_path=path)
    assert s2._bought is True


# ---------- volatility_breakout ----------


def test_volatility_breakout_had_position_marker(tmp_path):
    """인덱스가 아닌 '보유 중이었음' 불리언만 보존."""
    path = tmp_path / "state.json"
    s1 = _make("volatility_breakout", "BTC/USDT", "1d", state_path=path, k=0.5)
    s1._entered_bar = 42
    s1.save_state()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["state"]["had_position"] is True

    s2 = _make("volatility_breakout", "BTC/USDT", "1d", state_path=path, k=0.5)
    # -1 로 초기화되어 재시작 후 첫 bar 에서 청산 시도됨
    assert s2._entered_bar == -1


def test_volatility_breakout_no_position_state(tmp_path):
    path = tmp_path / "state.json"
    s1 = _make("volatility_breakout", "BTC/USDT", "1d", state_path=path, k=0.5)
    # _entered_bar 가 None 이면 had_position=False
    s1.save_state()

    s2 = _make("volatility_breakout", "BTC/USDT", "1d", state_path=path, k=0.5)
    assert s2._entered_bar is None


# ---------- 빈 파일 / 누락 키 ----------


def test_state_with_missing_keys_uses_defaults(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {"name": "swing_pullback", "symbol": "BTC/USDT", "timeframe": "4h", "state": {}}
        ),
        encoding="utf-8",
    )
    s = _make("swing_pullback", "BTC/USDT", "4h", state_path=path)
    assert s._ready is False  # 기본값


# ---------- 상태 없는 전략은 빈 state 유지 ----------


@pytest.mark.parametrize("name", ["ma_crossover", "rsi_reversal", "bollinger_breakout"])
def test_stateless_strategy_roundtrip_is_empty(tmp_path, name):
    path = tmp_path / "state.json"
    params_by_name = {
        "ma_crossover": {"fast": 20, "slow": 50},
        "rsi_reversal": {"period": 14, "oversold": 30, "overbought": 70},
        "bollinger_breakout": {"period": 20, "num_std": 2.0},
    }
    cls = get_strategy(name)
    s = cls(
        params=params_by_name[name],
        symbol="BTC/USDT",
        timeframe="1h",
        state_path=path,
    )
    s.save_state()
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    # 내부 상태 없는 전략은 state dict 가 빈 채로 저장됨
    assert data["state"] == {}
