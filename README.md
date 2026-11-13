# Monitor de Hardware — widget de desktop para Windows 11

> **Resumo:** widget de desktop para Windows 10/11, escrito em **Python (PySide6)**, que fica fixo na área de trabalho e mostra em tempo real temperatura, uso e frequência de CPU e GPU, RAM, disco, rede, bateria e ventoinhas. Também tem overlay para jogos (PresentMon/RTSS) e uma página web para acompanhar pelo celular.

<!-- Adicione aqui um print ou GIF: ![Widget](docs/widget.png) -->

**Stack:** Python 3.10+, PySide6, psutil, NVML (nvidia-ml-py), pywin32, pythonnet + LibreHardwareMonitor, PyInstaller e Inno Setup (instalador).

**Início rápido**
- *Usuário:* baixe o `WidgetMonitor-Setup.exe` na aba **Releases** e execute (não precisa de administrador).
- *Desenvolvedor:* `powershell -ExecutionPolicy Bypass -File instalar.ps1` (1ª vez) e depois `iniciar.bat`.

**Licença:** MIT. A leitura real da temperatura da CPU usa a [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) (MPL-2.0), baixada por `baixar_lib.ps1`.

A documentação completa começa abaixo.

**Versão <!--versao-->2.9.0<!--/versao-->** (definida no arquivo `VERSION`).

Widget compacto, sem borda nem barra de título, que fica **fixo na área de trabalho** (atrás das janelas, fora da barra de tarefas) e mostra em tempo real:

- **CPU** (i7-13700H): temperatura, uso (anel), frequência e potência (como administrador)
- **GPU NVIDIA RTX 4050**: temperatura, uso (anel), VRAM
- **Ventoinhas** (2): hélices animadas, com giro proporcional à rotação — ver nota abaixo sobre o RPM
- **GPU Intel Iris Xe**, **RAM**, **disco** (ocupação e espaço livre), **rede** (↓/↑) e **bateria**

Cada métrica tem ícone próprio; barras e anéis mudam de cor conforme a carga/temperatura (verde → âmbar → vermelho). Consumo: ~0,3 % de um núcleo e ~100 MB de RAM; com o widget oculto a leitura pausa.

## Instalador (recomendado)
Execute `installer\WidgetMonitor-Setup.exe` (Inno Setup, em pt-BR, **sem precisar de administrador**). Instala em `%LOCALAPPDATA%\Programs\WidgetMonitor`, cria atalho no Menu Iniciar e, opcionalmente (marcados por padrão), na Área de Trabalho e em "Iniciar com o Windows"; ao final oferece abrir o widget.

**Se já estiver instalado**, o instalador detecta (pelo AppId e pela chave de desinstalação) e mostra na tela inicial *"Versão X instalada, atualizar para Y"* / *"já é a mais recente — reparar"* / aviso de versão mais antiga (pede confirmação). A atualização é no lugar: mesma pasta, atalhos e início automático **como o usuário já deixou** (sem duplicar), configurações preservadas (ficam em `%APPDATA%\WidgetMonitor`), widget aberto é fechado e reaberto sozinho. Se ele estiver rodando como administrador e não puder ser fechado automaticamente, o instalador pede para fechá-lo pela bandeja (Sair) e tentar de novo. O desinstalador também fecha o widget e mantém a configuração.

**Versão:** definida só no arquivo `VERSION`; vale para o `.exe` (propriedades do arquivo), o Setup e este README (atualizado por `gerar_instalador.ps1`). Versão atual: <!--versao-->2.9.0<!--/versao-->.
Para recompilar (precisa do Inno Setup: `winget install JRSoftware.InnoSetup`): `powershell -ExecutionPolicy Bypass -File gerar_instalador.ps1`. A opção `-Teste -Versao x.y.z` gera um Setup de teste isolado (outro AppId e pasta) para experimentar atualizações sem tocar na instalação real.

## Como usar
**Executável (sem Python):** abra `dist\WidgetMonitor\WidgetMonitor.exe`.
**Do código (Python 3.10+):** `powershell -ExecutionPolicy Bypass -File instalar.ps1` (1ª vez) e depois `iniciar.bat`.
Para gerar o `.exe` de novo: `powershell -ExecutionPolicy Bypass -File gerar_exe.ps1` (feche o widget antes — se ele estiver rodando como administrador, feche-o pela bandeja, senão o Windows impede de sobrescrever os arquivos).

## Tudo se configura com o botão direito no widget
Métricas exibidas · Tamanho (75–175 %) · Opacidade · Tema (**Automático (Windows)** / Claro / Escuro) · Cor de destaque (**Automática (Windows)** ou 6 cores) · Efeito vidro · Intervalo de atualização (0,5/1/2/5 s) · Unidade °C/°F · Travar posição · Sempre no topo · Iniciar com o Windows · Reiniciar como administrador · Sair.

As mudanças valem na hora e ficam em `%APPDATA%\WidgetMonitor\config.json` (inclusive a posição: basta arrastar o widget). O ícone da bandeja serve para mostrar/ocultar, abrir as configurações e sair. Padrão: não fica sempre no topo (desktop de verdade); "Win+D" mostra a área de trabalho com o widget.

### Visual: vidro, tema e cor do Windows
- **Vidro (acrílico real):** o Windows desfoca o que estiver atrás do widget (outras janelas inclusive), com cantos arredondados limpos. Só funciona assim: `SetWindowCompositionAttribute` (acrílico) **mantendo os cantos arredondados do DWM** (`DWMWA_WINDOW_CORNER_PREFERENCE = ROUND`). Desligar os cantos do DWM ou usar `SetWindowRgn` faz o acrílico vazar um retângulo escuro; `DwmEnableBlurBehindWindow` não desfoca em janela sem borda no Windows 11. O raio da janela é o do sistema (8 px) e não acompanha o "Tamanho" do widget. Tinta neutra (grafite no escuro, branco-gelo no claro) pela opacidade do menu. Desligável.
- **Sem bordas:** por padrão não há contorno na janela nem nos cards (menu → *Bordas* os liga de volta, com brilho sutil).
- **Tema e cor automáticos:** o widget lê `AppsUseLightTheme` e a cor de destaque do Windows (`DWM\AccentColor`) e acompanha mudanças ao vivo (verificação a cada ~1,5 s). A cor de destaque é clareada/escurecida automaticamente para manter contraste de texto (≥ 4,5:1) nos dois temas.

## Iniciar com o Windows
Marque **Iniciar com o Windows** no menu (cria um atalho na pasta Inicializar). Para iniciar já como administrador, sem UAC a cada login, rode num PowerShell "Como administrador": `.\inicializacao.ps1 -Instalar -Admin` (`-Remover` desfaz).

## Sobre a temperatura da CPU (importante)
O Windows não expõe a temperatura real do processador a programas comuns:
- **Sem administrador**: o widget mostra a zona térmica ACPI do Windows, marcada com **≈** (aproximada).
- **Como administrador**: carrega a [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) (pasta `lib\`, MPL-2.0), que usa um driver de kernel para ler a temperatura **real** do pacote e a potência em watts. Use o menu → *Reiniciar como administrador*.
Se o Isolamento de Núcleo / Defender bloquear o driver, a temperatura continua aproximada (≈).
GPU NVIDIA, RAM, disco, rede e bateria funcionam sem administrador.

## Ventoinhas (RPM) — o que é real e o que é estimado
Ícone: o SVG de ventoinha em `assets\ventoinha.svg` (recolorido com a cor de destaque; só as pás e o cubo giram, a moldura fica parada).

**O que foi investigado (sem administrador) para obter o RPM neste Galaxy Book 3 Ultra:** `Win32_Fan`, `Win32_CoolingDevice`, `CIM_NumericSensor` (vazios); namespace `root\Samsung` (só a classe `BiosManager` — configurações de BIOS; lê-la exige administrador e não foi aberta, pois também tem métodos de escrita); `root\WMI` (só `MSAcpi_ThermalZoneTemperature`, sem ventoinha); NVML (`Not Supported` para a RTX 4050); dispositivo ACPI `SAM0429` (Samsung System Event Controller) e as pastas de dados dos serviços Samsung (nada com "fan"/"rpm"); contadores `Thermal Zone Information` (só temperatura). **O que ainda não foi tentado por exigir sua autorização:** (1) a LibreHardwareMonitor com administrador lendo placa-mãe/EC (implementado, mas nunca executado como administrador por mim) e (2) a leitura do EC por driver. Se nada disso expuser o RPM, a única fonte é o próprio software da Samsung.

Fontes de RPM real, em ordem: (a) LibreHardwareMonitor em modo administrador; (b) **HWiNFO**, se estiver aberto com *Settings → Shared Memory Support* ligado (o widget lê a memória compartilhada `HWiNFO_SENS_SM2`, somente leitura; o leitor foi validado só com dados simulados, não com um HWiNFO real).
- Quando houver RPM real, o widget mostra o valor e a hélice gira proporcional ao RPM (parada com 0 rpm; 6000 rpm ≈ 900°/s).
- Caso contrário, mostra um **nível estimado pela temperatura** (≈ %, rotulado "estimado") — não é RPM e não é medido. Parada abaixo de ~55 °C.
Ligar/desligar em botão direito → Métricas exibidas → Ventoinhas.

## Nomes no widget (v2.8)
O bloco da CPU mostra o **nome do processador** (ex.: `Intel Core i7-13700H`, `AMD Ryzen 9 7940HS`), lido do registro e limpo de `(R)`, `(TM)`, geração, frequência e sufixos; o da GPU mostra o nome da placa (ex.: `RTX 4050`). Nomes longos são cortados com reticências.

## Aparência do widget (v2.4)
- **Widget de área de trabalho de verdade:** por padrão a janela fica **logo acima do papel de parede e abaixo de todas as outras janelas** (como o Rainmeter em "On Desktop"): só aparece quando você olha a área de trabalho, nunca por cima de programas ou jogos, e clicar nele não o traz para a frente. "Sempre no topo" (menu) inverte isso.
- **Sem vidro nos blocos:** os blocos não têm mais fundo nem brilho; só a janela fica **desfocada** (acrílico do Windows). Quem quiser, liga *Aparência → Fundo nos blocos*. Sem fundo, uma divisória fina separa os blocos.
- **Menu do botão direito** redesenhado: minimalista, no tema claro/escuro do Windows, com ● marcando o que está ligado e agrupado em *Métricas, Aparência, Jogo e overlay, Perfil, Mais* + *Ajustes…*.
- **Overlay de jogo:** aparece **só com o jogo em primeiro plano** (Alt+Tab para outro programa o esconde) e tem um painel translúcido quadrado (Ajustes → Overlay → *Transparência do painel*; 0 = só texto; opção de desfocar o que está atrás).

## Overlay em tela cheia exclusiva: o que é possível (v2.8)
**Evidência no PC do usuário (log real):** com o Valorant em primeiro plano o `diagnostico.log` registra `decisao=JOGO ... overlay=visivel preso_ao_jogo=True ... tela_cheia_exclusiva_D3D=True` e o Windows (`SHQueryUserNotificationState = 3`) confirma **tela cheia exclusiva D3D**. O overlay existe, está no topo e preso à janela do jogo — mas o Windows não compõe nenhuma outra janela sobre um jogo nesse modo.
- **Preso à janela do jogo:** acompanha posição/tamanho/monitor da janela (relação dono/dependente + reposicionamento a cada 250 ms), ancora no canto escolhido, esconde com Alt+Tab e volta ao retornar ao jogo.
- **Funciona:** jogo em **janela**, **sem bordas (borderless)** e tela cheia **otimizada (FSO)** do Windows — testado com uma janela de teste em tela cheia sem bordas, por captura de tela.
- **Sem injeção, não existe forma em tela cheia exclusiva real:** o RTSS/Afterburner consegue porque injeta uma DLL no jogo. O widget não faz isso — mas pode **enviar os dados ao RTSS** (seção abaixo), se você já o usa.
- **Assistente (menu → Jogo e overlay → *Overlay em tela cheia exclusiva — assistente…*, e abre sozinho ao sair de um jogo detectado em tela cheia exclusiva):** passos exatos para Valorant (ESC → Configurações → Vídeo → Geral → *Janela sem bordas*), Battlefield (Vídeo → Modo de exibição → *Sem bordas*) e qualquer outro jogo (inclui a dica de **não** desativar as otimizações de tela cheia), com o botão **“Já mudei, testar agora”**: dá 10 s para voltar ao jogo, confere se ainda é exclusivo e, se não for, abre o overlay ali.
- **Alternativas sem mexer no jogo:** a **página do celular** (mesmos dados ao vivo no navegador de outro aparelho) e o widget **“Desempenho” do Xbox Game Bar (Win+G)**, nativo do Windows, que aparece sobre jogos em tela cheia.
- **Widget do Game Bar próprio:** exigiria um app UWP/WinUI empacotado (MSIX) com o Game Bar SDK — precisa de Visual Studio/MSBuild, Windows SDK, assinatura e modo desenvolvedor, nada disso disponível aqui; não foi feito.

## Mostrar os dados pelo RTSS (opcional, v2.9)
Para quem já usa o **RTSS** (RivaTuner Statistics Server, o do MSI Afterburner), o widget pode enviar os dados para o **OSD do RTSS**, que desenha dentro do jogo — inclusive em **tela cheia exclusiva**.
- **Como funciona:** o widget só **escreve texto** na memória compartilhada oficial do RTSS (`RTSSSharedMemoryV2`, a mesma API que o HWiNFO e o Afterburner usam), num slot próprio (`WidgetMonitor`, nunca o slot 0 do Afterburner nem o de outro programa). Posição e tamanho seguem as opções do RTSS; as cores vêm de tags (destaque do Windows no título, laranja CPU, roxo GPU, verde bateria). O widget **não injeta nada**; quem injeta é o RTSS.
- **Ajustes → Overlay → Modo de exibição:** *Nossa janela* (padrão) · *RTSS* · *Automático* (RTSS quando o jogo está em tela cheia exclusiva **e** o RTSS está rodando; senão a nossa janela). Nunca aparecem os dois ao mesmo tempo no mesmo jogo. Os “Itens exibidos” valem para os dois modos.
- **FPS:** por padrão o RTSS mostra o FPS dele e o widget não repete; há uma opção para incluir FPS/frametime no texto (lidos do próprio RTSS, sem precisar de permissão de administrador).
- **Estado e teste:** o menu (Jogo e overlay → *RTSS: …*) e a aba Overlay mostram se o RTSS está instalado/aberto/enxergando o jogo; o botão *Enviar teste ao RTSS (10 s)* escreve um texto de exemplo.
- **Limpeza:** o slot é zerado ao fechar o jogo, ao trocar de modo e ao sair do widget.
- **Não baixamos nem instalamos o RTSS.** Se não tiver: https://www.guru3d.com/page/rtss-rivatuner-statistics-server-download/ (vem junto com o MSI Afterburner).
- **Aviso:** o RTSS injeta código nos jogos. Cada jogo/anti-cheat decide se aceita; o risco é do RTSS, não deste widget. Use só onde você já usa o RTSS sem problemas.
- **Amigos da call do Discord:** não há fonte de dados implementada no widget, então ficaram **de fora** (nada foi inventado).
- **Limite técnico:** o RTSS usa um bit “ocupado” na memória compartilhada; as funções atômicas do Windows x64 não são acessíveis ao Python, então a verificação é teste-e-marca (janela de corrida de microssegundos; pior caso: um quadro de texto perdido).

## Overlay em 4:5 e temperatura real da CPU
- **Cartão em proporção 4:5 (retrato):** 330 × 412 px (antes do "Tamanho"). Mantém o desenho completo (título, FPS grande, média/1% low, frametime, barras de CPU/GPU/RAM/VRAM, linha de temperatura/clock/watts, bateria; o rodapé com app/resolução/power/driver vem **desligado** e pode ser religado em Ajustes). Com poucos itens ligados, a sobra é **repartida entre os blocos**; com muitos, o conteúdo é **reduzido** para caber — o cartão é sempre 4:5. Itens em Ajustes → Overlay.
- **Temperatura da CPU: só real no overlay.** O valor "≈" do widget é a zona térmica ACPI do chassi (estimativa) e **não é mostrado no overlay**. A leitura real exige **(1) executar como administrador** e **(2) o driver de sensores PawnIO** (a LibreHardwareMonitor 0.9.6 depende dele; ele **não vem instalado** e o widget **nunca instala drivers sozinho**). Menu → *Mais → Temperatura real da CPU…* explica o estado atual e, se faltar só o administrador, oferece o botão (o Windows pede a sua confirmação). Para o driver, uma vez, no PowerShell como administrador: `winget install namazso.PawnIO`. Já como administrador, *Mais → Iniciar sempre como administrador* cria a tarefa agendada que abre o widget elevado a cada login (sem UAC).

## Se o overlay não aparecer (diagnóstico)
1. **Menu (botão direito) → Jogo e overlay → "Mostrar overlay agora (teste)"** ou o ícone da bandeja → *Mostrar overlay agora*: mostra o overlay com ou sem jogo e **sem FPS** (aparece "FPS REQUER PERMISSAO" e o resto — CPU, GPU, RAM, temperaturas — continua).
2. **Log de diagnóstico:** `%LOCALAPPDATA%\WidgetMonitor\logs\diagnostico.log` (menu → *Abrir log de diagnóstico*). Cada linha mostra o programa em primeiro plano, se está em tela cheia/sem moldura, o uso de GPU 3D, **a decisão de detecção e o motivo** (na lista, ignorado, não cobre o monitor, GPU 3D abaixo do mínimo…), se o overlay está visível e preso ao jogo e o estado do FPS.
3. **Tela cheia exclusiva:** o widget pergunta ao Windows (`SHQueryUserNotificationState`) se há um jogo em tela cheia exclusiva D3D. Se houver, o log registra `tela_cheia_exclusiva_D3D=True` e o widget avisa (uma vez por jogo) para usar **"Janela sem bordas"**. Nesse modo nenhuma janela aparece por cima — é uma regra do Windows, não do widget.
4. **Como abrir as configurações** (várias formas): botão direito no widget, **ícone na bandeja** (Configurações…, Mostrar overlay agora, Mostrar/ocultar widget, menu completo, log, Sair) e o atalho global **Ctrl+Alt+M** (Ajustes). Tudo funciona mesmo com o widget embaixo das janelas.

## Consumo de CPU (leve por padrão)
- Atualização padrão a cada **2 s** (1 s só durante o jogo, para o FPS); dá para mudar em *Mais → Atualização*.
- Leituras caras (rede, discos, contadores de GPU) são feitas uma vez por ciclo ou em intervalos maiores; o widget redesenha só o que mudou. Medido neste notebook: ~**1 %** de um núcleo com o widget na área de trabalho; o overlay só gasta CPU enquanto está visível.
- O atalho global usa uma thread própria que dorme até a tecla ser pressionada (sem filtro de mensagens em Python).
- **Nenhuma notificação** ao gravar o log: sessões do mesmo jogo separadas por Alt+Tab viram **um único arquivo CSV**, gravado em silêncio 3 min depois de sair do jogo.

## Compatibilidade (qualquer PC com Windows 10/11 x64)
O widget detecta o hardware ao iniciar e **cada métrica indisponível simplesmente some** (nunca mostra valor inventado):
- **CPU Intel ou AMD** (nome e fabricante lidos do registro); temperatura real só com administrador, senão o valor aproximado do ACPI (marcado com ≈) ou nada.
- **Várias GPUs:** NVIDIA (via NVML: uso, temperatura, clock, potência, VRAM, driver), AMD e Intel (uso e memória pelos contadores do Windows; temperatura/clock/potência só com administrador via LibreHardwareMonitor). Dedicadas ganham cartão completo; integradas, uma linha.
- **Desktop sem bateria:** o cartão de bateria não aparece. **Sem sensor de ventoinha e sem temperatura:** o cartão de ventoinhas não aparece.
- **Vários discos:** até 4 unidades fixas (a do sistema primeiro). **Vários monitores:** posição salva que ficar fora de qualquer tela é descartada; widget e overlay podem ser posicionados em qualquer monitor (menu → Ajustes). **DPI/escala** variados são tratados pelo Qt.
- **Sem administrador:** tudo funciona, exceto temperatura real da CPU e RPM (e o FPS pode exigir permissão, veja abaixo).
O instalador é por usuário, x64.
**Testado só neste notebook (Galaxy Book 3 Ultra, Intel + NVIDIA)**; a lógica para AMD, vários monitores, desktop sem bateria etc. foi exercitada com dados simulados, não em outras máquinas.

## Overlay de jogo
Uma telinha separada (estilo MSI Afterburner), **idêntica ao overlay de referência**: sem painel de fundo (transparente, texto branco com contorno escuro), barras sólidas quadradas (CPU laranja, GPU roxa, bateria verde), FPS grande em roxo, linha de frametime e rodapé cinza. O painel de fundo é opcional (Ajustes → Overlay → *Fundo atrás do texto*, 0 = transparente). A página do celular usa o mesmo visual. Antes era que aparece sozinha ao entrar num jogo e some ao sair: título do aparelho, **FPS** grande + média + 1% low + frametime (ms) + gráfico de frametime, cartão da CPU (nome, %, barra, RAM, temperatura/clock/watts), cartão da GPU (nome, %, VRAM, temperatura/clock/watts), bateria e rodapé (executável do jogo, API, resolução, driver).
- **Como detecta o jogo:** janela em primeiro plano em **tela cheia/sem bordas** com uso de GPU 3D do processo acima de um limiar (padrão 2 %), fora da lista de ignorados (navegadores, players, etc.); ou qualquer `.exe` que você adicionar à **lista de jogos** (Ajustes → Jogos). Histerese evita abrir/fechar com Alt+Tab.
- **Mover o overlay onde você quiser (v2.6.1):** menu → *Jogo e overlay → Mover o overlay (arrastar)*, ícone da bandeja ou o atalho **Ctrl+Alt+P**. O overlay ganha uma moldura tracejada e passa a aceitar o mouse (sem tirar o foco do jogo): **arraste** e **duplo clique** (ou o atalho de novo) para concluir. A posição vira *canto mais próximo + margens* em relação à janela do jogo (ou ao monitor) e é gravada; os campos dos Ajustes se atualizam e ele continua acompanhando a janela. Também dá para digitar canto/margens/monitor em Ajustes → Overlay.
- **Mais compacto (v2.6.1):** barras mais finas, fontes e espaçamentos menores e largura de 285 px (antes 330): cerca de 25 % menor em altura. O layout *compacto* e o tamanho (%) continuam disponíveis para reduzir ainda mais.
- **Preso à janela do jogo (v2.5):** o overlay é "dependente" da janela do jogo (relação dono/dependente do Windows): fica **sempre logo acima dela** na ordem das janelas, sobe junto quando o jogo vem para a frente, **acompanha** a janela se ela mover/redimensionar e se posiciona no canto escolhido **da janela do jogo**. É só uma relação entre janelas — nada é injetado. Desligável em Ajustes → Overlay.
- **Por que o MSI Afterburner consegue em tela cheia exclusiva e o widget não:** o Afterburner/RTSS **injeta uma DLL no processo do jogo** e desenha dentro dele. Isso é exatamente o que este programa não faz (anti-cheat como o Vanguard pode bloquear ou punir). Em tela cheia exclusiva só há duas saídas seguras: **"Janela sem bordas"** no jogo, ou a **página do celular**.
- **Atalho global** (padrão **Ctrl+Alt+O**) mostra/oculta à mão; **Ctrl+Alt+W** mostra/oculta o widget. Ambos configuráveis (Ajustes → Atalhos).
- **Configuração:** botão direito → *Jogo e overlay*, ou *Ajustes do overlay, jogos e atalhos…*: canto da tela, margens, monitor, tamanho, opacidade, layout completo/compacto, estilo quadrado/arredondado, modo **clique-através** (não rouba foco nem cliques), itens exibidos (FPS, média, 1% low, frametime, CPU, RAM, GPU, VRAM, temperaturas, clocks, watts, bateria, rede, ventoinhas), °C/°F.
- **Segurança com anti-cheat:** o overlay é **uma janela separada, transparente e sempre no topo. Não injeta DLL, não faz hook e não lê a memória do jogo** — só lê a janela ativa, contadores do Windows e eventos ETW (o mesmo que o PresentMon). Por isso não deve disparar anti-cheat (Vanguard, EAC, BattlEye); ainda assim, cada jogo/anti-cheat tem sua política: use por sua conta e risco.
- **Limitação — tela cheia exclusiva:** janelas por cima de um jogo em *tela cheia exclusiva (exclusive fullscreen)* não aparecem. Use o modo **"Janela sem bordas" (borderless)** do jogo, ou deixe a otimização de tela cheia do Windows (FSO) ativa: Propriedades do `.exe` do jogo → *Compatibilidade* → *não* marque "Desativar otimizações de tela cheia".

### FPS e frametime (ETW / PresentMon)
O FPS vem do **PresentMon** oficial da Intel (MIT, assinado; `tools\PresentMon.exe`, baixado e verificado por SHA-256 e assinatura em `baixar_presentmon.ps1`). Ele lê os eventos de *Present* do DXGI/D3D via **ETW**, que o Windows só libera para **administrador ou para o grupo "Performance Log Users"**. Sem essa permissão o overlay mostra o restante e o aviso **"FPS requer permissão"** — nada é elevado automaticamente. Para liberar, **uma vez**, num PowerShell **como administrador**: `net localgroup "Performance Log Users" %USERNAME% /add` e depois **sair e entrar de novo** no Windows (ou abrir o widget como administrador). A média e o 1% low são calculados numa janela móvel de 30 s.

### Overlay no celular / segundo monitor (funciona com tela cheia exclusiva)
Jogos em **tela cheia exclusiva** (ex.: o modo "Tela cheia" do Valorant) cobrem qualquer janela do Windows, e a única forma de contornar isso dentro do PC seria injetar código no jogo, o que **não é feito** (risco de banimento). Por isso existe a **página para celular**: o widget serve uma página local, que você abre no navegador do **celular, tablet ou outro PC na mesma rede Wi‑Fi**, com FPS, média, 1% low, frametime, CPU, RAM, GPU, VRAM, bateria etc. em tempo real, no mesmo estilo quadrado.
- Ative em menu → *Jogo e overlay* → *Página para celular / segundo monitor* (ou Ajustes → **Celular**, que mostra o link e um **QR Code** para ler com a câmera). A porta padrão é 8765.
- O link tem uma **chave secreta**; sem ela o servidor responde 403. *Gerar novo link* invalida o anterior. O servidor só escuta enquanto a opção estiver ligada e só aceita a rede local (não há exposição à internet, a menos que você a encaminhe no roteador — não faça isso).
- Na primeira vez o **Firewall do Windows** pergunta se libera a rede privada: aceite só para redes de confiança. O widget não altera o firewall.
- O FPS na página também depende da permissão do PresentMon (veja "FPS e frametime").

## Outras funções
- **Perfis** (Desktop, Jogo, ou os seus): guardam estilo, métricas, tamanho, tema etc.; opção de trocar para o perfil "Jogo" automaticamente ao jogar.
- **Mini gráficos** de CPU/GPU (uso e temperatura nos últimos 60 s) — menu → *Mini gráficos*.
- **Alertas de temperatura** (notificação da bandeja, no máximo 1 a cada 5 min por componente); limites em Ajustes → Alertas (CPU só com leitura real).
- **Log de sessão de jogo em CSV** (FPS, média, 1% low, frametime, uso/temperatura/clock da CPU e GPU, VRAM, RAM, bateria — 1 linha por segundo) em `Documentos\WidgetMonitor\logs`; menu → *Exportar log da sessão atual* / *Abrir pasta de logs*.
- **Estilo Quadrado ou Arredondado** e posição por canto/monitor também para o widget (Ajustes → Widget).

## Arquivos
`app.py` (entrada) · `web.py` (página para celular) · `monitor.py` (widget, PySide6) · `overlay.py` · `jogo.py` (detecção, PresentMon/ETW, log, atalhos) · `gerente.py` · `rtss.py` (OSD do RTSS) · `assistente.py` · `ajustes.py` · `sensores.py` (psutil, NVML, contadores do Windows, LibreHardwareMonitor) · `lib\` (DLLs; `baixar_lib.ps1` baixa de novo) · `baixar_presentmon.ps1`, `instalar.ps1`, `iniciar.bat`, `gerar_exe.ps1`, `inicializacao.ps1`.


## Publicar no GitHub
O `.gitignore` já exclui `.venv`, `build*/`, `dist*/`, `installer/*.exe`, `__pycache__` e `lib/` (as DLLs da LibreHardwareMonitor voltam com `baixar_lib.ps1`, chamado por `instalar.ps1`). Anexe o `WidgetMonitor-Setup.exe` às *Releases* em vez de versioná-lo.





















