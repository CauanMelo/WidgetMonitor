"""Widget de desktop com o estado do hardware — Galaxy Book 3 Ultra (Windows 11).

Sem barra de título nem botão na barra de tarefas; tudo se configura com o botão direito.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import re
import subprocess
import threading
import winreg
from collections import deque
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QBrush, QColor, QCursor, QFont, QIcon, QImage, QLinearGradient, QPainter, QFontMetricsF, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from sensores import Sensores, eh_admin

NOME = "WidgetMonitor"


def _versao() -> str:
    for base in (Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parent):
        try:
            return (base / "VERSION").read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
    return "dev"


VERSAO = _versao()
CONFIG = Path(os.environ.get("APPDATA", Path.home())) / NOME / "config.json"
ATALHO = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup" / f"{NOME}.lnk"
LARG = 252  # largura lógica (antes da escala)
M = 8  # margem externa
HIST = 60

PADRAO = {
    "mostrar": {"cpu": True, "gpu": True, "fans": True, "igpu": True, "ram": True, "disco": True, "rede": True, "bateria": True},
    "escala": 100, "opacidade": 90, "tema": "auto", "destaque": "Auto", "intervalo": 2.0,
    "unidade": "C", "travar": False, "topo": False, "vidro": True, "bordas": False, "graficos": False, "animar": True, "web": {"ativo": False, "porta": 8765, "token": ""}, "estilo": "quadrado", "fundo_cards": False, "posicao": {"canto": "sup_dir", "margem_x": 24, "margem_y": 24, "monitor": 0},
    "alerta": {"ativo": True, "cpu": 90, "gpu": 85},
    "jogo": {"auto_detectar": True, "limiar_gpu3d": 2, "jogos": [], "ignorar": [], "log": True, "overlay_auto": True, "perfil_auto": False},
    "atalhos": {"overlay": "Ctrl+Alt+O", "widget": "Ctrl+Alt+W", "ajustes": "Ctrl+Alt+M", "posicao": "Ctrl+Alt+P"},
    "perfil": "Desktop", "perfis": {},
    "rtss": {"fps": False},   # incluir FPS/frametime (lidos do próprio RTSS) no texto enviado a ele
    "overlay": {
        "ativo": True, "canto": "sup_esq", "margem_x": 20, "margem_y": 20, "monitor": 0, "escala": 100, "opacidade": 45, "desfoque": False,
        "layout": "completo", "clique_atraves": True, "estilo": "quadrado", "preso_ao_jogo": True, "v": 5,
        "modo": "janela",   # janela | rtss | auto (RTSS quando o jogo está em tela cheia exclusiva e o RTSS roda)
        "itens": {"titulo": True, "fps": True, "media": True, "low1": True, "frametime": True, "grafico": True, "cpu": True, "ram": True,
                  "gpu": True, "vram": True, "temps": True, "clocks": True, "watts": True, "bateria": True,
                  "rede": False, "ventoinhas": False, "rodape": False},
    },
}
DESTAQUES = {
    "Azul": (96, 165, 250), "Roxo": (167, 139, 250), "Verde": (52, 211, 153),
    "Rosa": (244, 114, 182), "Laranja": (251, 146, 60), "Ciano": (34, 211, 238),
}
TEMAS = {
    "escuro": dict(fundo=(28, 30, 36), card=(255, 255, 255, 15), texto=(240, 243, 250), suave=(160, 168, 188), trilho=(255, 255, 255, 34), borda=(255, 255, 255, 36)),
    "claro": dict(fundo=(247, 248, 251), card=(0, 0, 0, 10), texto=(20, 24, 36), suave=(84, 92, 110), trilho=(0, 0, 0, 30), borda=(0, 0, 0, 30)),
}
RAIO_JANELA = 8  # raio dos cantos que o DWM aplica nas janelas do Windows 11 (em px lógicos do sistema, não escala com o widget)
RAIO_CARD = 10
CLARO = False  # tema efetivo; escurece as cores semânticas para manter contraste no claro


def _lum(c) -> float:
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def razao_contraste(a, b) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def ajustar_contraste(cor, fundo, minimo=3.0):
    """Clareia ou escurece a cor até ter contraste suficiente com o fundo."""
    c = tuple(cor)
    alvo = (255, 255, 255) if _lum(fundo) < 0.4 else (0, 0, 0)
    for i in range(12):
        if razao_contraste(c, fundo) >= minimo:
            break
        c = _lerp(c, alvo, 0.12)
    return c


def sistema_windows() -> tuple[str, tuple]:
    """Tema (claro/escuro) e cor de destaque definidos no Windows."""
    tema, cor = "escuro", DESTAQUES["Azul"]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            tema = "claro" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "escuro"
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\DWM") as k:
            try:
                v = winreg.QueryValueEx(k, "AccentColor")[0] & 0xFFFFFFFF  # 0xAABBGGRR
                cor = (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
            except OSError:
                v = winreg.QueryValueEx(k, "ColorizationColor")[0] & 0xFFFFFFFF  # 0xAARRGGBB
                cor = ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
    except OSError:
        pass
    return tema, cor
ROTULOS = {"cpu": "CPU", "gpu": "GPU NVIDIA", "fans": "Ventoinhas", "igpu": "GPU Intel", "ram": "Memória RAM", "disco": "Disco", "rede": "Rede", "bateria": "Bateria"}
VERDE, AMBAR, VERMELHO = (74, 222, 128), (251, 191, 36), (248, 90, 90)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def cor_escala(v: float, baixo: float, medio: float, alto: float) -> QColor:
    """Verde → âmbar → vermelho de forma contínua."""
    if v <= baixo:
        c = VERDE
    elif v <= medio:
        c = _lerp(VERDE, AMBAR, (v - baixo) / (medio - baixo))
    elif v <= alto:
        c = _lerp(AMBAR, VERMELHO, (v - medio) / (alto - medio))
    else:
        c = VERMELHO
    if CLARO:
        c = _lerp(c, (0, 0, 0), 0.38)
    return QColor(*c)


def cor_carga(p: float) -> QColor:
    return cor_escala(p, 50, 75, 95)


def cor_temp(t: float) -> QColor:
    return cor_escala(t, 50, 72, 92)


def fmt_vel(b: float) -> str:
    b = max(b, 0)
    for un in ("B/s", "KB/s", "MB/s", "GB/s"):
        if b < 1024 or un == "GB/s":
            return f"{b:.0f} {un}" if un == "B/s" else f"{b:.1f} {un}"
        b /= 1024
    return ""


def _mesclar(base: dict, novo: dict):
    for k, v in novo.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict) and k != "perfis":
            _mesclar(base[k], v)
        else:
            base[k] = v


def carregar_cfg() -> dict:
    cfg = json.loads(json.dumps(PADRAO))
    try:
        _mesclar(cfg, json.loads(CONFIG.read_text(encoding="utf-8")))
    except Exception:
        pass
    if cfg["overlay"].get("v", 0) < 5:  # desenho completo em 4:5, sem o rodapé (app, resolução, power, driver)
        cfg["overlay"]["itens"] = dict(PADRAO["overlay"]["itens"])
        cfg["overlay"]["v"] = 5
    if cfg["overlay"].get("opacidade") in (0, 80):  # padrões antigos (sem painel / painel escuro demais) -> translúcido
        cfg["overlay"]["opacidade"] = 45
    if cfg.get("intervalo") == 1.0 and not cfg.get("_intervalo_migrado"):  # leve por padrão: 2 s (o usuário pode voltar a 1 s no menu)
        cfg["intervalo"], cfg["_intervalo_migrado"] = 2.0, True
    if cfg["jogo"].get("limiar_gpu3d") == 15:  # padrão antigo (2.2.0) alto demais: menus/lobbies de jogos ficavam abaixo dele
        cfg["jogo"]["limiar_gpu3d"] = 2
    return cfg


def salvar_cfg(c: dict):
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(c, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- ícones
def _stroke(p: QPainter, cor: QColor, w=1.6):
    p.setPen(QPen(cor, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)


def icone_desenho(p: QPainter, nome: str, x: float, y: float, tam: float, cor: QColor):
    """Ícones vetoriais desenhados numa grade 20x20."""
    p.save()
    p.translate(x, y)
    p.scale(tam / 20, tam / 20)
    _stroke(p, cor)
    L = lambda a, b, c, d: p.drawLine(QPointF(a, b), QPointF(c, d))
    R = lambda a, b, c, d, r=2: p.drawRoundedRect(QRectF(a, b, c, d), r, r)
    if nome == "cpu":
        R(5, 5, 10, 10)
        R(8, 8, 4, 4, 1)
        for v in (8, 12):
            L(v, 2.5, v, 5); L(v, 15, v, 17.5); L(2.5, v, 5, v); L(15, v, 17.5, v)
    elif nome == "gpu":
        R(2, 5, 16, 10)
        p.drawEllipse(QPointF(9, 10), 3, 3)
        L(14, 8, 16, 8); L(14, 12, 16, 12)
        L(4, 15, 4, 17)
    elif nome == "igpu":
        R(2, 4, 16, 10)
        L(7, 17, 13, 17); L(10, 14, 10, 17)
    elif nome == "ram":
        R(2, 6, 16, 8, 1.5)
        for cx in (5, 9, 13):
            R(cx, 8.5, 2, 3, 0.5)
        for cx in (5, 8, 12, 15):
            L(cx, 14, cx, 16.5)
    elif nome == "disco":
        R(3, 3.5, 14, 13, 3)
        L(3, 12, 17, 12)
        p.drawPoint(QPointF(14, 14.4))
    elif nome == "rede":
        L(7, 16, 7, 4); L(7, 4, 4, 7); L(7, 4, 10, 7)
        L(13, 4, 13, 16); L(13, 16, 10, 13); L(13, 16, 16, 13)
    elif nome == "bateria":
        R(2, 6, 14, 8, 2)
        R(16.5, 8.5, 1.5, 3, 0.5)
    elif nome == "bolt":
        path = QPainterPath(QPointF(11, 3)); path.lineTo(5.5, 11); path.lineTo(10, 11); path.lineTo(9, 17); path.lineTo(14.5, 8.5); path.lineTo(10, 8.5); path.closeSubpath()
        p.drawPath(path)
    elif nome == "termo":
        R(8.3, 2.5, 3.4, 10, 1.7)
        p.drawEllipse(QPointF(10, 14.5), 3, 3)
        L(10, 6, 10, 14)
    p.restore()


_SVG = {"base": None, "rotor": None}
_SVG_CACHE: dict = {}


def _carregar_svg():
    """Separa o SVG fornecido em moldura (fixa) e rotor (8 pás + cubo, que gira)."""
    if _SVG["base"] is not None:
        return
    arq = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "ventoinha.svg"
    txt = arq.read_text(encoding="utf-8")
    caminhos = re.findall(r"<path\b[^>]*>(?:</path>)?", txt)
    pas_e_cubo = [c for i, c in enumerate(caminhos) if i <= 7 or i == 11]
    moldura = [c for i, c in enumerate(caminhos) if i in (8, 9, 10)]
    _SVG["rotor"], _SVG["base"] = pas_e_cubo, moldura


def _pixmap(partes: list[str], cor: QColor, px: int) -> QPixmap:
    chave = (id(partes), cor.name(), px)
    pm = _SVG_CACHE.get(chave)
    if pm is None:
        corpo = "".join(re.sub(r'style="[^"]*"', "", re.sub(r'class="[^"]*"', "", c)).replace("<path", f'<path fill="{cor.name()}"', 1) for c in partes)
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">{corpo}</svg>'
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        QSvgRenderer(svg.encode("utf-8")).render(q)
        q.end()
        _SVG_CACHE.clear() if len(_SVG_CACHE) > 24 else None
        _SVG_CACHE[chave] = pm
    return pm


def icone_ventoinha(p: QPainter, cx: float, cy: float, r: float, angulo: float, cor: QColor, escala_fisica: float = 1.0):
    """Ventoinha de gabinete (SVG do usuário) recolorida; só as pás e o cubo giram. Usa pixmaps em cache."""
    _carregar_svg()
    px = max(int(r * 2 * escala_fisica), 8)
    alvo = QRectF(-r, -r, r * 2, r * 2)
    p.save()
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.translate(cx, cy)
    base = _pixmap(_SVG["base"], cor, px)
    p.drawPixmap(alvo, base, QRectF(base.rect()))
    p.rotate(angulo)
    rot = _pixmap(_SVG["rotor"], cor, px)
    p.drawPixmap(alvo, rot, QRectF(rot.rect()))
    p.restore()


def icone_app() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(96, 165, 250))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    icone_desenho(p, "cpu", 12, 12, 40, QColor(16, 18, 26))
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- coleta
class Coletor(QObject):
    """Lê os sensores numa thread própria, para a interface nunca travar."""
    novo = Signal(dict)

    def __init__(self, intervalo: float = 1.0):
        super().__init__()
        self.intervalo = intervalo
        self.parar = threading.Event()
        self.pausa = threading.Event()
        self.sensores: Sensores | None = None
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        self.sensores = Sensores()
        while not self.parar.wait(self.intervalo):
            if self.pausa.is_set():
                continue
            try:
                self.novo.emit(self.sensores.ler())
            except Exception:
                pass
        self.sensores.fechar()


# ---------------------------------------------------------------- widget
class Widget(QWidget):
    def __init__(self, coletor: Coletor, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.coletor = coletor
        self.d: dict = {}
        self.h = {k: deque([0.0] * HIST, maxlen=HIST) for k in ("cpu", "cpu_t", "gpu", "gpu_t")}
        self.tray = None
        self._alertado: dict[str, float] = {}
        self._arrasto = None
        self._h_logica = 400
        self._ang = [0.0, 0.0]
        self._fan = []  # [{"rot": texto, "frac": 0..1}]
        self._fan_real = False
        self._rect_fans = None
        self._sis = sistema_windows()
        self._tz = QTimer(self)  # garante o 'só na área de trabalho' mesmo se outro programa mexer na ordem das janelas
        self._tz.timeout.connect(self._afundar)
        self._tz.start(1500)
        self._cache = None  # quadro estático (tudo menos as hélices); refeito a cada leitura/mudança
        self._fan_pos = []
        self._rel = QElapsedTimer()
        self._anim = QTimer(self)
        self._anim.setInterval(80)
        self._anim.timeout.connect(self._passo_anim)
        self.setWindowTitle("Monitor de Hardware")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.f_t = QFont("Segoe UI Variable Display", 9, QFont.Medium)
        self.f_n = QFont("Segoe UI Variable Text", 9)
        self.f_p = QFont("Segoe UI Variable Text", 7)
        self.f_g = QFont("Segoe UI Variable Display", 11, QFont.Medium)
        self.f_r = QFont("Segoe UI Variable Display", 8, QFont.Medium)
        coletor.novo.connect(self.atualizar)
        self.aplicar(recriar=True)
        if "x" in cfg and "y" in cfg and self._visivel(cfg["x"], cfg["y"]):
            self.move(cfg["x"], cfg["y"])
        else:
            tela = QApplication.primaryScreen().availableGeometry()
            self.move(tela.right() - self.width() - 24, tela.top() + 24)

    def R(self, v: float) -> float:
        """Raio de canto: 0 no estilo quadrado."""
        return 0.0 if self.cfg["estilo"] == "quadrado" else v

    def posicionar(self):
        """Coloca o widget no canto/monitor escolhidos nos ajustes e grava a posição."""
        c = self.cfg["posicao"]
        telas = QApplication.screens()
        t = telas[min(c["monitor"], len(telas) - 1)].availableGeometry()
        x = t.left() + c["margem_x"] if "esq" in c["canto"] else t.right() - self.width() - c["margem_x"]
        y = t.top() + c["margem_y"] if "sup" in c["canto"] else t.bottom() - self.height() - c["margem_y"]
        self.move(int(x), int(y))
        self.cfg.update(x=self.x(), y=self.y())
        salvar_cfg(self.cfg)

    def _visivel(self, x: int, y: int) -> bool:
        """A posição salva ainda cai dentro de algum monitor? (ex.: monitor externo desconectado)"""
        return any(t.availableGeometry().adjusted(-8, -8, 8, 8).contains(x + 30, y + 30) for t in QApplication.screens())

    # -- aplicar configuração na hora ------------------------------------
    @property
    def esc(self) -> float:
        return self.cfg["escala"] / 100

    def nome_tema(self) -> str:
        t = self.cfg["tema"]
        return self._sis[0] if t == "auto" else ("claro" if t == "claro" else "escuro")

    def tema(self) -> dict:
        global CLARO
        nome = self.nome_tema()
        CLARO = nome == "claro"
        return {k: QColor(*v) for k, v in TEMAS[nome].items()}

    def destaque(self) -> QColor:
        d = self.cfg["destaque"]
        base = self._sis[1] if d == "Auto" else DESTAQUES.get(d, DESTAQUES["Azul"])
        return QColor(*ajustar_contraste(base, TEMAS[self.nome_tema()]["fundo"], 4.5))

    def verificar_sistema(self):
        """Relê tema/cor do Windows; se mudou, repinta na hora."""
        novo = sistema_windows()
        if novo != self._sis:
            self._sis = novo
            self._efeito_vidro()
            self._cache = None
            self.update()

    def aplicar(self, recriar=False):
        """Reaplica flags, tamanho e efeitos. Chamado após qualquer mudança de configuração."""
        vis = self.isVisible()
        f = Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint
        if self.cfg["topo"]:
            f |= Qt.WindowStaysOnTopHint  # senão: fica só na área de trabalho (ver _afundar)
        if recriar or getattr(self, "_flags", None) != f:
            self._flags = f
            self.setWindowFlags(f)
            if vis:
                self.show()
        self.coletor.intervalo = float(self.cfg["intervalo"])
        self._cache = None
        self._redimensionar()
        if self.isVisible():
            self._efeito_vidro()
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self._efeito_vidro()
        self._afundar()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.ActivationChange:
            self._afundar()  # clicar no widget não pode trazê-lo para cima das janelas

    def _afundar(self):
        """Modo área de trabalho: manda a janela para o FUNDO da pilha (HWND_BOTTOM) — abaixo de todas as outras janelas,
        visível só na área de trabalho — e garante que ela nunca esteja no grupo 'sempre no topo'.
        (Inserir 'logo acima do desktop' falhava: a barra de tarefas fica logo acima do Progman e herdar a posição dela
        tornava o widget topmost.)"""
        if self.cfg["topo"]:
            return
        try:
            u = ctypes.windll.user32
            hwnd = int(self.winId())
            if u.GetWindowLongW(hwnd, -20) & 0x8:  # WS_EX_TOPMOST
                u.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_NOTOPMOST
            u.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_BOTTOM
        except Exception:
            pass

    def _efeito_vidro(self):
        """Acrílico real do Windows (desfoca o que estiver atrás, janelas incluídas) com os cantos arredondados do DWM.
        Importante: NÃO desligar os cantos do DWM nem usar SetWindowRgn — com isso o acrílico vaza um retângulo."""
        try:
            hwnd = int(self.winId())

            class ACCENT(ctypes.Structure):
                _fields_ = [("estado", ctypes.c_int), ("flags", ctypes.c_int), ("cor", ctypes.c_uint), ("anim", ctypes.c_int)]

            class DADOS(ctypes.Structure):
                _fields_ = [("attr", ctypes.c_int), ("dados", ctypes.c_void_p), ("tam", ctypes.c_size_t)]

            fundo = self.tema()["fundo"]
            a = ACCENT()
            if self.cfg["vidro"]:
                a.estado = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
                alfa = int(255 * (0.15 + 0.45 * self.cfg["opacidade"] / 100))
                a.cor = (alfa << 24) | (fundo.blue() << 16) | (fundo.green() << 8) | fundo.red()
            else:
                a.estado = 0
            d = DADOS(19, ctypes.cast(ctypes.pointer(a), ctypes.c_void_p), ctypes.sizeof(a))
            ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(d))
            redondo = ctypes.c_int(1 if self.cfg["estilo"] == "quadrado" else 2)  # DWMWCP_DONOTROUND / ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(redondo), 4)
            sem_borda = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE: a borda é a nossa (brilho sutil)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(sem_borda), 4)
        except Exception:
            pass

    def _redimensionar(self):
        self.setFixedSize(int(LARG * self.esc), int(self._h_logica * self.esc))

    def atualizar(self, d: dict):
        try:
            self._atualizar(d)
        except Exception as e:  # um erro de leitura nunca pode congelar o widget
            import diag
            diag.log(f"ERRO em atualizar: {e!r}")
            self.update()

    def _atualizar(self, d: dict):
        self.d = d
        self._cache = None
        self._calc_fans(d)
        self.h["cpu"].append(d.get("cpu_uso", 0))
        self.h["cpu_t"].append(d.get("cpu_temp") or 0)
        gd = self._gpu_principal(d)
        self.h["gpu"].append((gd or {}).get("uso") or 0)
        self.h["gpu_t"].append((gd or {}).get("temp") or 0)
        self._checar_alertas(d, gd)
        if self.isVisible():
            self.update()

    @staticmethod
    def _gpu_principal(d: dict):
        gs = d.get("gpus") or []
        return next((g for g in gs if g.get("dedicada")), None) or (gs[0] if gs else None)

    def _checar_alertas(self, d: dict, gd):
        """Notificação (no máx. a cada 5 min por componente) quando a temperatura passa do limite."""
        a = self.cfg["alerta"]
        if not a["ativo"] or self.tray is None:
            return
        agora = __import__("time").monotonic()
        itens = []
        if d.get("cpu_temp_real") and d.get("cpu_temp") is not None:
            itens.append(("cpu", "CPU", d["cpu_temp"], a["cpu"]))
        if gd and gd.get("temp") is not None:
            itens.append(("gpu", "GPU", gd["temp"], a["gpu"]))
        for chave, nome, t, lim in itens:
            if t >= lim and agora - self._alertado.get(chave, -1e9) > 300:
                self._alertado[chave] = agora
                self.tray.showMessage("Temperatura alta", f"{nome} em {self.temp(t)} (limite {self.temp(lim)}).", QSystemTrayIcon.Warning, 8000)

    # -- ventoinhas ------------------------------------------------------
    RPM_MAX = 6000.0

    def _calc_fans(self, d: dict):
        """RPM real (LibreHardwareMonitor, só administrador) ou, se indisponível, nível ESTIMADO pela temperatura."""
        reais = d.get("ventoinhas") or []
        if reais:
            self._fan_real = True
            self._fan = [{"rot": f"{f['rpm']:.0f} rpm" if f["rpm"] > 0 else "parada", "frac": min(f["rpm"] / self.RPM_MAX, 1.0)}
                         for f in reais[:2]]
        elif not d.get("cpu_temp") and not any(g.get("temp") for g in d.get("gpus", [])) and not d.get("gpu_temp"):
            self._fan_real, self._fan = False, []
        else:
            self._fan_real = False
            t = max(d.get("cpu_temp") or 0, d.get("gpu_temp") or 0, *[g.get("temp") or 0 for g in d.get("gpus", [])])
            nivel = min(max((t - 55) / 30.0, 0.0), 1.0)  # <55 °C parada; 85 °C ou mais = máximo
            nivel = max(nivel, min(d.get("cpu_uso", 0), d.get("gpu_uso", 0) if "gpu_uso" in d else 0) / 150)
            txt = "parada" if nivel <= 0.01 else f"≈ {nivel * 100:.0f}%"
            self._fan = [{"rot": txt, "frac": nivel}] * 2
        quer = self.cfg["mostrar"].get("fans") and self.cfg.get("animar", True) and self.isVisible() and any(f["frac"] > 0 for f in self._fan)
        if quer and not self._anim.isActive():
            self._rel.start()
            self._anim.start()
        elif not quer and self._anim.isActive():
            self._anim.stop()

    def _passo_anim(self):
        dt = self._rel.restart() / 1000.0
        for i, f in enumerate(self._fan[:2]):
            self._ang[i] = (self._ang[i] + 900.0 * f["frac"] * dt) % 360  # velocidade proporcional ao RPM
        r = self._rect_fans
        if r is not None:
            e = self.esc
            self.update(QRect(int(r.x() * e), int(r.y() * e), int(r.width() * e) + 1, int(r.height() * e) + 1))

    def _fans(self, p, y, c, ac, d):
        if not self._fan:
            return 0  # sem RPM real e sem temperatura para estimar: não mostra nada (nunca inventa valor)
        alt = 46 if self._fan_real else 56
        rc = self._card(p, y, alt, c)
        self._rect_fans = QRectF(rc)
        metade = (rc.width() - 24) / 2
        for i, f in enumerate(self._fan[:2]):
            x0 = rc.x() + 12 + i * metade
            cor = QColor(ac) if f["frac"] > 0 else QColor(c["suave"])
            self._fan_pos.append((x0 + 14, y + 24, 12, i, cor))
            p.setFont(self.f_p)
            p.setPen(c["suave"])
            p.drawText(QPointF(x0 + 34, y + 20), f"Ventoinha {i + 1}")
            p.setFont(self.f_t)
            p.setPen(c["texto"])
            p.drawText(QPointF(x0 + 34, y + 34), f["rot"])
        if not self._fan_real:
            p.setFont(self.f_p)
            p.setPen(c["suave"])
            p.drawText(QRectF(rc.x() + 12, y + 41, rc.width() - 24, 12), Qt.AlignLeft | Qt.AlignVCenter,
                       "estimado pela temperatura · RPM indisponível")
        return alt

    # -- mouse -----------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.cfg["travar"]:
            self._arrasto = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._arrasto is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._arrasto)

    def mouseReleaseEvent(self, e):
        if self._arrasto is not None:
            self._arrasto = None
            self.cfg.update(x=self.x(), y=self.y())
            salvar_cfg(self.cfg)

    def contextMenuEvent(self, e):
        menu_contexto(self, self.mapToGlobal(e.pos())).exec(self.mapToGlobal(e.pos()))

    # -- unidades --------------------------------------------------------
    def temp(self, c: float) -> str:
        if self.cfg["unidade"] == "F":
            return f"{c * 9 / 5 + 32:.0f}°F"
        return f"{c:.0f}°C"

    # -- desenho ---------------------------------------------------------
    def paintEvent(self, _):
        dpr = self.devicePixelRatioF()
        if self._cache is None or self._cache.size() != self.size() * dpr:
            pm = QPixmap(self.size() * dpr)
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            q.scale(self.esc, self.esc)
            self._fan_pos = []
            fim = self._desenhar(q)
            q.end()
            self._cache = pm
            alvo = int(fim + M)
            if alvo != self._h_logica:
                self._h_logica = alvo
                self._cache = None
                QTimer.singleShot(0, self._redimensionar)
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        if self._cache is not None:
            p.drawPixmap(0, 0, self._cache)
        p.scale(self.esc, self.esc)
        for cx, cy, r, i, cor in self._fan_pos:  # hélices desenhadas ao vivo sobre o quadro
            icone_ventoinha(p, cx, cy, r, self._ang[i], cor, self.esc * dpr)
        p.end()

    def _desenhar(self, p: QPainter) -> float:
        c = self.tema()
        ac = self.destaque()
        d = self.d
        vidro = self.cfg["vidro"]
        escuro = self.nome_tema() == "escuro"
        fundo = QColor(c["fundo"])
        # com vidro, o desfoque e a tinta vêm do acrílico do Windows; aqui só uma película leve
        fundo.setAlpha(int(255 * (0.10 if vidro else self.cfg["opacidade"] / 100)))
        r = QRectF(0.5, 0.5, LARG - 1, self._h_logica - 1)
        p.setBrush(fundo)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(r, self.R(RAIO_JANELA) / self.esc, self.R(RAIO_JANELA) / self.esc)
        # borda única, seguindo exatamente o recorte da janela, com brilho sutil no canto superior esquerdo
        if self.cfg["bordas"]:
            g = QLinearGradient(0, 0, LARG, self._h_logica)
            g.setColorAt(0, QColor(255, 255, 255, 120 if escuro else 230))
            g.setColorAt(0.5, QColor(255, 255, 255, 28 if escuro else 90) if vidro else c["borda"])
            g.setColorAt(1, QColor(255, 255, 255, 60 if escuro else 160) if vidro else c["borda"])
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QBrush(g), 1))
            p.drawRoundedRect(r, self.R(RAIO_JANELA) / self.esc, self.R(RAIO_JANELA) / self.esc)

        y = M
        self._rect_fans = None
        mostrar = self.cfg["mostrar"]
        if not d:
            p.setFont(self.f_n)
            p.setPen(c["suave"])
            p.drawText(QPointF(M + 8, y + 28), "Lendo sensores…")
            return y + 44
        n = 0
        for chave, fn in (("cpu", self._cpu), ("gpu", self._gpu), ("fans", self._fans), ("igpu", self._igpu), ("ram", self._ram),
                          ("disco", self._disco), ("rede", self._rede), ("bateria", self._bateria)):
            if not mostrar.get(chave):
                continue
            ret = fn(p, y, c, ac, d)
            if ret:
                y += ret + 4
                n += 1
        if n == 0:
            p.setFont(self.f_n)
            p.setPen(c["suave"])
            p.drawText(QPointF(M + 8, y + 28), "Nenhuma métrica ativa (botão direito)")
            y += 44
        return y - 4 if n else y

    # -- peças comuns ----------------------------------------------------
    def _card(self, p, y, h, c):
        rc = QRectF(M, y, LARG - 2 * M, h)
        raio = self.R(RAIO_CARD)
        if self.cfg["fundo_cards"]:
            p.setPen(Qt.NoPen)
            p.setBrush(c["card"])
            p.drawRoundedRect(rc, raio, raio)
        elif y > M + 1:  # sem fundo: uma divisória fina separa os blocos
            lin = QColor(c["texto"])
            lin.setAlpha(26)
            p.setPen(QPen(lin, 1))
            p.drawLine(QPointF(rc.left() + 2, y - 2.5), QPointF(rc.right() - 2, y - 2.5))
        return rc

    def _tile(self, p, rc, y_off, icone, cor, tam=34):
        t = QRectF(rc.x() + 10, rc.y() + y_off, tam, tam)
        fundo = QColor(cor)
        fundo.setAlpha(38)
        p.setPen(Qt.NoPen)
        p.setBrush(fundo)
        p.drawRoundedRect(t, self.R(8), self.R(8))
        ic = tam * 0.58
        icone_desenho(p, icone, t.x() + (tam - ic) / 2, t.y() + (tam - ic) / 2, ic, cor)

    def _titulo(self, p, x, y, texto, sub, c, largura=None):
        p.setFont(self.f_t)
        p.setPen(c["texto"])
        if largura:  # nome comprido: corta com reticências em vez de estourar o bloco
            texto = QFontMetricsF(self.f_t).elidedText(texto, Qt.ElideRight, largura)
        p.drawText(QPointF(x, y), texto)
        p.setFont(self.f_p)
        p.setPen(c["suave"])
        p.drawText(QPointF(x, y + 14), sub)

    def _anel(self, p, cx, cy, raio, pct, cor, c, texto=None):
        pct = max(0.0, min(pct, 100.0))
        box = QRectF(cx - raio, cy - raio, raio * 2, raio * 2)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(c["trilho"], 4, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(box)
        if pct > 0:
            p.setPen(QPen(cor, 4, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(box, 90 * 16, int(-pct * 3.6 * 16))
        p.setFont(self.f_r)
        p.setPen(c["texto"])
        p.drawText(box, Qt.AlignCenter, texto if texto is not None else f"{pct:.0f}%")

    def _barra(self, p, x, y, w, pct, cor, c, h=5):
        pct = max(0.0, min(pct, 100.0))
        p.setPen(Qt.NoPen)
        p.setBrush(c["trilho"])
        p.drawRoundedRect(QRectF(x, y, w, h), self.R(h / 2), self.R(h / 2))
        p.setBrush(cor)
        p.drawRoundedRect(QRectF(x, y, max(w * pct / 100, h), h), self.R(h / 2), self.R(h / 2))

    # -- seções ----------------------------------------------------------
    def _linha_temp(self, p, x, y, t, c, aprox=False):
        cor = cor_temp(t) if t is not None else c["suave"]
        icone_desenho(p, "termo", x, y - 11, 13, cor)
        p.setFont(self.f_g)
        p.setPen(cor)
        p.drawText(QPointF(x + 14, y + 1), ("≈" if aprox and t is not None else "") + (self.temp(t) if t is not None else "--"))

    def _cpu(self, p, y, c, ac, d):
        rc = self._card(p, y, 52 + (20 if self.cfg["graficos"] else 0), c)
        self._tile(p, rc, 12, "cpu", ac, 28)
        extra = f"{d['cpu_mhz'] / 1000:.1f} GHz" if d.get("cpu_mhz") else ""
        if d.get("cpu_watts") is not None:
            extra += f" · {d['cpu_watts']:.0f} W"
        nome = self.coletor.sensores.nome_cpu_completo if self.coletor.sensores else "CPU"
        self._titulo(p, rc.x() + 48, y + 20, nome, extra, c, largura=rc.width() - 48 - 46)
        self._linha_temp(p, rc.x() + 112, y + 36, d.get("cpu_temp"), c, aprox=not d.get("cpu_temp_real"))
        self._anel(p, rc.right() - 12 - 15, y + 26, 13, d["cpu_uso"], cor_carga(d["cpu_uso"]), c)
        if self.cfg["graficos"]:
            self._mini_grafico(p, rc.x() + 12, y + 55, rc.width() - 24, 13, self.h["cpu"], self.h["cpu_t"], ac, c)
            return 52 + 20
        return 52

    def _mini_grafico(self, p, x, y, w, h, uso, temp, ac, c):
        """Linha recente (60 s): uso (cor de destaque) e temperatura (cor quente), na mesma faixa."""
        def linha(serie, topo, cor, larg):
            pts = list(serie)
            n = len(pts)
            cam = QPainterPath()
            for i, v in enumerate(pts):
                px = x + w * i / (n - 1)
                py = y + h - h * max(min(v, topo), 0) / topo
                (cam.moveTo if i == 0 else cam.lineTo)(px, py)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(cor, larg))
            p.drawPath(cam)
        p.setPen(Qt.NoPen)
        p.setBrush(c["trilho"])
        p.drawRoundedRect(QRectF(x, y, w, h), self.R(3), self.R(3))
        linha(uso, 100, ac, 1.4)
        if any(temp):
            quente = QColor(251, 146, 60) if self.nome_tema() == "escuro" else QColor(194, 80, 10)
            linha(temp, 100, quente, 1.1)

    def _gpu(self, p, y, c, ac, d):
        gpus = [g for g in d.get("gpus", []) if g.get("dedicada")]
        total = 0
        for i, g in enumerate(gpus):
            if i:
                y += 5
                total += 5
            h = self._cartao_gpu(p, y, c, ac, g, principal=(i == 0))
            total += h
            y += h
        return total

    def _cartao_gpu(self, p, y, c, ac, g, principal):
        graf = self.cfg["graficos"] and principal
        alt = 60 + (20 if graf else 0)
        rc = self._card(p, y, alt, c)
        self._tile(p, rc, 12, "gpu", ac, 28)
        sub = []
        if g.get("vram_usada") is not None:
            sub.append(f"{g['vram_usada']:.1f}/{g['vram_total']:.0f} GB VRAM" if g.get("vram_total") else f"{g['vram_usada']:.1f} GB VRAM")
        self._titulo(p, rc.x() + 48, y + 20, g["nome"], (sub[0] if sub else ""), c, largura=rc.width() - 48 - 46)
        if g.get("temp") is not None:
            self._linha_temp(p, rc.x() + 126, y + 36, g["temp"], c)
        elif g.get("mhz"):
            p.setFont(self.f_n)
            p.setPen(c["suave"])
            p.drawText(QPointF(rc.x() + 126, y + 36), f"{g['mhz']:.0f} MHz")
        if g.get("uso") is not None:
            self._anel(p, rc.right() - 12 - 15, y + 26, 13, g["uso"], cor_carga(g["uso"]), c)
        if g.get("vram_usada") is not None and g.get("vram_total"):
            pct = g["vram_usada"] / g["vram_total"] * 100
            self._barra(p, rc.x() + 12, y + 52, rc.width() - 24, pct, cor_carga(pct) if pct > 85 else ac, c, 3)
        if graf:
            self._mini_grafico(p, rc.x() + 12, y + 61, rc.width() - 24, 13, self.h["gpu"], self.h["gpu_t"], ac, c)
        return alt

    def _linha_simples(self, p, y, c, ac, icone, titulo, valor, pct, legenda, cor_barra=None):
        rc = self._card(p, y, 36, c)
        self._tile(p, rc, 5, icone, ac, 26)
        x = rc.x() + 42
        w = rc.right() - 12 - x
        p.setFont(self.f_t)
        p.setPen(c["texto"])
        p.drawText(QPointF(x, y + 16), titulo)
        larg = p.fontMetrics().horizontalAdvance(titulo)
        p.setFont(self.f_p)
        p.setPen(c["suave"])
        p.drawText(QRectF(x + larg + 6, y + 5, w - larg - 6 - 40, 14), Qt.AlignLeft | Qt.AlignVCenter, legenda)
        p.setFont(self.f_t)
        p.setPen(c["texto"])
        p.drawText(QRectF(x, y + 4, w, 16), Qt.AlignRight | Qt.AlignVCenter, valor)
        self._barra(p, x, y + 25, w, pct, cor_barra or ac, c, 4)
        return 36

    def _igpu(self, p, y, c, ac, d):
        gpus = [g for g in d.get("gpus", []) if not g.get("dedicada")]
        total = 0
        for g in gpus:
            if total:
                y += 5
                total += 5
            u = g.get("uso")
            marca = g.get("marca") or "GPU"
            total += self._linha_simples(p, y, c, ac, "igpu", marca, f"{u:.0f}%" if u is not None else "--", u or 0,
                                         g["nome"][:24], cor_carga(u or 0))
            y += 36
        return total

    def _ram(self, p, y, c, ac, d):
        return self._linha_simples(p, y, c, ac, "ram", "RAM", f"{d['ram_uso']:.0f}%", d["ram_uso"],
                                   f"{d['ram_usada']:.1f}/{d['ram_total']:.0f} GB",
                                   cor_carga(d["ram_uso"]) if d["ram_uso"] > 75 else ac)

    def _disco(self, p, y, c, ac, d):
        discos = d.get("discos") or []
        if not discos and "disco_uso" in d:
            discos = [{"letra": d.get("disco_letra", ""), "uso": d["disco_uso"], "livre": d["disco_livre"]}]
        total = 0
        for i, k in enumerate(discos):
            if i:
                y += 5
                total += 5
            total += self._linha_simples(p, y, c, ac, "disco", f"Disco {k['letra']}", f"{k['uso']:.0f}%", k["uso"],
                                         f"{k['livre']:.0f} GB livres", cor_carga(k["uso"]) if k["uso"] > 85 else ac)
            y += 36
        return total

    def _rede(self, p, y, c, ac, d):
        rc = self._card(p, y, 32, c)
        self._tile(p, rc, 3, "rede", ac, 26)
        x = rc.x() + 42
        p.setFont(self.f_n)
        p.setPen(c["texto"])
        p.drawText(QPointF(x, y + 20), f"↓ {fmt_vel(d.get('rede_down', 0))}")
        p.drawText(QRectF(x, y + 8, rc.right() - 12 - x, 16), Qt.AlignRight | Qt.AlignVCenter,
                   f"↑ {fmt_vel(d.get('rede_up', 0))}")
        return 32

    def _bateria(self, p, y, c, ac, d):
        if d.get("bat_pct") is None:
            return 0
        pct = d["bat_pct"]
        leg = "carregando" if d["bat_ligada"] else "na bateria"
        if d.get("bat_resta") and not d["bat_ligada"]:
            s = int(d["bat_resta"])
            leg = f"{s // 3600}h{(s % 3600) // 60:02d}"
        cor = QColor(*VERMELHO) if pct <= 20 and not d["bat_ligada"] else QColor(*VERDE)
        ret = self._linha_simples(p, y, c, ac, "bateria", "Bateria", f"{pct:.0f}%", pct, leg, cor)
        return ret

    def _grafico(self, p, x, y, w, alt, serie, cor):
        pts = list(serie)
        n = len(pts)
        caminho = QPainterPath()
        for i, v in enumerate(pts):
            px = x + w * i / (n - 1)
            py = y + alt - alt * min(v, 100) / 100
            (caminho.moveTo if i == 0 else caminho.lineTo)(px, py)
        area = QPainterPath(caminho)
        area.lineTo(x + w, y + alt)
        area.lineTo(x, y + alt)
        area.closeSubpath()
        c2 = QColor(cor)
        c2.setAlpha(40)
        p.setPen(Qt.NoPen)
        p.setBrush(c2)
        p.drawPath(area)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(cor, 1.4))
        p.drawPath(caminho)


# ---------------------------------------------------------------- sistema
def comando_inicio() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    return sys.executable.replace("python.exe", "pythonw.exe"), f'"{Path(__file__).resolve().parent / "app.py"}"'


def inicia_com_windows() -> bool:
    return ATALHO.exists()


def definir_inicio(ativo: bool):
    try:
        if not ativo:
            ATALHO.unlink(missing_ok=True)
            return
        import win32com.client

        exe, args = comando_inicio()
        lnk = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(ATALHO))
        lnk.TargetPath = exe
        lnk.Arguments = args
        lnk.WorkingDirectory = str(Path(__file__).resolve().parent if not getattr(sys, "frozen", False) else Path(exe).parent)
        lnk.Save()
    except Exception:
        pass


def texto_temperatura_real(d: dict) -> tuple[str, str, bool]:
    """(título, texto, oferecer reinício como administrador) conforme o estado atual da leitura."""
    if d.get("cpu_temp_real"):
        return ("Temperatura real da CPU", "Já está lendo a temperatura REAL do processador (sensor do pacote, via LibreHardwareMonitor).", False)
    base = ("O Windows não entrega a temperatura do processador a programas comuns. O valor com “≈” é a zona térmica ACPI da placa "
            "(uma estimativa do chassi), não a do processador.\n\n")
    if d.get("admin"):
        return ("Temperatura real da CPU",
                base + "O widget já roda como administrador, mas não obteve a leitura: falta o driver de sensores que a LibreHardwareMonitor usa "
                       "(PawnIO), que NÃO está instalado neste PC. Para instalar (uma vez), abra o PowerShell como administrador e rode:\n\n"
                       "    winget install namazso.PawnIO\n\nDepois reinicie o widget. O widget nunca instala drivers sozinho.", False)
    return ("Temperatura real da CPU",
            base + "Para a leitura real são necessários DOIS passos:\n\n"
                   "1) Executar o widget como administrador (o Windows pedirá a sua confirmação — botão abaixo).\n"
                   "2) Ter o driver de sensores PawnIO instalado (uma vez, no PowerShell como administrador):\n"
                   "    winget install namazso.PawnIO\n\nSem o driver, mesmo como administrador a temperatura continua aproximada.", True)


def ajuda_temperatura(w):
    from PySide6.QtWidgets import QMessageBox
    titulo, texto, oferecer = texto_temperatura_real(w.d or {"admin": eh_admin()})
    cx = QMessageBox(w)
    cx.setWindowTitle(titulo)
    cx.setText(texto)
    b_admin = cx.addButton("Reiniciar como administrador", QMessageBox.AcceptRole) if oferecer else None
    cx.addButton("Fechar", QMessageBox.RejectRole)
    cx.setStyleSheet(f"QMessageBox {{ font: 9pt 'Segoe UI Variable Text'; }}")
    cx.exec()
    if b_admin is not None and cx.clickedButton() is b_admin:
        pedir_admin(w.coletor)


def inicio_admin_ativo() -> bool:
    try:
        return subprocess.run(["schtasks", "/Query", "/TN", "WidgetMonitorAdmin"], capture_output=True, creationflags=0x08000000).returncode == 0
    except Exception:
        return False


def definir_inicio_admin(ativo: bool):
    """Só funciona com o widget já elevado (o usuário o reiniciou como administrador): cria/remove uma tarefa agendada
    'ao entrar no Windows' com privilégio máximo, para abrir como administrador sem pedir confirmação a cada login."""
    try:
        if ativo:
            exe, args = comando_inicio()
            cmd = f'"{exe}" {args}'.strip()
            subprocess.run(["schtasks", "/Create", "/TN", "WidgetMonitorAdmin", "/TR", cmd, "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"],
                           capture_output=True, creationflags=0x08000000)
            ATALHO.unlink(missing_ok=True)  # evita abrir duas vezes (o atalho comum e a tarefa)
        else:
            subprocess.run(["schtasks", "/Delete", "/TN", "WidgetMonitorAdmin", "/F"], capture_output=True, creationflags=0x08000000)
    except Exception:
        pass


def pedir_admin(coletor: Coletor):
    """Reabre o programa com UAC (administrador) e encerra a instância atual."""
    exe, args = comando_inicio()
    # a instância elevada precisa que esta libere o mutex de instância única primeiro
    coletor.parar.set()
    liberar_mutex()
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, str(Path(__file__).resolve().parent), 1)
    if r > 32:
        QApplication.quit()
    else:  # UAC recusado: continua como está
        coletor.parar.clear()
        global _mutex
        _mutex = criar_mutex()
        threading.Thread(target=coletor._loop, daemon=True).start()


_mutex = None


def criar_mutex():
    h = ctypes.windll.kernel32.CreateMutexW(None, False, f"{NOME}_UnicaInstancia")
    return h, ctypes.windll.kernel32.GetLastError() == 183


def liberar_mutex():
    global _mutex
    if _mutex:
        ctypes.windll.kernel32.CloseHandle(_mutex[0])
        _mutex = None


# ---------------------------------------------------------------- menu
def estilo_menu(escuro: bool, destaque: QColor) -> str:
    if escuro:
        bg, txt, suave, borda, sel = "#171920", "#eceff6", "#8d94a8", "#2a2e3b", "#242836"
    else:
        bg, txt, suave, borda, sel = "#f7f8fb", "#171a24", "#6b7285", "#dadee8", "#e8ebf3"
    return f"""
        QMenu {{ background:{bg}; color:{txt}; border:1px solid {borda}; padding:6px 0; font:9pt 'Segoe UI Variable Text'; }}
        QMenu::item {{ padding:7px 28px 7px 18px; margin:0; }}
        QMenu::item:selected {{ background:{sel}; border-left:2px solid {destaque.name()}; padding-left:16px; }}
        QMenu::item:disabled {{ color:{suave}; }}
        QMenu::separator {{ height:1px; background:{borda}; margin:5px 14px; }}
        QMenu::right-arrow {{ margin-right:10px; }}
    """


def menu_contexto(w: Widget, pos=None) -> QMenu:
    cfg = w.cfg
    g = getattr(w, "gerente", None)

    def mudar(chave, valor):
        cfg[chave] = valor
        salvar_cfg(cfg)
        w.aplicar()

    m = QMenu()
    m.setStyleSheet(estilo_menu(w.nome_tema() == "escuro", w.destaque()))
    m.setWindowFlag(Qt.NoDropShadowWindowHint, False)

    def marca(on: bool, rot: str) -> str:
        return ("●   " if on else "     ") + rot

    def liga(menu, rot, ativo, fn):
        """Item liga/desliga: ● alinhado à esquerda em vez do indicador padrão do Qt."""
        a = menu.addAction(marca(ativo, rot))
        a.triggered.connect(lambda _=False: fn(not ativo))
        return a

    def radio(menu, itens, atual, chave, conv=lambda v: v):
        for rot, v in itens:
            a = menu.addAction(("●   " if atual == v else "     ") + rot)
            a.triggered.connect(lambda _=False, v=v: mudar(chave, conv(v)))

    # --- Métricas
    sub = m.addMenu("Métricas")
    for k, rot in ROTULOS.items():
        liga(sub, rot, cfg["mostrar"].get(k, True), lambda v, k=k: (cfg["mostrar"].__setitem__(k, v), mudar("mostrar", cfg["mostrar"])))

    # --- Aparência
    ap = m.addMenu("Aparência")
    radio(ap, [("Quadrado", "quadrado"), ("Arredondado", "vidro")], cfg["estilo"], "estilo")
    ap.addSeparator()
    radio(ap, [("Tema automático (Windows)", "auto"), ("Tema claro", "claro"), ("Tema escuro", "escuro")], cfg["tema"], "tema")
    ap.addSeparator()
    radio(ap, [("Cor do Windows", "Auto")] + [(k, k) for k in DESTAQUES], cfg["destaque"], "destaque")
    ap.addSeparator()
    liga(ap, "Desfocar o fundo", cfg["vidro"], lambda v: mudar("vidro", v))
    liga(ap, "Fundo nos blocos", cfg["fundo_cards"], lambda v: mudar("fundo_cards", v))
    liga(ap, "Bordas", cfg["bordas"], lambda v: mudar("bordas", v))
    liga(ap, "Mini gráficos", cfg["graficos"], lambda v: mudar("graficos", v))
    liga(ap, "Animar as ventoinhas (usa mais CPU)", cfg.get("animar", True), lambda v: mudar("animar", v))
    ap.addSeparator()
    sz = ap.addMenu("Tamanho")
    radio(sz, [(f"{v}%", v) for v in (75, 90, 100, 125, 150, 175)], cfg["escala"], "escala")
    op = ap.addMenu("Opacidade")
    radio(op, [(f"{v}%", v) for v in (40, 55, 70, 85, 90, 100)], cfg["opacidade"], "opacidade")

    # --- Jogo e overlay
    if g is not None:
        so = m.addMenu("Jogo e overlay")
        so.addAction(f"Mostrar overlay agora (teste)   {cfg['atalhos']['overlay']}").triggered.connect(g.mostrar_agora)
        so.addAction(f"Mover o overlay (arrastar)   {cfg['atalhos'].get('posicao', 'Ctrl+Alt+P')}").triggered.connect(g.editar_posicao)
        so.addAction("     Ocultar overlay").triggered.connect(lambda: (g.overlay.ocultar(), setattr(g, "forcado", False)))
        so.addSeparator()
        liga(so, "Abrir sozinho ao entrar no jogo", cfg["jogo"]["overlay_auto"], lambda v: (cfg["jogo"].__setitem__("overlay_auto", v), g.aplicar_config()))
        liga(so, "Layout compacto", cfg["overlay"]["layout"] == "compacto",
             lambda v: (cfg["overlay"].__setitem__("layout", "compacto" if v else "completo"), g.aplicar_config()))
        liga(so, "Clique-através", cfg["overlay"]["clique_atraves"], lambda v: (cfg["overlay"].__setitem__("clique_atraves", v), g.aplicar_config()))
        so.addSeparator()
        liga(so, "Página para celular (rede local)", g.web.ativo, g.alternar_web)
        so.addAction("     Mostrar o link da página").triggered.connect(g.mostrar_link_web)
        so.addSeparator()
        so.addAction("     Adicionar programa ativo à lista de jogos (5 s)").triggered.connect(g.adicionar_em_primeiro_plano)
        so.addAction("     Diagnóstico da detecção (5 s)").triggered.connect(g.diagnostico)
        so.addAction("     Overlay em tela cheia exclusiva — assistente…").triggered.connect(g.abrir_assistente)
        a_rtss = so.addAction("     RTSS: " + g.rtss_status(curto=True))
        a_rtss.triggered.connect(lambda: g.abrir_ajustes(aba="Overlay"))
        so.addAction("     Exportar log da sessão").triggered.connect(g.exportar_sessao)
        so.addAction("     Abrir pasta de logs").triggered.connect(g.abrir_pasta_logs)
        so.addAction("     Abrir log de diagnóstico").triggered.connect(g.abrir_diagnostico)

        sp = m.addMenu("Perfil")
        for nome in sorted(cfg["perfis"]):
            sp.addAction(("●   " if cfg["perfil"] == nome else "     ") + nome).triggered.connect(lambda _=False, nome=nome: g.aplicar_perfil(nome))
        sp.addSeparator()
        sp.addAction(f"     Salvar atual em “{cfg['perfil']}”").triggered.connect(lambda: g.salvar_perfil(cfg["perfil"]))

    # --- Mais
    mais = m.addMenu("Mais")
    radio(mais.addMenu("Atualização"), [("0,5 s", 0.5), ("1 s", 1.0), ("2 s", 2.0), ("5 s", 5.0)], float(cfg["intervalo"]), "intervalo")
    radio(mais.addMenu("Temperatura"), [("Celsius (°C)", "C"), ("Fahrenheit (°F)", "F")], cfg["unidade"], "unidade")
    mais.addAction("     Temperatura real da CPU…").triggered.connect(lambda: ajuda_temperatura(w))
    if eh_admin():
        liga(mais, "Iniciar sempre como administrador", inicio_admin_ativo(), definir_inicio_admin)
    liga(mais, "Alertas de temperatura alta", cfg["alerta"]["ativo"], lambda v: (cfg["alerta"].__setitem__("ativo", v), salvar_cfg(cfg)))

    if g is not None:
        m.addAction("Ajustes…").triggered.connect(g.abrir_ajustes)
    m.addSeparator()
    liga(m, "Travar posição", cfg["travar"], lambda v: mudar("travar", v))
    liga(m, "Sempre no topo", cfg["topo"], lambda v: mudar("topo", v))
    liga(m, "Iniciar com o Windows", inicia_com_windows(), definir_inicio)
    if not eh_admin():
        m.addAction("Reiniciar como administrador").triggered.connect(lambda: pedir_admin(w.coletor))
    m.addSeparator()
    m.addAction(f"Versão {VERSAO}").setEnabled(False)
    m.addAction("Sair").triggered.connect(QApplication.quit)
    return m


def main():
    global _mutex
    _mutex = criar_mutex()
    if _mutex[1] and "--multi" in sys.argv:  # só para testes: permite uma 2ª instância
        _mutex = (None, False)
    if _mutex[1]:
        # pode ser uma instância antiga a encerrar (reinício como administrador): espera um pouco
        import time
        for _ in range(20):
            time.sleep(0.25)
            liberar_mutex()
            _mutex = criar_mutex()
            if not _mutex[1]:
                break
        else:
            return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WidgetMonitor.Galaxy")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(icone_app())
    cfg = carregar_cfg()
    coletor = Coletor(float(cfg["intervalo"]))
    w = Widget(coletor, cfg)
    w.show()

    tray = QSystemTrayIcon(icone_app(), app)
    tray.setToolTip(f"Monitor de Hardware {VERSAO}")
    alterna = lambda: w.hide() if w.isVisible() else (w.show(), w.raise_())
    mt = QMenu()
    mt.addAction(f"Monitor de Hardware {VERSAO}").setEnabled(False)
    mt.addSeparator()
    from gerente import GerenteJogo  # import tardio: gerente/overlay importam este módulo
    g = GerenteJogo(w, app, tray)
    w.gerente = g
    w.tray = tray
    mt.setStyleSheet(estilo_menu(w.nome_tema() == "escuro", w.destaque()))
    mt.addAction("Configurações…").triggered.connect(g.abrir_ajustes)
    mt.addAction("Mostrar overlay agora").triggered.connect(g.mostrar_agora)
    mt.addAction("Mover o overlay (arrastar)").triggered.connect(g.editar_posicao)
    mt.addAction("Mostrar / ocultar widget").triggered.connect(alterna)
    mt.addAction("Abrir menu completo…").triggered.connect(lambda: menu_contexto(w).exec(QCursor.pos()))
    mt.addAction("Abrir log de diagnóstico").triggered.connect(g.abrir_diagnostico)
    mt.addSeparator()
    mt.addAction("Sair").triggered.connect(app.quit)
    tray.setContextMenu(mt)
    tray.activated.connect(lambda r: r == QSystemTrayIcon.Trigger and alterna())
    tray.show()

    # economia: não consulta sensores com o widget oculto
    t = QTimer()
    t.timeout.connect(lambda: coletor.pausa.set() if not (w.isVisible() or g.overlay.isVisible() or g.jogo or g.web.ativo) else coletor.pausa.clear())
    t.start(1000)
    t2 = QTimer()  # acompanha o tema/cor do Windows ao vivo
    t2.timeout.connect(w.verificar_sistema)
    t2.start(1500)
    app.aboutToQuit.connect(lambda: (g.encerrar(), coletor.parar.set(), salvar_cfg(cfg)))
    if "--autoteste" in sys.argv:  # verificação do pacote: abre o overlay, grava uma imagem e sai
        destino = sys.argv[sys.argv.index("--autoteste") + 1]
        def _auto():
            g.mostrar_agora()
            QTimer.singleShot(2500, lambda: (g.overlay._pix.save(destino), w.grab().save(destino + ".widget.png"), app.quit()))
        QTimer.singleShot(4000, _auto)
    sys.exit(app.exec())


if __name__ == "__main__":
    # execute pelo app.py: rodar este arquivo direto duplicaria o módulo para o overlay/gerente
    from app import iniciar
    iniciar()









