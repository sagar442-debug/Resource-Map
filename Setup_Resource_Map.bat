@echo off
setlocal
cd /d "%~dp0"
title Resource Map Setup

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

echo Installing/updating the small Python packages used by the map tool...
%PYTHON% -m pip install --user "folium>=0.20,<1.1" "geopy>=2.4,<3" "openpyxl>=3.1,<4"
set "RESULT=%errorlevel%"

if not "%RESULT%"=="0" (
    echo.
    echo Setup failed. Copy the error above if you need help troubleshooting it.
    pause
    exit /b %RESULT%
)

echo.
echo Setup completed successfully.
pause
exit /b 0
