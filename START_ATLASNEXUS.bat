@echo off
REM AtlasNexus Daily Console Launcher
REM This script activates the conda environment and starts the Dash app

echo ============================================================
echo AtlasNexus Daily Console Launcher
echo ============================================================
echo.

REM Activate conda environment
echo [1/3] Activating conda environment 'dev'...

REM Try standard conda locations in order
set CONDA_BAT=
if exist "%USERPROFILE%\anaconda3\condabin\conda.bat"   set CONDA_BAT=%USERPROFILE%\anaconda3\condabin\conda.bat
if exist "%USERPROFILE%\miniconda3\condabin\conda.bat"  set CONDA_BAT=%USERPROFILE%\miniconda3\condabin\conda.bat
if exist "C:\ProgramData\anaconda3\condabin\conda.bat"  set CONDA_BAT=C:\ProgramData\anaconda3\condabin\conda.bat
if exist "C:\ProgramData\miniconda3\condabin\conda.bat" set CONDA_BAT=C:\ProgramData\miniconda3\condabin\conda.bat

if "%CONDA_BAT%"=="" (
    echo ERROR: Could not find conda.bat. Please check your Anaconda/Miniconda installation.
    pause
    exit /b 1
)

call "%CONDA_BAT%" activate dev
if errorlevel 1 (
    echo ERROR: Failed to activate conda environment 'dev'
    echo Please ensure the 'dev' environment exists: conda create -n dev python=3.13
    pause
    exit /b 1
)

echo [2/3] Environment activated successfully
echo.

REM Change to correct directory
cd /d "%~dp0"

echo [3/3] Starting AtlasNexus Daily Console...
echo Server will start at: http://127.0.0.1:8080
echo Browser window will open automatically
echo.
echo Press Ctrl+C to stop the server
echo ============================================================
echo.

REM Start the Dash app
python web\apps\atlasnexus_daily.py

REM If the script exits, pause to show any error messages
if errorlevel 1 (
    echo.
    echo ============================================================
    echo ERROR: Application exited with error code %errorlevel%
    echo ============================================================
    pause
)
