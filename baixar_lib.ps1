# Baixa a LibreHardwareMonitor (MPL-2.0) do GitHub oficial e copia as DLLs necessárias para .\lib
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$versao = "v0.9.6"
$tmp = Join-Path $env:TEMP "lhm_download"
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $tmp | Out-Null
Invoke-WebRequest "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/$versao/LibreHardwareMonitor.zip" -OutFile "$tmp\lhm.zip" -UseBasicParsing
Expand-Archive "$tmp\lhm.zip" "$tmp\x" -Force
New-Item -ItemType Directory lib -Force | Out-Null
Get-ChildItem "$tmp\x" -Filter *.dll | Where-Object { $_.Name -notmatch "Aga|OxyPlot|TaskScheduler" } | Copy-Item -Destination lib -Force
Write-Host "DLLs copiadas para .\lib" -ForegroundColor Green
