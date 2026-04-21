@echo off
REM Oracle Cloud VM crypto-bot management menu.
REM Select a number to run the corresponding SSH command, then return to menu.

setlocal EnableDelayedExpansion
REM %~dp0 = folder where this batch file lives. Key placed in this folder is found automatically.
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
echo   1. Status check (systemctl status + latest log)
echo   2. View logs (service.log 50 lines + orders)
echo   3. Restart bot (no code pull)
echo   4. Update code (git pull + pip + restart)
echo   5. Interactive SSH
echo   6. Stop bot
echo   7. Start bot
echo.
echo   Q. Quit
echo.
echo =================================================
set /p choice=Select (1-7, Q):

if "%choice%"=="1" goto status
if "%choice%"=="2" goto logs
if "%choice%"=="3" goto restart
if "%choice%"=="4" goto update
if "%choice%"=="5" goto ssh
if "%choice%"=="6" goto stop
if "%choice%"=="7" goto start
if /i "%choice%"=="q" goto end
echo Invalid choice.
timeout /t 2 >nul
goto menu

:status
echo.
echo === [1] Bot status ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl status crypto-bot --no-pager | head -20"
echo.
echo === Latest log 10 lines ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -10 %PROJECT_DIR%/logs/service.log"
echo.
pause
goto menu

:logs
echo.
echo === [2] service.log last 50 lines ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -50 %PROJECT_DIR%/logs/service.log"
echo.
echo === Recent order events ===
ssh -i "%SSH_KEY%" %SSH_HOST% "ls -1t %PROJECT_DIR%/logs/orders*.jsonl 2>/dev/null | head -1 | xargs -I {} tail -10 {}"
echo.
pause
goto menu

:restart
echo.
echo === [3] Restarting bot... ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl restart crypto-bot && sleep 3 && sudo systemctl status crypto-bot --no-pager | head -10"
echo.
echo === Post-restart log 15 lines ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -15 %PROJECT_DIR%/logs/service.log"
echo.
pause
goto menu

:update
echo.
echo === [4] Update code + restart ===
echo.
echo [1/3] git pull...
ssh -i "%SSH_KEY%" %SSH_HOST% "cd %PROJECT_DIR% && git pull"
echo.
echo [2/3] pip install...
ssh -i "%SSH_KEY%" %SSH_HOST% "cd %PROJECT_DIR% && source .venv/bin/activate && pip install -e . --quiet"
echo.
echo [3/3] Restart bot...
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl restart crypto-bot && sleep 3 && sudo systemctl status crypto-bot --no-pager | head -10"
echo.
echo === Latest log 15 lines ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -15 %PROJECT_DIR%/logs/service.log"
echo.
pause
goto menu

:ssh
echo.
echo === [5] Interactive SSH. Type 'exit' to return to menu. ===
echo.
ssh -i "%SSH_KEY%" %SSH_HOST%
goto menu

:stop
echo.
echo === [6] Stop bot ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl stop crypto-bot && sudo systemctl status crypto-bot --no-pager | head -5"
echo.
pause
goto menu

:start
echo.
echo === [7] Start bot ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl start crypto-bot && sleep 3 && sudo systemctl status crypto-bot --no-pager | head -10"
echo.
echo === Initial log 15 lines ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -15 %PROJECT_DIR%/logs/service.log"
echo.
pause
goto menu

:end
echo.
echo Bye.
endlocal
exit /b 0
