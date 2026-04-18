"""실시간 OHLCV 데이터 피드.

``stream_bars()`` 는 다음 순서로 Bar 를 yield:
  1) 최근 과거 봉들을 워밍업용으로 먼저 흘려보낸 뒤,
  2) 타임프레임 주기로 폴링하며 새로 닫힌 봉을 실시간으로 yield.

주의: 마지막 봉은 아직 닫히지 않은 in-progress 일 수 있으므로 제외한다.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pandas as pd
from loguru import logger

from tradingbot.exchange.ccxt_adapter import CCXTAdapter
from tradingbot.strategies.base import Bar
from tradingbot.utils.timeframes import timeframe_to_seconds


def bar_from_row(row: pd.Series) -> Bar:
    ts = row["timestamp"]
    return Bar(
        timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
    )


class LiveDataFeed:
    def __init__(
        self,
        exchange: CCXTAdapter,
        symbol: str,
        timeframe: str,
        warmup_bars: int = 50,
        max_bars: int | None = None,
        backfill_exchange: CCXTAdapter | None = None,
    ) -> None:
        """
        ``backfill_exchange`` 가 주어지면 **초기 과거 데이터만** 그 어댑터로 받아
        실시간 폴링은 ``exchange`` 로. Binance Testnet 은 과거 OHLCV 를 17일 정도
        밖에 제공하지 않아 장기 지표(예: EMA 300) warmup 이 불가능한데,
        Mainnet public API 는 수년치 과거 데이터 무료 제공 → Mainnet 에서 backfill
        받고 주문·실시간은 여전히 Testnet 으로 분리 가능.
        """
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.warmup_bars = warmup_bars
        self.max_bars = max_bars
        self.backfill_exchange = backfill_exchange
        self._tf_seconds = timeframe_to_seconds(timeframe)

    def _completed_bars(
        self, limit: int, exchange: CCXTAdapter | None = None
    ) -> pd.DataFrame:
        """최근 ``limit`` 개 캔들을 요청하고 '닫힌' 봉만 반환 (마지막 봉 제외).

        ``exchange`` 생략 시 기본 self.exchange 사용.
        """
        src = exchange or self.exchange
        df = src.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
        if len(df) <= 1:
            return df.iloc[0:0]
        return df.iloc[:-1].reset_index(drop=True)

    def stream_bars(self) -> Iterator[Bar]:
        """최초 backfill 후 실시간 폴링으로 bar 를 yield."""
        initial_limit = max(self.warmup_bars + 2, 10)
        backfill_src = self.backfill_exchange or self.exchange
        history = self._completed_bars(initial_limit, exchange=backfill_src)
        logger.info(
            "초기 backfill: {symbol} {timeframe} {n} bars (source: {src})",
            symbol=self.symbol,
            timeframe=self.timeframe,
            n=len(history),
            src=(
                "mainnet" if self.backfill_exchange is not None else "primary"
            ),
        )

        emitted = 0
        last_ts = None
        for _, row in history.iterrows():
            bar = bar_from_row(row)
            yield bar
            last_ts = bar.timestamp
            emitted += 1
            if self.max_bars is not None and emitted >= self.max_bars:
                return

        # 실시간 폴링
        poll_interval = max(self._tf_seconds // 6, 5)
        while True:
            time.sleep(poll_interval)
            latest = self._completed_bars(limit=3)
            new_rows = (
                latest[latest["timestamp"] > last_ts] if last_ts is not None else latest
            )
            for _, row in new_rows.iterrows():
                bar = bar_from_row(row)
                yield bar
                last_ts = bar.timestamp
                emitted += 1
                if self.max_bars is not None and emitted >= self.max_bars:
                    return
