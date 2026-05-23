@echo off
chcp 65001 >nul
title 数字孪生 Web — 后端

:: 查找 Python
set PYTHON=
if exist "C:\Users\Administrator\.conda\envs\digital-twin\python.exe" set PYTHON=C:\Users\Administrator\.conda\envs\digital-twin\python.exe
if exist "C:\Users\Administrator\miniconda3\envs\digital-twin\python.exe" set PYTHON=C:\Users\Administrator\miniconda3\envs\digital-twin\python.exe
if exist "C:\Users\Administrator\anaconda3\envs\digital-twin\python.exe" set PYTHON=C:\Users\Administrator\anaconda3\envs\digital-twin\python.exe
if "%PYTHON%"=="" set PYTHON=python

echo 启动后端 (端口 5000)...
"%PYTHON%" backend\app.py
pause
