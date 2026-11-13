"""Log de diagnóstico simples: o que o widget vê (janela ativa, decisão de detecção e motivo, estado do overlay).

Arquivo: %LOCALAPPDATA%\\WidgetMonitor\\logs\\diagnostico.log (gira ao passar de 1 MB). Serve para entender, com evidência,
por que o overlay apareceu ou não apareceu num jogo.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

PASTA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WidgetMonitor" / "logs"
ARQUIVO = PASTA / "diagnostico.log"
LIMITE = 1_000_000


def log(msg: str):
    try:
        PASTA.mkdir(parents=True, exist_ok=True)
        if ARQUIVO.exists() and ARQUIVO.stat().st_size > LIMITE:
            ARQUIVO.replace(ARQUIVO.with_suffix(".1.log"))
        with open(ARQUIVO, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except OSError:
        pass
