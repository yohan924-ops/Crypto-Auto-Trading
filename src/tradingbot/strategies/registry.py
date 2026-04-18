"""전략 플러그인 레지스트리.

구현체는 ``@register`` 로 등록되고, 엔진은 ``get(name)`` 으로 이름 조회한다.
"""

from __future__ import annotations

from .base import Strategy

_REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    """전략 클래스를 레지스트리에 등록하는 데코레이터."""
    if not hasattr(cls, "name") or not cls.name:
        raise ValueError(f"{cls.__name__} 에 'name' 클래스 변수가 필요합니다.")
    if cls.name in _REGISTRY:
        raise ValueError(f"전략 이름 중복: {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def get(name: str) -> type[Strategy]:
    """이름으로 전략 클래스 조회."""
    if name not in _REGISTRY:
        available = sorted(_REGISTRY.keys())
        raise KeyError(f"등록되지 않은 전략: {name!r}. 사용 가능: {available}")
    return _REGISTRY[name]


def available() -> list[str]:
    """등록된 전략 이름 목록."""
    return sorted(_REGISTRY.keys())
