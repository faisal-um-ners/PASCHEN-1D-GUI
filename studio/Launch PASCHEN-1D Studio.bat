@echo off
REM Windows: double-click to start PASCHEN-1D Studio (installs on first use).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo First start: setting up PASCHEN-1D Studio...
  call "%~dp0install\install_windows.bat"
)
".venv\Scripts\python.exe" -c "import paschen_studio, PySide6" >nul 2>nul
if errorlevel 1 (
  echo The studio environment is incomplete - repairing it...
  call "%~dp0install\install_windows.bat"
)
start "" ".venv\Scripts\pythonw.exe" -m paschen_studio gui %*
