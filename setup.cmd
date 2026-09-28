@echo off
setlocal
cd /d "%~dp0"
title FLIR ONE Gen 2 Setup

echo.
echo FLIR ONE Gen 2 Windows Viewer setup
echo ===================================
echo.

set "PYTHON_EXE="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=py -3"
if "%PYTHON_EXE%"=="" (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_EXE=python"
)

if "%PYTHON_EXE%"=="" (
  echo Python 3 was not found.
  echo Install Python 3.11 or 3.12 from https://www.python.org/downloads/windows/
  echo Enable "Add python.exe to PATH" in the installer.
  pause
  exit /b 1
)

%PYTHON_EXE% --version
if errorlevel 1 exit /b 1

if not exist ".venv\Scripts\python.exe" (
  echo Creating the local virtual environment...
  %PYTHON_EXE% -m venv ".venv"
  if errorlevel 1 (
    echo Could not create .venv.
    pause
    exit /b 1
  )
)

echo Installing Python dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -c "import usb.core, libusb_package, numpy; from PIL import Image; print('Python dependencies: OK')"
if errorlevel 1 exit /b 1

echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\driver_check.ps1"
echo.
echo Setup completed. Read docs\USER_GUIDE.md before changing USB drivers.
pause
