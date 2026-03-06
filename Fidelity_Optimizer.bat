@echo off
title Fidelity Portfolio Optimizer
color 0B

echo ====================================================
echo      Fidelity Portfolio Optimizer Engine
echo ====================================================
echo.
echo Initializing environment...
cd /d "%~dp0"

:: Run the PowerShell script and bypass execution policies automatically
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File run_optimizer.ps1

echo.
echo Execution complete. Press any key to close this window.
pause >nul
