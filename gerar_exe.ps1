# Gera <Saida>\WidgetMonitor\WidgetMonitor.exe (pasta portátil, sem precisar de Python). Padrão: dist\
# A versão vem do arquivo VERSION (única fonte: .exe, Setup e README).
param([string]$Saida = "dist")
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$versao = (Get-Content VERSION -Raw).Trim()
$n = ($versao -split "\.") + @("0", "0", "0") | Select-Object -First 4
$tupla = ($n -join ", ")
@"
VSVersionInfo(ffi=FixedFileInfo(filevers=($tupla), prodvers=($tupla), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('041604b0', [StringStruct('CompanyName', 'Widget Monitor'),
    StringStruct('FileDescription', 'Monitor de Hardware'), StringStruct('FileVersion', '$versao'),
    StringStruct('ProductName', 'Monitor de Hardware'), StringStruct('ProductVersion', '$versao'),
    StringStruct('OriginalFilename', 'WidgetMonitor.exe')])]), VarFileInfo([VarStruct('Translation', [1046, 1200])])])
"@ | Set-Content build_versao.txt -Encoding UTF8
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --name WidgetMonitor `
    --icon assets\icone.ico --version-file build_versao.txt --distpath $Saida --workpath build_pyinstaller `
    --add-data "lib;lib" --add-data "assets;assets" --add-data "VERSION;." --add-data "tools;tools" `
    --collect-all pythonnet --collect-submodules win32com --hidden-import gerente --hidden-import overlay --hidden-import ajustes --hidden-import jogo --hidden-import rtss --hidden-import assistente app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou (feche o widget se ele estiver em execução)" }
Write-Host "`nPronto (v$versao): $Saida\WidgetMonitor\WidgetMonitor.exe" -ForegroundColor Green

