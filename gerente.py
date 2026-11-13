"""Orquestra detecção de jogo, overlay, FPS, log de sessão, perfis e atalhos globais."""
from __future__ import annotations

import copy
import os
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import diag
import jogo as J
import monitor as M
import rtss
from ajustes import CAMPOS_PERFIL, Ajustes
from assistente import AssistenteTelaCheia
from overlay import Overlay
from web import ServidorWeb


def _snapshot(cfg: dict) -> dict:
    return {k: copy.deepcopy(cfg[k]) for k in CAMPOS_PERFIL if k in cfg}


class GerenteJogo:
    def __init__(self, ctx, app: QApplication, tray: QSystemTrayIcon | None, fonte_janela=None):
        self.ctx, self.cfg, self.app, self.tray = ctx, ctx.cfg, app, tray
        self.detector = J.DetectorJogo(self.cfg["jogo"], fonte_janela or J.janela_em_primeiro_plano)
        self.leitor = J.LeitorPresentMon()
        self.overlay = Overlay(ctx, self.cfg["overlay"])
        self.overlay.ao_salvar = self._posicao_alterada
        self.jogo: dict | None = None
        self.sessao: J.SessaoLog | None = None
        self._dica_dada = False
        self._exclusiva_exe = None   # jogo que esteve em tela cheia exclusiva (o assistente abre ao sair dele)
        self._assistente = None
        self.saida_rtss = rtss.SaidaRTSS()
        self._rtss_excl = False      # o jogo (em primeiro plano) está em tela cheia exclusiva? (lembra ao dar Alt+Tab)
        self._rtss_n = 0
        self._rtss_sem_ver = 0       # segundos seguidos em que o RTSS não enxerga o jogo
        self._rtss_avisou = False
        self._rtss_erro = ""
        self._diag_ult, self._diag_t = None, 0.0
        self._pendente = None     # (instante, SessaoLog) aguardando para ser gravada
        self.silenciado = False   # o usuário ocultou o overlay à mão durante este jogo
        self.forcado = False      # o usuário o mostrou à mão fora de jogo
        self._perfil_antes: dict | None = None
        self.ajustes: Ajustes | None = None
        self.atalhos = J.AtalhosGlobais()
        self.web = ServidorWeb(self.snapshot, self.cfg["web"])
        if self.cfg["web"]["ativo"] and not self.web.iniciar():
            self.cfg["web"]["ativo"] = False
        self._garantir_perfis()
        self.registrar_atalhos()
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    # -- atalhos ---------------------------------------------------------
    def registrar_atalhos(self):
        a = self.cfg["atalhos"]
        falhas = self.atalhos.registrar({"Overlay": (a["overlay"], self.alternar_overlay), "Widget": (a["widget"], self.alternar_widget),
                                         "Ajustes": (a.get("ajustes", "Ctrl+Alt+M"), self.abrir_ajustes),
                                         "Posicao": (a.get("posicao", "Ctrl+Alt+P"), self.editar_posicao)})
        if falhas and self.tray:
            self.tray.showMessage("Atalhos", "Não foi possível registrar: " + ", ".join(falhas) + " (já em uso?)", QSystemTrayIcon.Warning, 6000)

    def editar_posicao(self):
        """Liga/desliga o modo de arrastar o overlay para onde quiser (mostra o overlay se estiver oculto)."""
        if self.overlay.editando:
            self.overlay.editar(False)
            M.salvar_cfg(self.cfg)
            diag.log(f"overlay: posição salva canto={self.cfg['overlay']['canto']} margens=({self.cfg['overlay']['margem_x']},{self.cfg['overlay']['margem_y']}) monitor={self.cfg['overlay']['monitor']}")
            return
        if not self.overlay.isVisible():
            self.mostrar_agora()
            if self.jogo:
                self._prender(self.jogo["hwnd"])
        self.overlay.editar(True)

    def _posicao_alterada(self, evento: str):
        M.salvar_cfg(self.cfg)
        if evento == "concluir":
            self.editar_posicao()
        elif self.ajustes is not None and self.ajustes.isVisible():
            self.ajustes.atualizar_posicao()

    def mostrar_agora(self):
        """Modo de teste: mostra o overlay já, com ou sem jogo (e sem FPS, se o ETW não estiver autorizado)."""
        self.overlay.mostrar()
        self.silenciado, self.forcado = False, True
        self.overlay.atualizar(self.ctx.d, self.leitor.resumo() if self.jogo else None, self.leitor.estado, self.leitor.mensagem, self.jogo, self.leitor.api)
        diag.log("overlay: 'Mostrar overlay agora' acionado pelo usuário (modo de teste)")

    def alternar_overlay(self):
        if self.overlay.isVisible():
            self.overlay.ocultar()
            self.silenciado, self.forcado = True, False
        else:
            self.overlay.mostrar()
            self.silenciado, self.forcado = False, True

    def alternar_widget(self):
        w = self.ctx
        w.hide() if w.isVisible() else (w.show(), w.raise_())

    # -- ciclo principal (1x por segundo) --------------------------------
    def tick(self):
        d = self.ctx.d
        if self._pendente and not self.jogo and time.monotonic() - self._pendente[0] > 180:
            self._fechar_pendente()
        if not d:
            return
        novo = self.detector.tick(d.get("gpu3d_pid", {}))
        alvo = 1.0 if (novo or self.jogo) else float(self.cfg["intervalo"])  # em jogo: 1 s (FPS/overlay); fora: o escolhido
        if self.ctx.coletor.intervalo != alvo:
            self.ctx.coletor.intervalo = alvo
        if novo and not self.jogo:
            self._iniciou(novo)
        elif not novo and self.jogo:
            self._terminou()
        if novo:
            self.jogo = novo
        fps = self.leitor.resumo() if self.jogo else None
        if self.sessao is not None and self.jogo:
            self.sessao.amostra(d, fps)
        self._rtss_tick(d, fps)
        self._so_no_jogo()
        self._diagnostico()
        if self._pendente and not self.jogo and time.monotonic() - self._pendente[0] > 180:
            self._fechar_pendente()
        if self.overlay.isVisible():
            self.overlay.atualizar(d, fps, self.leitor.estado, self.leitor.mensagem, self.jogo, self.leitor.api)

    def _diagnostico(self):
        """Uma linha no log quando algo muda (ou a cada 30 s): janela ativa, decisão e motivo, estado do overlay."""
        fg = self.detector.ultimo_fg or {}
        excl = J.tela_cheia_exclusiva()
        ov = self.overlay
        chave = (fg.get("exe"), bool(self.jogo), self.detector.motivo, ov.isVisible(), bool(ov._alvo), excl, self.leitor.estado)
        agora = time.monotonic()
        if chave == self._diag_ult and agora - self._diag_t < 30:
            return
        self._diag_ult, self._diag_t = chave, agora
        diag.log(f"fg={fg.get('exe', '-')} pid={fg.get('pid', '-')} tela_cheia={fg.get('tela_cheia', '-')} sem_moldura={fg.get('sem_moldura', '-')} "
                 f"3d={fg.get('gpu3d', 0):.1f}% | decisao={'JOGO' if self.jogo else 'nao'} ({self.detector.motivo}) | "
                 f"overlay={'visivel' if ov.isVisible() else 'oculto'} preso_ao_jogo={bool(ov._alvo)} | "
                 f"tela_cheia_exclusiva_D3D={excl} | fps={self.leitor.estado}")
        ov.aviso_exclusiva = bool(self.jogo) and excl
        if self.jogo and excl:
            self._exclusiva_exe = self.jogo["exe"]
        if self.jogo and excl:
            exe = self.jogo["exe"]
            vistos = self.cfg["jogo"].setdefault("dica_exclusiva", [])
            if exe not in vistos:  # uma vez por jogo: o Windows exibe a notificação depois que você sai da tela cheia
                vistos.append(exe)
                M.salvar_cfg(self.cfg)
                self._aviso("Overlay não aparece em tela cheia exclusiva",
                            f"{exe} está em tela cheia exclusiva (o Windows confirma). Troque para “Janela sem bordas” nas opções de vídeo "
                            "do jogo, ou abra a página do celular (menu → Jogo e overlay).")

    def _fechar_pendente(self):
        if self._pendente:
            self._pendente[1].salvar()
            self._pendente = None

    def _so_no_jogo(self):
        """O overlay só fica à vista com o JOGO em primeiro plano (Alt+Tab para outro programa o esconde)."""
        if not self.jogo or self.forcado or self.silenciado:
            return
        if self._usar_rtss():  # o RTSS desenha: a nossa janela fica escondida para não aparecer em dobro
            if self.overlay.isVisible() and not self.overlay.editando:
                self.overlay.ocultar()
            return
        if not (self.cfg["jogo"]["overlay_auto"] and self.cfg["overlay"]["ativo"]):
            return
        fg = self.detector.fonte()
        no_jogo = bool(fg) and fg["pid"] == self.jogo["pid"]
        if no_jogo and not self.overlay.isVisible():
            self.overlay.mostrar()
            self._prender(fg["hwnd"])
        elif not no_jogo and self.overlay.isVisible():
            self.overlay.ocultar()

    def _prender(self, hwnd: int):
        if self.cfg["overlay"].get("preso_ao_jogo", True):
            self.overlay.anexar(hwnd)

    def _iniciou(self, j: dict):
        self.jogo, self.silenciado = j, False
        self.leitor.iniciar(j["pid"])
        if self.cfg["jogo"]["log"]:
            pend = self._pendente
            if pend and pend[1].exe == j["exe"] and time.monotonic() - pend[0] < 180:
                self.sessao, self._pendente = pend[1], None  # voltou ao mesmo jogo (Alt+Tab): continua o mesmo log
            else:
                self._fechar_pendente()
                self.sessao = J.SessaoLog(j["exe"])
        if self.cfg["jogo"]["overlay_auto"] and self.cfg["overlay"]["ativo"] and not self._usar_rtss():
            self.overlay.mostrar()
            self._prender(j["hwnd"])
            if not self.cfg["jogo"].get("dica_vista"):  # uma única vez na vida, não a cada jogo
                self.cfg["jogo"]["dica_vista"] = True
                M.salvar_cfg(self.cfg)
                self._aviso("Overlay ativo", "Se não aparecer sobre o jogo, ele está em tela cheia exclusiva: use “Janela sem bordas” "
                                             "nas opções de vídeo ou abra a página do celular (menu → Jogo e overlay).")
        if self.cfg["jogo"]["perfil_auto"] and "Jogo" in self.cfg["perfis"]:
            self._perfil_antes = _snapshot(self.cfg)
            self.aplicar_perfil("Jogo", persistir=False)

    def _terminou(self):
        if self._exclusiva_exe:  # toast/dialogos ficam escondidos durante o jogo: o assistente abre ao voltar para a área de trabalho
            exe, self._exclusiva_exe = self._exclusiva_exe, None
            QTimer.singleShot(1500, lambda: self.abrir_assistente(exe))
        self.leitor.parar()
        self._rtss_liberar("jogo terminou")
        self._rtss_excl, self._rtss_sem_ver, self._rtss_avisou = False, 0, False
        if not self.forcado:
            self.overlay.ocultar()
        self.silenciado = False
        if self.sessao is not None:
            self._pendente, self.sessao = (time.monotonic(), self.sessao), None  # grava em silêncio depois de 3 min fora do jogo
        if self._perfil_antes is not None:
            self.cfg.update(self._perfil_antes)
            self._perfil_antes = None
            self.ctx.aplicar()
        self.jogo = None

    # -- RTSS (opcional): só envia TEXTO à memória compartilhada oficial; quem desenha (e injeta) é o RTSS ---------
    def _usar_rtss(self) -> bool:
        modo = self.cfg["overlay"].get("modo", "janela")
        if modo == "janela" or not self.jogo:
            return False
        if modo == "rtss":
            return True
        return self._rtss_excl and rtss.rodando()  # automático

    def _rtss_liberar(self, motivo: str = ""):
        if self.saida_rtss.ativo:
            self.saida_rtss.liberar()
            diag.log(f"rtss: slot de OSD liberado ({motivo})")

    def _rtss_tick(self, d: dict, fps: dict | None):
        j = self.jogo
        if j:
            fg = self.detector.fonte()
            if fg and fg["pid"] == j["pid"]:
                self._rtss_excl = J.tela_cheia_exclusiva()
        usar = self._usar_rtss()
        if not usar:
            self._rtss_liberar("modo/jogo mudou")
            return
        self._rtss_n += 1
        if self._rtss_n % 5 == 1:  # a cada 5 s: o RTSS enxerga o processo do jogo? (sem isso o texto não aparece em lugar nenhum)
            vis = rtss.fps_do_jogo(j["pid"])
            self._rtss_sem_ver = 0 if vis else self._rtss_sem_ver + 5
            if vis is None and self._rtss_sem_ver >= 15 and not self._rtss_avisou and rtss.rodando():
                self._rtss_avisou = True
                diag.log(f"rtss: o RTSS não está ativo em {j['exe']} (não aparece na lista de aplicativos dele)")
                self._aviso("RTSS não está desenhando neste jogo",
                            f"O RTSS está aberto, mas não enxerga {j['exe']}. Ele pode estar ignorando o jogo (perfil/lista de exclusão) ou o "
                            "anti-cheat o bloqueou. Este widget só envia o texto ao RTSS.")
        texto = self._rtss_texto(d, fps, j)
        if self.saida_rtss.escrever(texto):
            if self._rtss_erro:
                diag.log("rtss: voltou a escrever no OSD")
            self._rtss_erro = ""
        elif self.saida_rtss.erro != self._rtss_erro:
            self._rtss_erro = self.saida_rtss.erro
            diag.log(f"rtss: não escreveu o OSD — {self._rtss_erro}")

    def _rtss_texto(self, d: dict, fps: dict | None, j: dict | None) -> str:
        from overlay import COR_BAT, COR_CPU, COR_FPS, COR_GPU
        it = dict(self.cfg["overlay"]["itens"])
        f = None
        if self.cfg.get("rtss", {}).get("fps"):  # por padrão o RTSS mostra o FPS dele; aqui só se o usuário pedir
            r = rtss.fps_do_jogo(j["pid"]) if j else None
            f = dict(fps or {}, **{k: r[k] for k in ("fps", "frametime")}) if r else fps
        else:
            it["fps"] = it["media"] = it["low1"] = it["frametime"] = False
        s = self.ctx.coletor.sensores
        c = self.ctx.destaque()
        return rtss.montar_osd(d, f, it, self.cfg["unidade"], self.overlay.titulo, s.nome_cpu_completo if s else "CPU",
                               (c.red(), c.green(), c.blue()), {"cpu": COR_CPU, "gpu": COR_GPU, "bat": COR_BAT, "fps": COR_FPS})

    def rtss_status(self, curto: bool = False) -> str:
        """Texto simples sobre o estado do RTSS (menu e Ajustes)."""
        rodando = rtss.rodando()
        if not rodando:
            if rtss.instalado():
                return "instalado, mas fechado — abra o RTSS" if not curto else "fechado"
            return ("não encontrado — instale o RivaTuner Statistics Server (vem junto com o MSI Afterburner)" if not curto else "não instalado")
        if self.jogo:
            vis = rtss.fps_do_jogo(self.jogo["pid"])
            sit = "vendo o jogo" if vis else "aberto, mas ainda não vê o jogo"
        else:
            sit = "aberto e pronto"
        extra = f" — enviando para o slot {self.saida_rtss.slot}" if self.saida_rtss.ativo else ""
        return ("ativo, " + sit + extra) if not curto else ("ativo" + (" ✓" if self.saida_rtss.ativo else ""))

    def testar_rtss(self):
        """Envia o OSD ao RTSS por 10 s (com ou sem jogo) para você ver se aparece dentro de um jogo."""
        if not rtss.rodando():
            self._aviso("RTSS", "O RTSS não está aberto. " + self.rtss_status())
            return
        d = self.ctx.d or {}
        ok = self.saida_rtss.escrever(self._rtss_texto(d, None, self.jogo))
        diag.log(f"rtss: teste manual de 10 s -> {'enviado' if ok else 'falhou: ' + self.saida_rtss.erro}")
        QTimer.singleShot(10000, lambda: None if self._usar_rtss() else self._rtss_liberar("fim do teste"))
        self._aviso("RTSS", "Texto enviado por 10 s. Veja dentro de um jogo que o RTSS esteja desenhando." if ok else "Não consegui escrever: " + self.saida_rtss.erro)

    # -- página para celular / segundo monitor -------------------------------
    def snapshot(self) -> dict:
        """Dados para a página web (chamado em outra thread; só leitura)."""
        d = self.ctx.d or {}
        s = self.ctx.coletor.sensores
        fps = self.leitor.resumo() if self.jogo else None
        out = {"exclusiva": bool(self.jogo) and J.tela_cheia_exclusiva(), "aparelho": self.overlay.titulo, "unidade": self.cfg["unidade"], "estado_fps": self.leitor.estado,
               "fps": {k: v for k, v in fps.items() if k != "historico"} if fps else None,
               "jogo": {"exe": self.jogo["exe"], "larg": self.jogo["larg"], "alt": self.jogo["alt"], "api": self.leitor.api} if self.jogo else None}
        if "cpu_uso" in d:
            out["cpu"] = {"nome": s.nome_cpu if s else "CPU", "uso": d["cpu_uso"], "temp": d.get("cpu_temp"), "aprox": not d.get("cpu_temp_real"),
                          "mhz": d.get("cpu_mhz"), "watts": d.get("cpu_watts")}
        if "ram_uso" in d:
            out["ram"] = {"usada": d["ram_usada"], "total": d["ram_total"], "pct": d["ram_uso"]}
        out["gpus"] = [{k: g.get(k) for k in ("nome", "uso", "temp", "mhz", "watts", "vram_usada", "vram_total")} for g in d.get("gpus", []) if g.get("dedicada")] \
            or [{k: g.get(k) for k in ("nome", "uso", "temp", "mhz", "watts", "vram_usada", "vram_total")} for g in d.get("gpus", [])[:1]]
        if d.get("bat_pct") is not None:
            out["bateria"] = {"pct": d["bat_pct"], "ligada": d.get("bat_ligada"), "resta": d.get("bat_resta")}
        out["fans"] = d.get("ventoinhas") or []
        if "rede_down" in d:
            out["rede"] = {"down": M.fmt_vel(d["rede_down"]), "up": M.fmt_vel(d["rede_up"])}
        return out

    def alternar_web(self, ativo: bool):
        self.cfg["web"]["ativo"] = bool(ativo)
        if ativo:
            if self.web.iniciar():
                self.mostrar_link_web()
            else:
                self.cfg["web"]["ativo"] = False
                self._aviso("Página do celular", f"Não consegui abrir a porta {self.cfg['web']['porta']}: {self.web.erro}")
        else:
            self.web.parar()
        M.salvar_cfg(self.cfg)

    def mostrar_link_web(self):
        if not self.web.ativo:
            self._aviso("Página do celular", "Ative a página primeiro (menu → Jogo e overlay).")
            return
        self._aviso("Página do celular", f"Abra no celular (mesma rede Wi‑Fi):\n{self.web.url()}\nO Windows pode pedir para liberar a rede privada no Firewall.")

    # -- ajuda quando o overlay não aparece ------------------------------
    def _aviso(self, titulo: str, texto: str):
        if self.tray:
            self.tray.showMessage(titulo, texto, QSystemTrayIcon.Information, 9000)

    def adicionar_em_primeiro_plano(self):
        """Em 5 s lê o programa em primeiro plano (troque para o jogo) e o põe na lista de jogos."""
        def fazer():
            j = J.janela_em_primeiro_plano()
            if not j or not j["exe"] or j["exe"] == "widgetmonitor.exe":
                self._aviso("Lista de jogos", "Não achei um programa em primeiro plano. Tente de novo e troque para o jogo.")
                return
            if j["exe"] not in self.cfg["jogo"]["jogos"]:
                self.cfg["jogo"]["jogos"].append(j["exe"])
                M.salvar_cfg(self.cfg)
            self._aviso("Jogo adicionado", f"{j['exe']} agora sempre mostra o overlay.")
        self._aviso("Lista de jogos", "Troque para o jogo agora: em 5 segundos adiciono o programa em primeiro plano.")
        QTimer.singleShot(5000, fazer)

    def diagnostico(self):
        """Em 5 s mostra o que o detector está vendo (janela ativa, tela cheia, uso de GPU 3D) numa notificação."""
        def fazer():
            j = J.janela_em_primeiro_plano()
            if not j:
                self._aviso("Diagnóstico", "Nenhuma janela em primeiro plano.")
                return
            u3d = self.ctx.d.get("gpu3d_pid", {}).get(j["pid"], 0.0)
            ign = j["exe"] in {x.lower() for x in J.IGNORAR_PADRAO} | {x.lower() for x in self.cfg["jogo"]["ignorar"]}
            lista = j["exe"] in {x.lower() for x in self.cfg["jogo"]["jogos"]}
            self._aviso("Diagnóstico da detecção",
                        f"{j['exe']} | tela cheia: {'sim' if j['tela_cheia'] else 'não'} | GPU 3D: {u3d:.1f}% (mínimo {self.cfg['jogo']['limiar_gpu3d']}%) | "
                        f"na lista: {'sim' if lista else 'não'} | ignorado: {'sim' if ign else 'não'} | jogo detectado: {'sim' if self.jogo else 'não'}")
        self._aviso("Diagnóstico", "Troque para o jogo agora: em 5 segundos mostro o que o detector vê.")
        QTimer.singleShot(5000, fazer)

    # -- logs ------------------------------------------------------------
    def exportar_sessao(self):
        if self.sessao is None:
            if self.tray:
                self.tray.showMessage("Log de sessão", "Nenhuma sessão de jogo em andamento.", QSystemTrayIcon.Information, 4000)
            return None
        arq = self.sessao.salvar()
        if arq and self.tray:
            self.tray.showMessage("Log exportado", arq.name, QSystemTrayIcon.Information, 4000)
        return arq

    def abrir_assistente(self, exe: str = ""):
        exe = exe if isinstance(exe, str) and exe else (self.jogo["exe"] if self.jogo else (self.detector.ultimo_fg or {}).get("exe", ""))
        self._assistente = AssistenteTelaCheia(self.ctx, self, exe)
        self._assistente.show()
        self._assistente.raise_()

    def abrir_diagnostico(self):
        diag.PASTA.mkdir(parents=True, exist_ok=True)
        if not diag.ARQUIVO.exists():
            diag.log("log de diagnóstico criado")
        os.startfile(str(diag.ARQUIVO))

    def abrir_pasta_logs(self):
        os.startfile(str(J.pasta_logs()))

    # -- perfis ----------------------------------------------------------
    def _garantir_perfis(self):
        p = self.cfg["perfis"]
        if "Desktop" not in p:
            p["Desktop"] = _snapshot(self.cfg)
        if "Jogo" not in p:
            j = _snapshot(self.cfg)
            j["mostrar"] = {k: (k in ("cpu", "gpu", "ram")) for k in j["mostrar"]}
            j["escala"], j["opacidade"] = 90, 70
            p["Jogo"] = j

    def salvar_perfil(self, nome: str):
        self.cfg["perfis"][nome] = _snapshot(self.cfg)
        self.cfg["perfil"] = nome
        M.salvar_cfg(self.cfg)

    def aplicar_perfil(self, nome: str, persistir: bool = True):
        p = self.cfg["perfis"].get(nome)
        if not p:
            return
        for k, v in p.items():
            self.cfg[k] = copy.deepcopy(v)
        if persistir:
            self.cfg["perfil"] = nome
            M.salvar_cfg(self.cfg)
        self.ctx.aplicar()

    def excluir_perfil(self, nome: str):
        if nome not in ("Desktop",):
            self.cfg["perfis"].pop(nome, None)
            if self.cfg["perfil"] == nome:
                self.cfg["perfil"] = "Desktop"
            M.salvar_cfg(self.cfg)

    # -- ajustes ---------------------------------------------------------
    def abrir_ajustes(self, aba: str = ""):
        if self.ajustes is None or not self.ajustes.isVisible():
            self.ajustes = Ajustes(self.ctx, self)
        if aba and isinstance(aba, str):
            self.ajustes.ir_para(aba)
        self.ajustes.show()
        self.ajustes.raise_()
        self.ajustes.activateWindow()

    def aplicar_config(self):
        M.salvar_cfg(self.cfg)
        if not self._usar_rtss():
            self._rtss_liberar("configuração mudou")
        self.overlay.aplicar()
        self.ctx.aplicar()
        self.registrar_atalhos()
        w = self.cfg["web"]
        if w["ativo"] and (not self.web.ativo or self.web._srv.server_address[1] != int(w["porta"])):
            self.alternar_web(True)
        elif not w["ativo"] and self.web.ativo:
            self.alternar_web(False)

    def encerrar(self):
        self._rtss_liberar("widget encerrado")
        self.leitor.parar()
        self.web.parar()
        self.atalhos.liberar()
        self._fechar_pendente()
        if self.sessao is not None:
            self.sessao.salvar()
