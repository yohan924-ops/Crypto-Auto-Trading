"""CCXT 래퍼. 모든 거래소 접근의 유일한 통로.

exchange_id 만 바꾸면 Binance → Upbit 등으로 전환 가능.
읽기(fetch_ohlcv/ticker)와 쓰기(create_order/fetch_balance) 모두 여기로.
"""

from __future__ import annotations

import ccxt
import pandas as pd


class CCXTAdapter:
    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: str | None = None,
        api_secret: str | None = None,
        sandbox: bool = True,
    ) -> None:
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"ccxt 에서 지원하지 않는 거래소: {exchange_id}")
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class(
            {
                "apiKey": api_key or "",
                "secret": api_secret or "",
                "enableRateLimit": True,
            }
        )
        self.exchange_id = exchange_id
        self.sandbox = sandbox
        # sandbox=True 인데 거래소가 테스트 URL 을 제공하지 않으면 — Upbit 등 —
        # 조용히 실전 URL 로 접속되어 사용자가 속을 수 있다. 명시적으로 거부한다.
        # 사용자는 `exchange.sandbox: false` 로 바꾸고 실전 인지 상태에서 진입해야 함.
        if sandbox:
            if not self.exchange.urls.get("test"):
                raise ValueError(
                    f"거래소 '{exchange_id}' 는 sandbox(테스트넷) 를 지원하지 않습니다. "
                    f"config 에서 exchange.sandbox 를 false 로 설정하거나, Binance 같은 "
                    f"테스트넷 지원 거래소로 변경하세요."
                )
            self.exchange.set_sandbox_mode(True)

    # ---------- 읽기 ----------
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        """OHLCV를 pandas DataFrame 으로 반환.

        컬럼: timestamp(UTC datetime64), open, high, low, close, volume
        """
        raw = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    def fetch_ticker(self, symbol: str) -> dict:
        return self.exchange.fetch_ticker(symbol)

    def fetch_balance(self) -> dict:
        """전체 잔고. 반환 예: {'USDT': {'free': 1000.0, 'used': 0.0, 'total': 1000.0}, ...}"""
        return self.exchange.fetch_balance()

    # ---------- 쓰기 ----------
    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: float | None = None,
        params: dict | None = None,
    ) -> dict:
        """주문 생성. 거래소 원본 응답 dict 반환.

        type: 'market' | 'limit'
        side: 'buy' | 'sell'
        params: CCXT unified/거래소별 파라미터. ``clientOrderId`` 를 넣으면
        재시도 시 중복 주문 방지 (Binance: newClientOrderId, Upbit: identifier).

        전송 전 ``amount_to_precision`` / ``price_to_precision`` 으로 거래소별
        수량·호가 단위에 맞춤. 특히 Upbit 의 KRW 마켓은 호가 단위가 가격대별로
        다른데(0.5 / 1 / 10 …) CCXT 가 알아서 반올림해 Invalid Price 에러를 막는다.
        """
        amount_str = self.exchange.amount_to_precision(symbol, amount)
        amount_precise = float(amount_str)
        price_precise: float | None = None
        if price is not None:
            price_str = self.exchange.price_to_precision(symbol, price)
            price_precise = float(price_str)
        return self.exchange.create_order(
            symbol, type, side, amount_precise, price_precise, params or {}
        )

    # ---------- 정밀도 헬퍼 (외부에서 주문 전 미리 반올림할 때 사용) ----------
    def amount_to_precision(self, symbol: str, amount: float) -> float:
        return float(self.exchange.amount_to_precision(symbol, amount))

    def price_to_precision(self, symbol: str, price: float) -> float:
        return float(self.exchange.price_to_precision(symbol, price))

    def cancel_order(self, order_id: str, symbol: str) -> dict:
        return self.exchange.cancel_order(order_id, symbol)

    def fetch_order(self, order_id: str, symbol: str) -> dict:
        return self.exchange.fetch_order(order_id, symbol)
