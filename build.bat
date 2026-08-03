@echo off
REM Build script for VSSSIC Ground Station V3 (Windows)

echo ========================================
echo Building VSSSIC Ground Station V3
echo ========================================

REM Check if PyInstaller is installed
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
)

REM Create dist directory
if not exist dist mkdir dist

REM Build the executable
echo Building standalone executable...
pyinstaller build.spec

echo.
echo ========================================
echo Build Complete!
echo ========================================
echo Executable location: .\dist\VSSSIC_Ground_Station.exe
echo.
echo To run the application:
echo   .\dist\VSSSIC_Ground_Station.exe
echo.
echo On first launch it creates config\ and data\ alongside the executable.
echo Edit dist\config\config.json to change team ID, baud rate, or map origin.
echo.
pause
