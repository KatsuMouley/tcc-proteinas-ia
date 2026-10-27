"""Tela Configurações: ajustes deste computador e diagnóstico do ambiente.

Os ajustes ficam em config_local.json (fora do git) e valem ao reiniciar o sistema.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys

from .pastas import detectar
from .core import AJUSTES_LOCAIS, CONFIG_LOCAL, MODELO_ESM, REVISAO_ESM, exigir, ler_json

LIMITES = {"threads_pytorch": (1, 4), "threads_mmseqs": (1, 12)}


def ler(c):
    padrao = ler_json(c.raiz / "sistema_tcc/config.json")
    local_path = c.raiz / CONFIG_LOCAL
    local = ler_json(local_path) if local_path.is_file() else {}
    return {"ok": True, "arquivo_local": str(local_path), "descricoes": AJUSTES_LOCAIS,
            "padrao": {k: padrao.get(k, "auto" if k == "dispositivo" else None) for k in AJUSTES_LOCAIS},
            "local": local, "em_uso": {k: c.valores.get(k) for k in AJUSTES_LOCAIS},
            "nuvens_detectadas": detectar(),
            "reiniciar_para_aplicar": any(local.get(k) != c.valores.get(k) for k in local)}


def salvar(c, obj):
    exigir(isinstance(obj, dict) and obj and set(obj) <= set(AJUSTES_LOCAIS), "Ajuste desconhecido.")
    if "dispositivo" in obj:
        exigir(obj["dispositivo"] in ("auto", "cuda", "cpu"), "Processamento: use auto, cuda ou cpu.")
    for k, (lo, hi) in LIMITES.items():
        if k in obj:
            exigir(type(obj[k]) is int and lo <= obj[k] <= hi, f"{AJUSTES_LOCAIS[k]}: use de {lo} a {hi}.")
    if "wsl" in obj:
        exigir(isinstance(obj["wsl"], str) and 0 < len(obj["wsl"].strip()) <= 100, "Informe o nome da distribuição WSL.")
        obj["wsl"] = obj["wsl"].strip()
    if "reserva_gib" in obj:
        exigir(type(obj["reserva_gib"]) in (int, float) and 0 <= obj["reserva_gib"] <= 500, "Reserva de disco: 0 a 500 GiB.")
    if "pasta_nuvem" in obj:
        exigir(isinstance(obj["pasta_nuvem"], str), "Pasta na nuvem inválida.")
        if obj["pasta_nuvem"].strip():
            from .pastas import validar_pasta
            try:
                obj["pasta_nuvem"] = validar_pasta(obj["pasta_nuvem"])
            except ValueError as e:
                exigir(False, str(e))
        else:
            obj["pasta_nuvem"] = ""
    for k in ("salvar_fontes", "copiar_resultados"):
        if k in obj:
            exigir(type(obj[k]) is bool, f"{AJUSTES_LOCAIS[k]}: use verdadeiro ou falso.")
    if obj.get("salvar_fontes") or obj.get("copiar_resultados"):
        exigir(obj.get("pasta_nuvem"), "Informe a pasta na nuvem antes de escolher o que salvar nela.")
    destino = c.raiz / CONFIG_LOCAL
    atual = ler_json(destino) if destino.is_file() else {}
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(json.dumps({**atual, **obj}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, destino)
    return {**ler(c), "mensagem": "Configurações salvas. Reinicie o sistema (Ctrl+C e iniciar_sistema.cmd) para aplicar."}


def _item(nome, ok, detalhe, uso):
    return {"nome": nome, "ok": ok, "detalhe": detalhe, "uso": uso}


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def diagnosticar(c):
    itens, p = [], c.caminhos
    venv = ".venv" in Path(sys.executable).parts
    itens.append(_item("Python", sys.version_info >= (3, 11), f"{platform.python_version()} · {'ambiente .venv' if venv else sys.executable}", "Tudo"))
    try:
        import torch
        cuda = torch.cuda.is_available()
        gpu = torch.cuda.get_device_name(0) if cuda else None
        itens.append(_item("PyTorch", True, f"{torch.__version__} · CUDA {'disponível: ' + gpu if cuda else 'indisponível'}", "Tudo"))
        escolha = c.valores.get("dispositivo", "auto")
        efetivo = "cpu" if escolha == "cpu" or not cuda else "cuda"
        ok = not (escolha == "cuda" and not cuda)
        itens.append(_item("Processamento", ok, f"configurado: {escolha} · em uso: {'GPU ' + gpu if efetivo == 'cuda' else 'CPU (processador)'}"
                           + ("" if ok else " · escolha auto ou cpu"), "Consulta, embeddings e treino"))
    except Exception as e:
        itens.append(_item("PyTorch", False, f"não importou: {type(e).__name__}. Rode instalar.cmd.", "Tudo"))
    try:
        import transformers
        itens.append(_item("Transformers", True, transformers.__version__, "ESM-2"))
    except Exception as e:
        itens.append(_item("Transformers", False, f"não importou: {type(e).__name__}. Rode instalar.cmd.", "ESM-2"))
    snap = p["cache"] / ("models--" + MODELO_ESM.replace("/", "--")) / "snapshots" / REVISAO_ESM
    itens.append(_item("Modelo ESM-2 em cache", snap.is_dir(), f"{MODELO_ESM} revisão {REVISAO_ESM[:8]}" if snap.is_dir()
                       else "ausente. Rode instalar.cmd (baixa ~30 MB uma única vez).", "Consulta, embeddings"))
    regra = p["modelo"] / "modelo.pt"
    itens.append(_item("Modelo da regra (prova de conceito)", regra.is_file(), str(regra.relative_to(c.raiz)) if regra.is_file()
                       else "ausente. Rode git pull: os modelos vêm no repositório.", "Consulta"))
    ec = c.raiz / "dados/modelos/classificador_ec2_ec3/modelo_ec.pt"
    if ec.is_file():
        try:
            esperado = ler_json(ec.parent / "manifesto_ec.json")["hashes"]["modelo_ec.pt"]
            ok_ec = _sha(ec) == esperado
            itens.append(_item("Modelo EC 2 × EC 3", ok_ec, "hash confere" if ok_ec else "hash NÃO confere com o manifesto", "Consulta"))
        except Exception as e:
            itens.append(_item("Modelo EC 2 × EC 3", False, f"manifesto ilegível: {e}", "Consulta"))
    else:
        itens.append(_item("Modelo EC 2 × EC 3", False, "ausente. Rode git pull: os modelos vêm no repositório.", "Consulta"))
    try:
        from .ec7 import ultimo_treino
        pasta7, _ = ultimo_treino()
    except Exception:
        pasta7 = None
    itens.append(_item("Modelo EC (7 classes)", True if pasta7 else None, str(pasta7.relative_to(c.raiz)) if pasta7
                       else "ausente (opcional). Rode o experimento em Pipeline → Experimento EC7.", "Consulta (experimento)"))
    base = [p["base"] / n for n in ("embeddings.npy", "indice.csv", "sequencias.fasta")]
    tem_base = all(x.is_file() for x in base)
    itens.append(_item("Base do milhão", True if tem_base else None, "presente" if tem_base
                       else "ausente (opcional). A consulta usa os modelos do repositório; a base só é necessária para o mapa e as estatísticas do milhão.",
                       "Mapa e estatísticas do milhão"))
    n_fontes = sum(1 for pasta in p["fontes"] if pasta.is_dir() for x in pasta.rglob("*") if x.suffix.lower() in (".gz", ".zip"))
    itens.append(_item("Arquivos .gz do NCBI", n_fontes > 0 or None, f"{n_fontes} arquivo(s) .gz/.zip em: " + ", ".join(x.name for x in p["fontes"])
                       if n_fontes else "nenhum. Só é preciso para rodar um fluxo novo.", "Fluxo novo"))
    f1 = c.raiz / "fase1_extrator/genomic-data-extractor/agrupar_gz_ncbi.py"
    itens.append(_item("Fase 1 (Filipe)", f1.is_file() or None, "presente em fase1_extrator/" if f1.is_file()
                       else "ausente. instalar.cmd clona o repositório do Filipe (ou veja o README).", "Baixar e agrupar .gz do NCBI"))
    distro = c.valores.get("wsl", "Ubuntu")
    try:
        if os.name == "nt":
            cmd = ["wsl.exe", "--distribution", distro, "--exec", "mmseqs", "version"]
        else:
            exigir(shutil.which("mmseqs"), "mmseqs não está no PATH")
            cmd = ["mmseqs", "version"]
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        saida = r.stdout.decode("utf-8", "replace").replace("\x00", "").strip()
        itens.append(_item("WSL + MMseqs2", r.returncode == 0 and bool(saida), f"{distro}: MMseqs2 {saida}" if r.returncode == 0
                           else f"{distro}: não respondeu. Rode instalar_wsl_mmseqs.cmd (na pasta do projeto).", "Fluxo novo"))
    except Exception as e:
        itens.append(_item("WSL + MMseqs2", False, f"{distro}: {type(e).__name__}. Rode instalar_wsl_mmseqs.cmd (na pasta do projeto).", "Fluxo novo"))
    livre = shutil.disk_usage(c.raiz).free / 1024**3
    reserva = c.valores.get("reserva_gib", 10)
    itens.append(_item("Espaço em disco", livre > reserva + 5, f"{livre:.1f} GiB livres · reserva mínima {reserva} GiB", "Fluxo novo"))
    pronto_consulta = all(i["ok"] for i in itens if i["nome"] in ("Python", "PyTorch", "Processamento", "Transformers",
        "Modelo ESM-2 em cache", "Modelo da regra (prova de conceito)", "Modelo EC 2 × EC 3"))
    pronto_fluxo = pronto_consulta and all(i["ok"] for i in itens if i["nome"] in ("Arquivos .gz do NCBI", "WSL + MMseqs2", "Espaço em disco"))
    return {"ok": True, "itens": itens, "pronto_consulta": pronto_consulta, "pronto_fluxo": pronto_fluxo}
