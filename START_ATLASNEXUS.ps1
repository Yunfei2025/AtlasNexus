# AtlasNexus Daily Console Launcher (PowerShell)
# This script activates the conda environment and starts the Dash app

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "AtlasNexus Daily Console Launcher" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Get the script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "[1/3] Activating conda environment 'dev'..." -ForegroundColor Yellow

# Initialize conda for PowerShell
$CondaHook = "C:\ProgramData\anaconda3\shell\condabin\conda-hook.ps1"
if (Test-Path $CondaHook) {
    & $CondaHook
    conda activate dev
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[2/3] Environment activated successfully" -ForegroundColor Green
    } else {
        Write-Host "ERROR: Failed to activate conda environment 'dev'" -ForegroundColor Red
        Write-Host "Please ensure Anaconda/Miniconda is installed and 'dev' environment exists" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
} else {
    Write-Host "ERROR: Conda not found at expected location" -ForegroundColor Red
    Write-Host "Expected: $CondaHook" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "[3/3] Starting AtlasNexus Daily Console..." -ForegroundColor Yellow
Write-Host "Server will start at: http://127.0.0.1:8080" -ForegroundColor Green
Write-Host "Browser window will open automatically" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Start the Dash app
try {
    python web\apps\atlasnexus_daily.py
} catch {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "ERROR: Application crashed" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "ERROR: Application exited with error code $LASTEXITCODE" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Read-Host "Press Enter to exit"
}
