@echo off
REM Oracle VM 의 봇 재시작 (코드 pull 없이).
REM 단순히 프로세스만 재기동. 설정 파일 바뀌었을 때 유용.

set SSH_KEY=C:\Users\KKH\Downloads\ssh-key-2026-04-18.key
set SSH_HOST=ubuntu@134.185.97.110

echo === 봇 재시작 중... ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl restart crypto-bot && sleep 3 && echo '' && sudo systemctl status crypto-bot --no-pager | head -10"

echo.
echo === 최근 로그 15줄 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -15 ~/Crypto-Auto-Trading/logs/service.log"

pause
