"""설정 로더.

``config/settings.yaml`` 의 값을 기본으로 하고, ``.env`` 의 환경 변수로 시크릿을 덮어쓴다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExchangeCfg(BaseModel):
    id: str = "binance"
    sandbox: bool = True


class StrategyCfg(BaseModel):
    name: str = "buy_and_hold"
    params: dict = Field(default_factory=dict)


class PortfolioItemCfg(BaseModel):
    """멀티 자산 포트폴리오의 각 항목."""

    symbol: str
    strategy: StrategyCfg
    weight: float = 1.0


class RiskCfg(BaseModel):
    max_position_pct: float = 0.10
    stop_loss_pct: float = 0.05
    max_daily_loss_pct: float = 0.05


class Settings(BaseSettings):
    """YAML 기본값 + .env 로 시크릿 주입.

    환경변수 이름은 대문자. 중첩 필드는 ``__`` 로 구분 가능 (예: EXCHANGE__SANDBOX=false).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    mode: Literal["paper", "backtest", "live"] = "paper"
    live_confirmed: bool = False
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    starting_cash: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    use_websocket: bool = False  # paper/live 에서 REST 폴링 대신 WS 피드 사용

    exchange: ExchangeCfg = Field(default_factory=ExchangeCfg)
    strategy: StrategyCfg = Field(default_factory=StrategyCfg)
    portfolio: list[PortfolioItemCfg] | None = None  # 설정 시 멀티 자산 모드
    risk: RiskCfg = Field(default_factory=RiskCfg)
    notifiers: list[str] = Field(default_factory=lambda: ["console"])

    # 시크릿 (.env 에서 로드) — 거래소 공통 (Binance/Upbit 모두 이 키를 사용)
    exchange_api_key: str | None = None
    exchange_api_secret: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


def load_settings(config_path: str | Path = "config/settings.yaml") -> Settings:
    """YAML 로부터 설정을 읽어 Settings 인스턴스를 생성.

    YAML 이 없으면 기본값만 사용. .env 값은 항상 병합된다.
    """
    path = Path(config_path)
    yaml_data: dict = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
    return Settings(**yaml_data)
