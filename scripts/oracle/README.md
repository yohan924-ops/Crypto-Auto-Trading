# Oracle VM 관리 도구

Windows PC 에서 Oracle Cloud VM (crypto-bot) 을 메뉴 방식으로 관리.

## 전제

- SSH 키 파일 경로: `C:\Users\KKH\Downloads\ssh-key-2026-04-18.key`
- Oracle VM IP: `134.185.97.110`
- OS: Windows 10/11 (기본 OpenSSH 클라이언트 포함)

키 경로나 IP 바뀌면 `bot-manager.bat` 상단의 `SSH_KEY` / `SSH_HOST` 변수 수정.

## 사용법

1. `bot-manager.bat` **더블클릭**
2. 메뉴에서 번호 선택 (1~7, Q)
3. 작업 완료 후 아무 키나 눌러 메뉴로 복귀

## 메뉴 항목

| # | 항목 | 용도 |
|---|---|---|
| 1 | 봇 상태 확인 | systemctl status + 최근 로그 10줄 |
| 2 | 로그 보기 | service.log 50줄 + 최근 주문 이벤트 |
| 3 | 봇 재시작 | 코드 그대로, 프로세스만 재기동 |
| 4 | 코드 업데이트 | git pull + pip install + 재시작 |
| 5 | SSH 대화형 접속 | 직접 명령어 입력. exit 으로 메뉴 복귀 |
| 6 | 봇 정지 | 완전히 끄기 |
| 7 | 봇 시작 | 정지 상태에서 켜기 |
| Q | 종료 | 프로그램 종료 |

## 전형적 워크플로우

**매일 아침 확인**: 더블클릭 → 1 → 상태 확인

**텔레그램 이상 알림 왔을 때**: 더블클릭 → 2 → 로그 점검

**로컬에서 코드 push 후 서버 반영**: 
1. PC 에서 `git push`
2. `bot-manager.bat` → 4

**설정 파일만 수정하고 재시작**:
1. `bot-manager.bat` → 5 (SSH)
2. `nano config/paper_sleeve.yaml` 수정 후 저장·종료
3. 메뉴로 자동 복귀 → 3 (재시작)

## 주의

- SSH 키 파일은 절대 git 에 커밋 금지 (`.gitignore` 에 Downloads 따로 있지 않음, 키 자체 git 외부)
- `.bat` 파일엔 키 내용이 아닌 **경로만** 들어있어 커밋 안전
- 공개 PC 에서 실행 금지 (Oracle VM 접근 가능)
