@echo off
chcp 65001 >nul
rem Prefer the packaged EXE; fall back to running from source.
cd /d "%~dp0.."
if exist "dist\SwissBackdrop.exe" (
    start "" "dist\SwissBackdrop.exe" %*
    exit /b 0
)
cd /d "%~dp0"
py -3 swiss_backdrop.py %*
if errorlevel 1 pause
