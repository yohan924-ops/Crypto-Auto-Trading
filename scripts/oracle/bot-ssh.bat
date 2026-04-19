@echo off
REM Oracle VM 대화형 SSH 접속.
REM 터미널이 Oracle VM 셸로 바뀌어 자유롭게 명령어 입력 가능.
REM 종료: exit 입력 또는 Ctrl+D.

set SSH_KEY=C:\Users\KKH\Downloads\ssh-key-2026-04-18.key
set SSH_HOST=ubuntu@134.185.97.110

ssh -i "%SSH_KEY%" %SSH_HOST%
