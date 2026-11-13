# Gera installer\WidgetMonitor-Setup.exe com o Inno Setup. A versão vem do arquivo VERSION.
#   .\gerar_instalador.ps1              recompila o .exe (PyInstaller) e depois o instalador
#   .\gerar_instalador.ps1 -SemExe      só o instalador, reaproveitando -Origem
#   -Origem <pasta>                     pasta com WidgetMonitor.exe (padrão: dist\WidgetMonitor)
#   -Versao x.y.z -Teste                variante de TESTE isolada (outro AppId/pasta), para testar atualização sem tocar na instalação real
param([switch]$SemExe, [string]$Origem = "dist\WidgetMonitor", [string]$Versao = "", [switch]$Teste)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not $Versao) { $Versao = (Get-Content VERSION -Raw).Trim() }
if (-not $SemExe) { & "$PSScriptRoot\gerar_exe.ps1" }
if (-not (Test-Path "$Origem\WidgetMonitor.exe")) { throw "WidgetMonitor.exe não encontrado em $Origem" }
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup não encontrado. Instale com:  winget install JRSoftware.InnoSetup" }
$origemAbs = (Resolve-Path $Origem).Path
$args_ = @("/DOrigem=$origemAbs", "/DVersao=$Versao")
if ($Teste) { $args_ += "/DTeste=1" }
& $iscc @args_ "installer\WidgetMonitor.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC falhou" }
if (-not $Teste) {   # mantém o README em sincronia com VERSION
    $r = Get-Content README.md -Raw -Encoding UTF8
    $r = [regex]::Replace($r, "<!--versao-->.*?<!--/versao-->", "<!--versao-->$Versao<!--/versao-->")
    Set-Content README.md $r -Encoding UTF8
}
Write-Host "`nPronto (v$Versao): installer\WidgetMonitor-Setup$(if($Teste){'-teste'}).exe" -ForegroundColor Green
