# Inicia o widget junto com o Windows.
#   .\inicializacao.ps1 -Instalar [-Admin]   (-Admin: roda elevado SEM pedir UAC a cada login => temperatura real da CPU;
#                                              precisa ser executado uma vez num PowerShell "Como administrador")
#   .\inicializacao.ps1 -Remover
param([switch]$Instalar, [switch]$Admin, [switch]$Remover)
$ErrorActionPreference = "Stop"
$nome = "WidgetMonitor"
$exe = Join-Path $PSScriptRoot "dist\WidgetMonitor\WidgetMonitor.exe"
if (Test-Path $exe) { $prog = $exe; $args_ = "" }
else { $prog = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"; $args_ = "`"$PSScriptRoot\monitor.py`"" }
$atalho = Join-Path ([Environment]::GetFolderPath("Startup")) "$nome.lnk"

if ($Remover) {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $atalho -ErrorAction SilentlyContinue
    Write-Host "Inicialização automática removida."; return
}
if (-not $Instalar) { Write-Host "Use -Instalar ou -Remover (veja o README)."; return }

if ($Admin) {
    $eAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole("Administrator")
    if (-not $eAdmin) { throw "Para -Admin abra o PowerShell como administrador e rode de novo." }
    Remove-Item $atalho -ErrorAction SilentlyContinue
    $acao = if ($args_) { New-ScheduledTaskAction -Execute $prog -Argument $args_ -WorkingDirectory $PSScriptRoot } else { New-ScheduledTaskAction -Execute $prog -WorkingDirectory $PSScriptRoot }
    $gatilho = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $conf = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    $prin = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive
    Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $conf -Principal $prin -Force | Out-Null
    Write-Host "Tarefa agendada criada: o widget abrirá como administrador a cada login." -ForegroundColor Green
} else {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
    $sh = New-Object -ComObject WScript.Shell
    $l = $sh.CreateShortcut($atalho)
    $l.TargetPath = $prog; $l.Arguments = $args_; $l.WorkingDirectory = $PSScriptRoot; $l.Save()
    Write-Host "Atalho criado em Inicializar: $atalho (sem administrador: temperatura da CPU aproximada)." -ForegroundColor Green
}
