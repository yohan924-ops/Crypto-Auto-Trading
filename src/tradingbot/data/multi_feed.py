"""멀티 심볼 실시간 OHLCV 피드.

기존 ``LiveDataFeed`` 는 단일 심볼 전용이라 Sleeve 엔진(3자산 동시 운용)에 부적합.
본 ``MultiSymbolFeed`` 는 여러 심볼을 순차 폴링하며 (symbol, Bar) 튜플을 yield.

설계:
  Phase 1 (warmup): 각 심볼의 과거 데이터 fetch → timestamp 오름차순 merge → yield
    → Sleeve 워밍업 지표 (예: Bollinger 20봉) 계산을 위해 사전 데이터 주입
  Phase 2 (live): timeframe/6 초 간격 (4h → 40초) 으로 3심볼 순차 폴링
    → 닫힌 새 봉만 yield

공유 자원: Phase 1 은 ``backfill_exchange`` (제공 시 Mainnet public), Phase 2 는
``exchange`` (실전 매매에 쓰는 거래소). Binance Testnet 처럼 과거 데이터가 짧은
환경에서 Mainnet 과거 데이터로 워밍업하는 패턴 지원.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pandas as pd
from loguru import logger

from tradingbot.data.feed import bar_from_row
from tradingbot.exchange.ccxt_adapter import CCXTAdapter
from tradingbot.strategies.base import Bar
from tradingbot.utils.timeframes import timeframe_to_seconds


class MultiSymbolFeed:
    def __init__(
        self,
        exchange: CCXTAdapter,
        symbols: list[str],
        timeframe: str,
        warmup_bars: int = 300,
        backfill_exchange: CCXTAdapter | None = None,
        max_bars: int | None = None,
        poll_interval_seconds: int | None = None,
    ) -> None:
        if not symbols:
            raise ValueError("최소 1개 symbol 필요")
        self.exchange = exchange
        self.symbols = list(symbols)
        self.timeframe = timeframe
        self.warmup_bars = warmup_bars
        self.backfill_exchange = backfill_exchange
        self.max_bars = max_bars
        self._tf_seconds = timeframe_to_seconds(timeframe)
        # 실시간 폴링 간격 — timeframe/6 기본 (4h → 40초). 테스트에서 오버라이드 가능.
        self.poll_interval = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else max(self._tf_seconds // 6, 5)
        )

    def _fetch_completed(
        self, symbol: str, limit: int, exchange: CCXTAdapter | None = None
    ) -> pd.DataFrame:
        """지정 심볼의 최근 limit 개 캔들 중 '닫힌' 봉만 반환 (마지막 in-progress 제외)."""
        src = exchange or self.exchange
        df = src.fetch_ohlcv(symbol, self.timeframe, limit=limit)
        if len(df) <= 1:
            return df.iloc[0:0]
        return df.iloc[:-1].reset_index(drop=True)

    def stream(self) -> Iterator[tuple[str, Bar]]:
        """(symbol, Bar) 튜플을 yield.

        Phase 1: 모든 심볼의 warmup bar 를 timestamp 순으로 merge 해 yield.
        Phase 2: 폴링 주기마다 각 심볼 순차 fetch, 신규 봉만 yield.
        """
        initial_limit = max(self.warmup_bars + 2, 10)
        backfill_src = self.backfill_exchange or self.exchange

        # ---- Phase 1: warmup ----
        warmup_dfs: dict[str, pd.DataFrame] = {}
        for symbol in self.symbols:
            df = self._fetch_completed(
                symbol, initial_limit, exchange=backfill_src
            )
            warmup_dfs[symbol] = df
            logger.info(
                "초기 backfill: {symbol} {tf} {n} bars (source: {src})",
                symbol=symbol,
                tf=self.timeframe,
                n=len(df),
                src=("mainnet" if self.backfill_exchange is not None else "primary"),
            )

        events: list[tuple[pd.Timestamp, str, pd.Series]] = []
        for symbol, df in warmup_dfs.items():
            for _, row in df.iterrows():
                events.append((row["timestamp"], symbol, row))
        events.sort(key=lambda e: e[0])

        last_ts: dict[str, pd.Timestamp | None] = {s: None for s in self.symbols}
        emitted = 0
        for ts, symbol, row in events:
            bar = bar_from_row(row)
            yield (symbol, bar)
            last_ts[symbol] = ts
            emitted += 1
            if self.max_bars is not None and emitted >= self.max_bars:
                return

        # ---- Phase 2: live polling ----
        while True:
            time.sleep(self.poll_interval)
            for symbol in self.symbols:
                try:
                    df = self._fetch_completed(symbol, limit=3)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "실시간 폴링 실패 {} ({}): {}",
                        symbol,
                        type(exc).__name__,
                        exc,
                    )
                    continue
                if df.empty:
                    continue
                last = last_ts.get(symbol)
                new_rows = (
                    df[df["timestamp"] > last] if last is not None else df
                )
                for _, row in new_rows.iterrows():
                    bar = bar_from_row(row)
                    yield (symbol, bar)
                    last_ts[symbol] = row["timestamp"]
                    emitted += 1
                    if self.max_bars is not None and emitted >= self.max_bars:
                        return
