@echo off
REM Oracle VM 의 봇 로그 최근 50줄 확인.
REM 매매 신호, 워밍업 진행, 에러 등 상세 내용 표시.

set SSH_KEY=C:\Users\KKH\Downloads\ssh-key-2026-04-18.key
set SSH_HOST=ubuntu@134.185.97.110

echo === 최근 service 로그 50줄 ===
ssh -i "%SSH_KEY%" %SSH_HOST% "tail -50 ~/Crypto-Auto-Trading/logs/service.log"

echo.
echo === 최근 주문 이벤트 10개 (orders.jsonl) ===
ssh -i "%SSH_KEY%" %SSH_HOST% "ls -1t ~/Crypto-Auto-Trading/logs/orders*.jsonl 2>/dev/null | head -1 | xargs -I {} tail -10 {}"

pause
