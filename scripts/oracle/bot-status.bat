@echo off
REM Oracle Cloud VM 의 crypto-bot 서비스 상태 확인.
REM 봇이 돌고 있는지, 언제부터 돌았는지, PID 메모리 사용량 등 요약.

set SSH_KEY=C:\Users\KKH\Downloads\ssh-key-2026-04-18.key
set SSH_HOST=ubuntu@134.185.97.110

echo === crypto-bot.service 상태 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl status crypto-bot --no-pager | head -20"

echo.
echo === 최근 로그 10줄 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -10 ~/Crypto-Auto-Trading/logs/service.log"

pause
