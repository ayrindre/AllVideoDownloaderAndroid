@echo off
setlocal EnableExtensions
title All Video Downloader
cd /d "%~dp0"

if not exist "run.py" (
  echo [All Video Downloader] run.py not next to this .bat - move this file into the All Video Downloader folder.
  pause
  exit /b 1
)

REM ?? existing venv? ?????????????????????????????????????????????????????
if exist ".venv\Scripts\python.exe" goto :check_deps
echo [All Video Downloader] First run: creating the virtual environment + installing dependencies...
echo             ^(requires Python 3.10+ on PATH; get it from python.org if this fails^)
py -3 -m venv .venv 2>nul || python -m venv .venv || (echo [error] python not found - install Python 3 and retry. & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" (echo [error] venv creation failed. & pause & exit /b 1)

:check_deps
".venv\Scripts\python.exe" -c "import fastapi,uvicorn,httpx,yarl,curl_cffi" 2>nul
if not errorlevel 1 goto :run
echo [All Video Downloader] Installing missing dependencies...
".venv\Scripts\pip.exe" install -r requirements.txt --disable-pip-version-check
".venv\Scripts\python.exe" -c "import fastapi" 2>nul || (echo [error] dependency install failed - check your internet/proxy & pause & exit /b 1)

:run
".venv\Scripts\python.exe" run.py %*
if errorlevel 1 (
  echo.
  echo [All Video Downloader] exited abnormally. A full log is above.
  pause
)
