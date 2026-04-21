@echo off
REM Oracle Cloud VM crypto-bot 통합 관리 스크립트.
REM 메뉴에서 번호 선택 → SSH 로 해당 작업 실행 → 메뉴로 복귀.

setlocal EnableDelayedExpansion
REM %~dp0 = 이 배치 파일이 있는 폴더. 키를 이 폴더로 옮기면 경로 하드코딩 불필요.
set SSH_KEY=%~dp0ssh-key-2026-04-18.key
set SSH_HOST=ubuntu@134.185.97.110
set PROJECT_DIR=~/Crypto-Auto-Trading

:menu
cls
echo =================================================
echo   Oracle VM crypto-bot Manager
echo   Host: %SSH_HOST%
echo =================================================
echo.
echo   1. 봇 상태 확인 (systemctl status + 최근 로그)
echo   2. 로그 보기 (service.log 50줄 + 주문 이벤트)
echo   3. 봇 재시작 (코드 pull 없이)
echo   4. 코드 업데이트 (git pull + pip + restart)
echo   5. SSH 대화형 접속
echo   6. 봇 정지 (완전 끄기)
echo   7. 봇 시작 (정지 상태에서 켜기)
echo.
echo   Q. 종료
echo.
echo =================================================
set /p choice=선택 (1-7, Q):

if "%choice%"=="1" goto status
if "%choice%"=="2" goto logs
if "%choice%"=="3" goto restart
if "%choice%"=="4" goto update
if "%choice%"=="5" goto ssh
if "%choice%"=="6" goto stop
if "%choice%"=="7" goto start
if /i "%choice%"=="q" goto end
echo [!] 잘못된 선택.
timeout /t 2 >nul
goto menu

:status
echo.
echo === [1] 봇 상태 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl status crypto-bot --no-pager | head -20"
echo.
echo === 최근 로그 10줄 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -10 %PROJECT_DIR%/logs/service.log"
echo.
pause
goto menu

:logs
echo.
echo === [2] service.log 최근 50줄 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -50 %PROJECT_DIR%/logs/service.log"
echo.
echo === 최근 주문 이벤트 10개 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "ls -1t %PROJECT_DIR%/logs/orders*.jsonl 2>/dev/null | head -1 | xargs -I {} tail -10 {}"
echo.
pause
goto menu

:restart
echo.
echo === [3] 봇 재시작 중... ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl restart crypto-bot && sleep 3 && sudo systemctl status crypto-bot --no-pager | head -10"
echo.
echo === 재시작 후 로그 15줄 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -15 %PROJECT_DIR%/logs/service.log"
echo.
pause
goto menu

:update
echo.
echo === [4] 코드 업데이트 + 재시작 ===
echo.
echo [1/3] git pull...
ssh -i "%SSH_KEY%" %SSH_HOST% "cd %PROJECT_DIR% && git pull"
echo.
echo [2/3] pip install...
ssh -i "%SSH_KEY%" %SSH_HOST% "cd %PROJECT_DIR% && source .venv/bin/activate && pip install -e . --quiet"
echo.
echo [3/3] 봇 재시작...
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl restart crypto-bot && sleep 3 && sudo systemctl status crypto-bot --no-pager | head -10"
echo.
echo === 최근 로그 15줄 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -15 %PROJECT_DIR%/logs/service.log"
echo.
pause
goto menu

:ssh
echo.
echo === [5] SSH 대화형 접속. exit 로 종료. ===
echo.
ssh -i "%SSH_KEY%" %SSH_HOST%
goto menu

:stop
echo.
echo === [6] 봇 정지 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl stop crypto-bot && sudo systemctl status crypto-bot --no-pager | head -5"
echo.
pause
goto menu

:start
echo.
echo === [7] 봇 시작 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl start crypto-bot && sleep 3 && sudo systemctl status crypto-bot --no-pager | head -10"
echo.
echo === 초기 로그 15줄 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -15 %PROJECT_DIR%/logs/service.log"
echo.
pause
goto menu

:end
echo.
echo 종료합니다.
endlocal
exit /b 0
