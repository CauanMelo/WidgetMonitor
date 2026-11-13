# Baixa o PresentMon oficial da Intel (MIT) para .\tools\PresentMon.exe, confere o SHA-256 e a assinatura digital.
# Usado só para medir FPS/frametime via ETW (não injeta nada em jogos).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$versao = "2.6.0"
$sha256 = "B2A706BC6AD475749E3B7E3409263AA1E6906D45BDCF993F6DBC0F660188F1AF"
New-Item -ItemType Directory -Force tools | Out-Null
$destino = "tools\PresentMon.exe"
Invoke-WebRequest "https://github.com/GameTechDev/PresentMon/releases/download/v$versao/PresentMon-$versao-x64.exe" -OutFile $destino -UseBasicParsing
if ((Get-FileHash $destino -Algorithm SHA256).Hash -ne $sha256) { Remove-Item $destino; throw "SHA-256 do PresentMon não confere" }
$sig = Get-AuthenticodeSignature $destino
if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Intel Corporation") { Remove-Item $destino; throw "Assinatura digital inválida" }
Write-Host "PresentMon $versao verificado (assinado pela Intel)." -ForegroundColor Green
