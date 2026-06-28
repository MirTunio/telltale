@echo off
REM Telltale - sailing race scoring (web UI)
REM Double-click to start the local web interface; it opens in your browser.
REM The command-line app is unaffected - use run.bat any time.

cd /d "%~dp0"
title Telltale - Web UI

where py >nul 2>nul
if %errorlevel%==0 (
    py telltale_webui\serve.py
    goto done
)

where python >nul 2>nul
if %errorlevel%==0 (
    python telltale_webui\serve.py
    goto done
)

echo.
echo Python 3 was not found. Install it from https://www.python.org/downloads/
echo then double-click run_web.bat again.
echo.
pause
:done
