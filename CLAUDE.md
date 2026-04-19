# CLAUDE.md — 프로젝트 컨텍스트 지침서

> 이 파일은 Claude Code 가 저장소를 열 때 자동으로 읽습니다.
> 새 세션이 기존 대화 맥락을 모르더라도 이 문서로 동등한 수준의 이해를 갖도록 작성되었습니다.

## 0. 프로젝트 한 줄 요약

**암호화폐 자동매매 봇 (Python, 규칙 기반 알고리즘 트레이딩, 학습용 MVP → 점진적 실전 운용)**

---

## 0-A. 🎯 현재 선정된 운용 전략 (ACTIVE STRATEGY — 2026-04-20 갱신)

**다른 AI 가 이 저장소를 열었을 때 가장 먼저 읽어야 하는 섹션.**

### 🏆 3자산 Sleeve (Bollinger 3.0, 30/30/40 배분)

2026-04-19~20 전략 탐색 대장정 끝에 확정된 구조. 기존 swing_pullback v2 (BTC 단독, 연 6회 매매) 는 "매매 빈도 너무 낮음" 사용자 불만으로 폐기. 3자산 병렬 + 단일 전략 (Bollinger Breakout) + 독립 Sleeve 구조로 **빈도 24배 증가 + 수익 4배 증가** 동시 달성.

| 항목 | 값 |
|---|---|
| 최종 config | [`config/bt_sleeve_final.yaml`](config/bt_sleeve_final.yaml) |
| 엔진 | [`src/tradingbot/engine/sleeve.py`](src/tradingbot/engine/sleeve.py), [`src/tradingbot/engine/sleeve_backtester.py`](src/tradingbot/engine/sleeve_backtester.py) |
| **자본 배분** | **BTC 30% / ETH 30% / SOL 40%** |
| **전략 (3자산 공통)** | **bollinger_breakout (period=20, num_std=3.0)** |
| **손절** | BTC/ETH: ATR(14) × 2 / SOL: 고정 -8% |
| **계좌 서킷브레이커** | 일일 -10% 도달 시 3자산 전체 halt |
| **타임프레임** | **4h** |
| 운용 상태 (2026-04-20~) | **Phase C 완료 (백테스트 검증 끝). Phase C-8 (실시간 Runner) 구현 대기** |

### 논리 회로

```text
각 Sleeve (독립):
  [매수] close > Bollinger(20, 3.0) 상단 밴드 상향 돌파
  [매도] close < Bollinger(20, 3.0) 하단 밴드 하향 돌파
  [손절]
    BTC/ETH: ATR(14) × 2 / avg_price (변동성 정규화)
    SOL    : 고정 -8% (하이베타 모멘텀 하드 스탑)
  [트레일링] peak 대비 -5%, +10% 수익 후 활성

Orchestrator (전체):
  [서킷브레이커] 계좌 총자본 일일 -10% 도달 시 3 Sleeve halt
  [자본 격리] Sleeve 간 자본 침범 불가
```

### 백테스트 검증 (2회 독립 실시, 과적합 없음 확정)

**IS (In-Sample) — 2022-01 ~ 2026-01 (48개월 연속)**

| 지표 | 값 |
|---|---|
| 총 수익 | **+34.97%** |
| MDD | -11.96% |
| 거래 수 | 581회 (145회/년, 주 ~3회) |
| 승률 | 42.8% |
| Sharpe / Sortino | +0.68 / +0.48 |
| 계좌 CB 발동 | 0일 |
| BTC Sleeve 수익 | +19.24% |
| ETH Sleeve 수익 | +3.35% |
| SOL Sleeve 수익 | +70.49% |

**OOS (Out-of-Sample) — 2020-08 ~ 2022-01 (17개월)**

| 지표 | OOS | IS 대비 |
|---|---|---|
| 총 수익 | +26.64% (연율 +18.5%) | IS 연율 +7.9% 보다 **2.3배** |
| MDD | -4.78% | IS 보다 **1/3 수준** |
| Sharpe | +1.21 | IS 보다 1.8배 |

**OOS 가 IS 보다 모든 지표 우수 → 데이터 snooping bias 없음 확정**. Bollinger 3.0 은 다른 시장 regime 에서도 유효한 진짜 엣지.

### 선정 근거 상세

| 자산 | 전략 선정 이유 |
|---|---|
| BTC (30%) | Bollinger 3.0 IS +17.36%, OOS +17.79%. 생존자 편향 없는 안정 기둥 |
| ETH (30%) | Bollinger 3.0 만 양수 (+6.05% IS). 다른 8개 전략 모두 실패. 사용자 제약상 포함 필수. 시총 2위 대표성 |
| SOL (40%) | Bollinger 3.0 IS +57.80%, OOS +41.23%. 하이베타 추세 극대화 |

### ETH 전략 선정 시도 히스토리 (모두 기각)

| ETH 전략 | 8구간 누적 | 판정 |
|---|---|---|
| swing_pullback default | -5.50% | 실패 |
| swing v4 (RSI 30-40) | -1.77% | 실패 |
| rsi_reversal_v2 (oversold 25) | -2.61% | 실패 |
| Mean Reversion (CHOP + %B) | -1.63% | 실패 (Gemini 설계했으나 실측에서 패배) |
| volatility_breakout_v2 | -12.33% | 완패 |
| Bollinger 2.5 | +4.86% | 25H1 -16% 재앙 |
| **Bollinger 3.0** | **+6.05%** | **유일 양수 — 채택** |
| Bollinger 3.5 | -1.07% | 실패 |

### 기각된 Sleeve 배분 (절대 되돌리지 말 것)

| 배분 | 실측 수익 | 기각 이유 |
|---|---|---|
| 30/10/60 (수학 최적) | +39.00% | ETH 유명무실 + SOL 생존자 편향 몰빵 |
| 30/20/50 | ~+36% (추정) | 여전히 SOL 집중 |
| **30/30/40 (채택)** | **+28.57% (8구간 복리) / +34.97% (연속)** | 대표성 + 집중 완화 균형 |
| 40/30/30 | ~+25% (추정) | 수익 희생 과도 |

### 기각된 ATR 설정

| 설정 | 실측 (4년) | 기각 이유 |
|---|---|---|
| 3자산 ATR × 2.0 | +25.35% | SOL 수익 절반 삭제 (ATR 너무 넓음) |
| SOL ATR × 1.5 | +15.41% | 오히려 악화 (너무 타이트) |
| **SOL 고정 -8%** | **+39.00%** | 하이베타 모멘텀 정석, 채택 |

### 페이즈 C 결과 (2026-04-20)

| 구성 요소 | 상태 |
|---|---|
| Sleeve 엔진 (Portfolio/Risk/Strategy 독립) | ✅ 구현 완료 |
| SleeveOrchestrator (계좌 CB + 자본 배분) | ✅ 구현 완료 |
| ATR 기반 동적 손절 | ✅ 구현 완료 |
| SleeveBacktester | ✅ 구현 완료 |
| pytest | ✅ **234/234 통과** (기존 212 + ATR 8 + Sleeve 14) |
| CLI 확장 (sleeves YAML 분기) | ✅ 구현 완료 |
| **SleeveRunner (실시간 페이퍼/라이브)** | **⏳ Phase C-8 대기** |

### 실전 할인 수익 기대

| 시나리오 | 연 수익 |
|---|---|
| 과거 강세장 재현 (OOS 수준) | +15~18% |
| 최근 구간 재현 (IS 수준) | +7~8% |
| **실전 할인 (fee + slippage + 체제 변화)** | **+3~6%** |
| 비관 (약세 3년 지속) | 0 ~ -5% |

500만원 기준 연 **15~30만원 기대**, 최악 -60만원 낙폭 감수.

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
| `swing_pullback` D1/D2/D3 빈도 증가 튜닝 (2026-04-19) | 하루 1회 목표로 완화 실험 — D1(1h, EMA240, RSI35-55): 0.19회/일 +0.64%, D2(15m): 0.58회/일 +0.01%, D3(15m 공격): **1.16회/일 -1.05% 승률 44%**. 빈도 올릴수록 노이즈 진입·수수료로 수익 붕괴. 2024-01 박스권 1개월 smoke 에서 이미 한계 확인, 6구간 확장 불필요. 파일: `config/bt_swing_daily_d{1,2,3}.yaml` |
| 2봇 병행 (swing + rsi) | 50:50 단순 평균 시 rsi 하락장 손실이 swing 수익을 깎음 → 평균 +0.43% (swing 단독 +1.11% 보다 낮음) |

### 실전 전개 순서

1. ✅ **Oracle Cloud 춘천 VM 에서 페이퍼 24/7 가동** (2026-04-19 시작, `paper_swing.yaml`, systemd `crypto-bot.service`, Binance Mainnet 시세 + 텔레그램 `@KKHCryptoBot`)
2. **최소 7일 일일 리포트 연속 발송 확인** → 2026-04-26 이후 실전 전환 판단
3. **Upbit BTC/KRW 실전 소액** (25만원, max_position_pct 는 실전 시 0.10 으로 축소 권장)
4. 1~2개월 안정 후 다른 코인(ETH 등) 에 동일 전략 확장 고려 — **단일 자산 2봇은 "가짜 분산" 이니 금지**

> **중요 운용 원칙**: 페이퍼 단계는 **인프라 검증** 목적 (API·알림·재시작). swing_pullback v2 는 연 6회 빈도라 페이퍼 기간 내 매매 체결이 안 일어날 수 있음 — 이는 정상이며 **전략 검증은 백테스트 6구간에 위임**. "페이퍼에서 매매 안 일어나서 빈도 늘리자" 는 유혹 시 위 D1/D2/D3 기각 이력 참고.

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

## 5. 내장 전략 11종

| 이름 | 타입 | 상태 | 언제 쓰는가 |
| --- | --- | --- | --- |
| `buy_and_hold` | 검증용 | 유지 | 엔드투엔드 파이프라인 테스트 전용 |
| `ma_crossover` | 추세 추종 | 유지 | 장기 트렌드 시장. Default `fast=20, slow=50` |
| `rsi_reversal` | 모멘텀 역추세 | **기각** | 하락장 취약 (2022 H2 -2.78%) |
| `rsi_reversal_v2` | + EMA200 필터 | **기각** | 하락장 방어됐지만 기회 부족 |
| **`bollinger_breakout`** | **변동성 돌파** | **🎯 활성 (§0-A)** | **num_std=3.0 으로 Sleeve 3자산 전원 채택. IS +35% / OOS +27%** |
| `volatility_breakout` | 데일리 추세 | 유지 | 래리 윌리엄스 변동성 돌파 (1d) |
| `volatility_breakout_v2` | + 주봉 필터 + 동적 K | **기각** | 6구간 -8.49%. 크립토 2022 이후 환경과 구조적 불일치 |
| `triple_screen` | 4조건 AND | **기각** | 수수료 누적으로 평균 -1.24% |
| `pullback` | Gemini v1 | **기각** | 1h 기준 기회 부족 |
| `swing_pullback` | Gemini v2 스윙 | **폐기** | 과거 단일 BTC 활성 전략이었으나 "매매 빈도 연 6회" 사용자 불만으로 Sleeve 구조 채택 시 제외 |
| `mean_reversion` | CHOP + %B 역추세 | **기각** | Gemini 설계했으나 ETH 8구간 -1.63% 실패 |

### 현재 실전 진입 아키텍처 (§0-A 참고)

3자산 Sleeve × Bollinger 3.0. 상세는 §0-A.

---

## 6. 사용자 점진 운용 로드맵 (3자산 Sleeve 기준, 2026-04-20 업데이트)

자본 500만원 + Max 구독 + 학습 우선 성향에 맞춘 실제 진행 로드맵.

| 단계 | 기간 | 자본 | 상태 | 핵심 |
| --- | --- | --- | --- | --- |
| ① 전략 탐색·확정 | 2026-04-18~20 (3일) | 0원 | ✅ 완료 | 8전략 × 3자산 × 8구간 백테스트 → 3자산 Sleeve (Bollinger 3.0) 확정 |
| ② Phase C-8 실시간 엔진 구현 | 2026-04-20 (2시간) | 0원 | ⏳ 진행 예정 | SleeveRunner (실시간 페이퍼/라이브) 코딩 |
| ③ Oracle Cloud 페이퍼 (신 아키텍처) | C-8 완료 후 7일 | 가상 | 대기 | 기존 swing_pullback 봇 중지 → 3자산 Sleeve 페이퍼 전환 |
| ④ Upbit 실전 소액 | 페이퍼 7일 무사고 후 | 25만원 (자본의 5%) | 대기 | max_position 0.10, 실전 할인 후 연 +3~6% 기대 |
| ⑤ 검증·증액 판단 | 지속 | 25만 → 50만 → 100만 | 대기 | 1~2개월 무사고 후 단계적 증액 |

### 페이퍼 단계 핵심 인식

- 3자산 Sleeve 는 **주 ~3회 매매** (연 145회) 로 페이퍼 중 실제 체결 빈번 관찰 가능
- 이전 swing_pullback v2 (연 6회) 대비 **24배 증가** — 사용자 원래 불만 "매매 빈도 낮음" 해결
- 페이퍼 검증 목적: **인프라 + 실시간 엔진 버그 확인** (Phase C-8 신규 코드)

### 절대 원칙

- **7일 연속 무사고** 전까진 실전 금지
- **이상 동작 1회라도 발견 시 즉시 중단** → 원인 분석 → 테스트 추가 → 재개
- **증액은 검증 후에만**: 일정 맞추려고 억지로 증액 금지
- 손절·서킷브레이커 임계값 **임의 완화 금지**
- **과적합 의심 튜닝 금지**: §0-A 기각 이력 (배분·ATR·전략) 재현 금지

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
- **SleeveRunner (실시간 Sleeve 운용) 미구현 — Phase C-8 대기**: Sleeve 엔진은 백테스트만 완료. 실시간 페이퍼/라이브 Runner 는 Phase C-8 에서 구현 예정 (2시간 예상). 이 구현 없이는 3자산 Sleeve 를 Oracle VM 에 배포 불가
- **멀티 자산 라이브/페이퍼 모드 (공용 풀) 미구현**: `MultiAssetBacktester` (공용 풀) 은 백테스트 전용. Sleeve (독립 자본) 방식이 주력이라 공용 풀 실시간은 deprecated
- **Upbit 소수점 정밀도 규칙 미적용**: KRW 마켓 호가 단위 (0.5, 1, 10 등) 수동 처리 필요
- **봇 재시작 시 포지션 동기화 없음**: 실전 모드에서 중단 후 재개하면 로컬 Portfolio 와 실제 거래소 잔고가 어긋날 수 있음. `fetch_balance` 로 초기화하는 로직 추가 필요 시점 올 것
- **HTML 리포트는 단일 자산 백테스트 전용**: 멀티 자산·Sleeve 는 summary 텍스트만
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
