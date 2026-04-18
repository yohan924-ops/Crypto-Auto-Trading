"""포트폴리오 상태: 현금, 포지션, 평가액 계산."""

from __future__ import annotations

from dataclasses import dataclass, field

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
