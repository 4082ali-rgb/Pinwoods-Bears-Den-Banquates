@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py reset_journal_number.py
    goto :done
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python reset_journal_number.py
    goto :done
)
echo Python was not found on this computer.
echo.
echo Double-click SETUP.bat first - it will tell you what to install.
:done
echo.
pause
