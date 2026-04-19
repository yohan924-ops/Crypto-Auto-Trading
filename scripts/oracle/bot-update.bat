@echo off
REM Oracle VM 에서 최신 코드 pull + 의존성 설치 + 봇 재시작.
REM GitHub 에 새 커밋 push 한 뒤 서버 반영할 때 사용.

set SSH_KEY=C:\Users\KKH\Downloads\ssh-key-2026-04-18.key
set SSH_HOST=ubuntu@134.185.97.110

echo === 최신 코드 pull ===
ssh -i "%SSH_KEY%" %SSH_HOST% "cd ~/Crypto-Auto-Trading && git pull"

echo.
echo === 의존성 업데이트 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "cd ~/Crypto-Auto-Trading && source .venv/bin/activate && pip install -e . --quiet"

echo.
echo === 봇 재시작 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "sudo systemctl restart crypto-bot && sleep 3 && sudo systemctl status crypto-bot --no-pager | head -10"

echo.
echo === 최근 로그 15줄 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -15 ~/Crypto-Auto-Trading/logs/service.log"

pause
