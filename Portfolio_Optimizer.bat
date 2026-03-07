@echo off
title Portfolio Optimizer
color 0B

echo ====================================================
echo      Portfolio Optimizer Engine
echo ====================================================
echo.
echo Initializing environment...
cd /d "%~dp0"

:: Run the PowerShell script and bypass execution policies automatically
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File src\run_optimizer.ps1

echo.
echo Execution complete. This window will close automatically in 5 minutes.
echo Press any key to close it now.
timeout /t 300 >nul
