@echo off
title Push TeleBot to GitHub
cd /d E:\tele_bot
echo ===================================================
echo           Pushing TeleBot to GitHub
echo ===================================================
"E:\GIT\Git\cmd\git.exe" push -u origin main
echo.
pause
