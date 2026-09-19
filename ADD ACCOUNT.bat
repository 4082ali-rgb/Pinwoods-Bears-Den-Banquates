@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py add_account.py
) else (
    python add_account.py
)
echo.
pause
