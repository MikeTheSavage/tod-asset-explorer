@echo off
setlocal EnableExtensions
rem TOD Asset Explorer - extract (first run only) and open the viewer.
rem Usage: run.bat ["path\to\Total Overdose"]      (the folder with TOD.exe and blocks.naz)
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup, then run this again.
  pause
  exit /b 1
)

if not defined TOD_ASSETS set "TOD_ASSETS=%~dp0assets"

dir /s /b "%TOD_ASSETS%\*.glb" >nul 2>nul
if not errorlevel 1 goto serve

echo No extracted assets found in "%TOD_ASSETS%".
set "GAME=%~1"
if not defined GAME if exist "C:\GOG Games\Total Overdose\blocks.naz" set "GAME=C:\GOG Games\Total Overdose"
if defined GAME (
  echo Using game folder: "%GAME%"
) else (
  echo.
  echo Enter the Total Overdose install folder ^(the one that contains TOD.exe and blocks.naz^).
  set /p "GAME=Game folder: "
)
if not defined GAME (
  echo No folder given.
  pause
  exit /b 1
)
set "GAME=%GAME:"=%"
echo.
echo Extracting models, animations and textures (about a minute)...
%PY% "%~dp0extractor\tod_extract.py" --game "%GAME%" --out "%TOD_ASSETS%"
if errorlevel 1 (
  echo.
  echo Extraction failed - see the message above.
  pause
  exit /b 1
)

:serve
echo.
%PY% "%~dp0serve.py" --assets "%TOD_ASSETS%" --open
if errorlevel 1 pause
