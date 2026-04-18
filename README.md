# 코인 자동매매 봇 (Crypto Auto-Trading Bot)

학습용 **규칙 기반 알고리즘 트레이딩(rule-based algorithmic trading)** 프로젝트입니다.
페이퍼 트레이딩으로 안전하게 시작해 단계적으로 실전까지 확장합니다.

> ⚠️ **투자 조언이 아닙니다.** 암호화폐 자동매매는 원금 손실이 발생할 수 있습니다.
> 이 저장소의 코드 사용으로 인한 모든 손실은 사용자 본인의 책임입니다.

---

## 개요

- **규칙 기반**: 사람이 정한 매매 규칙을 컴퓨터가 24/7 실행합니다. AI/ML이 아닙니다.
- **페이퍼 트레이딩 우선**: 실제 돈 없이 가상 잔고로 전략을 충분히 검증한 뒤 실전 전환합니다.
- **플러그인 전략 구조**: 새 전략을 파일 하나로 추가할 수 있도록 `Strategy` ABC + Registry 패턴 사용.
- **거래소**: CCXT 기반. **Binance Testnet**으로 시작하고, 이후 Upbit 등으로 설정만 바꿔 확장 가능.
- **알림**: Telegram으로 신호·체결·손절·일일 리포트 수신 (Phase 3 이후).

---

## 빠른 시작

```bash
# 1. 가상환경 준비
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements-dev.txt

# 3. 환경 변수 파일 생성 (API 키 입력)
cp .env.example .env

# 4. CLI 확인
python -m tradingbot --help
```

---

## 운용 모드

| 모드 | 설명 | 실구현 페이즈 |
|---|---|---|
| `paper` | 실시간 시세 + 가상 잔고 (주문 시뮬레이션) | Phase 1 |
| `backtest` | 과거 OHLCV 데이터로 전략 시뮬레이션 | Phase 2 |
| `live` | **실제 자산 주문**. Testnet 우선, 이중 게이트 보호 | Phase 4 |

---

## 프로젝트 구조

```
Crypto-Auto-Trading/
├── config/              # settings.yaml, strategies/*.yaml
├── src/tradingbot/
│   ├── cli.py           # CLI 엔트리
│   ├── config.py        # 설정 로더 (Phase 1)
│   ├── exchange/        # CCXT 어댑터 (Phase 1)
│   ├── data/            # 실시간/과거 OHLCV (Phase 1, 2)
│   ├── strategies/      # Strategy ABC + 구체 전략 (Phase 2, 5)
│   ├── broker/          # 페이퍼/실전 브로커 (Phase 1, 4)
│   ├── portfolio/       # 잔고/포지션/리스크 (Phase 1, 3)
│   ├── notifier/        # 텔레그램 알림 (Phase 3)
│   ├── engine/          # 실시간 루프 + 백테스터 (Phase 1, 2)
│   └── utils/           # 지표 헬퍼 (Phase 2)
└── tests/
```

---

## 안전 안내

- `.env` 파일은 **절대로 git에 커밋하지 마세요** (`.gitignore`에 포함됨).
- Binance API 키 발급 시 **"Spot Trading"만 허용**하고 **"Withdrawal(출금)"은 반드시 비활성화**합니다.
- 실전 전환 전 페이퍼 트레이딩·백테스트로 충분히 검증하세요.
- 기본 설정값은 **Testnet**입니다 (`config/settings.yaml`의 `exchange.sandbox: true`).

---

## 핵심 용어 (초보자용)

| 용어 | 설명 |
|---|---|
| **OHLCV** | 한 기간의 시세 요약: 시가/고가/저가/종가/거래량 |
| **타임프레임** | 봉 하나의 길이 (`1h`, `1d` 등) |
| **SMA / EMA** | 단순·지수 이동평균. 추세 지표 |
| **RSI** | 0~100 모멘텀 지표. 30↓ 과매도, 70↑ 과매수 |
| **골든/데드 크로스** | 단기 이평선이 장기 이평선 상/하향 돌파 |
| **슬리피지** | 원한 가격과 실제 체결가 차이 |
| **bps** | 0.01% (`fee_bps=10` = 0.1%) |
| **Equity** | 현금 + 포지션 평가액 총합 |
| **MDD** | 최대 낙폭 (고점→저점 최대 손실%) |
| **페이퍼 트레이딩** | 실제 돈 없이 가상 체결 시뮬레이션 |
| **백테스트** | 과거 데이터로 전략 성능 검증 |
| **Testnet** | 거래소 제공 가짜 환경 (실전과 동일 API, 가상 자산) |

---

## 진행 상황

- [x] **Phase 0** — 프로젝트 스캐폴딩
- [x] **Phase 1** — 페이퍼 엔진 MVP (buy-and-hold, PaperBroker, Runner)
- [x] **Phase 2** — 이동평균 교차 전략 + 백테스트
- [x] **Phase 3** — 리스크 가드레일(손절/서킷브레이커) + 텔레그램 알림
- [x] **Phase 4** — Binance Testnet 실전 모드 (LiveBroker + 이중 게이트)
- [ ] **Phase 5** — RSI 전략 추가 + 다듬기

### 리스크 가드레일 & 알림

- **손절**: 포지션이 `stop_loss_pct` 이상 하락하면 자동 전량 청산
- **일일 서킷브레이커**: 하루 기준 `max_daily_loss_pct` 넘게 손실이면 당일 신규 진입 차단 (다음날 자동 해제)
- **드라이런**: `--dry-run` 으로 실제 주문 제출 없이 결정만 로그
- **텔레그램**: `.env` 에 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 설정 후
  `config/settings.yaml` 의 `notifiers` 에 `telegram` 추가하면 신호/체결/손절/일일 리포트를 봇으로 수신


### 백테스트 사용 예

```bash
# BTC/USDT 1h, 2024년 상반기, MA(20/50) 크로스 전략
python -m tradingbot backtest --start 2024-01-01 --end 2024-07-01

# 에쿼티 커브까지 CSV 저장
python -m tradingbot backtest --start 2024-01-01 --end 2024-07-01 \
    --save-curve logs/equity.csv
```

---

## 실전 모드 사용법 (Testnet 먼저!)

> ⚠️ 실전(live) 모드는 실제 자산이 움직일 수 있습니다. **반드시 Testnet 에서 충분히 돌려본 뒤** 메인넷으로 전환하세요.

### 1. Binance Testnet API 키 발급

1. https://testnet.binance.vision/ 접속 → "Log In with GitHub" 로 로그인
2. "Generate HMAC_SHA256 Key" 클릭 → **API Key / Secret Key** 복사
3. 기본 가상 잔고 (≈ 1 BTC, 10,000 USDT 등) 제공됨
4. 프로젝트의 `.env` 에 저장:

```
BINANCE_API_KEY=발급받은_키
BINANCE_API_SECRET=발급받은_시크릿
```

### 2. 실전 모드 이중 게이트 해제

`config/settings.yaml` 에서:

```yaml
live_confirmed: true          # 1차 게이트
exchange:
  sandbox: true               # Testnet 유지 (메인넷 전환 전 반드시 충분한 검증)
```

### 3. 실행

```bash
# Testnet 실행 (가상 자산, Binance 에서 주문 확인 가능)
python -m tradingbot live --i-understand-real-money

# 10봉만 돌려서 확인 후 종료
python -m tradingbot live --i-understand-real-money --max-bars 10
```

두 게이트(`live_confirmed: true` + `--i-understand-real-money`) 중 하나라도 없으면 프로그램은 안전하게 거부됩니다. 실행 시 5초 안전 카운트다운 후 진입.

### 4. 메인넷 전환 (숙련된 뒤 최후)

```yaml
exchange:
  sandbox: false              # 🚨 메인넷 = 실제 자산
```

`.env` 의 키도 Binance **메인넷** 키로 교체해야 하며, 다음을 꼭 지킵니다:
- API 키 권한에서 **"Spot Trading"만 허용**, **"Withdrawal(출금) 반드시 비활성화"**
- `starting_cash` 를 계정 실제 잔고와 일치시키기
- 소액으로 시작 (권장: 월 생활비의 수 %)

## 라이선스

Private learning project.
