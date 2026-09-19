@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py set_journal_number.py
) else (
    python set_journal_number.py
)
echo.
pause
