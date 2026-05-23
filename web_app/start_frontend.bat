@echo off
chcp 65001 >nul
title 数字孪生 Web — 前端

cd /d "%~dp0frontend"

echo 启动前端 (端口 3000)...
call npm run dev
pause
