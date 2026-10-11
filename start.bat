@echo off
title FileGuardian Telegram Bot
cd /d "%~dp0"
echo ===================================================
echo       Starting FileGuardian Telegram Bot
echo ===================================================

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py
) else (
    python run.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Bot stopped with error code %ERRORLEVEL%.
)
pause
