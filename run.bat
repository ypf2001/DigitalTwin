@echo off
chcp 65001 >nul
cd /d "D:\Digital Twin"
echo ============================================
echo  马铃薯施肥灌溉数字孪生系统
echo ============================================
venv\Scripts\python.exe main.py
pause
