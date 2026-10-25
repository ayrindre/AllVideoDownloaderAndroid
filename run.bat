@echo off
rem ==========================================================================
rem  WebFinder - one-click run for Windows
rem  Creates .venv, installs dependencies on first launch, opens the app.
rem  Use "run.bat --browser" to open in the default browser instead of the
rem  native frameless window.
rem ==========================================================================
setlocal EnableExtensions
chcp 65001 >nul
title WebFinder
cd /d "%~dp0"

set "PYEXE=%~dp0.venv\Scripts\python.exe"

if exist "%PYEXE%" goto :checkdeps

echo [WebFinder] First run - creating the Python environment...
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [WebFinder] ERROR: Python 3.10+ was not found.
    echo             Install it from https://www.python.org/downloads/
    echo             (tick "Add python.exe to PATH") and run this file again.
    pause
    exit /b 1
  )
  python -m venv .venv
)
if not exist "%PYEXE%" (
  echo [WebFinder] ERROR: could not create .venv - see messages above.
  pause
  exit /b 1
)

:checkdeps
"%PYEXE%" -c "import fastapi, uvicorn, httpx, yarl" >nul 2>nul
if %errorlevel%==0 goto :checkyt
echo [WebFinder] Installing core dependencies...
"%PYEXE%" -m pip install --upgrade pip --quiet
"%PYEXE%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [WebFinder] ERROR: pip install failed - check your internet connection.
  pause
  exit /b 1
)

:checkyt
"%PYEXE%" -c "import yt_dlp" >nul 2>nul
if %errorlevel%==0 goto :run
echo [WebFinder] Optional: installing yt-dlp for media-platform links...
"%PYEXE%" -m pip install yt-dlp --quiet

:run
echo [WebFinder] Starting - the app window will appear shortly.
echo             (Close this console or press Ctrl+C to stop the backend.)
"%PYEXE%" run.py %*
if errorlevel 1 (
  echo.
  echo [WebFinder] The app exited with an error. Common fix:
  echo   "%PYEXE%" -m pip install -r requirements.txt
  pause
)
endlocal
