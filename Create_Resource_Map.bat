@echo off
setlocal
cd /d "%~dp0"
title Resource Allocation Map

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON=py"
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set "PYTHON=python"
    ) else (
        echo ERROR: Python was not found on this computer.
        echo.
        pause
        exit /b 1
    )
)

%PYTHON% Create_Resource_Map.py
set "RESULT=%errorlevel%"

if not "%RESULT%"=="0" (
    echo.
    echo The map process ended with an error. See the message above.
    pause
    exit /b %RESULT%
)

exit /b 0
