; Instalador do Monitor de Hardware (Inno Setup 6). Compile com gerar_instalador.ps1
; (a versão vem do arquivo VERSION; /DTeste=1 gera uma variante isolada para testes, com outro AppId e pasta).
#ifndef Origem
  #define Origem "..\dist\WidgetMonitor"
#endif
#ifndef Versao
  #define Versao "0.0.0"
#endif
#ifdef Teste
  #define Nome "Monitor de Hardware (TESTE)"
  #define Guid "{{5B0E7C1A-3D44-4B7B-9C55-8A6E1F2D7AFF}"
  #define GuidReg "{5B0E7C1A-3D44-4B7B-9C55-8A6E1F2D7AFF}"
  #define Pasta "WidgetMonitorTeste"
  #define Atalho "WidgetMonitorTeste"
  #define Saida "WidgetMonitor-Setup-teste"
  #define Exe "WidgetMonitorTeste.exe"
  #define Params "--multi"
#else
  #define Nome "Monitor de Hardware"
  #define Guid "{{5B0E7C1A-3D44-4B7B-9C55-8A6E1F2D7A10}"
  #define GuidReg "{5B0E7C1A-3D44-4B7B-9C55-8A6E1F2D7A10}"
  #define Pasta "WidgetMonitor"
  #define Atalho "WidgetMonitor"
  #define Saida "WidgetMonitor-Setup"
  #define Exe "WidgetMonitor.exe"
  #define Params ""
#endif

[Setup]
AppId={#Guid}
AppName={#Nome}
AppVersion={#Versao}
VersionInfoVersion={#Versao}
AppPublisher=Widget Monitor
DefaultDirName={localappdata}\Programs\{#Pasta}
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
CloseApplications=no
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename={#Saida}
SetupIconFile=..\assets\icone.ico
UninstallDisplayIcon={app}\{#Exe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de &Trabalho"; GroupDescription: "Atalhos:"
Name: "startup"; Description: "&Iniciar com o Windows"; GroupDescription: "Inicialização:"

[Files]
#ifdef Teste
Source: "{#Origem}\*"; DestDir: "{app}"; Excludes: "WidgetMonitor.exe"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Origem}\WidgetMonitor.exe"; DestDir: "{app}"; DestName: "{#Exe}"; Flags: ignoreversion
#else
Source: "{#Origem}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
; Nomes fixos: reinstalar sobrescreve em vez de duplicar. Em atualização vale o que já existe (escolha do usuário).
Name: "{autoprograms}\{#Nome}"; Filename: "{app}\{#Exe}"
Name: "{autodesktop}\{#Nome}"; Filename: "{app}\{#Exe}"; Check: QuerAtalho('desktopicon')
Name: "{userstartup}\{#Atalho}"; Filename: "{app}\{#Exe}"; Check: QuerAtalho('startup')

[Run]
; Atualização com o widget aberto: reabre sozinho. Instalação nova (ou widget fechado): pergunta ao final.
Filename: "{app}\{#Exe}"; Parameters: "{#Params}"; Flags: nowait runasoriginaluser; Check: ReabrirAuto
Filename: "{app}\{#Exe}"; Parameters: "{#Params}"; Description: "Abrir o {#Nome} agora"; Flags: nowait postinstall skipifsilent runasoriginaluser; Check: not ReabrirAuto

[Code]
const
  ChaveDesinst = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#GuidReg}_is1';

var
  VersaoInstalada: String;
  EstavaAberto: Boolean;

function LerInstalada(): String;
var V: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, ChaveDesinst, 'DisplayVersion', V) then Result := V
  else if RegQueryStringValue(HKLM, ChaveDesinst, 'DisplayVersion', V) then Result := V;
end;

function ProxNumero(var S: String): Integer;
var P: Integer;
begin
  P := Pos('.', S);
  if P = 0 then begin Result := StrToIntDef(S, 0); S := ''; end
  else begin Result := StrToIntDef(Copy(S, 1, P - 1), 0); S := Copy(S, P + 1, MaxInt); end;
end;

// compara "a.b.c" com "x.y.z": -1 (menor), 0 (igual), 1 (maior)
function CompararVersao(A, B: String): Integer;
var NA, NB: Integer;
begin
  Result := 0;
  while (A <> '') or (B <> '') do begin
    NA := ProxNumero(A); NB := ProxNumero(B);
    if NA < NB then begin Result := -1; Exit; end;
    if NA > NB then begin Result := 1; Exit; end;
  end;
end;

function Atualizando(): Boolean;
begin
  Result := VersaoInstalada <> '';
end;

// Em atualização preserva o estado atual do atalho; na 1ª instalação segue a tarefa marcada.
function QuerAtalho(Qual: String): Boolean;
var Caminho: String;
begin
  if Qual = 'desktopicon' then Caminho := ExpandConstant('{autodesktop}\{#Nome}.lnk')
  else Caminho := ExpandConstant('{userstartup}\{#Atalho}.lnk');
  if Atualizando() then Result := FileExists(Caminho)
  else Result := WizardIsTaskSelected(Qual);
end;

function ReabrirAuto(): Boolean;
begin
  Result := EstavaAberto;
end;

function AppRodando(): Boolean;
var R: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\cmd.exe'), '/c tasklist /FI "IMAGENAME eq {#Exe}" | find /I "{#Exe}"', '', SW_HIDE, ewWaitUntilTerminated, R) and (R = 0);
end;

procedure FecharApp();
var R: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#Exe}', '', SW_HIDE, ewWaitUntilTerminated, R);
  Sleep(700);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  EstavaAberto := AppRodando();
  if EstavaAberto then FecharApp();
  // instância elevada não morre com taskkill comum: pede para fechar pela bandeja
  while AppRodando() do begin
    if WizardSilent() or (MsgBox('O Monitor de Hardware está aberto como administrador e não pôde ser fechado automaticamente.' + #13#10 +
        'Feche-o pelo ícone da bandeja (Sair) e clique em Repetir.', mbError, MB_RETRYCANCEL) = IDCANCEL) then begin
      Result := 'O Monitor de Hardware precisa ser fechado antes de continuar.';
      Exit;
    end;
  end;
end;

procedure InitializeWizard();
var Msg: String;
begin
  VersaoInstalada := LerInstalada();
  if VersaoInstalada = '' then Exit;
  case CompararVersao(VersaoInstalada, '{#Versao}') of
    -1: Msg := 'Versão ' + VersaoInstalada + ' instalada. Este instalador vai atualizar para a versão {#Versao}.';
     0: Msg := 'A versão {#Versao} já está instalada e é a mais recente. Continuar vai reparar (reinstalar) os arquivos.';
     1: Msg := 'ATENÇÃO: a versão instalada (' + VersaoInstalada + ') é mais recente que este instalador ({#Versao}). Continuar vai voltar para a versão {#Versao}.';
  end;
  WizardForm.WelcomeLabel2.Caption := Msg + #13#10#13#10 + 'Suas configurações e atalhos serão mantidos. Clique em Avançar para continuar.';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // atualização no lugar: mesma pasta e mesmas escolhas de atalhos/inicialização
  Result := Atualizando() and ((PageID = wpSelectDir) or (PageID = wpSelectTasks));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpReady) and Atualizando() then begin
    case CompararVersao(VersaoInstalada, '{#Versao}') of
      -1: WizardForm.NextButton.Caption := 'Atualizar';
       0: WizardForm.NextButton.Caption := 'Reparar';
       1: WizardForm.NextButton.Caption := 'Reverter';
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpWelcome) and Atualizando() and (CompararVersao(VersaoInstalada, '{#Versao}') = 1) then
    Result := MsgBox('A versão instalada (' + VersaoInstalada + ') é mais nova que este instalador ({#Versao}). Deseja mesmo voltar para a versão {#Versao}?', mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then FecharApp();
end;

function InitializeUninstall(): Boolean;
begin
  FecharApp();
  Result := True;
end;
