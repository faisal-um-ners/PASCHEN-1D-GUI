@echo off
REM PASCHEN-1D Studio installer for Windows.
REM Creates a private virtual environment in studio\.venv, installs the studio and every
REM solver dependency, verifies the installation and adds a desktop shortcut.
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."
set "STUDIO_DIR=%CD%"
echo ------------------------------------------------------------
echo   PASCHEN-1D Studio - installer
echo   folder: %STUDIO_DIR%
echo ------------------------------------------------------------

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo   Existing .venv uses an unsupported Python - rebuilding it.
    rmdir /s /q .venv
  )
)

if not exist ".venv\Scripts\python.exe" (
  set "PY="
  for %%V in (3.12 3.11 3.13 3.10) do (
    if not defined PY (
      py -%%V -c "import venv" >nul 2>nul && set "PY=py -%%V"
    )
  )
  if not defined PY (
    python -c "import sys, venv; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul && set "PY=python"
  )
  if not defined PY (
    echo.
    echo   No suitable Python found. PASCHEN-1D needs Python 3.10 - 3.13 ^(3.12 recommended^).
    echo   Install it from https://www.python.org/downloads/windows/
    echo   ^(tick "Add python.exe to PATH" and keep the "py launcher" option^), then run this again.
    echo.
    pause
    exit /b 1
  )
  echo   Using !PY!
  !PY! -m venv .venv || (echo Could not create the virtual environment & pause & exit /b 1)
)

set "VPY=%STUDIO_DIR%\.venv\Scripts\python.exe"
echo   Installing packages ^(numpy, scipy, matplotlib, numba, PySide6, ...^) - this takes a minute...
"%VPY%" -m pip install --upgrade pip --quiet
"%VPY%" -m pip install -e "%STUDIO_DIR%" || (echo Installation failed & pause & exit /b 1)
echo.
"%VPY%" -m paschen_studio info

echo.
echo   Verifying with a 1-second test simulation (also pre-compiles the Numba kernels)...
"%VPY%" -m paschen_studio run "%STUDIO_DIR%\examples\install_check.p1d.json" -w "%TEMP%\paschen_studio_check" -q >nul 2>nul
if errorlevel 1 (
  echo   ! The test simulation did not finish. Run it by hand to see the message:
  echo     "%VPY%" -m paschen_studio run "%STUDIO_DIR%\examples\install_check.p1d.json"
) else (
  echo   OK - PASCHEN-1D runs correctly.
)
rmdir /s /q "%TEMP%\paschen_studio_check" >nul 2>nul

REM Desktop shortcut (no console window)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'PASCHEN-1D Studio.lnk')); $s.TargetPath='%STUDIO_DIR%\.venv\Scripts\pythonw.exe'; $s.Arguments='-m paschen_studio gui'; $s.WorkingDirectory='%STUDIO_DIR%'; $s.IconLocation='%STUDIO_DIR%\paschen_studio\gui\assets\paschen_studio.ico'; $s.Description='PASCHEN-1D Studio'; $s.Save()" >nul 2>nul
if not errorlevel 1 echo   OK - "PASCHEN-1D Studio" shortcut added to your desktop.

echo.
echo   Done. Start the studio with any of:
echo     - the "PASCHEN-1D Studio" desktop shortcut
echo     - double-click  studio\Launch PASCHEN-1D Studio.bat
echo     - "%VPY%" -m paschen_studio gui
echo.
pause
