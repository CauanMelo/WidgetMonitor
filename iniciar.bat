@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo Ambiente nao encontrado. Execute primeiro: instalar.ps1
  pause & exit /b 1
)
start "" .venv\Scripts\pythonw.exe app.py

