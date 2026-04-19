"""전략 ABC 및 관련 데이터 구조.

모든 전략은 Strategy ABC를 상속하고 ``on_bar`` 에서 ``Signal`` 을 반환한다.
엔진/브로커는 전략 구현체를 직접 import 하지 않으며, ``registry`` 경유로만 참조한다.

상태 영속화:
  ``state_path`` 를 넘기면 전략 내부 상태(예: ``_ready``, ``_entered_bar``) 를
  JSON 파일로 자동 저장/복원한다. 봇 재시작 시 "눌림 진입 준비 상태" 같은
  플래그가 리셋돼 거래소의 실 포지션과 어긋나는 것을 막는다.
  각 구체 전략은 ``get_state() / set_state()`` 를 오버라이드해서 무엇을
  영속화할지 결정한다.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

import pandas as pd
from loguru import logger


class SignalType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Bar:
    """단일 OHLCV 캔들."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    """전략이 생성한 매매 신호.

    포지션 크기는 RiskManager가 결정하므로 size 정보는 포함하지 않는다.
    """

    type: SignalType
    symbol: str
    timestamp: datetime
    price: float
    reason: str = ""


class Strategy(ABC):
    """모든 전략의 공통 인터페이스.

    구현체는 ``name`` 클래스 변수를 정의하고 ``@register`` 데코레이터로 등록한다.
    """

    name: ClassVar[str]

    def __init__(
        self,
        params: dict,
        symbol: str,
        timeframe: str,
        *,
        state_path: Path | None = None,
    ) -> None:
        self.params = params
        self.symbol = symbol
        self.timeframe = timeframe
        self.state_path = state_path
        # 인스턴스 생성 직후 기존 상태 파일이 있으면 복원.
        # 백테스트 등 state_path 미지정 시엔 완전히 no-op.
        if state_path is not None:
            self._load_state_from_disk()

    @abstractmethod
    def warmup_bars(self) -> int:
        """전략 계산에 필요한 최소 봉 개수."""

    @abstractmethod
    def on_bar(self, bar: Bar, history: pd.DataFrame) -> Signal:
        """새 봉마다 호출. ``history`` 는 현재 봉을 마지막 행으로 포함한다.

        컬럼: timestamp, open, high, low, close, volume.
        """

    def on_start(self) -> None:
        """선택적 훅. 전략 초기화 직후 한 번 호출."""

    def on_stop(self) -> None:
        """선택적 훅. 엔진 종료 시 호출."""

    # ---------- Heartbeat (정기 상태 보고) ----------
    def status_snapshot(self, history: pd.DataFrame) -> str:
        """봇 상태 요약을 사람이 읽을 수 있는 한 줄로 반환.

        Heartbeat 알림에서 호출. 구체 전략이 오버라이드해서 현재 지표값
        (EMA, RSI, Supertrend 상태 등) 을 포함시킬 수 있다.
        기본은 전략 이름과 워밍업 진행도만.
        """
        need = self.warmup_bars()
        have = len(history)
        if have < need:
            return f"{self.name} 워밍업 {have}/{need}봉"
        return f"{self.name} 대기 중 (조건 미달)"

    # ---------- 상태 영속화 훅 ----------
    def get_state(self) -> dict:
        """영속화할 내부 상태 반환. 구체 전략이 오버라이드.

        예: ``return {"ready": self._ready}``
        기본은 빈 dict — 내부 상태 없는 전략(stateless)은 오버라이드 불필요.
        """
        return {}

    def set_state(self, state: dict) -> None:
        """복원된 상태 주입. 구체 전략이 오버라이드.

        예: ``self._ready = bool(state.get("ready", False))``
        """

    def _load_state_from_disk(self) -> None:
        path = self.state_path
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("전략 상태 파일 읽기 실패 ({}): {}", path, exc)
            return
        # 심볼/타임프레임/이름이 달라졌으면 안전하게 무시 — 오염 방지
        if (
            data.get("name") != self.name
            or data.get("symbol") != self.symbol
            or data.get("timeframe") != self.timeframe
        ):
            logger.warning(
                "전략 상태 파일 컨텍스트 불일치 — 복원 건너뜀 (파일 {} vs 현재 {}/{}/{})",
                path,
                self.name,
                self.symbol,
                self.timeframe,
            )
            return
        try:
            self.set_state(data.get("state", {}))
            logger.info("전략 상태 복원 완료: {}", path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("전략 상태 복원 중 예외 ({}): {}", path, exc)

    def save_state(self) -> None:
        """현재 내부 상태를 ``state_path`` 로 저장. state_path 미지정 시 no-op."""
        path = self.state_path
        if path is None:
            return
        try:
            state_dict = self.get_state()
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_state 실패 ({}): {}", self.name, exc)
            return
        payload = {
            "name": self.name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "state": state_dict,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.warning("전략 상태 저장 실패 ({}): {}", path, exc)
