"""WebSocket 피드 테스트 — 메시지 파싱 + 큐 기반 스트림."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

from tradingbot.data.ws_feed import BinanceWebSocketFeed


def _kline_msg(
    t_ms: int,
    o: float,
    h: float,
    lo: float,
    c: float,
    v: float,
    closed: bool = True,
) -> str:
    return json.dumps(
        {
            "e": "kline",
            "E": t_ms + 1000,
            "s": "BTCUSDT",
            "k": {
                "t": t_ms,
                "T": t_ms + 3600 * 1000 - 1,
                "s": "BTCUSDT",
                "i": "1h",
                "o": str(o),
                "c": str(c),
                "h": str(h),
                "l": str(lo),
                "v": str(v),
                "x": closed,
            },
        }
    )


def test_parse_closed_kline_returns_bar():
    msg = _kline_msg(
        t_ms=1_700_000_000_000,
        o=30_000,
        h=30_500,
        lo=29_500,
        c=30_200,
        v=12.3,
    )
    bar = BinanceWebSocketFeed.parse_message(msg)
    assert bar is not None
    assert bar.open == 30_000.0
    assert bar.close == 30_200.0
    assert bar.timestamp == datetime.fromtimestamp(1_700_000_000, tz=UTC)


def test_parse_unclosed_kline_returns_none():
    msg = _kline_msg(1_700_000_000_000, 1, 2, 1, 1.5, 1.0, closed=False)
    assert BinanceWebSocketFeed.parse_message(msg) is None


def test_parse_invalid_json_returns_none():
    assert BinanceWebSocketFeed.parse_message("not json") is None
    assert BinanceWebSocketFeed.parse_message(b"\x00\x01bad") is None


def test_parse_missing_kline_field():
    assert BinanceWebSocketFeed.parse_message(json.dumps({"e": "ping"})) is None


def test_url_construction_sandbox_vs_mainnet():
    f1 = BinanceWebSocketFeed(symbol="BTC/USDT", timeframe="1h", sandbox=False)
    f2 = BinanceWebSocketFeed(symbol="BTC/USDT", timeframe="1h", sandbox=True)
    assert "testnet.binance.vision" in f2.url
    assert "testnet.binance.vision" not in f1.url
    assert "btcusdt@kline_1h" in f1.url
    assert "btcusdt@kline_1h" in f2.url


def test_stream_bars_yields_from_queue(monkeypatch):
    """백그라운드 스레드 대신 큐에 직접 넣어 주 로직 검증."""
    feed = BinanceWebSocketFeed(
        symbol="BTC/USDT",
        timeframe="1h",
        sandbox=False,
        max_bars=2,
        backfill_exchange=None,
    )

    # WebSocket 루프 대신 no-op 스레드
    def fake_thread_target():
        pass

    # _run_ws 를 호출해도 실제 소켓 연결을 시도하지 않도록 스텁
    feed._run_ws = fake_thread_target  # type: ignore[assignment]

    # 큐에 bar 2개 미리 넣어둔다
    from tradingbot.strategies.base import Bar

    bars_in = [
        Bar(
            timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
            open=100, high=101, low=99, close=100.5, volume=1.0,
        ),
        Bar(
            timestamp=datetime(2024, 1, 1, 1, 0, tzinfo=UTC),
            open=100.5, high=102, low=100, close=101.5, volume=1.0,
        ),
    ]
    for b in bars_in:
        feed._queue.put(b)

    # 스트림 소비
    out = list(feed.stream_bars())
    assert len(out) == 2
    assert out[0].timestamp < out[1].timestamp


def test_stream_bars_dedups_by_timestamp(monkeypatch):
    feed = BinanceWebSocketFeed(symbol="BTC/USDT", timeframe="1h", max_bars=2)
    feed._run_ws = lambda: None  # type: ignore[assignment]

    from tradingbot.strategies.base import Bar

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    # 같은 timestamp 의 두 번째 bar 는 무시되어야 함
    feed._queue.put(Bar(timestamp=ts, open=100, high=100, low=100, close=100, volume=1))
    feed._queue.put(Bar(timestamp=ts, open=101, high=101, low=101, close=101, volume=1))
    feed._queue.put(
        Bar(
            timestamp=ts.replace(hour=1),
            open=102, high=102, low=102, close=102, volume=1,
        )
    )

    out = list(feed.stream_bars())
    assert len(out) == 2
    assert out[0].close == 100
    assert out[1].close == 102


def test_stream_bars_sentinel_stops_iteration(monkeypatch):
    feed = BinanceWebSocketFeed(symbol="BTC/USDT", timeframe="1h")
    feed._run_ws = lambda: None  # type: ignore[assignment]

    feed._queue.put(None)  # sentinel
    out = list(feed.stream_bars())
    assert out == []
    # 종료 이벤트가 설정됐는지
    assert isinstance(feed._stop, threading.Event)
