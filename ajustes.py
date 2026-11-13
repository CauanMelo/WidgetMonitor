"""Tela de ajustes (overlay, jogos, alertas, atalhos e perfis). Simples e fora do caminho: só abre pelo menu."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QKeySequenceEdit,
                               QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

CANTOS = [("Superior esquerdo", "sup_esq"), ("Superior direito", "sup_dir"), ("Inferior esquerdo", "inf_esq"), ("Inferior direito", "inf_dir")]
ITENS = [("titulo", "Título (nome do aparelho)"), ("fps", "FPS"), ("media", "Média"), ("low1", "1% low"), ("frametime", "Frametime"), ("grafico", "Gráfico de frametime"),
         ("cpu", "CPU"), ("ram", "RAM"), ("gpu", "GPU"), ("vram", "VRAM"), ("temps", "Temperaturas"), ("clocks", "Clocks"),
         ("watts", "Consumo (W)"), ("bateria", "Bateria"), ("rede", "Rede"), ("ventoinhas", "Ventoinhas"), ("rodape", "Rodapé (jogo, API, resolução)")]
CAMPOS_PERFIL = ["estilo", "fundo_cards", "mostrar", "escala", "opacidade", "tema", "destaque", "vidro", "bordas", "graficos", "unidade"]


def estilo(escuro: bool) -> str:
    if escuro:
        return ("QDialog,QWidget{background:#1b1e29;color:#eef1f8;font:9pt 'Segoe UI Variable Text';} "
                "QTabWidget::pane{border:1px solid #343848;} QTabBar::tab{padding:6px 12px;background:#232736;} QTabBar::tab:selected{background:#2d3346;} "
                "QLineEdit,QSpinBox,QComboBox,QListWidget,QKeySequenceEdit{background:#232736;border:1px solid #343848;border-radius:6px;padding:3px;} "
                "QPushButton{background:#2d3346;border:1px solid #3d4358;border-radius:6px;padding:5px 12px;} QPushButton:hover{background:#38405a;}")
    return ("QDialog,QWidget{background:#f5f6fa;color:#141824;font:9pt 'Segoe UI Variable Text';} "
            "QTabWidget::pane{border:1px solid #cfd3de;} QTabBar::tab{padding:6px 12px;background:#e6e9f1;} QTabBar::tab:selected{background:#ffffff;} "
            "QLineEdit,QSpinBox,QComboBox,QListWidget,QKeySequenceEdit{background:#ffffff;border:1px solid #cfd3de;border-radius:6px;padding:3px;} "
            "QPushButton{background:#e6e9f1;border:1px solid #cfd3de;border-radius:6px;padding:5px 12px;} QPushButton:hover{background:#d9deea;}")


def _lista_editavel(titulo: str, dados: list[str], ao_mudar) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.addWidget(QLabel(titulo))
    lista = QListWidget()
    lista.addItems(dados)
    v.addWidget(lista)
    linha = QHBoxLayout()
    campo = QLineEdit()
    campo.setPlaceholderText("nome do programa, ex.: eldenring.exe")
    add = QPushButton("Adicionar")
    rem = QPushButton("Remover")
    linha.addWidget(campo, 1)
    linha.addWidget(add)
    linha.addWidget(rem)
    v.addLayout(linha)

    def adicionar():
        t = campo.text().strip().lower()
        if t and not t.endswith(".exe"):
            t += ".exe"
        if t and t not in dados:
            dados.append(t)
            lista.addItem(t)
            campo.clear()
            ao_mudar()

    def remover():
        for it in lista.selectedItems():
            dados.remove(it.text())
            lista.takeItem(lista.row(it))
        ao_mudar()

    add.clicked.connect(adicionar)
    campo.returnPressed.connect(adicionar)
    rem.clicked.connect(remover)
    return w


class QRWidget(QWidget):
    """QR Code desenhado direto (sem imagens), para abrir a página no celular."""

    def __init__(self):
        super().__init__()
        self.matriz: list[list[bool]] = []
        self.setFixedSize(190, 190)

    def definir(self, texto: str):
        import qrcode
        q = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
        q.add_data(texto)
        q.make(fit=True)
        self.matriz = q.get_matrix()
        self.update()

    def paintEvent(self, _):
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 255, 255))
        n = len(self.matriz)
        if not n:
            return
        lado = (self.width() - 16) / n
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0))
        for y, lin in enumerate(self.matriz):
            for x, v in enumerate(lin):
                if v:
                    p.drawRect(int(8 + x * lado), int(8 + y * lado), int(lado) + 1, int(lado) + 1)


class Ajustes(QDialog):
    def __init__(self, ctx, gerente):
        super().__init__()
        self.ctx, self.g = ctx, gerente
        cfg = ctx.cfg
        self.setWindowTitle("Monitor de Hardware — Ajustes")
        self.setStyleSheet(estilo(ctx.nome_tema() == "escuro"))
        self.resize(480, 640)
        raiz = QVBoxLayout(self)
        self.abas = abas = QTabWidget()
        raiz.addWidget(abas)

        # ---- Widget
        wd = QWidget()
        fw = QFormLayout(wd)
        self.cb_est = QComboBox()
        self.cb_est.addItem("Quadrado (barras)", "quadrado")
        self.cb_est.addItem("Arredondado", "vidro")
        self.cb_est.setCurrentIndex(0 if cfg["estilo"] == "quadrado" else 1)
        fw.addRow("Estilo", self.cb_est)
        self.cb_wcanto = QComboBox()
        for t, v in CANTOS:
            self.cb_wcanto.addItem(t, v)
        self.cb_wcanto.setCurrentIndex(max(0, [v for _, v in CANTOS].index(cfg["posicao"]["canto"])))
        fw.addRow("Posição na tela", self.cb_wcanto)
        self.sp_wmx = self._spin(0, 3000, cfg["posicao"]["margem_x"])
        self.sp_wmy = self._spin(0, 3000, cfg["posicao"]["margem_y"])
        fw.addRow("Margem horizontal (px)", self.sp_wmx)
        fw.addRow("Margem vertical (px)", self.sp_wmy)
        self.cb_wmon = QComboBox()
        for i, t in enumerate(QApplication.screens()):
            self.cb_wmon.addItem(f"Monitor {i + 1} ({t.size().width()}×{t.size().height()})", i)
        self.cb_wmon.setCurrentIndex(min(cfg["posicao"]["monitor"], self.cb_wmon.count() - 1))
        fw.addRow("Monitor", self.cb_wmon)
        b_pos = QPushButton("Posicionar agora")
        b_pos.clicked.connect(self._posicionar_widget)
        fw.addRow(b_pos)
        self.sp_wesc = self._spin(75, 175, cfg["escala"], 5)
        self.sp_wop = self._spin(40, 100, cfg["opacidade"], 5)
        fw.addRow("Tamanho (%)", self.sp_wesc)
        fw.addRow("Opacidade (%)", self.sp_wop)
        self.c_wcards = QCheckBox("Fundo nos blocos (desligado = só o desfoque da janela)")
        self.c_wcards.setChecked(cfg["fundo_cards"])
        fw.addRow(self.c_wcards)
        self.c_wblur = QCheckBox("Desfocar o fundo da janela (acrílico)")
        self.c_wblur.setChecked(cfg["vidro"])
        fw.addRow(self.c_wblur)
        self.c_wgraf = QCheckBox("Mini gráficos de CPU/GPU (últimos 60 s)")
        self.c_wgraf.setChecked(cfg["graficos"])
        fw.addRow(self.c_wgraf)
        self.c_wtravar = QCheckBox("Travar posição (não arrastar)")
        self.c_wtravar.setChecked(cfg["travar"])
        fw.addRow(self.c_wtravar)
        self.c_wtopo = QCheckBox("Sempre no topo")
        self.c_wtopo.setChecked(cfg["topo"])
        fw.addRow(self.c_wtopo)
        self.metricas = {}
        gm = QGridLayout()
        for n, (k, rot) in enumerate([("cpu", "CPU"), ("gpu", "GPU dedicada"), ("fans", "Ventoinhas"), ("igpu", "GPU integrada"),
                                      ("ram", "Memória RAM"), ("disco", "Discos"), ("rede", "Rede"), ("bateria", "Bateria")]):
            c = QCheckBox(rot)
            c.setChecked(cfg["mostrar"].get(k, True))
            self.metricas[k] = c
            gm.addWidget(c, n // 2, n % 2)
        fw.addRow(QLabel("Métricas exibidas:"))
        fw.addRow(gm)
        abas.addTab(wd, "Widget")

        # ---- Overlay
        ov = cfg["overlay"]
        pg = QWidget()
        f = QFormLayout(pg)
        self.c_auto = QCheckBox("Mostrar automaticamente quando um jogo for detectado")
        self.c_auto.setChecked(cfg["jogo"]["overlay_auto"])
        f.addRow(self.c_auto)
        self.cb_modo = QComboBox()
        self.cb_modo.addItem("Nossa janela (jogos em janela ou sem bordas)", "janela")
        self.cb_modo.addItem("RTSS (para tela cheia exclusiva)", "rtss")
        self.cb_modo.addItem("Automático: RTSS em tela cheia exclusiva, senão nossa janela", "auto")
        self.cb_modo.setCurrentIndex(max(0, self.cb_modo.findData(ov.get("modo", "janela"))))
        f.addRow("Modo de exibição", self.cb_modo)
        self.l_rtss = QLabel("")
        self.l_rtss.setWordWrap(True)
        f.addRow(self.l_rtss)
        lr = QHBoxLayout()
        b_vrtss = QPushButton("Verificar RTSS")
        b_trtss = QPushButton("Enviar teste ao RTSS (10 s)")
        b_vrtss.clicked.connect(self._atualizar_rtss)
        b_trtss.clicked.connect(self.g.testar_rtss)
        lr.addWidget(b_vrtss)
        lr.addWidget(b_trtss)
        lr.addStretch(1)
        f.addRow(lr)
        self.c_rtss_fps = QCheckBox("Incluir FPS/frametime no texto do RTSS (ele já mostra o dele; ligue só se não quiser duplicar)")
        self.c_rtss_fps.setChecked(cfg.get("rtss", {}).get("fps", False))
        f.addRow(self.c_rtss_fps)
        av = QLabel("Aviso: o RTSS funciona injetando código nos jogos. Cada jogo/anti-cheat decide se aceita; o risco é do RTSS, não deste "
                    "widget (que só envia texto a ele). Não baixamos nem instalamos o RTSS. Posição e tamanho do texto seguem as opções do RTSS. "
                    "Os “Itens exibidos” abaixo valem para os dois modos.")
        av.setWordWrap(True)
        f.addRow(av)
        self.cb_modo.currentIndexChanged.connect(self._atualizar_rtss)
        self._atualizar_rtss()
        self.cb_canto = QComboBox()
        for t, v in CANTOS:
            self.cb_canto.addItem(t, v)
        self.cb_canto.setCurrentIndex(max(0, [v for _, v in CANTOS].index(ov["canto"])))
        f.addRow("Posição na tela", self.cb_canto)
        self.sp_mx = self._spin(0, 2000, ov["margem_x"])
        self.sp_my = self._spin(0, 2000, ov["margem_y"])
        f.addRow("Margem horizontal (px)", self.sp_mx)
        f.addRow("Margem vertical (px)", self.sp_my)
        self.cb_mon = QComboBox()
        for i, t in enumerate(QApplication.screens()):
            self.cb_mon.addItem(f"Monitor {i + 1} ({t.size().width()}×{t.size().height()})", i)
        self.cb_mon.setCurrentIndex(min(ov["monitor"], self.cb_mon.count() - 1))
        f.addRow("Monitor", self.cb_mon)
        b_arrastar = QPushButton("Mover o overlay arrastando…")
        b_arrastar.clicked.connect(self.g.editar_posicao)
        f.addRow(b_arrastar)
        self.sp_esc = self._spin(50, 250, ov["escala"], 10)
        self.sp_op = self._spin(0, 100, ov["opacidade"], 5)
        f.addRow("Tamanho (%)", self.sp_esc)
        f.addRow("Transparência do painel (0 = sem painel)", self.sp_op)
        self.cb_lay = QComboBox()
        self.cb_lay.addItem("Completo", "completo")
        self.cb_lay.addItem("Compacto", "compacto")
        self.cb_lay.setCurrentIndex(0 if ov["layout"] == "completo" else 1)
        f.addRow("Layout", self.cb_lay)
        self.cb_est_ov = QComboBox()
        self.cb_est_ov.addItem("Quadrado (barras)", "quadrado")
        self.cb_est_ov.addItem("Arredondado", "vidro")
        self.cb_est_ov.setCurrentIndex(0 if ov.get("estilo", "quadrado") == "quadrado" else 1)
        f.addRow("Estilo", self.cb_est_ov)
        self.c_ov_blur = QCheckBox("Desfocar o que está atrás do overlay (acrílico)")
        self.c_ov_blur.setChecked(ov.get("desfoque", False))
        f.addRow(self.c_ov_blur)
        self.c_preso = QCheckBox("Prender à janela do jogo (fica sempre à frente dela e a acompanha)")
        self.c_preso.setChecked(ov.get("preso_ao_jogo", True))
        f.addRow(self.c_preso)
        self.c_click = QCheckBox("Clique-através (não rouba foco nem cliques do jogo)")
        self.c_click.setChecked(ov["clique_atraves"])
        f.addRow(self.c_click)
        self.cb_un = QComboBox()
        self.cb_un.addItem("Celsius (°C)", "C")
        self.cb_un.addItem("Fahrenheit (°F)", "F")
        self.cb_un.setCurrentIndex(0 if cfg["unidade"] == "C" else 1)
        f.addRow("Unidade de temperatura", self.cb_un)
        grade = QGridLayout()
        self.itens = {}
        for n, (k, rot) in enumerate(ITENS):
            c = QCheckBox(rot)
            c.setChecked(ov["itens"].get(k, True))
            self.itens[k] = c
            grade.addWidget(c, n // 2, n % 2)
        f.addRow(QLabel("Itens exibidos:"))
        f.addRow(grade)
        abas.addTab(pg, "Overlay")

        # ---- Jogos
        pj = QWidget()
        v = QVBoxLayout(pj)
        self.c_det = QCheckBox("Detectar jogos automaticamente (tela cheia/sem bordas + uso de GPU 3D)")
        self.c_det.setChecked(cfg["jogo"]["auto_detectar"])
        v.addWidget(self.c_det)
        lim = QHBoxLayout()
        lim.addWidget(QLabel("Uso mínimo de GPU 3D para considerar jogo (%):"))
        self.sp_lim = self._spin(1, 90, cfg["jogo"]["limiar_gpu3d"])
        lim.addWidget(self.sp_lim)
        v.addLayout(lim)
        self.c_log = QCheckBox("Gravar log CSV de cada sessão de jogo")
        self.c_log.setChecked(cfg["jogo"]["log"])
        v.addWidget(self.c_log)
        self.c_perfil = QCheckBox("Trocar para o perfil “Jogo” enquanto jogo e voltar depois")
        self.c_perfil.setChecked(cfg["jogo"]["perfil_auto"])
        v.addWidget(self.c_perfil)
        v.addWidget(_lista_editavel("Jogos conhecidos (sempre mostram o overlay):", cfg["jogo"]["jogos"], self._salvar))
        v.addWidget(_lista_editavel("Ignorar (nunca tratar como jogo):", cfg["jogo"]["ignorar"], self._salvar))
        abas.addTab(pj, "Jogos")

        # ---- Alertas
        pa = QWidget()
        fa = QFormLayout(pa)
        self.c_al = QCheckBox("Avisar quando a temperatura passar do limite")
        self.c_al.setChecked(cfg["alerta"]["ativo"])
        fa.addRow(self.c_al)
        self.sp_acpu = self._spin(50, 110, cfg["alerta"]["cpu"])
        self.sp_agpu = self._spin(50, 110, cfg["alerta"]["gpu"])
        fa.addRow("Limite da CPU (°C) — só com leitura real (administrador)", self.sp_acpu)
        fa.addRow("Limite da GPU (°C)", self.sp_agpu)
        abas.addTab(pa, "Alertas")

        # ---- Atalhos
        pt = QWidget()
        ft = QFormLayout(pt)
        self.k_ov = QKeySequenceEdit(QKeySequence(cfg["atalhos"]["overlay"]))
        self.k_wd = QKeySequenceEdit(QKeySequence(cfg["atalhos"]["widget"]))
        ft.addRow("Mostrar/ocultar overlay", self.k_ov)
        ft.addRow("Mostrar/ocultar widget", self.k_wd)
        self.k_aj = QKeySequenceEdit(QKeySequence(cfg["atalhos"].get("ajustes", "Ctrl+Alt+M")))
        ft.addRow("Abrir estes ajustes", self.k_aj)
        self.k_pos = QKeySequenceEdit(QKeySequence(cfg["atalhos"].get("posicao", "Ctrl+Alt+P")))
        ft.addRow("Mover o overlay (arrastar)", self.k_pos)
        ft.addRow(QLabel("Use sempre uma combinação com Ctrl, Alt, Shift ou Win."))
        abas.addTab(pt, "Atalhos")

        # ---- Celular
        pc = QWidget()
        vc = QVBoxLayout(pc)
        vc.addWidget(QLabel("Mostra o overlay em outro aparelho (celular, tablet, segundo PC) pelo navegador, na mesma rede Wi‑Fi.\n"
                            "Funciona mesmo com o jogo em tela cheia exclusiva, pois nada é desenhado sobre o jogo."))
        self.c_web = QCheckBox("Ativar a página para celular / segundo monitor")
        self.c_web.setChecked(cfg["web"]["ativo"])
        vc.addWidget(self.c_web)
        pr = QHBoxLayout()
        pr.addWidget(QLabel("Porta:"))
        self.sp_porta = self._spin(1024, 65535, cfg["web"]["porta"])
        pr.addWidget(self.sp_porta)
        b_link = QPushButton("Gerar novo link")
        pr.addWidget(b_link)
        pr.addStretch(1)
        vc.addLayout(pr)
        self.lb_url = QLabel()
        self.lb_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_url.setWordWrap(True)
        vc.addWidget(self.lb_url)
        self.qr = QRWidget()
        vc.addWidget(self.qr, 0, Qt.AlignHCenter)
        vc.addWidget(QLabel("O link tem uma chave secreta: quem não a tiver não vê nada. Na primeira vez o Firewall do Windows pode\n"
                            "perguntar se libera a rede privada — aceite só para redes de confiança."))
        vc.addStretch(1)
        abas.addTab(pc, "Celular")
        b_link.clicked.connect(self._novo_link)
        self._atualizar_url()

        # ---- Perfis
        pp = QWidget()
        vp = QVBoxLayout(pp)
        self.cb_perfil = QComboBox()
        vp.addWidget(QLabel("Perfis guardam aparência e métricas do widget (Desktop, Jogo…)."))
        vp.addWidget(self.cb_perfil)
        linha = QHBoxLayout()
        b_ap, b_del = QPushButton("Aplicar"), QPushButton("Excluir")
        linha.addWidget(b_ap)
        linha.addWidget(b_del)
        vp.addLayout(linha)
        ln = QHBoxLayout()
        self.ed_nome = QLineEdit()
        self.ed_nome.setPlaceholderText("nome do novo perfil")
        b_sv = QPushButton("Salvar configuração atual como…")
        ln.addWidget(self.ed_nome, 1)
        ln.addWidget(b_sv)
        vp.addLayout(ln)
        vp.addStretch(1)
        abas.addTab(pp, "Perfis")
        self._preencher_perfis()
        b_ap.clicked.connect(lambda: self.g.aplicar_perfil(self.cb_perfil.currentText()))
        b_del.clicked.connect(self._excluir_perfil)
        b_sv.clicked.connect(self._salvar_perfil)

        # ---- botões
        rodape = QHBoxLayout()
        ok, fechar = QPushButton("Aplicar e salvar"), QPushButton("Fechar")
        rodape.addStretch(1)
        rodape.addWidget(ok)
        rodape.addWidget(fechar)
        raiz.addLayout(rodape)
        ok.clicked.connect(self._salvar)
        fechar.clicked.connect(self.close)

    @staticmethod
    def _spin(a, b, v, passo=1) -> QSpinBox:
        s = QSpinBox()
        s.setRange(a, b)
        s.setSingleStep(passo)
        s.setValue(int(v))
        return s

    def _atualizar_url(self):
        if not self.ctx.cfg["web"]["token"]:
            self.g.web.novo_token()
        url = self.g.web.url()
        self.lb_url.setText(url)
        self.qr.definir(url)

    def _novo_link(self):
        self.g.web.novo_token()
        self.ctx.cfg["web"]["porta"] = self.sp_porta.value()
        self._atualizar_url()

    def atualizar_posicao(self):
        """O overlay foi arrastado: reflete canto/margens/monitor nos campos."""
        ov = self.ctx.cfg["overlay"]
        self.cb_canto.setCurrentIndex(max(0, [v for _, v in CANTOS].index(ov["canto"])))
        self.sp_mx.setValue(ov["margem_x"])
        self.sp_my.setValue(ov["margem_y"])
        self.cb_mon.setCurrentIndex(min(ov["monitor"], self.cb_mon.count() - 1))

    def _posicionar_widget(self):
        c = self.ctx.cfg["posicao"]
        c.update(canto=self.cb_wcanto.currentData(), margem_x=self.sp_wmx.value(), margem_y=self.sp_wmy.value(), monitor=self.cb_wmon.currentData() or 0)
        self.ctx.posicionar()

    def _preencher_perfis(self):
        self.cb_perfil.clear()
        self.cb_perfil.addItems(sorted(self.ctx.cfg["perfis"]))
        i = self.cb_perfil.findText(self.ctx.cfg["perfil"])
        if i >= 0:
            self.cb_perfil.setCurrentIndex(i)

    def _salvar_perfil(self):
        nome = self.ed_nome.text().strip() or self.cb_perfil.currentText() or "Desktop"
        self.g.salvar_perfil(nome)
        self.ed_nome.clear()
        self._preencher_perfis()

    def _excluir_perfil(self):
        self.g.excluir_perfil(self.cb_perfil.currentText())
        self._preencher_perfis()

    def _atualizar_rtss(self, *_):
        self.l_rtss.setText("RTSS: " + self.g.rtss_status())

    def ir_para(self, nome: str):
        for i in range(self.abas.count()):
            if self.abas.tabText(i) == nome:
                self.abas.setCurrentIndex(i)

    def _salvar(self):
        cfg = self.ctx.cfg
        ov = cfg["overlay"]
        ov["modo"] = self.cb_modo.currentData()
        cfg.setdefault("rtss", {})["fps"] = self.c_rtss_fps.isChecked()
        ov.update(canto=self.cb_canto.currentData(), margem_x=self.sp_mx.value(), margem_y=self.sp_my.value(),
                  monitor=self.cb_mon.currentData() or 0, escala=self.sp_esc.value(), opacidade=self.sp_op.value(),
                  layout=self.cb_lay.currentData(), clique_atraves=self.c_click.isChecked())
        ov["itens"].update({k: c.isChecked() for k, c in self.itens.items()})
        ov["estilo"] = self.cb_est_ov.currentData()
        cfg["estilo"] = self.cb_est.currentData()
        cfg["escala"], cfg["opacidade"] = self.sp_wesc.value(), self.sp_wop.value()
        cfg["fundo_cards"], cfg["vidro"] = self.c_wcards.isChecked(), self.c_wblur.isChecked()
        ov["desfoque"] = self.c_ov_blur.isChecked()
        ov["preso_ao_jogo"] = self.c_preso.isChecked()
        cfg["graficos"], cfg["travar"], cfg["topo"] = self.c_wgraf.isChecked(), self.c_wtravar.isChecked(), self.c_wtopo.isChecked()
        cfg["mostrar"].update({k: c.isChecked() for k, c in self.metricas.items()})
        cfg["posicao"].update(canto=self.cb_wcanto.currentData(), margem_x=self.sp_wmx.value(), margem_y=self.sp_wmy.value(), monitor=self.cb_wmon.currentData() or 0)
        cfg["web"].update(ativo=self.c_web.isChecked(), porta=self.sp_porta.value())
        cfg["unidade"] = self.cb_un.currentData()
        j = cfg["jogo"]
        j.update(overlay_auto=self.c_auto.isChecked(), auto_detectar=self.c_det.isChecked(), limiar_gpu3d=self.sp_lim.value(),
                 log=self.c_log.isChecked(), perfil_auto=self.c_perfil.isChecked())
        cfg["alerta"].update(ativo=self.c_al.isChecked(), cpu=self.sp_acpu.value(), gpu=self.sp_agpu.value())
        cfg["atalhos"].update(overlay=self.k_ov.keySequence().toString(), widget=self.k_wd.keySequence().toString(), ajustes=self.k_aj.keySequence().toString(), posicao=self.k_pos.keySequence().toString())
        self.g.aplicar_config()
