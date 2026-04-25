
$Host.UI.RawUI.WindowTitle = "Portfolio Optimizer"
[Console]::ForegroundColor = [ConsoleColor]::Cyan

Write-Host "===================================================="
Write-Host "     Portfolio Optimizer Engine"
Write-Host "===================================================="
Write-Host ""
Write-Host "Initializing environment..."

Set-Location $PSScriptRoot

powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\src\run_optimizer.ps1"

Write-Host ""
Write-Host "Execution complete. This window will close automatically in 5 minutes."
Write-Host "Press any key to close it now."

$timeout = 300
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
while ($stopwatch.Elapsed.TotalSeconds -lt $timeout) {
    try {
        if ([console]::KeyAvailable) {
            $null = [system.console]::readkey($true)
            break
        }
    } catch {
        # IDE integrated terminals may not support raw console key detection.
        # Catch silently so it doesn't spam errors, and let it just timeout normally.
    }
    Start-Sleep -Milliseconds 100
}
