"""Integração OPCIONAL com o RivaTuner Statistics Server (RTSS, o que acompanha o MSI Afterburner).

Este módulo NÃO injeta nada em jogo nenhum. Ele só usa a API pública e documentada do RTSS (SDK, RTSSSharedMemory.h):
um arquivo mapeado em memória chamado "RTSSSharedMemoryV2" onde qualquer programa (HWiNFO, Afterburner, este widget)
escreve TEXTO num "slot de OSD". Quem desenha o texto dentro do jogo é o próprio RTSS, que já está instalado e é
quem injeta (ou não) o código nos jogos. O risco/aceitação por anti-cheat é, portanto, o do RTSS.

Regras do protocolo seguidas aqui (iguais ao exemplo oficial do SDK):
  * o slot 0 é reservado ao Afterburner; começamos a procurar no slot 1;
  * só escrevemos em um slot vazio ou que já tenha o NOSSO identificador ("WidgetMonitor") — nunca no de outro programa;
  * v2.7+ usa o texto estendido (4096 bytes); v2.14+ exige respeitar o bit "ocupado" (dwBusy) enquanto escrevemos;
  * depois de escrever, incrementa dwOSDFrame para o RTSS redesenhar;
  * ao sair / fechar o jogo, zera o nosso slot (como o ReleaseOSD do exemplo).
"""
from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes

NOME_MAPA = "RTSSSharedMemoryV2"
DONO = "WidgetMonitor"
ASSINATURA = 0x52545353          # 'RTSS' (constante multi-char do MSVC)
FILE_MAP_ALL_ACCESS = 0xF001F

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.OpenFileMappingW.restype = wintypes.HANDLE
_k.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k.MapViewOfFile.restype = ctypes.c_void_p
_k.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k.CloseHandle.argtypes = [wintypes.HANDLE]

def _CAS(endereco: int, novo: int, esperado: int) -> int:
    """Compare-and-set do bit "ocupado". As funções Interlocked* do Windows x64 são intrínsecas (não são exportadas),
    então é teste-e-marca em duas leituras: a janela de corrida é de microssegundos e o pior caso é um quadro de OSD
    perdido/redesenhado (o RTSS só lê o texto; nada trava). Devolve o valor anterior.""" 
    ant = struct.unpack("<i", ctypes.string_at(endereco, 4))[0]
    if ant == esperado:
        ctypes.memmove(endereco, struct.pack("<i", novo), 4)
    return ant

# Cabeçalho v2.x (offsets fixos desde a v2.0; o resto vem dos campos de tamanho/offset, como manda o SDK)
OFF_VERSAO, OFF_APP_ENTRY, OFF_APP_OFF, OFF_APP_N = 4, 8, 12, 16
OFF_OSD_ENTRY, OFF_OSD_OFF, OFF_OSD_N, OFF_FRAME, OFF_BUSY = 20, 24, 28, 32, 36
# Dentro de cada slot de OSD
OFF_SLOT_TEXTO, OFF_SLOT_DONO, OFF_SLOT_TEXTO_EX = 0, 256, 512
TAM_TEXTO, TAM_DONO, TAM_TEXTO_EX = 256, 256, 4096

CAMINHOS = [os.path.join(os.environ.get(v, ""), p, "RTSS.exe") for v in ("ProgramFiles(x86)", "ProgramFiles")
            for p in ("RivaTuner Statistics Server",)]
ONDE_OBTER = "https://www.guru3d.com/page/rtss-rivatuner-statistics-server-download/ (ou instalado junto com o MSI Afterburner)"

AVISO = ("O RTSS funciona injetando código nos jogos. Cada jogo/anti-cheat decide se aceita isso; o risco é do RTSS, "
         "não deste widget (que só envia texto ao RTSS). Use só nos jogos em que você já usa o Afterburner/RTSS sem problemas.")


class _Mapa:
    """Abre o mapeamento do RTSS; valida assinatura/versão. Fecha ao sair do `with`."""

    def __enter__(self):
        self.h = self.p = None
        self.versao = 0
        self.h = _k.OpenFileMappingW(FILE_MAP_ALL_ACCESS, False, NOME_MAPA)
        if not self.h:
            return self
        self.p = _k.MapViewOfFile(self.h, FILE_MAP_ALL_ACCESS, 0, 0, 0)
        if self.p:
            assin, self.versao = struct.unpack("<II", ctypes.string_at(self.p, 8))
            if assin != ASSINATURA or self.versao < 0x00020000:
                self.p = self._sem(self.p)
        return self

    @staticmethod
    def _sem(p):
        _k.UnmapViewOfFile(p)
        return None

    def __exit__(self, *a):
        if self.p:
            _k.UnmapViewOfFile(self.p)
        if self.h:
            _k.CloseHandle(self.h)

    @property
    def ok(self) -> bool:
        return bool(self.p)

    def u32(self, off: int) -> int:
        return struct.unpack("<I", ctypes.string_at(self.p + off, 4))[0]

    def slot(self, i: int) -> int:
        return self.p + self.u32(OFF_OSD_OFF) + i * self.u32(OFF_OSD_ENTRY)

    def n_slots(self) -> int:
        return self.u32(OFF_OSD_N)


def _txt(p: int, tam: int) -> str:
    return ctypes.string_at(p, tam).split(b"\0", 1)[0].decode("latin-1")


def instalado() -> str | None:
    """Caminho do RTSS.exe se estiver instalado nas pastas padrão (ou rodando); senão None."""
    for c in CAMINHOS:
        if os.path.isfile(c):
            return c
    try:
        import psutil
        for pr in psutil.process_iter(["name", "exe"]):
            if (pr.info["name"] or "").lower() == "rtss.exe":
                return pr.info["exe"]
    except Exception:
        pass
    return None


def rodando() -> bool:
    """O RTSS está ativo? (a memória compartilhada só existe e é válida enquanto ele roda)."""
    with _Mapa() as m:
        return m.ok


def fps_do_jogo(pid: int) -> dict | None:
    """FPS/frametime que o próprio RTSS mediu para o processo `pid` (None se o RTSS não 'vê' o jogo)."""
    with _Mapa() as m:
        if not m.ok:
            return None
        ent, off, n = m.u32(OFF_APP_ENTRY), m.u32(OFF_APP_OFF), m.u32(OFF_APP_N)
        for i in range(n):
            base = m.p + off + i * ent
            if struct.unpack("<I", ctypes.string_at(base, 4))[0] != pid:
                continue
            flags, t0, t1, frames, ft = struct.unpack("<IIIII", ctypes.string_at(base + 264, 20))
            api = flags & 0xFFFF
            if ft:
                fps = 1_000_000.0 / ft
            elif t1 > t0 and frames:
                fps = 1000.0 * frames / (t1 - t0)
            else:
                fps = 0.0
            return {"fps": fps, "frametime": ft / 1000.0 if ft else (1000.0 / fps if fps else 0.0), "api": api}
    return None


class SaidaRTSS:
    """Escreve/limpa o nosso slot de OSD no RTSS."""

    def __init__(self):
        self.ativo = False       # temos texto escrito no momento?
        self.slot = None
        self.ultimo = ""
        self.erro = ""           # motivo da última falha (para o diagnóstico/Ajustes)

    def escrever(self, texto: str) -> bool:
        dados = texto.encode("latin-1", "replace")
        with _Mapa() as m:
            if not m.ok:
                self.erro = "RTSS fechado (memória compartilhada indisponível)"
                self.ativo = False
                return False
            n = m.n_slots()
            alvo = None
            for passe in (0, 1):                 # 1º: slot já nosso; 2º: primeiro slot vazio
                for i in range(1, n):            # o 0 é do Afterburner
                    s = m.slot(i)
                    dono = _txt(s + OFF_SLOT_DONO, TAM_DONO)
                    if dono == DONO or (passe and not dono):
                        alvo = (i, s)
                        break
                if alvo:
                    break
            if not alvo:
                self.erro = "todos os slots de OSD do RTSS estão ocupados por outros programas"
                return False
            i, s = alvo
            if m.versao >= 0x0002000E:           # respeitar o 'ocupado' do renderizador do RTSS
                if _CAS(m.p + OFF_BUSY, 1, 0) != 0:
                    self.erro = "RTSS ocupado desenhando (tenta de novo no próximo ciclo)"
                    return False
            try:
                if not _txt(s + OFF_SLOT_DONO, TAM_DONO):
                    b = DONO.encode() + b"\0"
                    ctypes.memmove(s + OFF_SLOT_DONO, b, len(b))
                if m.versao >= 0x00020007:
                    dados = dados[:TAM_TEXTO_EX - 1] + b"\0"
                    ctypes.memmove(s + OFF_SLOT_TEXTO_EX, dados, len(dados))
                else:
                    dados = dados[:TAM_TEXTO - 1] + b"\0"
                    ctypes.memmove(s + OFF_SLOT_TEXTO, dados, len(dados))
                ctypes.memmove(m.p + OFF_FRAME, struct.pack("<I", (m.u32(OFF_FRAME) + 1) & 0xFFFFFFFF), 4)
            finally:
                if m.versao >= 0x0002000E:
                    ctypes.memmove(m.p + OFF_BUSY, struct.pack("<i", 0), 4)
            self.ativo, self.slot, self.ultimo, self.erro = True, i, texto, ""
            return True

    def liberar(self):
        """Zera o(s) slot(s) que são nossos (como o ReleaseOSD do SDK). Seguro de chamar sempre."""
        self.ativo, self.ultimo = False, ""
        with _Mapa() as m:
            if not m.ok:
                return
            tam = m.u32(OFF_OSD_ENTRY)
            busy = m.versao >= 0x0002000E
            if busy:
                for _ in range(20):               # espera curta pelo 'ocupado'
                    if _CAS(m.p + OFF_BUSY, 1, 0) == 0:
                        break
                    import time
                    time.sleep(0.005)
                else:
                    busy = False
            try:
                for i in range(1, m.n_slots()):
                    s = m.slot(i)
                    if _txt(s + OFF_SLOT_DONO, TAM_DONO) == DONO:
                        ctypes.memset(s, 0, tam)
                        ctypes.memmove(m.p + OFF_FRAME, struct.pack("<I", (m.u32(OFF_FRAME) + 1) & 0xFFFFFFFF), 4)
            finally:
                if busy:
                    ctypes.memmove(m.p + OFF_BUSY, struct.pack("<i", 0), 4)


# ---------------------------------------------------------------- texto do OSD
def _limpa(s: str, n: int = 24) -> str:
    s = (s or "").replace("<", "").replace(">", "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "."


def _hex(c) -> str:
    return "%02X%02X%02X" % tuple(c[:3])


def montar_osd(d: dict, fps: dict | None, it: dict, unidade: str, titulo: str, nome_cpu: str,
               acento, cores: dict) -> str:
    """Monta o texto com tags do RTSS (<C0=RRGGBB> cor, <C> volta ao padrão). Sem <P=>/<S>: posição e escala são as do RTSS.
    Mesma ordem do overlay do widget: título, FPS, CPU (+RAM), GPU (+VRAM), bateria, rede, ventoinhas. Linhas curtas."""
    def t(c):
        return f"{c * 9 / 5 + 32:.0f}°F" if unidade == "F" else f"{c:.0f}°C"

    L: list[str] = []
    cab = f"<C0={_hex(acento)}><C1={_hex(cores['cpu'])}><C2={_hex(cores['gpu'])}><C3={_hex(cores['bat'])}><C4={_hex(cores['fps'])}>"
    if it.get("titulo", True):
        L.append(f"<C0>{_limpa(titulo, 22)}<C>")
    if fps and (it.get("fps") or it.get("frametime")):
        partes = []
        if it.get("fps"):
            partes.append(f"<C4>FPS<C> {fps['fps']:.0f}")
        if it.get("frametime") and fps.get("frametime"):
            partes.append(f"{fps['frametime']:.1f} ms".replace(".", ","))
        if it.get("media") and fps.get("media"):
            partes.append(f"méd {fps['media']:.0f}")
        if it.get("low1") and fps.get("low1"):
            partes.append(f"1% {fps['low1']:.0f}")
        L.append("  ".join(partes))
    gp = next((g for g in d.get("gpus", []) if g.get("dedicada")), None) or (d.get("gpus") or [None])[0]

    if it.get("cpu") and "cpu_uso" in d:
        L.append(f"<C1>CPU<C> {_limpa(nome_cpu, 22)}")
        p = [f"{d['cpu_uso']:.0f}%"]
        if it.get("temps") and d.get("cpu_temp_real") and d.get("cpu_temp") is not None:
            p.append(t(d["cpu_temp"]))
        if it.get("clocks") and d.get("cpu_mhz"):
            p.append(f"{d['cpu_mhz']:.0f} MHz")
        if it.get("watts") and d.get("cpu_watts") is not None:
            p.append(f"{d['cpu_watts']:.0f} W")
        L.append("  ".join(p))
    if it.get("ram") and "ram_uso" in d:
        L.append(f"<C1>RAM<C> {d['ram_usada']:.1f}/{d['ram_total']:.0f} GB  {d['ram_uso']:.0f}%".replace(".", ","))
    if it.get("gpu") and gp and gp.get("uso") is not None:
        L.append(f"<C2>GPU<C> {_limpa(gp['nome'], 22)}")
        p = [f"{gp['uso']:.0f}%"]
        if it.get("temps") and gp.get("temp") is not None:
            p.append(t(gp["temp"]))
        if it.get("clocks") and gp.get("mhz"):
            p.append(f"{gp['mhz']:.0f} MHz")
        if it.get("watts") and gp.get("watts") is not None:
            p.append(f"{gp['watts']:.0f} W")
        L.append("  ".join(p))
        if it.get("vram") and gp.get("vram_usada") is not None:
            tot = gp.get("vram_total")
            L.append((f"<C2>VRAM<C> {gp['vram_usada']:.1f}/{tot:.0f} GB" if tot else f"<C2>VRAM<C> {gp['vram_usada']:.1f} GB").replace(".", ","))
    if it.get("bateria") and d.get("bat_pct") is not None:
        sufixo = " (carregando)" if d.get("bat_ligada") else ""
        if d.get("bat_resta") and not d.get("bat_ligada"):
            s = int(d["bat_resta"])
            sufixo = f" ({s // 3600}h{(s % 3600) // 60:02d})"
        L.append(f"<C3>BAT<C> {d['bat_pct']:.0f}%{sufixo}")
    if it.get("rede") and "rede_down" in d:
        import monitor as M
        L.append(f"DL {M.fmt_vel(d['rede_down'])}  UL {M.fmt_vel(d['rede_up'])}")
    if it.get("ventoinhas") and d.get("ventoinhas"):
        L.append("  ".join(f"V{i + 1} {f['rpm']:.0f} rpm" for i, f in enumerate(d["ventoinhas"][:3])))
    return cab + "\n".join(L)

