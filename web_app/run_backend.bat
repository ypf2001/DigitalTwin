@echo off
chcp 65001 >nul
cd /d "%~dp0backend"

set "PYTHON="
if exist "C:\Users\Administrator\.conda\envs\digital-twin\python.exe" set "PYTHON=C:\Users\Administrator\.conda\envs\digital-twin\python.exe"
if exist "C:\Users\Administrator\miniconda3\envs\digital-twin\python.exe" set "PYTHON=C:\Users\Administrator\miniconda3\envs\digital-twin\python.exe"
if exist "C:\Users\Administrator\anaconda3\envs\digital-twin\python.exe" set "PYTHON=C:\Users\Administrator\anaconda3\envs\digital-twin\python.exe"
if "%PYTHON%"=="" set "PYTHON=python"

echo ========================================
echo   后端 API 服务
echo   http://localhost:5000
echo   关闭此窗口即停止服务
echo ========================================
echo.
"%PYTHON%" app.py
pause
