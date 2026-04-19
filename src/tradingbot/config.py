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


class HeartbeatCfg(BaseModel):
    """Heartbeat (정기 상태 보고) 설정.

    ``enabled=True`` 이면 지정된 UTC 시각이 지날 때마다 NotifyEvent.HEARTBEAT
    알림을 발송한다. 스윙 전략처럼 매매 빈도가 낮을 때 "봇이 살아있음" 신호 역할.
    """

    enabled: bool = False
    # UTC 시각 목록. 기본은 00:00, 12:00 UTC (KST 09:00, 21:00).
    hours_utc: list[int] = Field(default_factory=lambda: [0, 12])


class RiskCfg(BaseModel):
    max_position_pct: float = 0.10
    stop_loss_pct: float = 0.05
    max_daily_loss_pct: float = 0.05
    # 트레일링 스탑: 포지션 평가 최고점 대비 하락률이 이 값 이상이면 강제 청산.
    # 기본값 0.0 = 비활성 (기존 전략 동작 호환). 활성화 예: 0.02 = 최고점 대비 -2%.
    trailing_stop_pct: float = 0.0
    # 트레일링은 "수익권 진입" 후에만 작동. 활성화 임계: 평균진입가 대비 +pct.
    # 매수 직후 횡보에서 트레일링이 일반 손절보다 먼저 트리거되는 것을 방지.
    trailing_activate_pct: float = 0.05
    # ATR 기반 동적 손절. True 면 stop_loss_pct 대신 atr × atr_multiplier 사용.
    use_atr_stop: bool = False
    atr_multiplier: float = 2.0


class SleeveCfg(BaseModel):
    """Sleeve 1개의 설정 (심볼 + 전략 + 배분 + 개별 리스크 규칙)."""

    name: str
    symbol: str
    allocation_pct: float  # 0.0~1.0, 전체 자본 중 비율
    strategy: StrategyCfg
    risk: RiskCfg = Field(default_factory=RiskCfg)


class Settings(BaseSettings):
    """YAML 기본값 + .env 로 시크릿 주입.

    .env/환경변수로는 시크릿(대문자 최상위 필드)만 주입한다.
    거래 파라미터(symbol, exchange.sandbox, risk.*)는 반드시 settings.yaml 에서만
    설정하도록 중첩 delimiter 를 비활성화했다. 과거 EXCHANGE__SANDBOX 같은 환경변수
    한 줄로 Testnet→Mainnet 전환이 일어나는 사고를 막기 위함.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
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
    portfolio: list[PortfolioItemCfg] | None = None  # 설정 시 멀티 자산 모드 (공용 풀)
    sleeves: list[SleeveCfg] | None = None  # 설정 시 Sleeve 모드 (독립 자본)
    # Sleeve 모드에서 계좌 전체 일일 손실 서킷브레이커 임계
    sleeve_max_daily_loss_pct: float = 0.10
    risk: RiskCfg = Field(default_factory=RiskCfg)
    heartbeat: HeartbeatCfg = Field(default_factory=HeartbeatCfg)
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
