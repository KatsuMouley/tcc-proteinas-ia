"""Como o MMseqs2 e executado: WSL (Ubuntu), nativo do Windows ou o proprio Linux.

Ajuste `mmseqs_modo` (Configuracoes): "auto" (padrao: nativo se ferramentas/mmseqs existir, senao WSL),
"wsl" ou "nativo". A Fase 1 do Filipe (baixar/agrupar .gz) continua usando o WSL.
"""
from __future__ import annotations

import os
from pathlib import Path

MODOS = ("auto", "wsl", "nativo")


def exe_nativo(raiz):
    base = Path(raiz) / "ferramentas" / "mmseqs"
    if base.is_dir():
        for nome in ("mmseqs.bat", "mmseqs.exe"):
            achados = sorted(base.rglob(nome), key=lambda p: len(p.parts))
            if achados:
                return achados[0]
    return None


def modo(valores, raiz):
    """'linux', 'wsl' ou 'nativo' (este ultimo so existe no Windows)."""
    if os.name != "nt":
        return "linux"
    escolhido = valores.get("mmseqs_modo", "auto")
    if escolhido == "auto":
        return "nativo" if exe_nativo(raiz) else "wsl"
    return escolhido


def distro_wsl(valores, raiz):
    """Nome da distribuicao WSL a usar, ou None se for nativo/Linux."""
    return valores.get("wsl", "Ubuntu") if modo(valores, raiz) == "wsl" else None
