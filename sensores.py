"""Leitura dos sensores de hardware (CPU, GPUs, RAM, disco, rede, bateria).

Camadas, da mais leve à mais completa:
  * psutil ........... uso de CPU/RAM/disco/rede/bateria (sem privilégio)
  * NVML ............. NVIDIA: temperatura, uso, VRAM, clock, potência (sem privilégio)
  * PDH (contadores) . frequência real da CPU, uso da Intel Iris Xe, zona térmica ACPI (sem privilégio)
  * LibreHardwareMonitor (opcional) ... temperatura real do pacote/núcleos e potência da CPU;
    exige driver de kernel => só funciona como ADMINISTRADOR.
"""
from __future__ import annotations

import ctypes
import os
import re
import sys
import time
import winreg
from pathlib import Path

import psutil

try:
    import win32pdh
except Exception:  # pragma: no cover
    win32pdh = None

try:
    import pynvml
except Exception:  # pragma: no cover
    pynvml = None


def base_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def eh_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class _Pdh:
    """Contadores de desempenho com nomes em inglês (independem do idioma do Windows)."""

    def __init__(self):
        self.q = win32pdh.OpenQuery()
        self.c: dict[str, object] = {}

    def add(self, nome: str, caminho: str):
        try:
            self.c[nome] = win32pdh.AddEnglishCounter(self.q, caminho)
        except Exception:
            pass

    def coletar(self):
        try:
            win32pdh.CollectQueryData(self.q)
        except Exception:
            pass

    def valor(self, nome: str):
        c = self.c.get(nome)
        if c is None:
            return None
        try:
            return win32pdh.GetFormattedCounterValue(c, win32pdh.PDH_FMT_DOUBLE)[1]
        except Exception:
            return None

    def matriz(self, nome: str) -> dict:
        c = self.c.get(nome)
        if c is None:
            return {}
        try:
            return win32pdh.GetFormattedCounterArray(c, win32pdh.PDH_FMT_DOUBLE)
        except Exception:
            return {}


def _luid_intel() -> str | None:
    """LUID (formato do contador 'GPU Engine') do adaptador Intel integrado."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\DirectX") as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as s:
                        desc = winreg.QueryValueEx(s, "Description")[0]
                        if "intel" in desc.lower():
                            luid = int(winreg.QueryValueEx(s, "AdapterLuid")[0])
                            return f"luid_0x{luid >> 32:08x}_0x{luid & 0xFFFFFFFF:08x}"
                except OSError:
                    continue
    except OSError:
        pass
    return None


def _fabricante_cpu() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            v = winreg.QueryValueEx(k, "VendorIdentifier")[0]
        return "AMD" if "AMD" in v else "Intel" if "Intel" in v else v
    except OSError:
        return ""


def _nome_cpu() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            n = winreg.QueryValueEx(k, "ProcessorNameString")[0]
    except OSError:
        n = "CPU"
    for lixo in ("(R)", "(TM)", "Intel", "AMD", "CPU", "Processor", "with Radeon Graphics", "with Radeon Vega Mobile Gfx"):
        n = n.replace(lixo, "")
    n = re.sub(r"\b\d+-Core\b", "", n)
    n = re.sub(r"@.*$", "", n)  # "@ 3.20GHz" (a frequência aparece à parte)
    return " ".join(n.split()).replace("13th Gen ", "").replace("12th Gen ", "").replace("11th Gen ", "") or "CPU"


def nome_cpu_completo() -> str:
    """'13th Gen Intel(R) Core(TM) i7-13700H' -> 'Intel Core i7-13700H'; 'AMD Ryzen 9 7940HS w/ Radeon 780M Graphics' -> 'AMD Ryzen 9 7940HS'.
    Lê o registro (vale em qualquer PC) e remove marcas, geração, frequência e sufixos."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            n = winreg.QueryValueEx(k, "ProcessorNameString")[0]
    except OSError:
        return "CPU"
    n = re.sub(r"\((R|TM|tm|r)\)", "", n)
    n = re.sub(r"@\s*[\d.,]+\s*[GM]Hz", "", n, flags=re.I)
    n = re.sub(r"\b\d+(st|nd|rd|th)\s+Gen\b", "", n, flags=re.I)
    n = re.sub(r"\b(with|w/)\s+Radeon.*$", "", n, flags=re.I)
    n = re.sub(r"\b\d+-Core\s+Processor\b", "", n, flags=re.I)
    n = re.sub(r"\b(CPU|Processor)\b", "", n, flags=re.I)
    return " ".join(n.split()) or "CPU"


def gpus_registro() -> list[dict]:
    """Adaptadores de vídeo vistos pelo DirectX (qualquer fabricante), com LUID, VRAM dedicada e tipo."""
    achadas: list[dict] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\DirectX") as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as g:
                        desc = winreg.QueryValueEx(g, "Description")[0]
                        luid = int(winreg.QueryValueEx(g, "AdapterLuid")[0])
                        try:
                            vendor = int(winreg.QueryValueEx(g, "VendorId")[0])
                        except OSError:
                            vendor = 0
                        try:
                            vram = int(winreg.QueryValueEx(g, "DedicatedVideoMemory")[0])
                        except OSError:
                            vram = 0
                except (OSError, ValueError):
                    continue
                if vendor == 0x1414 or "basic render" in desc.lower() or "basic display" in desc.lower():
                    continue
                marca = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x1022: "AMD", 0x8086: "Intel"}.get(vendor, "")
                achadas.append({
                    "nome": desc, "marca": marca, "vendor": vendor,
                    "luid": f"luid_0x{luid >> 32:08x}_0x{luid & 0xFFFFFFFF:08x}",
                    "vram_total": vram / 2**30,
                    "dedicada": vram >= 1 << 30,  # APU/Intel integrada reserva bem menos de 1 GB
                })
    except OSError:
        pass
    achadas.sort(key=lambda g: (not g["dedicada"], g["nome"]))
    return achadas


def nome_curto_gpu(n: str) -> str:
    for lixo in ("NVIDIA GeForce ", "NVIDIA ", "AMD ", "Radeon(TM) ", "(R)", "(TM)", " Laptop GPU", " Graphics", "Intel "):
        n = n.replace(lixo, "")
    return " ".join(n.split())


def drivers_video() -> dict[str, str]:
    """Versão do driver por nome do adaptador (classe Display no registro)."""
    r: dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}") as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as g:
                        r[winreg.QueryValueEx(g, "DriverDesc")[0]] = winreg.QueryValueEx(g, "DriverVersion")[0]
                except OSError:
                    continue
    except OSError:
        pass
    return r


def versao_driver_nvidia(v: str) -> str:
    """'32.0.15.6094' -> '560.94' (formato mostrado pela NVIDIA)."""
    p = v.split(".")
    if len(p) == 4 and p[2].isdigit() and p[3].isdigit():
        n = (p[2][-1] + p[3]).rjust(5, "0")
        return f"{int(n[:3])}.{n[3:]}"
    return v


def ler_ventoinhas_hwinfo(nome_mapa: str = "Global\\HWiNFO_SENS_SM2") -> list[dict]:
    """Ventiladores lidos da memória compartilhada do HWiNFO (se instalado, aberto e com
    'Shared Memory Support' ligado em Settings). Somente leitura; nada é instalado nem elevado."""
    import struct

    k32 = ctypes.windll.kernel32
    k32.OpenFileMappingW.restype = ctypes.c_void_p
    k32.MapViewOfFile.restype = ctypes.c_void_p
    k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_size_t]
    k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.OpenFileMappingW(0x0004, False, nome_mapa)  # FILE_MAP_READ
    if not h:
        return []
    achadas: list[dict] = []
    base = k32.MapViewOfFile(h, 0x0004, 0, 0, 0)
    try:
        if base:
            cab = ctypes.string_at(base, 44)
            assin, _ver, _rev, _poll, _o_s, _t_s, _n_s, o_l, t_l, n_l = struct.unpack("<IIIqIIIIII", cab)
            if assin == 0x53695748 and 0 < t_l < 4096 and n_l < 5000:  # 'HWiS'
                bloco = ctypes.string_at(base + o_l, t_l * n_l)
                for i in range(n_l):
                    el = bloco[i * t_l:(i + 1) * t_l]
                    tipo = struct.unpack_from("<I", el, 0)[0]
                    if tipo != 3:  # SENSOR_TYPE_FAN
                        continue
                    nome = el[12 + 128:12 + 256].split(b"\0")[0].decode("utf-8", "replace") or el[12:12 + 128].split(b"\0")[0].decode("utf-8", "replace")
                    valor = struct.unpack_from("<d", el, 12 + 128 + 128 + 16)[0]
                    achadas.append({"nome": nome, "rpm": float(valor)})
    except Exception:
        achadas = []
    finally:
        if base:
            k32.UnmapViewOfFile(base)
        k32.CloseHandle(h)
    return achadas


_RE_LUID = re.compile(r"(luid_0x[0-9a-f]+_0x[0-9a-f]+)")
_RE_PID = re.compile(r"pid_(\d+)_")


class Sensores:
    def __init__(self):
        self.admin = eh_admin()
        self.nome_cpu = _nome_cpu()
        self.nome_cpu_completo = nome_cpu_completo()
        self.nome_gpu = "NVIDIA"
        self.nome_igpu = "Intel Iris Xe"
        self._luid_igpu = _luid_intel()
        self._net = psutil.net_io_counters()
        self._disk = psutil.disk_io_counters()
        self._t = time.monotonic()
        psutil.cpu_percent(percpu=True)

        self.pdh = None
        if win32pdh:
            self.pdh = _Pdh()
            self.pdh.add("freq", r"\Processor Information(_Total)\Processor Frequency")
            self.pdh.add("perf", r"\Processor Information(_Total)\% Processor Performance")
            self.pdh.add("termica", r"\Thermal Zone Information(*)\Temperature")
            self.pdh.add("gpu_eng", r"\GPU Engine(*)\Utilization Percentage")
            self.pdh.coletar()

        self.fabricante_cpu = _fabricante_cpu()
        self.gpus_info = gpus_registro()
        self._drivers = drivers_video()
        if self.pdh:
            self.pdh.add("gpu_mem_ded", r"\GPU Adapter Memory(*)\Dedicated Usage")
            self.pdh.add("gpu_mem_comp", r"\GPU Adapter Memory(*)\Shared Usage")

        self._nvml = None
        self._nvml_todas: list = []
        self.driver_nvidia = ""
        if pynvml:
            try:
                pynvml.nvmlInit()
                for i in range(pynvml.nvmlDeviceGetCount()):
                    self._nvml_todas.append(pynvml.nvmlDeviceGetHandleByIndex(i))
                self._nvml = self._nvml_todas[0] if self._nvml_todas else None
                if self._nvml is not None:
                    n = pynvml.nvmlDeviceGetName(self._nvml)
                    self.nome_gpu = (n.decode() if isinstance(n, bytes) else n).replace("NVIDIA GeForce ", "").replace(" Laptop GPU", "")
                try:
                    dv = pynvml.nvmlSystemGetDriverVersion()
                    self.driver_nvidia = dv.decode() if isinstance(dv, bytes) else dv
                except Exception:
                    pass
            except Exception:
                self._nvml = None
                self._nvml_todas = []

        self._lhm = None
        self._lhm_cpu = None
        if self.admin:
            self._iniciar_lhm()

    # -- LibreHardwareMonitor (somente administrador) -------------------
    def _iniciar_lhm(self):
        try:
            import clr  # pythonnet

            d = str(base_dir() / "lib")
            sys.path.append(d)
            clr.AddReference("LibreHardwareMonitorLib")
            from LibreHardwareMonitor.Hardware import Computer, HardwareType

            pc = Computer()
            pc.IsCpuEnabled = True
            pc.IsMotherboardEnabled = True  # Super I/O / controlador embarcado: onde ficam os ventiladores
            pc.IsControllerEnabled = True
            pc.IsGpuEnabled = True  # AMD/Intel: temperatura, clock e potência (NVIDIA já vem do NVML)
            pc.Open()
            self._lhm = pc
            self._lhm_outros = []
            self._lhm_gpus = []
            for h in pc.Hardware:
                tipo = str(h.HardwareType)
                if h.HardwareType == HardwareType.Cpu:
                    self._lhm_cpu = h
                elif tipo in ("GpuAmd", "GpuIntel"):
                    self._lhm_gpus.append((tipo, h))
                elif tipo != "GpuNvidia":
                    self._lhm_outros.append(h)
        except Exception:
            self._lhm = None

    def _ler_lhm(self) -> dict:
        r: dict = {}
        h = self._lhm_cpu
        if h is None:
            return r
        try:
            h.Update()
            nucleos = []
            for s in h.Sensors:
                v = s.Value
                if v is None:
                    continue
                tipo, nome = str(s.SensorType), str(s.Name)
                if tipo == "Temperature":
                    if nome == "CPU Package":
                        r["cpu_temp"] = float(v)
                    elif nome == "Core Max":
                        r["cpu_temp_max"] = float(v)
                    elif "Core #" in nome and "Distance" not in nome:
                        nucleos.append(float(v))
                elif tipo == "Power" and nome == "CPU Package":
                    r["cpu_watts"] = float(v)
            if "cpu_temp" not in r and "cpu_temp_max" in r:
                r["cpu_temp"] = r["cpu_temp_max"]
            if nucleos:
                r["cpu_temp_nucleos"] = nucleos
        except Exception:
            pass
        return r

    def _ler_lhm_gpu(self, marca: str) -> dict:
        r: dict = {}
        alvo = "GpuAmd" if marca == "AMD" else "GpuIntel"
        for tipo, h in getattr(self, "_lhm_gpus", []):
            if tipo != alvo:
                continue
            try:
                h.Update()
                for sn in h.Sensors:
                    v = sn.Value
                    if v is None:
                        continue
                    t, nome = str(sn.SensorType), str(sn.Name)
                    if t == "Temperature" and "temp" not in r:
                        r["temp"] = float(v)
                    elif t == "Clock" and "Core" in nome and "mhz" not in r:
                        r["mhz"] = float(v)
                    elif t == "Power" and "watts" not in r:
                        r["watts"] = float(v)
            except Exception:
                pass
            break
        return r

    def _ler_ventoinhas(self) -> list[dict]:
        """RPM reais dos ventiladores, se a LibreHardwareMonitor enxergar algum."""
        achadas = []

        def varre(h):
            h.Update()
            for s in h.Sensors:
                if str(s.SensorType) == "Fan" and s.Value is not None:
                    achadas.append({"nome": str(s.Name), "rpm": float(s.Value)})
            for sh in h.SubHardware:
                varre(sh)

        try:
            for h in getattr(self, "_lhm_outros", []):
                varre(h)
        except Exception:
            pass
        return achadas

    def _gpu3d_por_pid(self) -> dict[int, float]:
        """Uso de GPU (engines 3D) por processo: usado para reconhecer jogos."""
        r: dict[int, float] = {}
        if not self.pdh:
            return r
        for nome, v in getattr(self, "_eng", {}).items():
            if "engtype_3D" not in nome:
                continue
            m = _RE_PID.search(nome)
            if m:
                r[int(m.group(1))] = r.get(int(m.group(1)), 0.0) + v
        return r

    def _discos(self) -> list[dict]:
        """Partições e ocupação mudam devagar: relê a cada 15 s."""
        agora = time.monotonic()
        if agora - getattr(self, "_discos_t", -1e9) >= 15:
            self._discos_cache, self._discos_t = self._discos_ler(), agora
        return self._discos_cache

    def _discos_ler(self) -> list[dict]:
        out = []
        try:
            for p in psutil.disk_partitions(all=False):
                if "cdrom" in p.opts.lower() or not p.fstype:
                    continue
                try:
                    du = psutil.disk_usage(p.mountpoint)
                except OSError:
                    continue
                out.append({"letra": p.mountpoint[:2], "uso": du.percent, "livre": du.free / 2**30, "total": du.total / 2**30})
        except Exception:
            pass
        sistema = os.environ.get("SystemDrive", "C:")
        out.sort(key=lambda x: (x["letra"] != sistema, x["letra"]))
        return out[:4]

    def _montar_gpus(self, d: dict) -> list[dict]:
        """Uma entrada por adaptador (NVIDIA, AMD, Intel…): integrada e dedicada, quantas houver."""
        por_luid: dict[str, dict[str, float]] = {}
        if self.pdh:
            for nome, v in getattr(self, "_eng", {}).items():
                m = _RE_LUID.search(nome)
                if m:
                    tipo = nome.rsplit("engtype_", 1)[-1]
                    por_luid.setdefault(m.group(1), {})
                    por_luid[m.group(1)][tipo] = por_luid[m.group(1)].get(tipo, 0.0) + v
            ded = {m.group(1): v for k, v in self.pdh.matriz("gpu_mem_ded").items() if (m := _RE_LUID.search(k))}
            comp = {m.group(1): v for k, v in self.pdh.matriz("gpu_mem_comp").items() if (m := _RE_LUID.search(k))}
        else:
            ded, comp = {}, {}
        lista = []
        nv_idx = 0
        for info in self.gpus_info:
            g = {"nome": nome_curto_gpu(info["nome"]), "nome_completo": info["nome"], "marca": info["marca"], "dedicada": info["dedicada"],
                 "uso": min(max(por_luid.get(info["luid"], {"": 0.0}).values(), default=0.0), 100.0) if self.pdh else None,
                 "temp": None, "mhz": None, "watts": None,
                 "vram_usada": None, "vram_total": info["vram_total"] or None,
                 "driver": self._drivers.get(info["nome"], "")}
            if info["luid"] in ded and info["dedicada"]:
                g["vram_usada"] = ded[info["luid"]] / 2**30
            elif info["luid"] in comp:
                g["vram_usada"] = comp[info["luid"]] / 2**30
                g["vram_total"] = None  # integrada usa memória compartilhada da RAM
            if info["marca"] == "NVIDIA" and nv_idx < len(self._nvml_todas):
                h = self._nvml_todas[nv_idx]
                nv_idx += 1
                try:
                    g["uso"] = float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
                    m = pynvml.nvmlDeviceGetMemoryInfo(h)
                    g["vram_usada"], g["vram_total"] = m.used / 2**30, m.total / 2**30
                    g["temp"] = float(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
                    g["mhz"] = float(pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_GRAPHICS))
                    try:
                        g["watts"] = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
                    except Exception:
                        pass
                except Exception:
                    pass
                if self.driver_nvidia:
                    g["driver"] = versao_driver_nvidia(self.driver_nvidia)
            elif info["marca"] in ("AMD", "Intel") and getattr(self, "_lhm", None):
                g.update({k: v for k, v in self._ler_lhm_gpu(info["marca"]).items()})
            lista.append(g)
        return lista

    # -- coleta principal ----------------------------------------------
    def ler(self) -> dict:
        d: dict = {"admin": self.admin}
        agora = time.monotonic()
        dt = max(agora - self._t, 0.001)
        self._t = agora

        # CPU
        por_thread = psutil.cpu_percent(percpu=True)
        d["cpu_threads"] = por_thread
        d["cpu_uso"] = sum(por_thread) / len(por_thread) if por_thread else 0.0
        d["cpu_temp"] = None
        d["cpu_temp_real"] = False
        d["cpu_watts"] = None
        fans = self._ler_ventoinhas() if self._lhm else []
        if not any(f["rpm"] > 0 for f in fans):  # LHM mudo? tenta o HWiNFO (se o usuário o mantiver aberto)
            hw = ler_ventoinhas_hwinfo()
            if hw:
                fans = hw
                d["ventoinha_fonte"] = "HWiNFO"
        d["ventoinhas"] = fans

        if self.pdh:
            self.pdh.coletar()
            f = self.pdh.valor("freq")
            p = self.pdh.valor("perf")
            if f:
                d["cpu_mhz"] = f
            elif p:
                d["cpu_mhz"] = (psutil.cpu_freq().max or 0) * p / 100.0
            # zona térmica ACPI: Kelvin; é o que o Windows expõe sem driver
            zonas = [v - 273.15 for v in self.pdh.matriz("termica").values() if v > 200]
            if zonas:
                d["cpu_temp"] = max(zonas)
            # Intel iGPU (usa a mesma leitura das engines das demais GPUs: a matriz é grande e cara)
            eng = self._eng = self.pdh.matriz("gpu_eng")
            igpu = None
            if self._luid_igpu:
                por_tipo: dict[str, float] = {}
                for nome, v in eng.items():
                    if self._luid_igpu in nome:
                        tipo = nome.rsplit("engtype_", 1)[-1]
                        por_tipo[tipo] = por_tipo.get(tipo, 0.0) + v
                igpu = min(max(por_tipo.values(), default=0.0), 100.0)
            d["igpu_uso"] = igpu

        if self._lhm:
            lhm = self._ler_lhm()
            if "cpu_temp" in lhm:
                d["cpu_temp"] = lhm["cpu_temp"]
                d["cpu_temp_real"] = True
            if d["cpu_temp_real"]:  # sem o driver o LHM devolve 0 W
                d["cpu_watts"] = lhm.get("cpu_watts")
                d["cpu_temp_nucleos"] = lhm.get("cpu_temp_nucleos")

        # GPU NVIDIA
        if self._nvml:
            g = self._nvml
            try:
                u = pynvml.nvmlDeviceGetUtilizationRates(g)
                m = pynvml.nvmlDeviceGetMemoryInfo(g)
                d["gpu_uso"] = float(u.gpu)
                d["gpu_temp"] = float(pynvml.nvmlDeviceGetTemperature(g, pynvml.NVML_TEMPERATURE_GPU))
                d["gpu_vram_usada"] = m.used / 2**30
                d["gpu_vram_total"] = m.total / 2**30
                d["gpu_mhz"] = float(pynvml.nvmlDeviceGetClockInfo(g, pynvml.NVML_CLOCK_GRAPHICS))
                try:
                    d["gpu_watts"] = pynvml.nvmlDeviceGetPowerUsage(g) / 1000.0
                except Exception:
                    d["gpu_watts"] = None
            except Exception:
                pass

        d["cpu_fabricante"] = self.fabricante_cpu
        d["gpus"] = self._montar_gpus(d)
        d["gpu3d_pid"] = self._gpu3d_por_pid()
        self._eng = {}

        # RAM
        vm = psutil.virtual_memory()
        d["ram_uso"] = vm.percent
        d["ram_usada"] = vm.used / 2**30
        d["ram_total"] = vm.total / 2**30

        # Disco
        try:
            sistema = os.environ.get("SystemDrive", "C:") + "\\"
            du = psutil.disk_usage(sistema)
            d["disco_uso"] = du.percent
            d["disco_livre"] = du.free / 2**30
            d["disco_total"] = du.total / 2**30
            d["disco_letra"] = sistema[:2]
        except Exception:
            pass
        dio = psutil.disk_io_counters()
        if dio and self._disk:
            d["disco_leit"] = (dio.read_bytes - self._disk.read_bytes) / dt
            d["disco_escr"] = (dio.write_bytes - self._disk.write_bytes) / dt
        self._disk = dio

        d["discos"] = self._discos()

        # Rede (leitura cara: no máximo a cada 2 s; entre leituras repete a última taxa)
        if agora - getattr(self, "_net_t", -1e9) >= 2.0:
            net = psutil.net_io_counters()
            dtn = max(agora - getattr(self, "_net_t", agora - 1.0), 0.001) if hasattr(self, "_net_t") else 1.0
            self._net_taxa = ((net.bytes_recv - self._net.bytes_recv) / dtn, (net.bytes_sent - self._net.bytes_sent) / dtn)
            self._net, self._net_t = net, agora
        d["rede_down"], d["rede_up"] = getattr(self, "_net_taxa", (0.0, 0.0))

        # Bateria
        b = psutil.sensors_battery()
        if b:
            d["bat_pct"] = b.percent
            d["bat_ligada"] = bool(b.power_plugged)
            d["bat_resta"] = b.secsleft if b.secsleft and b.secsleft > 0 else None
        return d

    def fechar(self):
        try:
            if self._lhm:
                self._lhm.Close()
            if self._nvml:
                pynvml.nvmlShutdown()
        except Exception:
            pass


if __name__ == "__main__":  # teste rápido no terminal
    import json

    s = Sensores()
    time.sleep(1)
    print(json.dumps(s.ler(), indent=1, default=str))
