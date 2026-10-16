@echo off
REM AtlasNexus Daily Console Launcher
REM This script activates the conda environment and starts the Dash app

echo ============================================================
echo AtlasNexus Daily Console Launcher
echo ============================================================
echo.

REM Activate standalone 'prod' env (no conda.bat needed)
echo [1/3] Activating standalone env 'prod'...

set PROD_ENV=D:\cmbc\.conda\envs\prod

if not exist "%PROD_ENV%\python.exe" (
    echo ERROR: Could not find python.exe under %PROD_ENV%.
    pause
    exit /b 1
)

set "PATH=%PROD_ENV%;%PROD_ENV%\Scripts;%PROD_ENV%\Library\bin;%PATH%"
set CONDA_PREFIX=%PROD_ENV%
set CONDA_DEFAULT_ENV=prod

echo       OK
echo.

REM -- 2. Dash server (separate window, auto-closes on exit) ------
echo [2/3] Starting Dash server on port 8080...
set FI_SHOW_LOG_WINDOW=0
REM Runtime toggles (explicitly opt in to Wind/data background tasks)
set FI_DISABLE_WIND=0
set FI_AUTO_INITIALISE=1
set FI_AUTO_REFRESH=1
cd /d "%~dp0"
start "AtlasNexus Server" cmd /k "python main.py daily-web"
echo       Started in background window.
echo.

REM Give the server a moment to bind the port
timeout /t 4 /nobreak >nul

REM -- 3. Cloudflare tunnel (this window) ------------------------
echo [3/3] Starting Cloudflare tunnel (anwin ^> anwin.mayunfei.org)...
echo.
echo   Local:   http://127.0.0.1:8080
echo   Public:  https://anwin.mayunfei.org
echo.
echo Share https://anwin.mayunfei.org with your friends.
echo Close this window to stop the tunnel (server window closes separately).
echo ============================================================
echo.

cloudflared tunnel --config "%USERPROFILE%\.cloudflared\config.yml" run anwin

if errorlevel 1 (
    echo.
    echo ERROR: Tunnel failed. Is cloudflared installed and the tunnel authenticated?
    echo        Run: cloudflared tunnel login
)
pause
