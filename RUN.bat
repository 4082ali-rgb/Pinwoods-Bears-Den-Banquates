@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py run_batch.py
) else (
    python run_batch.py
)
echo.
pause
