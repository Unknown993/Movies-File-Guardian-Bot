@echo off
title Push TeleBot to GitHub
cd /d "%~dp0"
echo ===================================================
echo           Pushing TeleBot to GitHub
echo ===================================================

where git >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    git push -u origin main
) else if exist "E:\GIT\Git\cmd\git.exe" (
    "E:\GIT\Git\cmd\git.exe" push -u origin main
) else (
    echo Error: git was not found in PATH or at E:\GIT\Git\cmd\git.exe
)

echo.
pause
