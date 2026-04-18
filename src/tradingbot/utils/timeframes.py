"""타임프레임 유틸."""

from __future__ import annotations

_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def timeframe_to_seconds(timeframe: str) -> int:
    """ccxt 스타일 타임프레임을 초 단위로 변환.

    예: "1m" -> 60, "1h" -> 3600, "4h" -> 14400, "1d" -> 86400
    """
    if not timeframe:
        raise ValueError("timeframe 이 비어 있음")
    unit = timeframe[-1]
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"지원하지 않는 타임프레임 단위: {unit}")
    try:
        count = int(timeframe[:-1])
    except ValueError as exc:
        raise ValueError(f"잘못된 타임프레임 형식: {timeframe}") from exc
    if count <= 0:
        raise ValueError(f"타임프레임 숫자는 양수여야 함: {timeframe}")
    return count * _UNIT_SECONDS[unit]
