"""Binance WebSocket 실시간 피드.

REST 폴링 대신 WebSocket 으로 봉이 닫히는 즉시 push 받는다.
- 초기 backfill 은 REST(fetch_ohlcv) 로 최근 과거봉을 받아 전략 워밍업.
- 이후 WebSocket 스트림에서 kline 이벤트를 받아 ``k.x == true`` (봉 종료) 일 때만 emit.
- 네트워크 오류 시 지수 백오프로 자동 재연결.
- 백그라운드 스레드에서 async 루프를 돌리고, sync iterator 로 노출.

참고:
  - 엔드포인트: wss://stream.binance.com:9443/ws/{sym}@kline_{interval}
  - Testnet: wss://testnet.binance.vision/ws/...
  - Kline 메시지: https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-streams
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from queue import Empty, Queue

import websockets
from loguru import logger

from tradingbot.exchange.ccxt_adapter import CCXTAdapter
from tradingbot.strategies.base import Bar

from .feed import bar_from_row

_MAINNET = "wss://stream.binance.com:9443"
_TESTNET = "wss://testnet.binance.vision"


class BinanceWebSocketFeed:
    def __init__(
        self,
        symbol: str,
        timeframe: str,
        *,
        sandbox: bool = False,
        warmup_bars: int = 50,
        max_bars: int | None = None,
        backfill_exchange: CCXTAdapter | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.sandbox = sandbox
        self.warmup_bars = warmup_bars
        self.max_bars = max_bars
        self.backfill_exchange = backfill_exchange
        self._queue: Queue[Bar | None] = Queue(maxsize=1024)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        sym = self.symbol.replace("/", "").lower()
        base = _TESTNET if self.sandbox else _MAINNET
        return f"{base}/ws/{sym}@kline_{self.timeframe}"

    @staticmethod
    def parse_message(raw: str | bytes) -> Bar | None:
        """WebSocket kline 메시지를 Bar 로 변환. 닫히지 않은 봉은 None."""
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return None
        k = msg.get("k") if isinstance(msg, dict) else None
        if not isinstance(k, dict) or not k.get("x"):
            return None
        try:
            ts_ms = int(k["t"])
            return Bar(
                timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
            )
        except (KeyError, ValueError, TypeError):
            return None

    def stream_bars(self) -> Iterator[Bar]:
        """초기 backfill 후 WebSocket 으로 새 봉을 yield."""
        emitted = 0
        last_ts: datetime | None = None

        # 1) REST backfill
        if self.backfill_exchange is not None:
            df = self.backfill_exchange.fetch_ohlcv(
                self.symbol, self.timeframe, limit=max(self.warmup_bars + 2, 10)
            )
            completed = df.iloc[:-1] if len(df) >= 2 else df.iloc[0:0]
            logger.info("WS backfill: {} {} {} bars", self.symbol, self.timeframe, len(completed))
            for _, row in completed.iterrows():
                bar = bar_from_row(row)
                yield bar
                last_ts = bar.timestamp
                emitted += 1
                if self.max_bars is not None and emitted >= self.max_bars:
                    return

        # 2) WebSocket 스트림 시작
        self._thread = threading.Thread(target=self._run_ws, daemon=True)
        self._thread.start()

        try:
            while True:
                try:
                    bar = self._queue.get(timeout=120)
                except Empty:
                    logger.warning("WebSocket idle > 120s — 연결 유지 중")
                    continue
                if bar is None:
                    # sentinel (종료)
                    break
                if last_ts is not None and bar.timestamp <= last_ts:
                    continue  # 중복 봉 스킵 (재연결 시 과거 봉 재수신 가능성)
                last_ts = bar.timestamp
                yield bar
                emitted += 1
                if self.max_bars is not None and emitted >= self.max_bars:
                    return
        finally:
            self._stop.set()

    # ---- 내부 async 루프 ----
    def _run_ws(self) -> None:
        try:
            asyncio.run(self._ws_loop())
        except Exception as exc:  # noqa: BLE001
            logger.exception("WS 백그라운드 스레드 종료: {}", exc)
            self._queue.put(None)

    async def _ws_loop(self) -> None:
        delay = 1
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=30) as ws:
                    delay = 1
                    logger.info("WebSocket connected: {}", self.url)
                    async for message in ws:
                        if self._stop.is_set():
                            break
                        bar = self.parse_message(message)
                        if bar is not None:
                            self._queue.put(bar)
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    return
                logger.warning("WebSocket error ({}), {}초 후 재시도", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
