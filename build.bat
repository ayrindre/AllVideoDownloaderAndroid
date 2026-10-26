@echo off
rem ==========================================================================
rem  All Video Downloader - build a single-file Windows EXE
rem
rem    build.bat              build  ->  dist\AllVideoDownloader.exe
rem    build.bat --run        build, then launch it
rem    build.bat --no-pause   build without waiting for a keypress
rem
rem  Works from a fresh copy: it creates .venv, installs the runtime + build
rem  dependencies, and only then packages. Every step is checked - a failure
rem  prints the reason instead of a Python traceback that scrolls away.
rem  Full build log: build\build.log
rem ==========================================================================
setlocal EnableExtensions
chcp 65001 >nul
title All Video Downloader - build

set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "LOG=%ROOT%build\build.log"
set "DIST=%ROOT%dist"
set "WORK=%ROOT%build\obj"
set "SPEC=%ROOT%build\webfinder.spec"
set "EXE=%DIST%\AllVideoDownloader.exe"
set "RUN_AFTER=0"
set "PAUSE_AT_END=1"
if /i "%~1"=="--run"      set "RUN_AFTER=1"
if /i "%~1"=="--no-pause" set "PAUSE_AT_END=0"
if /i "%~2"=="--run"      set "RUN_AFTER=1"

rem  keep Python's output in UTF-8 so a stray unicode character in a warning
rem  can never abort the build with UnicodeEncodeError
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH="
set "PIP_DISABLE_PIP_VERSION_CHECK=1"

echo.
echo  ==========================================================
echo    All Video Downloader - Windows EXE build
echo  ==========================================================
echo.

if not exist "%ROOT%run.py"      goto :no_source
if not exist "%SPEC%"            goto :no_spec
if not exist "%ROOT%web\index.html" goto :no_web

rem ---------------------------------------------------------------- 1. python
if exist "%PY%" goto :deps
echo  [1/5] Creating the virtual environment (.venv)...
set "BASEPY="
for %%P in (py.exe) do if exist "%%~$PATH:P" set "BASEPY=py -3"
if not defined BASEPY for %%P in (python.exe) do if exist "%%~$PATH:P" set "BASEPY=python"
if not defined BASEPY goto :no_python
%BASEPY% -m venv "%ROOT%.venv"
if errorlevel 1 goto :no_venv
if not exist "%PY%" goto :no_venv
echo        ok - %PY%

:deps
echo  [2/5] Checking build dependencies...
"%PY%" -m pip --version >nul 2>&1
if not errorlevel 1 goto :install_reqs
echo        repairing pip...
"%PY%" -m ensurepip --upgrade >nul 2>&1
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 goto :no_pip

:install_reqs
"%PY%" -m pip install -r "%ROOT%requirements.txt" --quiet
if errorlevel 1 echo        [warn] a runtime package failed to install - the EXE may miss a feature.

"%PY%" -c "import PyInstaller" >nul 2>&1
if not errorlevel 1 goto :have_pyinstaller
echo        installing PyInstaller...
"%PY%" -m pip install --upgrade pyinstaller --quiet
if errorlevel 1 goto :no_pyinstaller
"%PY%" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 goto :no_pyinstaller

:have_pyinstaller
"%PY%" -c "import fastapi, uvicorn, yt_dlp" >nul 2>&1
if errorlevel 1 goto :no_core
for /f "delims=" %%V in ('"%PY%" -m PyInstaller --version 2^>nul') do set "PI_VER=%%V"
echo        ok - PyInstaller %PI_VER%

rem ----------------------------------------------------------------- 3. clean
echo  [3/5] Cleaning previous artifacts...
tasklist /fi "imagename eq AllVideoDownloader.exe" 2>nul | find /i "AllVideoDownloader.exe" >nul
if not errorlevel 1 goto :exe_running
if exist "%DIST%" rmdir /s /q "%DIST%" 2>nul
if exist "%WORK%" rmdir /s /q "%WORK%" 2>nul
if exist "%ROOT%build\exe" rmdir /s /q "%ROOT%build\exe" 2>nul
if exist "%DIST%" goto :dist_locked
if not exist "%ROOT%build" mkdir "%ROOT%build"
break > "%LOG%"

rem ----------------------------------------------------------------- 4. build
echo  [4/5] Packaging (2-5 minutes on the first run, less afterwards)...
echo        log: %LOG%
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN --distpath "%DIST%" --workpath "%WORK%" "%SPEC%" >"%LOG%" 2>&1
if errorlevel 1 goto :build_failed
if not exist "%EXE%" goto :build_failed

rem ---------------------------------------------------------------- 5. verify
echo  [5/5] Verifying the artifact...
for %%F in ("%EXE%") do set "EXE_SIZE=%%~zF"
if not defined EXE_SIZE goto :build_failed
if %EXE_SIZE% LSS 5000000 goto :small_build
echo        %EXE_SIZE% bytes

echo.
echo  ==========================================================
echo    BUILD OK
echo    %EXE%
echo  ==========================================================
echo.
where iscc >nul 2>&1
if not errorlevel 1 echo  Installer: iscc build\installer.iss
if /i "%RUN_AFTER%"=="1" start "" "%EXE%"
if /i "%PAUSE_AT_END%"=="1" pause
endlocal
exit /b 0

rem ================================ errors ==================================
:no_source
echo  [error] run.py is not next to this script.
echo          Run build.bat from the All Video Downloader folder.
goto :fail

:no_spec
echo  [error] build\webfinder.spec is missing - the repo copy is incomplete.
goto :fail

:no_web
echo  [error] web\index.html is missing - the frontend was not copied.
goto :fail

:no_python
echo  [error] Python 3.10+ was not found on PATH.
echo          Install it from https://www.python.org/downloads/ and tick
echo          "Add python.exe to PATH", then run build.bat again.
goto :fail

:no_venv
echo  [error] Could not create .venv (antivirus? permissions? disk full?).
echo          Try running run.bat once, then build.bat again.
goto :fail

:no_pip
echo  [error] pip is unusable inside .venv.
echo          Delete the .venv folder and run build.bat again.
goto :fail

:no_pyinstaller
echo  [error] PyInstaller could not be installed (no internet / proxy?).
echo          Behind a proxy:  set HTTPS_PROXY=http://host:port   then retry.
goto :fail

:no_core
echo  [error] The runtime dependencies are incomplete (fastapi / uvicorn / yt-dlp).
echo          Run:  .venv\Scripts\pip install -r requirements.txt
goto :fail

:exe_running
echo  [error] AllVideoDownloader.exe is running - close it first.
echo          (Windows locks the file, so dist\ cannot be cleaned.)
goto :fail

:dist_locked
echo  [error] dist\ could not be cleaned. Close any Explorer window showing it,
echo          or delete the folder manually, then retry.
goto :fail

:build_failed
echo.
echo  [error] PyInstaller failed. Last lines of %LOG%:
echo  ------------------------------------------------------------
where powershell >nul 2>&1
if errorlevel 1 goto :tail_type
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path '%LOG%') { Get-Content -LiteralPath '%LOG%' -Tail 40 }"
goto :fail
:tail_type
if exist "%LOG%" type "%LOG%"
goto :fail

:small_build
echo  [error] The EXE was built but looks far too small (%EXE_SIZE% bytes) -
echo          assets were probably not bundled. Delete the dist folder and re-run build.bat.
goto :fail

:fail
echo.
if /i "%PAUSE_AT_END%"=="1" pause
endlocal
exit /b 1
