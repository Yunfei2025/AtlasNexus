@echo off
REM AtlasNexus — Windows Launcher
REM Starts the Dash server and Cloudflare tunnel in one window.

echo ============================================================
echo   AtlasNexus Daily Console
echo ============================================================
echo.

REM ── 1. Conda environment ────────────────────────────────────────
echo [1/3] Activating conda environment 'prod'...

set CONDA_BAT=
if exist "%USERPROFILE%\anaconda3\condabin\conda.bat"   set CONDA_BAT=%USERPROFILE%\anaconda3\condabin\conda.bat
if exist "%USERPROFILE%\miniconda3\condabin\conda.bat"  set CONDA_BAT=%USERPROFILE%\miniconda3\condabin\conda.bat
if exist "C:\ProgramData\anaconda3\condabin\conda.bat"  set CONDA_BAT=C:\ProgramData\anaconda3\condabin\conda.bat
if exist "C:\ProgramData\miniconda3\condabin\conda.bat" set CONDA_BAT=C:\ProgramData\miniconda3\condabin\conda.bat
if exist "D:\ProgramData\miniconda3\condabin\conda.bat" set CONDA_BAT=D:\ProgramData\miniconda3\condabin\conda.bat

if "%CONDA_BAT%"=="" (
    echo ERROR: Could not find conda. Check your Anaconda/Miniconda installation.
    pause & exit /b 1
)

call "%CONDA_BAT%" activate prod
if errorlevel 1 (
    echo ERROR: Could not activate conda env 'prod'.
    echo        Run: conda create -n prod python=3.13
    pause & exit /b 1
)
echo       OK
echo.

REM ── 2. Dash server (separate window, auto-closes on exit) ────────
echo [2/3] Starting Dash server on port 8080...
set FI_SHOW_LOG_WINDOW=0
cd /d "%~dp0"
start "AtlasNexus Server" /min cmd /c "python main.py daily-web & pause"
echo       Started in background window.
echo.

REM Give the server a moment to bind the port
timeout /t 4 /nobreak >nul

REM ── 3. Cloudflare tunnel (this window) ──────────────────────────
echo [3/3] Starting Cloudflare tunnel (atlasnexus ^> mayunfei.org)...
echo.
echo   Local:   http://127.0.0.1:8080
echo   Public:  https://mayunfei.org
echo.
echo Share https://mayunfei.org with your friends.
echo Close this window to stop the tunnel (server window closes separately).
echo ============================================================
echo.

cloudflared tunnel --config "%USERPROFILE%\.cloudflared\config.yml" run atlasnexus

if errorlevel 1 (
    echo.
    echo ERROR: Tunnel failed. Is cloudflared installed and the tunnel authenticated?
    echo        Run: cloudflared tunnel login
)
pause
