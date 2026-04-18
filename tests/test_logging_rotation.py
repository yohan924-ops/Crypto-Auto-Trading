"""orders.jsonl 일별 회전 테스트."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import tradingbot.logging_setup as ls


def _reset_state():
    ls._last_rotation_day = None


def test_no_rotation_when_file_absent(tmp_path, monkeypatch):
    _reset_state()
    monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
    monkeypatch.setattr(ls, "ORDERS_FILE", tmp_path / "orders.jsonl")
    # 파일 없어도 에러 안 남
    ls._rotate_orders_if_needed(datetime(2026, 4, 18, tzinfo=UTC))
    assert not (tmp_path / "orders.jsonl").exists()


def test_rotation_moves_yesterday_file(tmp_path, monkeypatch):
    _reset_state()
    monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
    monkeypatch.setattr(ls, "ORDERS_FILE", tmp_path / "orders.jsonl")

    # 어제 날짜의 파일 생성
    yesterday = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
    orders = tmp_path / "orders.jsonl"
    orders.write_text('{"event":"signal"}\n', encoding="utf-8")
    # mtime 을 어제로 설정
    ts = yesterday.timestamp()
    os.utime(orders, (ts, ts))

    ls._rotate_orders_if_needed(datetime(2026, 4, 18, 0, 5, tzinfo=UTC))

    assert not orders.exists(), "orders.jsonl 이 이동돼야 함"
    archive = tmp_path / "orders-2026-04-17.jsonl"
    assert archive.exists()
    assert archive.read_text(encoding="utf-8") == '{"event":"signal"}\n'


def test_same_day_no_rotation(tmp_path, monkeypatch):
    _reset_state()
    monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
    monkeypatch.setattr(ls, "ORDERS_FILE", tmp_path / "orders.jsonl")

    today = datetime(2026, 4, 18, 10, 0, tzinfo=UTC)
    orders = tmp_path / "orders.jsonl"
    orders.write_text('{"event":"x"}\n', encoding="utf-8")
    os.utime(orders, (today.timestamp(), today.timestamp()))

    ls._rotate_orders_if_needed(datetime(2026, 4, 18, 15, 0, tzinfo=UTC))

    assert orders.exists(), "같은 날짜면 회전 X"
    assert orders.read_text(encoding="utf-8") == '{"event":"x"}\n'


def test_rotation_runs_only_once_per_day(tmp_path, monkeypatch):
    _reset_state()
    monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
    monkeypatch.setattr(ls, "ORDERS_FILE", tmp_path / "orders.jsonl")

    yesterday = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
    orders = tmp_path / "orders.jsonl"
    orders.write_text('{"a":1}\n', encoding="utf-8")
    os.utime(orders, (yesterday.timestamp(), yesterday.timestamp()))

    # 첫 호출 — 회전 발생
    ls._rotate_orders_if_needed(datetime(2026, 4, 18, 0, 5, tzinfo=UTC))
    archive = tmp_path / "orders-2026-04-17.jsonl"
    assert archive.exists()

    # 새로운 이벤트 쓴 뒤 오늘 같은 날짜로 다시 호출 — 회전 안 됨
    orders.write_text('{"b":2}\n', encoding="utf-8")
    os.utime(orders, (datetime(2026, 4, 18, 1, 0, tzinfo=UTC).timestamp(),) * 2)
    ls._rotate_orders_if_needed(datetime(2026, 4, 18, 23, 0, tzinfo=UTC))
    assert orders.exists() and orders.read_text(encoding="utf-8") == '{"b":2}\n'


def test_log_order_event_triggers_rotation(tmp_path, monkeypatch):
    _reset_state()
    monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
    monkeypatch.setattr(ls, "ORDERS_FILE", tmp_path / "orders.jsonl")

    # 어제자 파일 존재
    orders = tmp_path / "orders.jsonl"
    orders.write_text('{"old":true}\n', encoding="utf-8")
    yesterday = datetime.now(UTC) - timedelta(days=2)
    os.utime(orders, (yesterday.timestamp(), yesterday.timestamp()))

    # 실제 log_order_event 호출 시 회전 발생 + 오늘자 새 파일 생성
    ls.log_order_event({"event": "test", "price": 100.0})

    # 회전된 아카이브 존재
    archives = list(tmp_path.glob("orders-*.jsonl"))
    assert len(archives) == 1

    # 새 orders.jsonl 에 방금 기록 포함
    assert orders.exists()
    content = orders.read_text(encoding="utf-8").strip()
    assert json.loads(content)["event"] == "test"


def test_existing_archive_gets_appended(tmp_path, monkeypatch):
    """같은 날짜의 아카이브가 이미 있으면 덮어쓰지 않고 append."""
    _reset_state()
    monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
    monkeypatch.setattr(ls, "ORDERS_FILE", tmp_path / "orders.jsonl")

    yesterday = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
    # 기존 아카이브
    archive = tmp_path / "orders-2026-04-17.jsonl"
    archive.write_text('{"prior":1}\n', encoding="utf-8")
    # 새로 회전될 파일
    orders = tmp_path / "orders.jsonl"
    orders.write_text('{"new":2}\n', encoding="utf-8")
    os.utime(orders, (yesterday.timestamp(), yesterday.timestamp()))

    ls._rotate_orders_if_needed(datetime(2026, 4, 18, tzinfo=UTC))

    assert not orders.exists()
    assert archive.exists()
    lines = archive.read_text(encoding="utf-8").strip().split("\n")
    assert lines == ['{"prior":1}', '{"new":2}']
