"""과거 OHLCV 일괄 조회 + CSV 캐시.

``fetch_historical`` 은 [start, end) 구간의 봉을 거래소에서 페이지 단위로
반복 요청하여 하나의 DataFrame으로 병합한다. 로컬 CSV 캐시가 있으면 필요한
구간만 보충 조회.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from tradingbot.exchange.ccxt_adapter import CCXTAdapter
from tradingbot.utils.timeframes import timeframe_to_seconds

_PAGE_LIMIT = 1000


def _cache_path(cache_dir: Path, exchange_id: str, symbol: str, timeframe: str) -> Path:
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    return cache_dir / f"{exchange_id}_{safe_symbol}_{timeframe}.csv"


def _load_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _save_cache(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values("timestamp", inplace=True)
    df.drop_duplicates(subset=["timestamp"], inplace=True)
    df.to_csv(path, index=False)


def fetch_historical(
    exchange: CCXTAdapter,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    cache_dir: Path | str = "data",
) -> pd.DataFrame:
    """[start, end) 구간의 OHLCV를 pandas DataFrame 으로 반환.

    - 캐시 CSV 가 있으면 재사용하고 모자란 구간만 조회.
    - 반환 DataFrame 은 timestamp 오름차순, 컬럼은 timestamp/open/high/low/close/volume.
    """
    cache_dir = Path(cache_dir)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end <= start:
        raise ValueError(f"end({end}) 는 start({start}) 보다 커야 함")

    path = _cache_path(cache_dir, exchange.exchange_id, symbol, timeframe)
    cached = _load_cache(path)

    tf_ms = timeframe_to_seconds(timeframe) * 1000
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    # 요청 구간 [start, end) 중 캐시가 커버하지 못하는 부분 두 곳을 모두 조회:
    #   1) 앞쪽 gap: [start, cached_min)
    #   2) 뒤쪽 gap: (cached_max, end)
    # 과거 구현은 뒤쪽만 조회해 start < cached_min 이면 앞쪽 구간을 통째로 놓쳤다.
    fetch_ranges: list[tuple[int, int]] = []
    if cached.empty:
        fetch_ranges.append((start_ms, end_ms))
    else:
        cached_min_ms = int(cached["timestamp"].min().timestamp() * 1000)
        cached_max_ms = int(cached["timestamp"].max().timestamp() * 1000)
        if start_ms < cached_min_ms:
            fetch_ranges.append((start_ms, min(cached_min_ms, end_ms)))
        if cached_max_ms + tf_ms < end_ms:
            fetch_ranges.append((max(start_ms, cached_max_ms + tf_ms), end_ms))

    pages: list[pd.DataFrame] = []
    for range_start, range_end in fetch_ranges:
        cursor = range_start
        while cursor < range_end:
            logger.debug("fetch_ohlcv since={} limit={}", cursor, _PAGE_LIMIT)
            page = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=_PAGE_LIMIT)
            if page.empty:
                break
            pages.append(page)
            last_ts = int(page["timestamp"].iloc[-1].timestamp() * 1000)
            if last_ts <= cursor:
                break
            cursor = last_ts + tf_ms

    fetched = pd.concat(pages, ignore_index=True) if pages else cached.iloc[0:0]
    merged = pd.concat([cached, fetched], ignore_index=True)
    if not merged.empty:
        merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True)
        merged.sort_values("timestamp", inplace=True)
        merged.drop_duplicates(subset=["timestamp"], inplace=True)
        _save_cache(merged, path)

    # 요청 구간만 슬라이스
    mask = (merged["timestamp"] >= start) & (merged["timestamp"] < end)
    result = merged.loc[mask].reset_index(drop=True)
    logger.info(
        "fetch_historical {} {} {} bars from {} to {}",
        symbol,
        timeframe,
        len(result),
        start.isoformat(),
        end.isoformat(),
    )
    return result
