@echo off
chcp 65001 >nul
title Cortes Automaticos
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
    echo Rode primeiro o 1_INSTALAR.bat
    pause
    exit /b 1
)

".venv\Scripts\python.exe" cortes.py %*
echo.
pause
