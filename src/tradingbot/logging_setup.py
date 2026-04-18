"""로깅 설정: 콘솔용 loguru + JSONL 주문 이벤트 로거."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

LOG_DIR = Path("logs")
ORDERS_FILE = LOG_DIR / "orders.jsonl"
APP_LOG_FILE = LOG_DIR / "app.log"


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


def log_order_event(event: dict) -> None:
    """주문/체결/신호 이벤트를 JSONL 파일에 한 줄씩 기록."""
    LOG_DIR.mkdir(exist_ok=True)
    with open(ORDERS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=_json_default, ensure_ascii=False) + "\n")
