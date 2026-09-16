@echo off
setlocal
cd /d "%~dp0"
title FLIR ONE Gen 2 Windows Viewer

if not exist ".venv\Scripts\pythonw.exe" (
  echo First-run setup is required.
  call setup.cmd
  if errorlevel 1 exit /b 1
)

start "FLIR ONE Gen 2" ".venv\Scripts\pythonw.exe" "outputs\flir_live_viewer.py"

