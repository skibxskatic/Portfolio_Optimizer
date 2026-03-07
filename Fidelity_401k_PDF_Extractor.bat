@echo off
title Fidelity 401k PDF Extractor
color 0D

echo ====================================================
echo      Fidelity 401k PDF Text Extractor
echo ====================================================
echo.
echo Initializing environment...
cd /d "%~dp0"

:: Run the PowerShell script and bypass execution policies automatically
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File src\run_pdf_extractor.ps1

echo.
echo Execution complete. This window will close automatically in 5 minutes.
echo Press any key to close it now.
timeout /t 300 >nul
