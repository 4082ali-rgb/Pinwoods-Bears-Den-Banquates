@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py setup.py
    goto :done
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python setup.py
    goto :done
)
echo Python was not found on this computer.
echo.
echo Install it from https://www.python.org/downloads/ - on the first setup
echo screen, tick the box that says "Add python.exe to PATH" before clicking
echo Install. Then double-click SETUP.bat again.
:done
echo.
pause
