@echo off
rem ==========================================================================
rem  WebFinder - build a single-file Windows EXE (dist\WebFinder.exe)
rem  Requires: run.bat executed once (so .venv exists). PyInstaller is
rem  installed into .venv automatically on first build.
rem ==========================================================================
setlocal EnableExtensions
chcp 65001 >nul
title WebFinder - build EXE
cd /d "%~dp0"

set "PYEXE=%~dp0.venv\Scripts\python.exe"
set "PIP=%PYEXE%"

if not exist "%PYEXE%" (
  echo [build] ERROR: no .venv found - run "run.bat" once first to set up Python.
  pause
  exit /b 1
)

echo [build] Ensuring PyInstaller + dependencies...
"%PIP%" -m pip install --upgrade pip --quiet
"%PIP%" -m pip install -r requirements.txt --quiet
"%PIP%" -c "import PyInstaller" >nul 2>nul || "%PIP%" -m pip install pyinstaller

echo [build] Cleaning previous artifacts...
if exist build\exe rmdir /s /q build\exe
if exist dist  rmdir /s /q dist

echo [build] Packaging (this takes a few minutes on first run)...
"%PYEXE%" -m PyInstaller build\webfinder.spec --noconfirm --distpath dist --workpath build\exe
if errorlevel 1 (
  echo.
  echo [build] ERROR: PyInstaller failed - scroll up for the traceback.
  pause
  exit /b 1
)

echo.
echo [build] SUCCESS -> %~dp0dist\WebFinder.exe
echo         Optional installer: install Inno Setup 6, then run
echo           "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" build\installer.iss
echo.
if /i "%~1"=="--run" start "" "%~dp0dist\WebFinder.exe"
pause
endlocal
