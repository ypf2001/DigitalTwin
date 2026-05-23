@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 找 Python
set "PYTHON="
if exist "C:\Users\Administrator\.conda\envs\digital-twin\python.exe" set "PYTHON=C:\Users\Administrator\.conda\envs\digital-twin\python.exe"
if exist "C:\Users\Administrator\miniconda3\envs\digital-twin\python.exe" set "PYTHON=C:\Users\Administrator\miniconda3\envs\digital-twin\python.exe"
if exist "C:\Users\Administrator\anaconda3\envs\digital-twin\python.exe" set "PYTHON=C:\Users\Administrator\anaconda3\envs\digital-twin\python.exe"
if "%PYTHON%"=="" set "PYTHON=python"

"%PYTHON%" start.py
pause
