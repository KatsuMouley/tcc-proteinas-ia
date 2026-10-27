"""Pasta na nuvem escolhida pelo usuario (Google Drive, OneDrive... sincronizados pelo app deles).

O sistema le e grava nela como numa pasta comum; quem envia para a nuvem e o app de sincronizacao.
O usuario escolhe o que vai para la (instalar.cmd ou tela Configuracoes):
- salvar_fontes: .gz e CSVs do NCBI ficam em <pasta>/arquivos .gz e <pasta>/arquivos csv
  (download, agrupamento da Fase 1 e leitura pelos fluxos novos);
- copiar_resultados: execucoes novas e treinos EC7 rodam no PC e, ao terminar, sao copiados
  para <pasta>/resultados_tcc.
Ficam sempre no projeto: fila (SQLite), logs, cache, .venv e modelos. SQLite em pasta sincronizada
pode corromper, e o MMseqs2 (WSL) nem sempre enxerga unidades virtuais de nuvem.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CHAVES = ("pasta_nuvem", "salvar_fontes", "copiar_resultados")


def ajustes(raiz=RAIZ):
    try:
        d = json.loads((Path(raiz) / "config_local.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def nuvem(raiz=RAIZ):
    v = ajustes(raiz).get("pasta_nuvem")
    return Path(v) if isinstance(v, str) and v.strip() else None


def pastas_fontes(raiz=RAIZ):
    """(pasta dos .gz, pasta dos CSVs) usadas pela Fase 1."""
    n = nuvem(raiz)
    if n and ajustes(raiz).get("salvar_fontes") is True:
        return n / "arquivos .gz", n / "arquivos csv"
    return Path(raiz) / "arquivos .gz", Path(raiz) / "arquivos csv"


def raizes_permitidas(raiz=RAIZ):
    """Pastas de onde o sistema aceita ler fontes: o projeto e, se escolhida, a pasta na nuvem."""
    n = nuvem(raiz)
    return [Path(raiz).resolve()] + ([n.resolve()] if n and ajustes(raiz).get("salvar_fontes") is True else [])


def copiar_resultado(origem, nome, raiz=RAIZ, log=print):
    """Copia uma pasta de resultado concluida para <nuvem>/resultados_tcc/<nome>. Nunca derruba quem chamou."""
    n = nuvem(raiz)
    if not (n and ajustes(raiz).get("copiar_resultados") is True):
        return None
    destino = n / "resultados_tcc" / nome
    try:
        shutil.copytree(origem, destino, dirs_exist_ok=True)
        log(f"Copiado para a nuvem: {destino}\n")
        return destino
    except OSError as e:
        log(f"Aviso: nao foi possivel copiar para a nuvem ({type(e).__name__}: {e}). O resultado continua no PC: {origem}\n")
        return None


def detectar():
    """Pastas de nuvem sincronizadas que parecem existir neste PC (Drive, OneDrive, Dropbox)."""
    import os
    casa = Path.home()
    cand = [os.environ.get("OneDrive"), os.environ.get("OneDriveConsumer"), os.environ.get("OneDriveCommercial"),
            casa / "OneDrive", casa / "Google Drive", casa / "Dropbox"]
    cand += [f"{l}:\\Meu Drive" for l in "DEFGHIJ"] + [f"{l}:\\My Drive" for l in "DEFGHIJ"]
    vistos, achadas = set(), []
    for c in cand:
        if not c:
            continue
        p = Path(c)
        try:
            if p.is_dir() and str(p) not in vistos:
                vistos.add(str(p))
                achadas.append(str(p))
        except OSError:
            pass
    return achadas


def validar_pasta(texto):
    """Confere que a pasta existe e aceita gravacao; devolve o caminho normalizado."""
    p = Path(texto.strip())
    if not p.is_absolute() or not p.is_dir():
        raise ValueError("A pasta na nuvem precisa ser um caminho completo de uma pasta que ja existe (ex.: G:\\Meu Drive\\TCC).")
    teste = p / ".tcc_teste_gravacao"
    try:
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
    except OSError as e:
        raise ValueError(f"Nao foi possivel gravar nessa pasta ({e}).")
    return str(p)
