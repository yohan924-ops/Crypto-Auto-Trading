# CLAUDE.md — 프로젝트 컨텍스트 지침서

> 이 파일은 Claude Code 가 저장소를 열 때 자동으로 읽습니다.
> 새 세션이 기존 대화 맥락을 모르더라도 이 문서로 동등한 수준의 이해를 갖도록 작성되었습니다.

## 0. 프로젝트 한 줄 요약

**암호화폐 자동매매 봇 (Python, 규칙 기반 알고리즘 트레이딩, 학습용 MVP → 점진적 실전 운용)**

---

## 0-A. 🎯 현재 선정된 운용 전략 (ACTIVE STRATEGY)

**다른 AI 가 이 저장소를 열었을 때 가장 먼저 읽어야 하는 섹션.** 지금 이 프로젝트에서 실전·페이퍼 운용 후보로 **확정된 전략은 단 하나**:

### 🏆 Swing Pullback v2 (Gemini 제안 + 거래량 필터 튜닝)

| 항목 | 값 |
|---|---|
| 전략 이름 | `swing_pullback` |
| 전략 소스 | [`src/tradingbot/strategies/swing_pullback.py`](src/tradingbot/strategies/swing_pullback.py) |
| 백테스트 설정 | [`config/bt_swing_pullback_v2.yaml`](config/bt_swing_pullback_v2.yaml) |
| **타임프레임** | **4h** |
| 심볼 (검증) | BTC/USDT |

### 논리 회로 (상태 머신)

```text
[1단계 거시 필터]  close > EMA(300)         ← 하락장 차단 (4h × 300 = 50일 ≈ 1D EMA50 근사)
[2단계 눌림 포착]  RSI(14) ∈ [40, 45]       ← ready = True (상승장 pullback 감지)
[3단계 진입 확인]  Supertrend(10, 3) = UP
                 AND MACD(12,26,9) 히스토그램 음→양 전환
                 AND volume > volume_ma(20)
→ 모두 ✅ 이고 ready=True 이면 BUY

[청산 규칙 (전략 내부)]
- Supertrend 상→하 전환 → SELL (동적 손절)
- RSI(14) ≥ 70 → SELL (과매수 익절)

[청산 규칙 (RiskManager 외부 방어선)]
- stop_loss_pct: 0.08     (진입가 대비 -8%)
- trailing_activate_pct: 0.10  (+10% 수익권 도달 후 활성)
- trailing_stop_pct: 0.05      (피크 대비 -5% 하락 시 청산)
- max_daily_loss_pct: 0.10
- max_position_pct: 0.30
```

### 선정 근거 (백테스트 6구간 × 3.5년)

| 구간 | 수익률 | 거래 | MDD |
|---|---|---|---|
| 2022 H2 (하락장 🔥) | **+1.40%** | 4 | 0.12% |
| 2023 H1 (완만 상승) | +1.01% | 2 | 0.05% |
| 2024 H1 (박스권) | -0.92% | 6 | 1.90% |
| 2024 H2 (강한 추세) | **+2.93%** | 6 | 0.88% |
| 2025 H1 | **+2.15%** | 4 | 1.00% |
| 2025 H2 | 0% (거래 0회) | 0 | 0% |
| **복리 누적** | **+6.72%** | — | 최악 -0.92% |

**핵심 의사결정**: 같은 기간 rsi_reversal 은 2022 H2 하락장에 -2.78% 로 무너짐. swing_pullback 만 **하락장에서도 + 수익** 냄.

### 기각된 대안 (절대 되돌리지 말 것)

| 전략 | 기각 이유 |
|---|---|
| `rsi_reversal` | 하락장(2022 H2) -2.78% 치명적. 추세 필터 없음 |
| `rsi_reversal_v2` | EMA200 필터 추가했지만 기회 너무 줄어 평균 -0.23% |
| `triple_screen` | 조건 4개 AND "상태 유지" 방식 — 수수료 누적으로 6구간 평균 -1.24% |
| `pullback` | EMA(120) 1h 너무 엄격, 기회 부족. 3구간 평균 -0.17% |
| `swing_pullback` v3/v4/v5 튜닝안 | RSI 범위↓, Supertrend mult↑, 거래량 임계↑ — **전부 v2 대비 개선 없거나 악화** |
| 2봇 병행 (swing + rsi) | 50:50 단순 평균 시 rsi 하락장 손실이 swing 수익을 깎음 → 평균 +0.43% (swing 단독 +1.11% 보다 낮음) |

### 실전 전개 순서

1. **Testnet 페이퍼 72봉 이상 관찰** (4h × 72 = 12일 권장) — `paper_swing.yaml` 로 (미생성 시 `bt_swing_pullback_v2.yaml` 의 `sandbox: false` 를 `true` 로, `mode: paper` 로 변경 복사)
2. **Upbit BTC/KRW 실전 소액** (25만원, max_position_pct 는 실전 시 0.10 으로 축소 권장)
3. 1~2개월 안정 후 다른 코인(ETH 등) 에 동일 전략 확장 고려 — **단일 자산 2봇은 "가짜 분산" 이니 금지**

---

## 1. 프로젝트가 무엇이고 무엇이 아닌가

### 이것이다
- **규칙 기반(Rule-based) 알고리즘 트레이딩**: 사람이 정한 매매 규칙을 Python 이 실시간 실행
- **학습용 MVP**: 초보자가 시장·매매·인프라를 이해하면서 점진 확장
- **거래소 범용**: CCXT 위에 얇게 추상화, `exchange.id` 만 바꿔 Binance ↔ Upbit 전환
- **플러그인 전략 구조**: `@register` 한 줄로 새 전략 파일 추가 가능, 엔진 코드 무수정

### 이것이 아니다
- **AI 에이전트 봇이 아님** (LLM 이 의사결정하는 구조 아님)
- **프로덕션 트레이딩 인프라 아님** (수백억 자본 운용 목적 X)
- **수익 보장 없음** — 백테스트 성과는 과거일 뿐

### AI 에이전트를 기본에서 제외한 이유 (결정 배경)
1. 학습 단계에서 "왜 샀는지" 본인이 모르면 개선 불가
2. LLM 응답은 완전히 결정론적이지 않음 → 백테스트 신뢰도 하락
3. API 호출당 비용 + 지연 → 스캘핑/고빈도 불가
4. 실제 수익 내는 퀀트 펀드들은 규칙/ML 기반이지 LLM 기반 아님
5. LLM 공급자 다운타임·모델 변경 리스크

단, `Strategy` ABC 는 AI 전략도 받을 수 있도록 설계됨. 사용자가 규칙 기반으로 충분히 숙달한 뒤 `strategies/llm_agent.py` 를 추가하는 것이 권장 경로.

---

## 2. 사용자 프로필

- **수준**: 자동매매·Python 모두 초보자 (완전 입문자 출발)
- **언어**: 한국어 우선 (문서·주석·로그 한국어)
- **Claude 구독**: **Max 플랜** (Claude Code Remote Control 사용 가능)
- **자본 규모**: 500만원 이상 (고정비 월 수만원은 허용되지만 월 $50+ API 비용은 부담)
- **목표**: 학습 → 점진적 자본 증액 → 안정적 자동 운용
- **리스크 태도**: **버그 우려가 큼, 점진적·방어적 접근 선호**
- **거래소 선호**: 당장은 Binance Testnet 학습, 실전 진입 시점에 Upbit 전환 가능성 높음 (원화·세금·한국 자료 이점)
- **알림**: 텔레그램 봇 사용 의향 있음

---

## 3. 아키텍처 결정 (결정과 이유)

| 결정 | 선택 | 이유 |
|---|---|---|
| 거래소 라이브러리 | **CCXT** | Binance→Upbit 설정 한 줄 전환, Upbit 공식 문서도 CCXT 권장 |
| 첫 거래소 | **Binance Testnet** | 공식 테스트넷 존재, 실전 전환 시 코드 변경 최소 |
| 매매 판단 | **규칙 기반** | 위 §1 참고 |
| 전략 등록 | **ABC + Registry + `@register`** | 파일 하나로 전략 추가, 엔진 코드 수정 없음 |
| 데이터 피드 | **REST 폴링 기본 + WebSocket 옵션** | 1h/1d 전략엔 폴링 충분, 1m 이하 필요 시 WS 활성화 |
| DB | **JSONL 파일** | 개인용·MVP 범위에서 Supabase 등 오버엔지니어링 |
| 알림 전송 | **stdlib `urllib`** | `python-telegram-bot` async 복잡도 회피, 실패는 삼키고 로그만 |
| 프로세스 구조 | **sync 단일 프로세스** | 백테스트/페이퍼 단순화. WS 만 백그라운드 스레드 + 큐 |
| 실전 진입 장벽 | **이중 게이트** (`live_confirmed: true` YAML + `--i-understand-real-money` CLI + API 키 존재 + 5초 카운트다운) | 초보자 실수 방지 |
| 환경변수 네이밍 | **`EXCHANGE_API_KEY/SECRET`** | Binance·Upbit 공통, 전환 시 값만 교체 |

---

## 4. 페이즈 히스토리 (12개 커밋)

| Phase | 커밋 | 내용 |
|---|---|---|
| 0 | `a6d7eca` | 프로젝트 스캐폴딩, CLI 스텁, 한국어 README |
| 1 | `421ca20` | 페이퍼 엔진 MVP (PaperBroker, Portfolio, Runner, RiskManager 최소) |
| 2 | `87ffef0` | MA 크로스오버 전략 + 백테스터 + `process_bar` 공통화 |
| 3 | `d196b88` | 손절/서킷브레이커, Notifier 플러그인(Console/Telegram), --dry-run |
| 4 | `71dccda` | LiveBroker + CLI `live` 이중 게이트 + Testnet 가이드 |
| 5 | `8a6d469` | RSI 전략 + Sharpe/Sortino/승률 + GitHub Actions CI |
| Refactor | `b8b6e84` | `BINANCE_*` → `EXCHANGE_API_*` 네이밍 통일 (Upbit 전환 준비) |
| 6A | `f6066bc` | 볼린저·변동성 돌파 전략 + Bollinger/ATR 지표 |
| 6B | `c13ba58` | Plotly HTML 백테스트 리포트 (`--save-report`) |
| 6C | `ca81fd1` | 멀티 자산 백테스트 (`portfolio:` 설정) |
| 6D | `37eb55a` | Streamlit 웹 대시보드 (`tradingbot dashboard`) |
| 6E | `c05cbce` | Binance WebSocket 실시간 피드 (`use_websocket: true`) |
| Security | `24e6e79` | 실전 진입 전 취약점·버그 14건 일괄 수정 (ENV 오버라이드 차단, clientOrderId, 트레일링 인프라 등) |
| Strategy | `b069ae8` | MACD/Volume MA/Supertrend 지표 + triple_screen/pullback/swing_pullback/rsi_reversal_v2 전략 + 6구간 튜닝 실험 (swing_pullback_v2 확정) |

---

## 5. 내장 전략 9종

| 이름 | 타입 | 상태 | 언제 쓰는가 |
| --- | --- | --- | --- |
| `buy_and_hold` | 검증용 | 유지 | 엔드투엔드 파이프라인 테스트 전용 |
| `ma_crossover` | 추세 추종 | 유지 | 장기 트렌드 시장. Default `fast=20, slow=50` |
| `rsi_reversal` | 모멘텀 역추세 | **기각** | 하락장 취약 (2022 H2 -2.78%) — §0-A 참고 |
| `rsi_reversal_v2` | + EMA200 필터 | 실험 | 하락장 방어됐지만 기회 부족 — 평균 -0.23% |
| `bollinger_breakout` | 변동성 추종 | 유지 | 변동성 확장기. 현재 바 제외한 밴드 기준 돌파 |
| `volatility_breakout` | 데일리 추세 | 유지 | 래리 윌리엄스 변동성 돌파 (1일봉 권장) |
| `triple_screen` | 4조건 AND | **기각** | 수수료 누적으로 평균 -1.24% — §0-A 참고 |
| `pullback` | Gemini v1 | **기각** | 1h 기준 기회 부족 — 평균 -0.17% |
| **`swing_pullback`** | **Gemini v2 스윙** | **🎯 활성 후보** | **§0-A 참고, 6구간 복리 +6.72%** |

### 첫 실전 진입 추천 전략 (2026-04 업데이트)

**`swing_pullback` v2 on `BTC/USDT` `4h`** — 파라미터는 [`config/bt_swing_pullback_v2.yaml`](config/bt_swing_pullback_v2.yaml)

이유:

- 6구간 3.5년 백테스트 **유일하게 하락장·상승장·박스권 모두 양수 또는 손실 최소**
- Supertrend + MACD + RSI + Volume MA 4축 교차 검증 — "왜 샀는지" 완전 설명 가능
- 거래 빈도 반년당 4~6회 — 스윙 스타일, 심리·관찰 부담 최소
- 트레일링 스탑 병렬 운용으로 큰 추세 수익 자동 극대화

> **과거 권장**(volatility_breakout 1d Upbit/KRW) 은 백테스트 6구간 평균 -0.25% 로 **재검증 결과 기각**.

---

## 6. 사용자 점진 운용 로드맵 (2주 빠른 트랙 — 기본)

자본 500만원 + Max 구독 + 학습 우선 성향에 맞춘 압축 로드맵.

| Day | 단계 | 자본 | 핵심 |
|---|---|---|---|
| D1 | 백테스트·전략 선정 | 0원 | 5개 전략 × 2년 BTC/USDT 1h, HTML 리포트 비교 → 전략 1~2개 확정 |
| D2~D4 | Binance Testnet 페이퍼 | 가상 | tmux 24시간, 텔레그램 알림 ON. **최소 72바 이상 관찰** (1h 기준 3일) |
| D5~D11 | Upbit 실전 소액 | 25만원 (자본의 5%) | `max_position_pct: 0.10`, `stop_loss_pct: 0.03`, `max_daily_loss_pct: 0.03` |
| D12~D14 | 검증 및 증액 판단 | 유지 또는 50만원 | 승률·MDD·수수료 포함 실수익률 확인. 문제 없으면 10% 증액, 이상 시 원인 분석 |

### 타임프레임 가이드
- 2주 내 관찰 데이터 확보를 위해 **1h 타임프레임 전략 (ma_crossover / rsi_reversal / bollinger_breakout)** 우선
- 변동성 돌파(1d) 는 백테스트 비중을 더 크게 가져가고 실전 관찰 기간 짧게 잡을 것

### 절대 원칙
- **단계별 최소 관찰 시간 단축 금지**: Testnet 72바 / 실전 1주는 버그 검출 최저선
- **이상 동작 1회라도 발견 시 즉시 중단** → 원인 분석 → 테스트 추가 → 재개
- **증액은 검증 후에만**: 일정 맞추려고 억지로 증액 금지
- 손절·서킷브레이커 임계값 **임의 완화 금지**

### 트랙 선택 옵션
- **2주 빠른 트랙 (기본)** — 위 표
- **1주 초고속 트랙** — 백테스트 1일 + Testnet 2일 + 실전 4일. 학습비 10만원 각오. 버그 검출 가능성 낮음
- **4주 보수 트랙** — 각 단계 2배. 급하지 않을 때 + 초보자 극도 주의형에 적합

---

## 7. 새 Claude Code 세션이 지켜야 할 행동 수칙

- **한국어로 대화**. 코드 주석·문서도 한국어 우선 (영문 docstring 혼용 OK).
- **규칙 기반 우선 원칙**: LLM 에이전트/AI 매매 의사결정 제안 전에 반드시 사용자에게 확인받기.
- **점진·방어적 접근**: 실전 키·실전 모드 관련 작업은 사용자 명시 요청 시에만 진행.
- **자본·리스크 파라미터 보수적**: 기본값 바꿀 때 사용자 확인. 특히 `max_position_pct`, `stop_loss_pct`, `max_daily_loss_pct`.
- **테스트 우선**: 새 코드는 반드시 pytest 테스트 동반. 78개+ 기존 테스트 깨뜨리지 않기.
- **린트 통과**: `ruff check src/ tests/` 가 초록 상태 유지.
- **커밋 메시지 한국어 본문** + Phase 번호 접두. 빌드/세션 URL 포함 (기존 커밋 참고).
- **브랜치**: `claude/crypto-trading-bot-LVOJf` 기본. main 머지 전에 사용자 확인.
- **AI API 사용 제안 금지 (기본값)**: Anthropic/OpenAI/Tavily 등 외부 AI API 통합은 비용·재현성 이유로 **사용자가 명시 요청할 때만**.
- **파일 내용물 삭제 신중**: 버그 fix 를 위해 로직 삭제 전에 의도를 사용자에게 확인.
- **실전 거래소 키가 .env 에 있을 수 있음** — git 에 절대 커밋하지 말 것. .gitignore 확인.

---

## 8. 알려진 제한·TODO

- **LiveBroker 부분 체결 미구현**: 현재는 전량 체결 가정 (페이퍼는 Phase 3 에서 지정가/부분 체결 지원)
- **멀티 자산 라이브/페이퍼 모드 미구현**: 현재는 백테스트 전용 (MultiAssetBacktester)
- **Upbit 소수점 정밀도 규칙 미적용**: KRW 마켓 호가 단위 (0.5, 1, 10 등) 수동 처리 필요
- **봇 재시작 시 포지션 동기화 없음**: 실전 모드에서 중단 후 재개하면 로컬 Portfolio 와 실제 거래소 잔고가 어긋날 수 있음. `fetch_balance` 로 초기화하는 로직 추가 필요 시점 올 것
- **HTML 리포트는 단일 자산 백테스트 전용**: 멀티 자산은 summary 텍스트만
- **세금·세무**: 자동 리포팅 미지원

---

## 9. 안전·보안 수칙

- **`.env` 는 절대 git 커밋 금지** (`.gitignore` 포함되어 있음)
- **거래소 API 키 권한**: 현물 거래만 허용, **출금 권한 반드시 비활성화**, 가능하면 IP 화이트리스트
- **실전 키 대화창 입력 금지** (테스트넷은 OK, 메인넷 키는 사용자가 직접 `.env` 편집)
- **이중 게이트 우회 금지**: `--skip-countdown` 은 자동화 테스트 용, 실전에서는 카운트다운 유지
- **일일 손실 서킷브레이커 임의로 해제 금지**
- **커밋 전 `ruff` + `pytest`** 통과 확인
- **Claude Code Remote Control 사용 시**: Pro/Max 세션 유지 필요, tmux 로 무중단

---

## 10. 실행 방법 빠른 참조

```bash
# 최초 셋업
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# 테스트
pytest

# 백테스트 (API 키 불필요)
python -m tradingbot backtest --start 2024-01-01 --end 2024-07-01

# 백테스트 + HTML 리포트
python -m tradingbot backtest --start 2024-01-01 --end 2024-07-01 \
    --save-report logs/report.html

# 멀티 자산 백테스트
python -m tradingbot backtest --config config/portfolio_example.yaml \
    --start 2024-01-01 --end 2024-07-01

# 페이퍼 트레이딩 (실시간 시세)
python -m tradingbot paper --max-bars 10

# Dry-run (판단만, 주문 제출 없음)
python -m tradingbot paper --dry-run

# Binance Testnet 실전 (이중 게이트 필요)
python -m tradingbot live --i-understand-real-money --max-bars 5

# 웹 대시보드
python -m tradingbot dashboard

# tmux 로 24시간 무중단
tmux new -s bot
python -m tradingbot paper
# Ctrl+B → D (분리)
tmux attach -t bot                   # 다시 붙기
```

---

## 11. 자주 사용하는 설정 파일 경로

- `config/settings.yaml` — 기본 단일 자산 설정
- `config/portfolio_example.yaml` — 멀티 자산 예시 (BTC/ETH/SOL)
- `config/strategies/ma_crossover.yaml`, `config/strategies/rsi_reversal.yaml` — 전략별 파라미터 참고
- `.env.example` — 환경변수 템플릿 (`EXCHANGE_API_KEY`, `TELEGRAM_BOT_TOKEN` 등)
- `pyproject.toml` — ruff / pytest 설정
- `requirements.txt`, `requirements-dev.txt` — 의존성

---

## 12. 개발·디버깅 팁

- 문제 재현 어려울 때: `logs/orders.jsonl` 에 모든 이벤트 (signal / order_submitted / order_filled / order_rejected / stop_loss / circuit_breaker / daily_report) JSON 한 줄씩 기록되어 있음
- 실시간 모니터링: `python -m tradingbot dashboard` 로 Streamlit UI
- 백테스트 한 번에 여러 파라미터 비교: `--config` 로 별도 YAML 만들어 반복 실행
- 전략 추가: `src/tradingbot/strategies/새전략.py` 에 `@register` 붙인 클래스 한 개, `cli.py::_register_strategies` 에 import 한 줄

---

**이 문서는 대화 히스토리의 압축 버전입니다. 세부 맥락이 더 필요하면 각 Phase 커밋 메시지(한국어 본문)를 참고하세요.**
