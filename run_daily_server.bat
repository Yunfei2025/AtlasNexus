@echo off
REM Supervisor: restarts the daily web app if it dies (e.g. a native Wind crash).
REM Close this window (or Ctrl+C twice) to stop.
cd /d "%~dp0"
:loop
echo [%date% %time%] starting python main.py daily-web
python main.py daily-web
echo [%date% %time%] app exited (code %errorlevel%) - restarting in 5s, see logs\crash.log
timeout /t 5 /nobreak >nul
goto loop
