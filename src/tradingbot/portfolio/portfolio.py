"""포트폴리오 상태: 현금, 포지션, 평가액 계산."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from tradingbot.broker.base import Fill, OrderSide


@dataclass
class Position:
    symbol: str
    amount: float = 0.0
    avg_price: float = 0.0


@dataclass
class Portfolio:
    starting_cash: float
    quote_ccy: str = "USDT"
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cash == 0.0:
            self.cash = self.starting_cash

    def get_position(self, symbol: str) -> Position:
        return self.positions.setdefault(symbol, Position(symbol=symbol))

    def apply_fill(self, fill: Fill) -> None:
        """체결 이벤트를 잔고·포지션에 반영. 수수료는 현금에서 차감."""
        position = self.get_position(fill.symbol)
        notional = fill.amount * fill.price

        if fill.side == OrderSide.BUY:
            self.cash -= notional + fill.fee
            total_amount = position.amount + fill.amount
            if total_amount > 0:
                position.avg_price = (
                    position.amount * position.avg_price + fill.amount * fill.price
                ) / total_amount
            position.amount = total_amount
        else:  # SELL
            # 거래소 응답 불일치로 보유분보다 많이 팔린 것으로 기록되면
            # 포지션이 음수가 되어 이후 사이징/리스크 로직이 전부 오염된다.
            # 보유분까지만 반영하고 초과 체결은 경고 후 버린다.
            sell_amount = fill.amount
            if sell_amount > position.amount + 1e-12:
                logger.warning(
                    "오버셀 감지 {}: fill.amount={:.8f} > position.amount={:.8f}. 보유분까지만 반영.",
                    fill.symbol,
                    fill.amount,
                    position.amount,
                )
                sell_amount = position.amount
            realized_notional = sell_amount * fill.price
            self.cash += realized_notional - fill.fee
            position.amount -= sell_amount
            if position.amount <= 1e-12:
                position.amount = 0.0
                position.avg_price = 0.0

    def sync_from_exchange(
        self,
        balance: dict[str, Any],
        symbol: str,
        current_price: float | None = None,
    ) -> None:
        """거래소 실제 잔고를 Portfolio 에 반영.

        봇 재시작 시 호출. 로컬 포지션과 거래소 실제 잔고가 어긋나면 "미아 포지션"
        이 발생하므로, live 모드 시작 직후 이 함수로 동기화해야 한다.

        ``balance`` 는 CCXT ``fetch_balance()`` 결과. 예::

            {"USDT": {"free": 8000.0, "used": 0.0, "total": 8000.0},
             "BTC":  {"free": 0.01,   "used": 0.0, "total": 0.01}, ...}

        ``symbol`` 은 이 봇이 운용하는 단일 페어 (예 ``BTC/USDT``). base/quote 를
        추출해서 해당 두 자산만 반영. 다른 자산 보유분은 건드리지 않는다.

        ``current_price`` 가 제공되고 로컬 avg_price 가 0 이면 "최초 진입가"를
        current_price 로 가정. 손절 기준이 비정상 동작하는 것을 막는 보수적 선택.
        """
        base, quote = symbol.split("/")
        quote_info = balance.get(quote) or {}
        base_info = balance.get(base) or {}
        quote_free = float(quote_info.get("free") or 0.0)
        base_total = float(base_info.get("total") or 0.0)

        self.cash = quote_free
        position = self.get_position(symbol)
        prev_amount = position.amount
        position.amount = base_total

        if base_total > 0 and position.avg_price <= 0:
            # 재시작 직후 과거 avg_price 를 모를 때 — 현재가를 보수적 기준으로 사용.
            # 손절 -5% 가 진입가 -5% 가 아니라 "시작가 기준 -5%" 로 동작해 부작용
            # 가능성 있으므로 반드시 로그로 알림.
            if current_price and current_price > 0:
                position.avg_price = current_price
                logger.warning(
                    "동기화 후 avg_price 를 현재가({:.2f})로 초기화 — 실제 진입가 확인 권장",
                    current_price,
                )
            else:
                logger.warning(
                    "동기화 후 avg_price 를 모름. 손절 비활성 상태 (fetch_ticker 권장)."
                )
        elif base_total <= 0:
            position.avg_price = 0.0

        logger.info(
            "거래소 잔고 동기화: cash={:.2f} {}, {} amount {:.8f} → {:.8f} (avg={:.2f})",
            self.cash, quote, base, prev_amount, position.amount, position.avg_price,
        )

    def equity(self, marks: dict[str, float]) -> float:
        """현금 + 보유 포지션의 시가 평가 총합.

        ``marks`` 는 심볼→현재가(또는 최근 종가) 매핑.
        """
        total = self.cash
        for symbol, position in self.positions.items():
            if position.amount > 0:
                mark = marks.get(symbol)
                if mark is None:
                    raise KeyError(f"심볼 {symbol} 의 mark 가격이 제공되지 않음")
                total += position.amount * mark
        return total
