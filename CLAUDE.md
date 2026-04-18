# CLAUDE.md — 프로젝트 컨텍스트 지침서

> 이 파일은 Claude Code 가 저장소를 열 때 자동으로 읽습니다.
> 새 세션이 기존 대화 맥락을 모르더라도 이 문서로 동등한 수준의 이해를 갖도록 작성되었습니다.

## 0. 프로젝트 한 줄 요약

**암호화폐 자동매매 봇 (Python, 규칙 기반 알고리즘 트레이딩, 학습용 MVP → 점진적 실전 운용)**

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

---

## 5. 내장 전략 5종

| 이름 | 타입 | 언제 쓰는가 |
|---|---|---|
| `buy_and_hold` | 검증용 | 엔드투엔드 파이프라인 테스트 전용 |
| `ma_crossover` | 추세 추종 | 장기 트렌드 시장. Default `fast=20, slow=50` |
| `rsi_reversal` | 모멘텀 역추세 | 박스권·횡보장. Default `period=14, oversold=30, overbought=70` |
| `bollinger_breakout` | 변동성 추종 | 변동성 확장기. 현재 바 제외한 밴드 기준 상·하단 돌파 |
| `volatility_breakout` | 데일리 추세 | **한국 커뮤니티 검증 다수, 일봉 BTC/KRW 기본 추천** |

### 첫 실전 진입 추천 전략
**`volatility_breakout` (K=0.5) on Upbit `BTC/KRW` `1d`**

이유:
- 한국 퀀트 커뮤니티 10년+ 검증
- 1일 1회 체결 → 버그 노출 기회 최소
- 로직 3줄로 설명 가능 (사용자가 완전히 이해 가능)

---

## 6. 사용자 점진 운용 로드맵 (6주 기준)

| 주차 | 단계 | 자본 | 핵심 |
|---|---|---|---|
| 1주 | 백테스트 체득 | 0원 | 5개 전략 × 2년 BTC/USDT 1h, HTML 리포트 비교 |
| 2주 | Binance Testnet 페이퍼 | 가상 | tmux 24시간, 텔레그램 알림, 1주 관찰 |
| 3~4주 | Upbit 실전 소액 | 25만원 (자본의 5%) | `max_position_pct: 0.10`, `stop_loss_pct: 0.03`, `max_daily_loss_pct: 0.03` |
| 5~6주 | 검증 후 증액 | 50만원 (10%) | 기록/지표 문제없으면 |
| 7주+ | 점진 증액 | ~20% | 각 단계마다 최소 1개월 안정 확인 |

**절대 규칙**: 각 단계 최소 1~2주 관찰. 손실 발생 시 즉시 중단, 원인 분석, 테스트 추가 후 재개.

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
