@echo off
title Telethon Channel Indexer
cd /d "%~dp0"
echo ===================================================
echo       Running Telethon Channel Indexer
echo ===================================================

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" telethon_indexer.py
) else (
    python telethon_indexer.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Telethon Indexer stopped with code %ERRORLEVEL%.
)
pause
