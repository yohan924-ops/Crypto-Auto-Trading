"""로깅 설정: 콘솔용 loguru + JSONL 주문 이벤트 로거.

주문 이벤트는 ``logs/orders.jsonl`` 에 append-only 로 기록되며, 파일이 무한정
커지는 것을 막기 위해 **하루 경계** 에서 자동 회전한다:

  logs/orders.jsonl                   ← 오늘자 (대시보드가 읽음)
  logs/orders-2026-04-17.jsonl        ← 어제
  logs/orders-2026-04-16.jsonl        ← 그제
  ...

회전은 ``log_order_event`` 호출 시점에서 지연 평가로 수행 — 별도 스레드나 핸들러
없이 간단하고 크래시 복구에도 안전.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

LOG_DIR = Path("logs")
ORDERS_FILE = LOG_DIR / "orders.jsonl"
APP_LOG_FILE = LOG_DIR / "app.log"

# 내부 회전 추적 (프로세스 수명 동안만 유지되어도 충분 — 최악의 경우 하루 지연됨)
_last_rotation_day: date | None = None


def _json_default(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def setup_logging(level: str = "INFO") -> None:
    """콘솔(rich) + 파일 로거 설정."""
    LOG_DIR.mkdir(exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
        colorize=True,
    )
    logger.add(
        APP_LOG_FILE,
        level="DEBUG",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
    )


def _rotate_orders_if_needed(now: datetime | None = None) -> None:
    """날짜가 바뀌었으면 현재 orders.jsonl 을 ``orders-YYYY-MM-DD.jsonl`` 로 이동.

    내부 상태 ``_last_rotation_day`` 로 하루당 최대 1회만 실행.
    파일 시스템 에러가 나도 로깅 자체는 계속 동작하도록 예외를 삼킨다.
    """
    global _last_rotation_day
    now = now or datetime.now(UTC)
    today = now.date()
    if _last_rotation_day == today:
        return
    try:
        if ORDERS_FILE.exists():
            # 파일의 마지막 수정 시각으로 rotation 대상 날짜 결정 (더 정확)
            mtime = datetime.fromtimestamp(ORDERS_FILE.stat().st_mtime, tz=UTC).date()
            if mtime < today:
                archive = LOG_DIR / f"orders-{mtime.isoformat()}.jsonl"
                if not archive.exists():
                    ORDERS_FILE.rename(archive)
                else:
                    # 같은 날짜 아카이브가 이미 있으면 append
                    with open(archive, "a", encoding="utf-8") as dst, open(
                        ORDERS_FILE, encoding="utf-8"
                    ) as src:
                        dst.write(src.read())
                    ORDERS_FILE.unlink()
    except OSError as exc:
        logger.warning("orders.jsonl 회전 실패: {}", exc)
    _last_rotation_day = today


def log_order_event(event: dict) -> None:
    """주문/체결/신호 이벤트를 JSONL 파일에 한 줄씩 기록. 하루 단위 자동 회전."""
    LOG_DIR.mkdir(exist_ok=True)
    _rotate_orders_if_needed()
    with open(ORDERS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=_json_default, ensure_ascii=False) + "\n")
