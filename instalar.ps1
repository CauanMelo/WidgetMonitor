# Cria o ambiente Python e instala as dependências. Uso:  powershell -ExecutionPolicy Bypass -File instalar.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3.10+ não encontrado. Instale em python.org ou pela Microsoft Store." }
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
if (-not (Test-Path lib\LibreHardwareMonitorLib.dll)) { & "$PSScriptRoot\baixar_lib.ps1" }
if (-not (Test-Path tools\PresentMon.exe)) { & "$PSScriptRoot\baixar_presentmon.ps1" }
Write-Host "`nPronto! Abra com iniciar.bat" -ForegroundColor Green

