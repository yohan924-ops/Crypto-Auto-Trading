"""Risk Manager: 포지션 사이징 + 손절 + 일일 손실 서킷브레이커.

- max_position_pct: 신규 진입 시 자산의 몇 % 까지 할당할지
- stop_loss_pct: 포지션 평가손이 이 비율을 넘으면 강제 청산 신호
- max_daily_loss_pct: 일일 손실이 이 비율에 도달하면 당일 추가 거래 차단

상태 영속화:
  halt/day_start_equity 는 프로세스 메모리에만 있으면 재시작으로 손실 한도가 리셋되어
  일일 서킷브레이커를 우회할 수 있다. ``state_path`` 를 지정하면 매 업데이트마다
  JSON 으로 저장하고 생성 시 복원한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from loguru import logger

from tradingbot.portfolio.portfolio import Position
from tradingbot.strategies.base import Signal, SignalType


@dataclass
class RiskManager:
    max_position_pct: float = 0.10
    stop_loss_pct: float = 0.05
    max_daily_loss_pct: float = 0.05
    trailing_stop_pct: float = 0.0  # 0 = 비활성
    trailing_activate_pct: float = 0.05
    state_path: Path | None = None  # 지정 시 halt/일일 자산을 이 파일에 영속화

    # 내부 상태 (일자별 리셋)
    _current_day: date | None = field(default=None, repr=False)
    _day_start_equity: float | None = field(default=None, repr=False)
    _halted: bool = field(default=False, repr=False)
    # 심볼별 포지션 평가 최고가 (트레일링 스탑용). 프로세스 메모리에만 유지.
    _position_peaks: dict[str, float] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.state_path is not None:
            self._load_state()

    # ---------- 영속화 ----------
    def _load_state(self) -> None:
        path = self.state_path
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("RiskManager 상태 파일 읽기 실패 ({}): {}", path, exc)
            return
        day_str = data.get("current_day")
        self._current_day = date.fromisoformat(day_str) if day_str else None
        self._day_start_equity = data.get("day_start_equity")
        self._halted = bool(data.get("halted", False))
        logger.info(
            "RiskManager 상태 복원: day={}, halted={}, day_start={}",
            self._current_day,
            self._halted,
            self._day_start_equity,
        )

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "current_day": self._current_day.isoformat() if self._current_day else None,
            "day_start_equity": self._day_start_equity,
            "halted": self._halted,
        }
        try:
            self.state_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("RiskManager 상태 저장 실패 ({}): {}", self.state_path, exc)

    def size_order(
        self,
        signal: Signal,
        equity: float,
        price: float,
        position_amount: float,
        weight: float = 1.0,
    ) -> float:
        """주문 수량 결정. 0 반환 시 주문 스킵.

        - BUY: 이미 포지션 보유 중이면 0, 아니면 max_position_pct*weight 만큼 매수
        - SELL: 보유 수량 전체 청산
        - HOLD: 0

        ``weight`` 는 멀티 자산 포트폴리오에서 심볼별 할당 비중. 단일 자산은 1.0.
        """
        if signal.type == SignalType.BUY:
            if position_amount > 0:
                return 0.0
            if price <= 0 or equity <= 0 or weight <= 0:
                return 0.0
            target_notional = equity * self.max_position_pct * weight
            return target_notional / price
        if signal.type == SignalType.SELL:
            return max(position_amount, 0.0)
        return 0.0

    def update_peak(self, symbol: str, high_price: float, position_amount: float) -> None:
        """포지션 평가 최고가 추적. 포지션 없으면 기록 삭제."""
        if position_amount <= 0:
            self._position_peaks.pop(symbol, None)
            return
        if high_price <= 0:
            return
        current = self._position_peaks.get(symbol)
        self._position_peaks[symbol] = high_price if current is None else max(current, high_price)

    def check_stop_loss(
        self,
        position: Position,
        current_price: float,
        low_price: float | None = None,
        symbol: str | None = None,
    ) -> bool:
        """손절 또는 트레일링 스탑 트리거 여부.

        세 가지 축을 함께 검사한다 — 하나라도 해당되면 True:
          1) 평균진입가 기준 손절: (current|low) / avg - 1 <= -stop_loss_pct
          2) 트레일링 스탑: 피크까지 trailing_activate_pct 이상 상승했던 포지션이
             피크 대비 trailing_stop_pct 이상 하락한 경우
        low_price 가 주어지면 봉 내 저가도 "가장 불리한 가격" 으로 반영.
        """
        if position.amount <= 0 or position.avg_price <= 0 or current_price <= 0:
            return False
        worst = current_price
        if low_price is not None and low_price > 0:
            worst = min(worst, low_price)

        # 1) 고정 손절
        avg_pnl = (worst - position.avg_price) / position.avg_price
        if avg_pnl <= -self.stop_loss_pct:
            return True

        # 2) 트레일링 — activate 임계 통과한 경우에만
        if symbol is not None and self.trailing_stop_pct > 0:
            peak = self._position_peaks.get(symbol)
            if peak is not None and peak > 0:
                peak_gain = (peak - position.avg_price) / position.avg_price
                if peak_gain >= self.trailing_activate_pct:
                    peak_pnl = (worst - peak) / peak
                    if peak_pnl <= -self.trailing_stop_pct:
                        return True
        return False

    def update_day(self, now: datetime, equity: float) -> bool:
        """일자 경계를 관리. 날짜가 바뀌면 True 반환하고 상태 리셋.

        새로운 날 시작 → 손실 한도도 초기화.
        """
        today = now.date()
        if self._current_day != today:
            self._current_day = today
            self._day_start_equity = equity
            self._halted = False
            self._save_state()
            return True
        return False

    def update_circuit_breaker(self, equity: float) -> None:
        """현재 자산이 일일 손실 한도를 초과하면 halted 플래그 설정."""
        if self._day_start_equity is None or self._day_start_equity <= 0:
            return
        daily_pnl_pct = (equity - self._day_start_equity) / self._day_start_equity
        if daily_pnl_pct <= -self.max_daily_loss_pct and not self._halted:
            self._halted = True
            self._save_state()

    @property
    def halted(self) -> bool:
        return self._halted

    def daily_pnl_pct(self, equity: float) -> float:
        if self._day_start_equity is None or self._day_start_equity <= 0:
            return 0.0
        return (equity - self._day_start_equity) / self._day_start_equity * 100.0
