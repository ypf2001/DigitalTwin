@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
echo ========================================
echo   前端开发服务器
echo   http://localhost:3000
echo   关闭此窗口即停止服务
echo ========================================
echo.
call "D:\nodejs\npm.cmd" run dev
pause
