@echo off
REM AtlasNexus Daily Console - Combined Launcher
REM Starts both the web server and Cloudflare Tunnel for permanent access

echo ============================================================
echo Starting AtlasNexus with Permanent Cloudflare Tunnel
echo ============================================================
echo.

REM Open web server in one window
echo [1/2] Starting web server (port 8080)...
start cmd /k "cd /d %~dp0 && call START_win.bat"

REM Give it time to start before opening tunnel
timeout /t 3 /nobreak

REM Open tunnel in another window
echo [2/2] Starting Cloudflare Tunnel...
start cmd /k "cd /d %~dp0 && call server.bat"

echo.
echo ============================================================
echo Both server and tunnel are starting!
echo - Web server: http://127.0.0.1:8080 (local)
echo - Public URL: Check your Cloudflare dashboard or the tunnel window
echo ============================================================
echo.
pause
