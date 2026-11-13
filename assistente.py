"""Assistente de tela cheia exclusiva: explica, com os passos exatos de cada jogo, como ativar o modo "sem bordas".

Janelas externas (overlay, widget, qualquer coisa) NÃO aparecem por cima de um jogo em tela cheia exclusiva D3D — o próprio
Windows confirma esse estado (SHQueryUserNotificationState). Sem injetar código no jogo, só o modo sem bordas resolve.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

import ajustes
import jogo as J

PASSOS = {
    "valorant": ("Valorant", "1) Dentro do Valorant, abra o menu (ESC) → Configurações.\n"
                             "2) Vídeo → Geral.\n"
                             "3) Modo de exibição: escolha “Janela sem bordas” (Windowed Fullscreen) em vez de “Tela cheia”.\n"
                             "4) Aplique. O desempenho é praticamente o mesmo e o overlay passa a aparecer."),
    "bf6": ("Battlefield", "1) No jogo: Configurações → Vídeo (Video).\n"
                           "2) Modo de exibição (Display Mode): escolha “Sem bordas” (Borderless).\n"
                           "3) Aplique/confirme."),
    "battlefield": None,
}
GENERICO = ("Seu jogo", "1) Nas opções de vídeo do jogo procure “Modo de exibição / Display Mode / Window Mode”.\n"
                         "2) Troque “Tela cheia” (Fullscreen/Exclusive) por “Sem bordas” (Borderless / Windowed Fullscreen).\n"
                         "3) Se o jogo só oferece “Tela cheia”: clique com o botão direito no .exe do jogo → Propriedades → Compatibilidade e "
                         "NÃO marque “Desativar otimizações de tela cheia” (com elas ligadas o Windows costuma tratar o modo como sem bordas).")


def passos_para(exe: str) -> tuple[str, str]:
    e = (exe or "").lower()
    for chave in ("valorant", "bf6", "battlefield"):
        if chave in e:
            return PASSOS.get(chave) or PASSOS["bf6"]
    return GENERICO


class AssistenteTelaCheia(QDialog):
    def __init__(self, ctx, gerente, exe: str = ""):
        super().__init__()
        self.ctx, self.g, self.exe = ctx, gerente, exe
        self.setWindowTitle("Overlay em tela cheia exclusiva")
        self.setStyleSheet(ajustes.estilo(ctx.nome_tema() == "escuro"))
        self.resize(520, 420)
        v = QVBoxLayout(self)
        nome, passos = passos_para(exe)
        t = QLabel(f"<b>{nome}</b> está em <b>tela cheia exclusiva</b>.<br>"
                   "Nesse modo o Windows esconde qualquer janela por cima do jogo — inclusive este overlay. Isso é uma regra do Windows; "
                   "só um programa que injeta código no jogo (como o RTSS) escapa dela. Este widget NÃO injeta nada; mas, se você já usa o RTSS, "
                   "ele pode enviar os dados para o OSD do RTSS (Ajustes → Overlay → Modo de exibição).")
        t.setWordWrap(True)
        v.addWidget(t)
        p = QLabel(passos)
        p.setWordWrap(True)
        p.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(p)
        alt = QLabel("<b>Outras formas de ver os números sem mudar o jogo:</b><br>"
                     "• <b>RTSS (se você já o usa):</b> Ajustes → Overlay → Modo de exibição → RTSS ou Automático. O RTSS injeta código nos jogos e cada "
                     "anti-cheat decide se aceita; o risco é do RTSS, não deste widget.<br>"
                     "• <b>Celular / segundo monitor:</b> menu → Jogo e overlay → Página para celular (mostra os mesmos dados ao vivo).<br>"
                     "• <b>Xbox Game Bar (Win+G):</b> o widget “Desempenho” do próprio Windows aparece por cima de jogos em tela cheia.")
        alt.setWordWrap(True)
        v.addWidget(alt)
        self.estado = QLabel("")
        self.estado.setWordWrap(True)
        v.addWidget(self.estado)
        linha = QHBoxLayout()
        self.b_teste = QPushButton("Já mudei, testar agora")
        b_fechar = QPushButton("Fechar")
        linha.addStretch(1)
        linha.addWidget(self.b_teste)
        linha.addWidget(b_fechar)
        v.addLayout(linha)
        self.b_teste.clicked.connect(self.testar)
        b_fechar.clicked.connect(self.close)
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._resta = 0

    def testar(self):
        """Dá 10 s para voltar ao jogo e então confere: ainda exclusiva? Se não, mostra o overlay ali mesmo."""
        self._resta = 10
        self.b_teste.setEnabled(False)
        self._t.start(1000)
        self._tick()

    def _tick(self):
        if self._resta > 0:
            self.estado.setText(f"Volte para o jogo agora (Alt+Tab). Conferindo em {self._resta} s…")
            self._resta -= 1
            return
        self._t.stop()
        self.b_teste.setEnabled(True)
        fg = J.janela_em_primeiro_plano()
        excl = J.tela_cheia_exclusiva()
        no_jogo = bool(fg) and fg["exe"] not in ("widgetmonitor.exe", "python.exe", "pythonw.exe") and fg["tela_cheia"]
        if not fg or not no_jogo:
            msg = "Não encontrei o jogo em primeiro plano. Troque para ele (em tela cheia/sem bordas) e clique de novo."
        elif excl:
            msg = f"{fg['exe']} AINDA está em tela cheia exclusiva (o Windows confirma). Mude o modo de exibição do jogo e teste de novo."
        else:
            msg = (f"{fg['exe']} está em tela cheia sem bordas: o overlay passa a aparecer por cima dele. "
                   "Ele foi aberto agora (Ctrl+Alt+O alterna).")
            self.g.mostrar_agora()
            self.g.overlay.anexar(fg["hwnd"])
        import diag
        diag.log(f"assistente: teste pós-mudança de modo -> {msg}")
        self.estado.setText(msg)
