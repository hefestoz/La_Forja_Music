@echo off
title La Forja Music
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py %*
) else (
    python main.py %*
)
if %errorlevel% neq 0 (
    echo.
    echo Bot stopped with an error code: %errorlevel%
    pause
)
