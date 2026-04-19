# Oracle VM 관리 배치 파일

Windows PC 에서 Oracle Cloud VM (crypto-bot) 을 SSH 없이 더블클릭으로 관리.

## 전제

- SSH 키 파일 경로: `C:\Users\KKH\Downloads\ssh-key-2026-04-18.key`
- Oracle VM IP: `134.185.97.110`
- OS: Windows 10/11 (기본 OpenSSH 클라이언트 포함)

키 경로나 IP 가 바뀌면 각 `.bat` 파일 상단의 `SSH_KEY` / `SSH_HOST` 변수만 수정.

## 파일 목록

| 파일 | 용도 | 실행 시점 |
|---|---|---|
| `bot-status.bat` | 봇 동작 여부 + 최근 로그 10줄 | 가장 자주 — 봇 살아있나 확인 |
| `bot-logs.bat` | 로그 50줄 + 최근 주문 이벤트 | 매매 있었는지 상세 확인 |
| `bot-restart.bat` | 봇 재시작 (코드 pull 없이) | 설정 파일만 바뀌었을 때 |
| `bot-update.bat` | git pull + pip install + 재시작 | GitHub 에 새 커밋 push 후 |
| `bot-ssh.bat` | 대화형 SSH 접속 | 직접 명령어 칠 때 |

## 사용법

1. 이 폴더 (`scripts/oracle/`) 를 탐색기로 연다
2. 원하는 `.bat` 파일 **더블클릭**
3. 결과 확인 후 아무 키나 눌러 창 닫기

## 전형적 워크플로우

**매일 아침 (봇 살아있나 확인)**:
- `bot-status.bat` 더블클릭 → "Active: active (running)" 확인

**텔레그램 이상한 메시지 왔을 때**:
- `bot-logs.bat` 더블클릭 → 로그 확인

**코드 업데이트 (GitHub push 후 서버 반영)**:
- 로컬 PC 에서 `git push`
- `bot-update.bat` 더블클릭 → Oracle VM 자동 업데이트

**설정 수정 후 재가동**:
- `bot-ssh.bat` 로 접속 → `nano config/paper_sleeve.yaml` 수정 → exit
- `bot-restart.bat` 더블클릭

## 주의

- SSH 키 파일은 절대 git 에 커밋 금지 (`.gitignore` 에 이미 제외됨)
- `.bat` 파일 자체엔 키 내용이 아닌 **경로만** 들어있어 커밋 안전
- 공개 PC 에서는 사용 금지 (Oracle VM 접근 가능)
