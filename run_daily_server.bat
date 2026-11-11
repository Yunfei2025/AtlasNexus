@echo off
REM Supervisor: restarts the daily web app if it dies (e.g. a native Wind crash).
REM Wind is enabled by default; set FI_DISABLE_WIND=1 before launch only when needed.
set FI_AUTO_INITIALISE=0
set FI_AUTO_REFRESH=0
set FI_AUTO_EOD=0
cd /d "%~dp0"
:loop
echo [%date% %time%] starting python main.py daily-web
python main.py daily-web
echo [%date% %time%] app exited (code %errorlevel%) - restarting in 5s, see logs\crash.log
timeout /t 5 /nobreak >nul
goto loop
