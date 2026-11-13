"""Detecção de jogos, FPS (via PresentMon/ETW), registro de sessão e atalhos globais.

Nada aqui injeta DLL nem faz hook em processos: só lê a janela em primeiro plano, contadores do Windows e a saída
do PresentMon (Intel), que usa ETW — o mesmo mecanismo do MSI Afterburner/PresentMon, seguro com anti-cheat.
"""
from __future__ import annotations

import csv
import ctypes
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.MonitorFromWindow.restype = wintypes.HANDLE
kernel32.OpenProcess.restype = wintypes.HANDLE

# programas que nunca são tratados como jogo na detecção automática (a lista do usuário se soma a esta)
IGNORAR_PADRAO = [
    "explorer.exe", "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
    "vlc.exe", "mpc-hc64.exe", "mpv.exe", "wmplayer.exe", "applicationframehost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe", "lockapp.exe", "widgetmonitor.exe", "python.exe",
    "pythonw.exe", "code.exe", "devenv.exe", "obs64.exe", "teams.exe", "discord.exe", "spotify.exe", "claude.exe",
]


def nome_exe(pid: int) -> str:
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h)
    return ""


def tela_cheia_exclusiva() -> bool:
    """O próprio Windows informa se há um app D3D em TELA CHEIA EXCLUSIVA (QUNS_RUNNING_D3D_FULL_SCREEN = 3).
    Nesse modo nenhuma outra janela (nem sempre-no-topo) aparece por cima do jogo."""
    try:
        st = ctypes.c_int()
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(st)) == 0:
            return st.value == 3
    except Exception:
        pass
    return False


def janela_em_primeiro_plano() -> dict | None:
    """Janela ativa: pid, exe, retângulo, se cobre o monitor inteiro e se é sem moldura (borderless)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(mi)
    hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
    m = mi.rcMonitor
    cobre = r.left <= m.left + 1 and r.top <= m.top + 1 and r.right >= m.right - 1 and r.bottom >= m.bottom - 1
    estilo = user32.GetWindowLongW(hwnd, -16)
    return {"hwnd": int(hwnd), "pid": int(pid.value), "exe": nome_exe(int(pid.value)), "larg": r.right - r.left, "alt": r.bottom - r.top,
            "tela_cheia": cobre, "sem_moldura": not (estilo & 0x00C00000), "monitor": (m.left, m.top, m.right, m.bottom)}


class DetectorJogo:
    """Decide se há um jogo em primeiro plano. Manual (lista do usuário) tem prioridade sobre a detecção automática.

    Automático = janela em tela cheia/sem borda + processo com uso de GPU 3D acima do limiar, fora da lista de ignorados.
    Histerese: 2 leituras seguidas para entrar, 6 sem jogo para sair (alt-tab rápido não fecha o overlay).
    """

    def __init__(self, cfg: dict, fonte=janela_em_primeiro_plano):
        self.cfg = cfg
        self.fonte = fonte
        self.atual: dict | None = None
        self.motivo = "sem leitura ainda"
        self.ultimo_fg: dict | None = None
        self._cand = 0
        self._sem = 0

    def _avaliar(self, d3d_por_pid: dict) -> dict | None:
        j = self.fonte()
        self.ultimo_fg = j
        if not j or not j["exe"]:
            self.motivo = "nenhuma janela em primeiro plano"
            return None
        exe = j["exe"]
        j["gpu3d"] = d3d_por_pid.get(j["pid"], 0.0)
        lim = self.cfg.get("limiar_gpu3d", 15)
        ign = {x.lower() for x in IGNORAR_PADRAO} | {x.lower() for x in self.cfg.get("ignorar", [])}
        if exe in {x.lower() for x in self.cfg.get("jogos", [])}:
            j["origem"] = "lista"
            self.motivo = f"{exe} está na lista de jogos do usuário"
            return j
        if exe in ign:
            self.motivo = f"{exe} está na lista de ignorados"
            return None
        if not self.cfg.get("auto_detectar", True):
            self.motivo = "detecção automática desligada"
            return None
        if not j["tela_cheia"]:
            self.motivo = f"{exe}: janela não cobre o monitor inteiro (não é tela cheia/sem bordas)"
            return None
        if j["gpu3d"] < lim:
            self.motivo = f"{exe}: tela cheia, mas GPU 3D {j['gpu3d']:.1f}% < mínimo {lim}%"
            return None
        j["origem"] = "auto"
        self.motivo = f"{exe}: tela cheia + GPU 3D {j['gpu3d']:.1f}% >= {lim}%"
        return j

    def tick(self, d3d_por_pid: dict) -> dict | None:
        j = self._avaliar(d3d_por_pid)
        if j:
            self._sem = 0
            if self.atual and self.atual["pid"] == j["pid"]:
                self.atual = j
            else:
                self._cand += 1
                if self._cand >= 2 or j["origem"] == "lista":
                    self.atual, self._cand = j, 0
        else:
            self._cand = 0
            if self.atual:
                self._sem += 1
                if self._sem >= 6:
                    self.atual, self._sem = None, 0
        return self.atual


# ------------------------------------------------------------------ FPS (PresentMon / ETW)
def tem_permissao_etw() -> bool:
    """ETW de sessão em tempo real exige administrador ou o grupo 'Performance Log Users' (SID S-1-5-32-559)."""
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return True
        out = subprocess.run(["whoami", "/groups", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=8,
                             creationflags=0x08000000).stdout
        return "S-1-5-32-559" in out
    except Exception:
        return False


def caminho_presentmon() -> Path | None:
    for base in (Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parent):
        p = base / "tools" / "PresentMon.exe"
        if p.is_file():
            return p
    return None


class EstatisticasFps:
    """Janela móvel de quadros: FPS atual, média e 1% low (FPS do quadro no percentil 99 de frametime)."""

    def __init__(self, janela_s: float = 30.0):
        self.janela = janela_s
        self.q: deque[tuple[float, float]] = deque()  # (instante, frametime ms)

    def quadro(self, ms: float, agora: float | None = None):
        if ms <= 0:
            return
        t = agora if agora is not None else time.monotonic()
        self.q.append((t, ms))
        corte = t - self.janela
        while self.q and self.q[0][0] < corte:
            self.q.popleft()

    def resumo(self, agora: float | None = None) -> dict | None:
        t = agora if agora is not None else time.monotonic()
        while self.q and self.q[0][0] < t - self.janela:
            self.q.popleft()
        if len(self.q) < 5 or t - self.q[-1][0] > 3.0:
            return None
        todos = [ms for _, ms in self.q]
        recentes = [ms for ts, ms in self.q if ts >= t - 1.0] or todos[-10:]
        media_ms = sum(todos) / len(todos)
        ordenado = sorted(todos)
        p99 = ordenado[min(int(len(ordenado) * 0.99), len(ordenado) - 1)]
        rec_ms = sum(recentes) / len(recentes)
        return {"fps": 1000.0 / rec_ms, "media": 1000.0 / media_ms, "low1": 1000.0 / p99, "frametime": rec_ms,
                "historico": [ms for _, ms in list(self.q)[-90:]]}


def interpretar_linha(cabecalho: list[str], linha: list[str]) -> tuple[float, str] | None:
    """(frametime em ms, runtime/API) de uma linha CSV do PresentMon (1.x: MsBetweenPresents; 2.x: FrameTime)."""
    try:
        col = {n: i for i, n in enumerate(cabecalho)}
        for nome in ("MsBetweenPresents", "FrameTime"):
            if nome in col:
                ms = float(linha[col[nome]])
                api = linha[col["PresentRuntime"]] if "PresentRuntime" in col else ""
                return ms, api
    except (ValueError, IndexError):
        pass
    return None


class LeitorPresentMon:
    """Roda o PresentMon (somente leitura de eventos ETW) filtrando pelo PID do jogo e alimenta EstatisticasFps."""

    def __init__(self):
        self.stats = EstatisticasFps()
        self.estado = "parado"  # parado | iniciando | ok | permissao | indisponivel | erro | sem_dados
        self.api = ""
        self.mensagem = ""
        self._proc: subprocess.Popen | None = None
        self._pid = None
        self._t0 = 0.0
        self._recebeu = False

    def iniciar(self, pid: int):
        if self._pid == pid and self._proc and self._proc.poll() is None:
            return
        self.parar()
        self.stats = EstatisticasFps()
        self.api, self.mensagem, self._recebeu = "", "", False
        exe = caminho_presentmon()
        if exe is None:
            self.estado, self.mensagem = "indisponivel", "PresentMon não encontrado (tools\\PresentMon.exe)"
            return
        if not tem_permissao_etw():
            self.estado = "permissao"
            self.mensagem = "FPS requer permissão (administrador ou grupo 'Performance Log Users')"
            return
        self._pid, self._t0, self.estado = pid, time.monotonic(), "iniciando"
        try:
            self._proc = subprocess.Popen(
                [str(exe), "--output_stdout", "--no_console_stats", "--stop_existing_session", "--terminate_on_proc_exit",
                 "--process_id", str(pid)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, creationflags=0x08000000)
        except OSError as e:
            self.estado, self.mensagem = "erro", str(e)
            return
        threading.Thread(target=self._ler, args=(self._proc,), daemon=True).start()
        threading.Thread(target=self._ler_erro, args=(self._proc,), daemon=True).start()

    def _ler(self, proc: subprocess.Popen):
        cab: list[str] | None = None
        for linha in proc.stdout:
            partes = next(csv.reader([linha.strip()]), [])
            if not partes:
                continue
            if cab is None:
                if "Application" in partes or "ProcessName" in partes:
                    cab = partes
                continue
            r = interpretar_linha(cab, partes)
            if r:
                self.stats.quadro(r[0])
                self.api = r[1] or self.api
                self._recebeu = True
                self.estado = "ok"
        if proc is self._proc and self.estado != "ok" and not self.mensagem:
            self.estado = "erro"
            self.mensagem = "PresentMon encerrou sem dados"

    def _ler_erro(self, proc: subprocess.Popen):
        txt = proc.stderr.read() if proc.stderr else ""
        if txt and proc is self._proc:
            self.mensagem = txt.strip().splitlines()[-1][:160]
            if re.search(r"administrator|Performance Log|access|privilege|permiss", txt, re.I):
                self.estado = "permissao"
                self.mensagem = "FPS requer permissão (administrador ou grupo 'Performance Log Users')"

    def resumo(self) -> dict | None:
        r = self.stats.resumo()
        if r is None and self.estado == "ok" and self._recebeu and time.monotonic() - self._t0 > 6:
            return None
        if r is None and self.estado == "iniciando" and time.monotonic() - self._t0 > 8:
            self.estado = "sem_dados"
        return r

    def parar(self):
        p, self._proc, self._pid = self._proc, None, None
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass
        self.estado = "parado"


# ------------------------------------------------------------------ registro de sessão (CSV)
def pasta_logs() -> Path:
    base = Path(os.path.expandvars(r"%USERPROFILE%\Documents")) / "WidgetMonitor" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


class SessaoLog:
    CAMPOS = ["tempo_s", "fps", "media_fps", "low1_fps", "frametime_ms", "cpu_pct", "cpu_temp_c", "cpu_mhz", "gpu_pct",
              "gpu_temp_c", "gpu_mhz", "gpu_w", "vram_gb", "ram_gb", "bateria_pct"]

    def __init__(self, exe: str):
        self.exe, self.t0 = exe, time.monotonic()
        self.inicio = datetime.now()
        self.linhas: list[list] = []

    def amostra(self, d: dict, fps: dict | None):
        g = next((x for x in d.get("gpus", []) if x.get("dedicada")), None) or (d.get("gpus") or [None])[0] or {}
        r = lambda v, n=1: None if v is None else round(v, n)
        self.linhas.append([round(time.monotonic() - self.t0, 1),
                            r(fps and fps["fps"]), r(fps and fps["media"]), r(fps and fps["low1"]), r(fps and fps["frametime"], 2),
                            r(d.get("cpu_uso")), r(d.get("cpu_temp")), r(d.get("cpu_mhz"), 0),
                            r(g.get("uso")), r(g.get("temp")), r(g.get("mhz"), 0), r(g.get("watts")), r(g.get("vram_usada"), 2),
                            r(d.get("ram_usada"), 2), r(d.get("bat_pct"), 0)])

    def salvar(self) -> Path | None:
        if len(self.linhas) < 3:
            return None
        nome = f"{Path(self.exe).stem}_{self.inicio:%Y%m%d_%H%M%S}.csv"
        arq = pasta_logs() / nome
        with open(arq, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(self.CAMPOS)
            w.writerows(self.linhas)
        return arq


# ------------------------------------------------------------------ atalhos globais
MODIFICADORES = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8, "meta": 0x8}
TECLAS_ESPECIAIS = {"f%d" % i: 0x6F + i for i in range(1, 25)}
TECLAS_ESPECIAIS.update({"insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdown": 0x22, "space": 0x20,
                         "pageup": 0x21, "pagedown": 0x22, "pause": 0x13, "esc": 0x1B, "tab": 0x09,
                         "ins": 0x2D, "del": 0x2E, "return": 0x0D, "enter": 0x0D, "backspace": 0x08, "print": 0x2C})


def interpretar_atalho(txt: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+O' -> (modificadores, tecla virtual)."""
    mod, vk = 0, 0
    for p in [x.strip().lower() for x in txt.split("+") if x.strip()]:
        if p in MODIFICADORES:
            mod |= MODIFICADORES[p]
        elif p in TECLAS_ESPECIAIS:
            vk = TECLAS_ESPECIAIS[p]
        elif len(p) == 1 and p.isalnum():
            vk = ord(p.upper())
        else:
            return None
    return (mod | 0x4000, vk) if vk and mod else None  # 0x4000 = MOD_NOREPEAT


class AtalhosGlobais(QObject):
    """RegisterHotKey numa thread própria com seu laço de mensagens (GetMessage dorme sem gastar CPU).
    Evita o filtro nativo do Qt, que chamaria Python a CADA mensagem do Windows e pesava no processador."""

    disparou = Signal(int)

    def __init__(self):
        super().__init__()
        self.acoes: dict[int, callable] = {}
        self._thread: threading.Thread | None = None
        self._tid = 0
        self.disparou.connect(self._executar)

    def _executar(self, i: int):
        fn = self.acoes.get(i)
        if fn:
            fn()

    def registrar(self, mapa: dict[str, tuple[str, callable]]) -> list[str]:
        """mapa: nome -> (texto do atalho, função). Retorna os atalhos que não puderam ser registrados."""
        self.liberar()
        self.acoes = {0xA000 + n: fn for n, (_, (_, fn)) in enumerate(mapa.items(), start=1)}
        pronto, falhas = threading.Event(), []

        def laco():
            self._tid = kernel32.GetCurrentThreadId()
            for n, (nome, (txt, _)) in enumerate(mapa.items(), start=1):
                a = interpretar_atalho(txt)
                if not a or not user32.RegisterHotKey(None, 0xA000 + n, a[0], a[1]):
                    falhas.append(f"{nome} ({txt})")
            pronto.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:  # bloqueia até chegar uma mensagem
                if msg.message == 0x0312:  # WM_HOTKEY
                    self.disparou.emit(int(msg.wParam))
            for n in range(1, len(mapa) + 1):
                user32.UnregisterHotKey(None, 0xA000 + n)

        self._thread = threading.Thread(target=laco, daemon=True)
        self._thread.start()
        pronto.wait(3)
        return falhas

    def liberar(self):
        if self._thread and self._thread.is_alive() and self._tid:
            user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT: o laço desregistra as teclas e termina
            self._thread.join(2)
        self._thread, self._tid = None, 0
