@echo off
REM Telltale - sailing race scoring
REM Double-click to start. It opens MAXIMISED in its own window and that window
REM closes completely when you exit Telltale.

REM --- relaunch ourselves in a maximised console that CLOSES on exit (/c) ---
if not "%~1"=="__win" (
    start "Telltale - Race Scoring" /max cmd /c ""%~f0" __win"
    exit /b
)

cd /d "%~dp0"
title Telltale - Race Scoring

where py >nul 2>nul
if %errorlevel%==0 (
    py telltale.py
    goto end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python telltale.py
    goto end
)

echo.
echo Python was not found on this computer.
echo Please install Python 3 from https://www.python.org/downloads/
echo (tick "Add Python to PATH" during install), then run this file again.
echo.
pause

:end
REM Reached after a clean exit. Under "cmd /c" the window now closes by itself.
