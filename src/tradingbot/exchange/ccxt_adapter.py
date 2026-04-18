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
        # Binance 는 set_sandbox_mode 지원. 일부 거래소는 테스트 URL 이 없어 건너뜀.
        if sandbox and self.exchange.urls.get("test"):
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
    ) -> dict:
        """주문 생성. 거래소 원본 응답 dict 반환.

        type: 'market' | 'limit'
        side: 'buy' | 'sell'
        """
        params: dict = {}
        return self.exchange.create_order(symbol, type, side, amount, price, params)

    def cancel_order(self, order_id: str, symbol: str) -> dict:
        return self.exchange.cancel_order(order_id, symbol)

    def fetch_order(self, order_id: str, symbol: str) -> dict:
        return self.exchange.fetch_order(order_id, symbol)
