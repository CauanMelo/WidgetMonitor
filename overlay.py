"""Overlay de jogo: janela separada, transparente e sempre no topo (sem injeção em jogos).

Visual idêntico ao dos overlays de FPS de referência: sem painel de fundo, texto branco com contorno escuro, barras
quadradas sólidas (CPU laranja, GPU roxa, bateria verde), FPS grande, linha de frametime e rodapé em cinza.
Aparece sobre jogos em modo janela ou sem bordas (borderless). Não funciona sobre tela cheia EXCLUSIVA.
"""
from __future__ import annotations

import ctypes
import winreg

from ctypes import wintypes

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

import monitor as M

LARGURA = 330
PROPORCAO = 5 / 4  # altura / largura: o cartão é sempre 4:5 (retrato)
COR_CPU, COR_GPU, COR_BAT = (246, 164, 26), (176, 92, 232), (88, 196, 52)
COR_FPS = (186, 104, 255)
BRANCO = QColor(255, 255, 255)
SOMBRA = QColor(0, 0, 0, 235)


def nome_aparelho() -> str:
    for chave in ("SystemFamily", "SystemProductName"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as k:
                v = str(winreg.QueryValueEx(k, chave)[0]).strip()
            if v and v.lower() not in ("to be filled by o.e.m.", "default string", "system product name", "type1productconfigid"):
                return v
        except OSError:
            continue
    import platform
    return platform.node() or "Meu PC"


def _fonte(tam: float, peso=QFont.Bold) -> QFont:
    fam = "Bahnschrift" if "Bahnschrift" in QFontDatabase.families() else "Segoe UI Variable Display"
    f = QFont(fam)
    f.setPixelSize(int(tam * 1.33))
    f.setWeight(peso)
    return f


class Overlay(QWidget):
    _medindo = False  # True durante a passada que só mede a altura (nada é desenhado)

    def __init__(self, ctx, cfg: dict):
        super().__init__()
        self.ctx = ctx            # Widget principal: tema, unidade
        self.cfg = cfg            # cfg["overlay"]
        self.d: dict = {}
        self.fps: dict | None = None
        self.estado_fps = "parado"
        self.msg_fps = ""
        self.jogo: dict | None = None
        self.api = ""
        self.titulo = nome_aparelho()
        self._pix: QPixmap | None = None
        self._altura_medida = 0.0
        self.aviso_exclusiva = False
        self.editando = False       # modo 'arrastar para posicionar'
        self.ao_salvar = None       # callback chamado ao soltar o overlay numa nova posição
        self._arr = None            # estado do arrasto: (cursor físico inicial, posição física inicial)
        self.setWindowTitle("Overlay Monitor de Hardware")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._topo = QTimer(self)  # jogos disputam o "topo": reafirma de tempos em tempos, sem roubar foco
        self._topo.timeout.connect(self._reafirmar_topo)
        self._alvo = 0               # HWND do jogo ao qual o overlay está preso (janela "dona")
        self._ult_rect = None
        self._seguir_t = QTimer(self)
        self._seguir_t.timeout.connect(self._seguir)
        self.aplicar()

    # -- janela ----------------------------------------------------------
    def aplicar(self):
        f = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        if self.cfg["clique_atraves"] and not self.editando:
            f |= Qt.WindowTransparentForInput
        vis = self.isVisible()
        if getattr(self, "_f", None) != f:
            self._f = f
            self.setWindowFlags(f)
            if vis:
                self.show()
        self._redesenhar()

    def mostrar(self):
        if not self.isVisible():
            self.show()
            self._estilo_nativo()
        self._desfoque()
        self._topo.start(700)
        self._redesenhar()

    def ocultar(self):
        self._topo.stop()
        self.desanexar()
        self.hide()

    def alternar(self):
        self.ocultar() if self.isVisible() else self.mostrar()

    def _estilo_nativo(self):
        """Garante WS_EX_NOACTIVATE|TOOLWINDOW (não tira o foco do jogo nem aparece no Alt+Tab)."""
        try:
            hwnd = int(self.winId())
            u = ctypes.windll.user32
            ex = u.GetWindowLongW(hwnd, -20) | 0x08000000 | 0x80
            u.SetWindowLongW(hwnd, -20, ex)
        except Exception:
            pass

    def _desfoque(self):
        """Acrílico do Windows atrás do overlay (opcional). Sem cantos arredondados do DWM: o painel é quadrado."""
        try:
            hwnd = int(self.winId())

            class ACCENT(ctypes.Structure):
                _fields_ = [("estado", ctypes.c_int), ("flags", ctypes.c_int), ("cor", ctypes.c_uint), ("anim", ctypes.c_int)]

            class DADOS(ctypes.Structure):
                _fields_ = [("attr", ctypes.c_int), ("dados", ctypes.c_void_p), ("tam", ctypes.c_size_t)]

            a = ACCENT()
            fundo = self.ctx.tema()["fundo"]
            if self.cfg.get("desfoque") and self.cfg["opacidade"] > 0:
                a.estado = 4
                a.cor = (int(255 * self.cfg["opacidade"] / 100 * 0.8) << 24) | (fundo.blue() << 16) | (fundo.green() << 8) | fundo.red()
            d = DADOS(19, ctypes.cast(ctypes.pointer(a), ctypes.c_void_p), ctypes.sizeof(a))
            ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(d))
            reto = ctypes.c_int(1)  # DWMWCP_DONOTROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(reto), 4)
        except Exception:
            pass

    # -- preso à janela do jogo ---------------------------------------------
    def anexar(self, hwnd_jogo: int):
        """Prende o overlay à janela do jogo: ela vira a "dona" (owner) do overlay, que passa a ficar SEMPRE logo acima
        dela na ordem das janelas e a acompanhar sua posição/tamanho. Só relação entre janelas: nada é injetado no jogo."""
        if not hwnd_jogo:
            return
        try:
            u = ctypes.windll.user32
            u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            u.SetWindowLongPtrW.restype = ctypes.c_void_p
            self._alvo = int(hwnd_jogo)
            u.SetWindowLongPtrW(int(self.winId()), -8, self._alvo)  # GWLP_HWNDPARENT
            self._ult_rect = None
            self._seguir_t.start(250)
            self._seguir()
        except Exception:
            self._alvo = 0

    def desanexar(self):
        self._seguir_t.stop()
        if self._alvo:
            try:
                u = ctypes.windll.user32
                u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                u.SetWindowLongPtrW(int(self.winId()), -8, None)
            except Exception:
                pass
        self._alvo, self._ult_rect = 0, None

    def _seguir(self):
        """Posiciona o overlay no canto escolhido DA JANELA DO JOGO (e acompanha se ela mover/redimensionar)."""
        u = ctypes.windll.user32
        if not self._alvo or not u.IsWindow(self._alvo):
            self.desanexar()
            return
        rc = wintypes.RECT()
        if not u.GetWindowRect(self._alvo, ctypes.byref(rc)):
            return
        chave = (rc.left, rc.top, rc.right, rc.bottom, self.width(), self.height())
        if chave == self._ult_rect:
            return
        self._ult_rect = chave
        dpr = self.devicePixelRatioF()
        mx, my = int(self.cfg["margem_x"] * dpr), int(self.cfg["margem_y"] * dpr)
        w, h = int(self.width() * dpr), int(self.height() * dpr)
        x = rc.left + mx if "esq" in self.cfg["canto"] else rc.right - w - mx
        y = rc.top + my if "sup" in self.cfg["canto"] else rc.bottom - h - my
        u.SetWindowPos(int(self.winId()), 0, int(x), int(y), 0, 0, 0x0001 | 0x0004 | 0x0010)  # NOSIZE|NOZORDER|NOACTIVATE

    def _reafirmar_topo(self):
        """HWND_TOPMOST + NOACTIVATE: repetido, porque jogos/launchers disputam o topo ao mudar o primeiro plano.
        (Preso ao jogo, o overlay também é 'dependente' da janela dele, o que reforça a ordem.)"""
        try:
            ctypes.windll.user32.SetWindowPos(int(self.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
        except Exception:
            pass

    def _posicionar(self):
        if self._alvo:
            self._ult_rect = None
            self._seguir()
            return
        telas = QApplication.screens()
        t = telas[min(self.cfg["monitor"], len(telas) - 1)].availableGeometry()
        mx, my = self.cfg["margem_x"], self.cfg["margem_y"]
        x = t.left() + mx if "esq" in self.cfg["canto"] else t.right() - self.width() - mx
        y = t.top() + my if "sup" in self.cfg["canto"] else t.bottom() - self.height() - my
        self.move(int(x), int(y))

    # -- dados -----------------------------------------------------------
    def atualizar(self, d: dict, fps: dict | None, estado_fps: str, msg_fps: str, jogo: dict | None, api: str):
        self.d, self.fps, self.estado_fps, self.msg_fps, self.jogo, self.api = d, fps, estado_fps, msg_fps, jogo, api
        if self.isVisible():
            self._redesenhar()

    @property
    def esc(self) -> float:
        return self.cfg["escala"] / 100

    def _largura(self) -> int:
        return int(LARGURA * (0.72 if self.cfg["layout"] == "compacto" else 1.0))

    def _redesenhar(self):
        larg = self._largura()
        alvo = larg * PROPORCAO
        dpr = self.devicePixelRatioF()
        d, it = self.d, dict(self.cfg["itens"])
        compacto = self.cfg["layout"] == "compacto"
        if compacto:
            it.update(ram=False, grafico=False, rodape=False, media=False, low1=False, frametime=False)
        Overlay._medindo = True
        try:
            nat, n = self._conteudo(None, larg, it, d, compacto, 0.0)
        finally:
            Overlay._medindo = False
        util = alvo - 8
        escala_c, extra = 1.0, 0.0
        if nat > util:        # muita coisa ligada: reduz o conteúdo para caber em 4:5
            escala_c = util / nat
        else:                 # pouca coisa: reparte a sobra entre os blocos
            extra = (util - nat) / max(n - 1, 1)
        pm = QPixmap(int(larg * self.esc * dpr), int(alvo * self.esc * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.scale(self.esc, self.esc)
        op = self.cfg["opacidade"]
        if op > 0:  # painel translúcido quadrado atrás de tudo (0 = só texto, como a referência)
            fundo = QColor(*self.ctx.tema()["fundo"].getRgb()[:3])
            fundo.setAlpha(int(255 * op / 100 * (0.25 if self.cfg.get("desfoque") else 1.0)))
            p.fillRect(QRectF(0, 0, larg, alvo), fundo)
            p.setPen(QPen(QColor(255, 255, 255, 28), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(0.5, 0.5, larg - 1, alvo - 1))
        p.translate(0, 4)
        p.scale(escala_c, escala_c)
        self._conteudo(p, larg / escala_c, it, d, compacto, extra)
        p.end()
        self._pix = pm
        tam = (int(larg * self.esc), int(alvo * self.esc))
        if self.size().width() != tam[0] or self.size().height() != tam[1]:
            self.setFixedSize(*tam)
            self._posicionar()
        self.update()

    def paintEvent(self, _):
        if self._pix is not None:
            p = QPainter(self)
            p.drawPixmap(0, 0, self._pix)
            if self.editando:  # moldura tracejada + instrução, só enquanto se reposiciona
                p.setRenderHint(QPainter.Antialiasing)
                p.setPen(QPen(QColor(255, 255, 255, 230), 2, Qt.DashLine))
                p.setBrush(QColor(0, 0, 0, 70))
                p.drawRect(self.rect().adjusted(1, 1, -2, -2))
                p.setPen(QColor(255, 255, 255))
                p.setFont(_fonte(8))
                p.drawText(self.rect().adjusted(6, 0, -6, -4), Qt.AlignBottom | Qt.AlignHCenter,
                           "ARRASTE PARA MOVER · DUPLO CLIQUE OU ATALHO PARA CONCLUIR")

    # -- reposicionar arrastando ---------------------------------------------
    def editar(self, ligar: bool):
        """Liga/desliga o modo de arrastar. Ligado, o overlay deixa de ser clique-através (sem roubar o foco do jogo)."""
        self.editando = ligar
        self.setCursor(Qt.SizeAllCursor if ligar else Qt.ArrowCursor)
        self._f = None
        self.aplicar()
        if self.isVisible():
            self.show()
            self._estilo_nativo()
            self._reafirmar_topo()
        self.update()

    def _fisico(self, ev) -> tuple[int, int]:
        dpr = self.devicePixelRatioF()
        g = ev.globalPosition()
        return int(g.x() * dpr), int(g.y() * dpr)

    def _rect_fisico(self):
        rc = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(int(self.winId()), ctypes.byref(rc))
        return rc

    def mousePressEvent(self, ev):
        if self.editando and ev.button() == Qt.LeftButton:
            rc = self._rect_fisico()
            self._arr = (self._fisico(ev), (rc.left, rc.top))

    def mouseMoveEvent(self, ev):
        if self.editando and self._arr:
            (cx0, cy0), (x0, y0) = self._arr
            cx, cy = self._fisico(ev)
            ctypes.windll.user32.SetWindowPos(int(self.winId()), 0, x0 + cx - cx0, y0 + cy - cy0, 0, 0, 0x0001 | 0x0004 | 0x0010)

    def mouseReleaseEvent(self, ev):
        if self.editando and self._arr:
            self._arr = None
            self._gravar_posicao()

    def mouseDoubleClickEvent(self, ev):
        if self.editando and self.ao_salvar:
            self.ao_salvar("concluir")

    def _gravar_posicao(self):
        """Converte a posição solta em canto + margens (em relação à janela do jogo ou ao monitor) e grava na configuração."""
        u = ctypes.windll.user32
        r = self._rect_fisico()
        ref = wintypes.RECT()
        if self._alvo and u.IsWindow(self._alvo):
            u.GetWindowRect(self._alvo, ctypes.byref(ref))
            mon = None
        else:
            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
            u.MonitorFromWindow.restype = wintypes.HANDLE
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(mi)
            u.GetMonitorInfoW(u.MonitorFromWindow(int(self.winId()), 2), ctypes.byref(mi))
            ref = mi.rcWork
            # índice do monitor escolhido (o que contém o centro do overlay)
            cx, cy = (r.left + r.right) / 2, (r.top + r.bottom) / 2
            dpr = self.devicePixelRatioF()
            mon = next((i for i, t in enumerate(QApplication.screens())
                        if t.geometry().contains(int(cx / dpr), int(cy / dpr))), self.cfg["monitor"])
        dpr = self.devicePixelRatioF()
        esq = (r.left + r.right) / 2 < (ref.left + ref.right) / 2
        sup = (r.top + r.bottom) / 2 < (ref.top + ref.bottom) / 2
        mx = (r.left - ref.left) if esq else (ref.right - r.right)
        my = (r.top - ref.top) if sup else (ref.bottom - r.bottom)
        self.cfg.update(canto=("sup" if sup else "inf") + "_" + ("esq" if esq else "dir"),
                        margem_x=max(0, int(mx / dpr)), margem_y=max(0, int(my / dpr)))
        if mon is not None:
            self.cfg["monitor"] = mon
        self._ult_rect = None
        if self.ao_salvar:
            self.ao_salvar("salvar")

    # -- primitivas ------------------------------------------------------
    def _t(self, c: float) -> str:
        return f"{c * 9 / 5 + 32:.0f} °F" if self.ctx.cfg["unidade"] == "F" else f"{c:.0f} °C"

    @staticmethod
    def _texto(q: QPainter, x: float, y_base: float, txt: str, fonte: QFont, cor=BRANCO, alinhar="e", largura=0.0) -> float:
        """Texto com contorno escuro (legível sobre qualquer cena do jogo). alinhar: e/d/c dentro de `largura`."""
        w = QFontMetricsF(fonte).horizontalAdvance(txt)
        if alinhar == "d":
            x = x + largura - w
        elif alinhar == "c":
            x = x + (largura - w) / 2
        if Overlay._medindo:
            return w
        q.setFont(fonte)
        q.setPen(SOMBRA)
        for dx, dy in ((-1.3, 0), (1.3, 0), (0, -1.3), (0, 1.3), (-1, -1), (1, 1)):
            q.drawText(QPointF(x + dx, y_base + dy), txt)
        q.setPen(cor)
        q.drawText(QPointF(x, y_base), txt)
        return w

    def _barra(self, q, x, y, w, h, pct, cor, nome, valor, f_nome, f_valor):
        """Barra sólida quadrada (sem trilho): preenche até o % e leva o nome por cima; o valor fica na ponta direita."""
        pct = max(0.0, min(pct, 100.0))
        if Overlay._medindo:
            return
        q.setPen(Qt.NoPen)
        q.setBrush(QColor(*cor))
        q.drawRect(QRectF(x, y, max(w * pct / 100, 3), h))
        base = y + h / 2 + QFontMetricsF(f_nome).ascent() / 2 - 1
        self._texto(q, x + 6, base, nome, f_nome)
        if valor:
            base_v = y + h / 2 + QFontMetricsF(f_valor).ascent() / 2 - 1
            self._texto(q, x, base_v, valor, f_valor, alinhar="d", largura=w)

    def _grafico(self, q, x, y, w, h, serie):
        if Overlay._medindo or not serie or len(serie) < 2:
            return
        topo = max(max(serie), 16.7) * 1.2
        caminho = QPainterPath()
        for i, v in enumerate(serie):
            px = x + w * i / (len(serie) - 1)
            py = y + h - h * min(v, topo) / topo
            (caminho.moveTo if i == 0 else caminho.lineTo)(px, py)
        q.setBrush(Qt.NoBrush)
        q.strokePath(caminho, QPen(SOMBRA, 3.0))
        q.strokePath(caminho, QPen(BRANCO, 1.4))

    def _stats(self, q, x, y, w, partes, fonte) -> float:
        """Temperatura, clock e potência espalhados na linha, como na referência."""
        partes = [t for t in partes if t]
        if not partes:
            return y + 2
        col = w / len(partes)
        for i, t in enumerate(partes):
            self._texto(q, x + i * col, y + 17, t, fonte, alinhar="e", largura=col)
        return y + 24

    # -- conteúdo --------------------------------------------------------
    def _conteudo(self, p, larg, it, d, compacto, extra=0.0):
        """Desenha (p != None) ou apenas mede (p == None). Devolve (y final, nº de blocos).
        `extra` é somado entre os blocos para o cartão preencher a proporção 4:5."""
        dummy = QPixmap(2, 2)  # precisa viver até q.end(): senão o QPainter pinta num pixmap já destruído
        q = p or QPainter(dummy)
        x, w = 4.0, larg - 8.0
        f_titulo, f_fps, f_rot = _fonte(15), _fonte(30), _fonte(9)
        f_val, f_nome, f_peq, f_stats, f_rod = _fonte(11), _fonte(13), _fonte(8.5), _fonte(11), _fonte(8)
        y, n = 2.0, 0
        fps, estado = self.fps, self.estado_fps

        def fim_bloco():
            nonlocal y, n
            y += extra
            n += 1

        # título (nome do aparelho) centralizado
        if it.get("titulo", True):
            self._texto(q, x, y + 20, self.titulo.upper(), f_titulo, alinhar="c", largura=w)
            y += 28
            fim_bloco()
        if self.aviso_exclusiva:
            self._texto(q, x, y + 12, "TELA CHEIA EXCLUSIVA: USE JANELA SEM BORDAS", f_peq, QColor(*COR_CPU), alinhar="c", largura=w)
            y += 18

        # FPS grande + média / 1% low + frametime
        if it["fps"] or it["frametime"]:
            if fps:
                if it["fps"]:
                    wl = self._texto(q, x, y + 34, "FPS ", f_fps)
                    self._texto(q, x + wl, y + 34, f"{fps['fps']:.0f}", f_fps, QColor(*COR_FPS))
                if it["media"]:
                    self._texto(q, x + 168, y + 12, "MEDIA", f_rot)
                    self._texto(q, x + 212, y + 12, f"{fps['media']:.0f}", f_rot)
                if it["low1"]:
                    self._texto(q, x + 168, y + 28, "1% LOW", f_rot)
                    self._texto(q, x + 212, y + 28, f"{fps['low1']:.0f}", f_rot)
                if it["frametime"]:
                    self._texto(q, x, y + 22, f"{fps['frametime']:.1f} MS".replace(".", ","), f_val, alinhar="d", largura=w)
                y += 44
                if it["grafico"]:
                    self._grafico(q, x, y, w, 12, fps["historico"])
                    y += 18
                else:
                    y += 4
            else:
                rot = {"permissao": "FPS REQUER PERMISSAO", "indisponivel": "FPS INDISPONIVEL", "sem_dados": "FPS: SEM QUADROS (TELA CHEIA EXCLUSIVA?)",
                       "erro": "FPS: ERRO NO PRESENTMON", "iniciando": "FPS: INICIANDO…", "parado": "FPS: AGUARDANDO JOGO"}
                self._texto(q, x, y + 16, rot.get(estado, "FPS INDISPONIVEL"), f_peq, QColor(*COR_CPU), alinhar="c", largura=w)
                y += 24
            fim_bloco()

        gp = next((g for g in d.get("gpus", []) if g.get("dedicada")), None) or (d.get("gpus") or [None])[0]
        # CPU (temperatura só se for REAL: a zona térmica ACPI é estimativa do chassi e fica de fora)
        if it["cpu"] and "cpu_uso" in d:
            nome = (self.ctx.coletor.sensores.nome_cpu if self.ctx.coletor.sensores else "CPU").upper()
            self._barra(q, x, y, w, 30, d["cpu_uso"], COR_CPU, nome, f"{d['cpu_uso']:.0f}%", f_nome, f_nome)
            y += 34
            if it["ram"] and "ram_uso" in d:
                self._barra(q, x, y, w * 0.78, 20, d["ram_uso"], COR_CPU, f"{d['ram_usada']:.2f}/{d['ram_total']:.0f}GB RAM".replace(".", ","), "", f_peq, f_peq)
                self._texto(q, x, y + 14, f"{d['ram_uso']:.0f}%", f_peq, alinhar="d", largura=w)
                y += 25
            y = self._stats(q, x, y, w, [self._t(d["cpu_temp"]) if (it["temps"] and d.get("cpu_temp_real") and d.get("cpu_temp") is not None) else None,
                                         f"{d['cpu_mhz']:.0f} MHZ" if (it["clocks"] and d.get("cpu_mhz")) else None,
                                         f"{d['cpu_watts']:.0f} W" if (it["watts"] and d.get("cpu_watts") is not None) else None], f_stats)
            fim_bloco()
        elif it["ram"] and "ram_uso" in d:
            self._barra(q, x, y, w * 0.78, 20, d["ram_uso"], COR_CPU, f"{d['ram_usada']:.2f}/{d['ram_total']:.0f}GB RAM".replace(".", ","), "", f_peq, f_peq)
            y += 26
            fim_bloco()

        # GPU
        if it["gpu"] and gp and gp.get("uso") is not None:
            self._barra(q, x, y, w, 30, gp["uso"], COR_GPU, gp["nome"].upper(), f"{gp['uso']:.0f}%", f_nome, f_nome)
            y += 34
            if it["vram"] and gp.get("vram_usada") is not None:
                tot = gp.get("vram_total")
                pct = gp["vram_usada"] / tot * 100 if tot else 0
                rot = f"{gp['vram_usada']:.2f}/{tot:.0f}GB VRAM" if tot else f"{gp['vram_usada']:.2f}GB VRAM"
                self._barra(q, x, y, w * 0.78, 20, pct, COR_GPU, rot.replace(".", ","), "", f_peq, f_peq)
                if tot:
                    self._texto(q, x, y + 14, f"{pct:.0f}%", f_peq, alinhar="d", largura=w)
                y += 25
            y = self._stats(q, x, y, w, [self._t(gp["temp"]) if (it["temps"] and gp.get("temp") is not None) else None,
                                         f"{gp['mhz']:.0f} MHZ" if (it["clocks"] and gp.get("mhz")) else None,
                                         f"{gp['watts']:.0f} W" if (it["watts"] and gp.get("watts") is not None) else None], f_stats)
            fim_bloco()

        # bateria (só se existir)
        if it["bateria"] and d.get("bat_pct") is not None:
            if d.get("bat_resta") and not d.get("bat_ligada"):
                sec = int(d["bat_resta"])
                rot = f"BATERIA RESTANTE: {sec // 3600}H{(sec % 3600) // 60:02d}"
            else:
                rot = "BATERIA: CARREGANDO" if d.get("bat_ligada") else "BATERIA"
            self._barra(q, x, y, w, 30, d["bat_pct"], COR_BAT, rot, f"{d['bat_pct']:.0f}%", _fonte(10.5), f_nome)
            y += 36
            fim_bloco()

        if it["rede"] and "rede_down" in d:
            self._texto(q, x, y + 12, f"↓ {M.fmt_vel(d['rede_down'])}", f_stats)
            self._texto(q, x, y + 12, f"↑ {M.fmt_vel(d['rede_up'])}", f_stats, alinhar="d", largura=w)
            y += 20
        if it["ventoinhas"] and d.get("ventoinhas"):
            self._texto(q, x, y + 12, "  ".join(f"VENT {i + 1}: {f['rpm']:.0f} RPM" for i, f in enumerate(d["ventoinhas"][:3])), f_stats)
            y += 20

        if it["rodape"] and self.jogo:
            cinza = QColor(215, 215, 215)
            api = (self.api or "").upper()
            api = {"DXGI": "D3D12", "D3D9": "D3D9"}.get(api, api)
            self._texto(q, x, y + 12, f"{self.jogo['exe'].upper()} {api}".strip(), f_rod, cinza)
            watts = (d.get("cpu_watts") or 0) + ((gp or {}).get("watts") or 0)
            self._texto(q, x, y + 12, f"POWER: {watts:.0f}W" if watts else "POWER: W", f_rod, cinza, "d", w)
            y += 14
            self._texto(q, x, y + 12, f"RESOLUCAO: {self.jogo['larg']}x{self.jogo['alt']}", f_rod, cinza)
            if gp and gp.get("driver"):
                self._texto(q, x, y + 12, f"DRIVER {gp['driver']}", f_rod, cinza, "d", w)
            y += 14
            fim_bloco()
        if p is None:
            q.end()
        return y, n
