"""Explorar representantes: mapa 2D dos embeddings ESM-2 com os detalhes de cada proteína.

Somente leitura: não altera bases, execuções nem modelos. Cada ponto é o representante
de um grupo MMseqs2 (50% de identidade). Posição = PCA (2 componentes) dos embeddings,
ajustada numa amostra fixa (semente 42). Proximidade no mapa é aproximada.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import threading
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .core import exigir, ler_json

VERSAO = 1
QUANTIDADES = (10, 50, 100)
CATEGORIAS = {"tipo": ("Completa", "Incompleta"), "ec": ("Transferase", "Hidrolase")}
POOL_MILHAO = 4000      # maiores grupos do milhão considerados no mapa
MEMBROS = 12            # membros listados por grupo no detalhe
AMOSTRA_PCA = 20000
EXIBICAO_EC = {"Hidrolase": "Hidrolase (EC 3)", "Transferase": "Transferase (EC 2)"}
LIMITES = [
    "Cada ponto é o representante de um grupo MMseqs2 (50% de identidade, 80% de cobertura).",
    "Posição: 2 componentes principais (PCA) dos embeddings ESM-2. Pontos próximos tendem a ser parecidos, mas a projeção perde informação.",
    "Classe EC prevista pelo modelo EC 2 × EC 3: ele sempre escolhe uma das duas, mesmo para proteínas de outra classe ou que não são enzimas.",
]

_trava = threading.Lock()
_memoria = {}
_ec = None


def _ec_modelo(raiz):
    """Pesos do modelo EC em NumPy (verificados pelo hash do manifesto). None se indisponível."""
    global _ec
    if _ec is None:
        try:
            import torch
            pasta = raiz / "dados/modelos/classificador_ec2_ec3"
            man = ler_json(pasta / "manifesto_ec.json")
            exigir(hashlib.sha256((pasta / "modelo_ec.pt").read_bytes()).hexdigest() == man["hashes"]["modelo_ec.pt"],
                   "Hash do modelo EC diferente do manifesto.")
            cp = torch.load(pasta / "modelo_ec.pt", map_location="cpu", weights_only=True)
            exigir(list(cp["classes"]) == ["Hidrolase", "Transferase"], "Classes EC inesperadas.")
            e = cp["estado"]
            _ec = tuple(t.detach().float().numpy().astype(np.float64)
                        for t in (e["0.weight"], e["0.bias"], e["2.weight"], e["2.bias"], cp["media"], cp["dp"]))
        except Exception:
            _ec = False
    return _ec or None


def _prever_ec(raiz, x):
    m = _ec_modelo(raiz)
    if m is None or not len(x):
        return None
    w0, b0, w2, b2, mu, dp = m
    h = np.maximum(((np.asarray(x, np.float64) - mu) / dp) @ w0.T + b0, 0)
    z = h @ w2.T + b2
    z -= z.max(axis=1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=1, keepdims=True)  # colunas: Hidrolase, Transferase


def _pca(amostra):
    a = np.asarray(amostra, np.float64)
    mu = a.mean(axis=0)
    _, _, vt = np.linalg.svd(a - mu, full_matrices=False)
    v = vt[:2].copy()
    v *= np.sign(v[np.arange(2), np.abs(v).argmax(axis=1)])[:, None]
    return mu, v


def _completar(raiz, pool, emb, amostra):
    mu, v = _pca(amostra)
    xy = (np.asarray(emb, np.float64) - mu) @ v.T
    p = _prever_ec(raiz, emb)
    for i, item in enumerate(pool):
        item["x"], item["y"] = round(float(xy[i, 0]), 4), round(float(xy[i, 1]), 4)
        if p is not None:
            classe = "Transferase" if p[i, 1] >= p[i, 0] else "Hidrolase"
            item["ec"] = classe
            item["ec_confianca"] = round(float(max(p[i])), 4)
    return p is not None


def _assinatura(*arquivos):
    return [VERSAO] + [[str(a.name), a.stat().st_size, int(a.stat().st_mtime)] for a in arquivos]


def _milhao(c):
    base, grupos, part = c.caminhos["base"], c.caminhos["grupos"], c.caminhos["particoes"]
    arq_g, arq_e = part / "grupos_por_linha.npy", base / "embeddings.npy"
    assinatura = _assinatura(arq_g, arq_e)
    cache = c.raiz / "dados/sistema_tcc/explorar_original.json"
    if cache.is_file():
        try:
            dados = json.loads(cache.read_text(encoding="utf-8"))
            if dados.get("assinatura") == assinatura and (dados.get("ec_ok") or _ec_modelo(c.raiz) is None):
                return dados
        except (ValueError, OSError):
            pass
    g = np.asarray(np.load(arq_g, mmap_mode="r"))
    reps, cont = np.unique(g, return_counts=True)
    ordem = np.lexsort((reps, -cont))[:POOL_MILHAO]
    pool_ix, pool_tam = reps[ordem], cont[ordem]
    por_grupo = np.argsort(g, kind="stable")
    g_ord = g[por_grupo]
    membros = {}
    for r in pool_ix.tolist():
        ini = int(np.searchsorted(g_ord, r))
        ms = [int(m) for m in por_grupo[ini:ini + MEMBROS + 1] if m != r][:MEMBROS]
        membros[r] = ms
    precisa = set(pool_ix.tolist()).union(*membros.values())
    info = {}
    with open(base / "indice.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            i = int(row["indice_global"])
            if i in precisa:
                info[i] = row
    particao = {}
    alvo = set(pool_ix.tolist())
    with open(part / "particoes.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            i = int(row["indice_global"])
            if i in alvo:
                particao[i] = row["particao"]
    uids = {info[i]["uid"]: i for i in alvo}
    seqs, atual = {}, None
    with open(grupos / "global_rep_seq.fasta", encoding="utf-8") as f:
        for linha in f:
            if linha.startswith(">"):
                atual = linha[1:].split()[0]
                atual = atual if atual in uids else None
                if atual:
                    seqs[atual] = []
            elif atual:
                seqs[atual].append(linha.strip())
    pool = []
    for r, tam in zip(pool_ix.tolist(), pool_tam.tolist()):
        row = info[r]
        pool.append({"uid": row["uid"], "id": row["id_original"], "grupo": row["uid"], "tamanho_grupo": tam,
                     "tipo": row["Tipo_Nutricional"], "particao": particao.get(r), "comprimento": int(row["tamanho"]),
                     "origem": row["arquivo_origem"], "descricao": None, "sequencia": "".join(seqs.get(row["uid"], [])),
                     "membros": [info[m]["id_original"] for m in membros[r] if m in info]})
    e = np.load(arq_e, mmap_mode="r")
    emb = e[np.asarray(pool_ix)]
    rng = np.random.default_rng(42)
    amostra = e[np.sort(rng.choice(e.shape[0], min(AMOSTRA_PCA, e.shape[0]), replace=False))]
    ec_ok = _completar(c.raiz, pool, emb, amostra)
    dados = {"assinatura": assinatura, "ec_ok": ec_ok, "base": "Base original · 1 milhão",
             "proteinas": int(len(g)), "grupos": int(len(reps)),
             "selecao": "Os " + format(len(pool), ",").replace(",", ".") + " maiores grupos do milhão (mais membros primeiro).",
             "pool": pool}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache)
    except OSError:
        pass
    return dados


def _execucao(execucoes, ident):
    row, _ = execucoes.obter(ident)
    pasta = Path(row["pasta"])
    banco, arq_e = pasta / "banco.sqlite3", pasta / "base/embeddings.npy"
    exigir(banco.is_file() and arq_e.is_file(), "Esta execução ainda não tem banco e embeddings. Conclua o fluxo primeiro.")
    db = sqlite3.connect(banco.as_uri() + "?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        rows = [dict(x) for x in db.execute(
            "SELECT uid,id_original,descricao,origem,sequencia,comprimento,rotulo,indice_embedding,uid_base,grupo_global,particao "
            "FROM proteinas WHERE indice_embedding IS NOT NULL AND grupo_global IS NOT NULL ORDER BY uid")]
    finally:
        db.close()
    exigir(rows, "O banco desta execução não tem proteínas com grupo e embedding.")
    tam = Counter(r["grupo_global"] for r in rows)
    membros = defaultdict(list)
    for r in rows:
        if r["uid_base"] != r["grupo_global"] and len(membros[r["grupo_global"]]) < MEMBROS:
            membros[r["grupo_global"]].append(r["id_original"] or r["uid"])
    reps = sorted((r for r in rows if r["uid_base"] == r["grupo_global"]),
                  key=lambda r: (-tam[r["grupo_global"]], r["uid"]))
    pool = [{"uid": r["uid"], "id": r["id_original"] or r["uid"], "grupo": r["grupo_global"],
             "tamanho_grupo": tam[r["grupo_global"]], "tipo": r["rotulo"], "particao": r["particao"],
             "comprimento": r["comprimento"], "origem": (r["origem"] or "").replace("\\", "/").split("/")[-1],
             "descricao": r["descricao"], "sequencia": r["sequencia"], "membros": membros[r["grupo_global"]]}
            for r in reps]
    e = np.load(arq_e, mmap_mode="r")
    emb = e[np.asarray([r["indice_embedding"] for r in reps])]
    rng = np.random.default_rng(42)
    amostra = e[np.sort(rng.choice(e.shape[0], min(AMOSTRA_PCA, e.shape[0]), replace=False))]
    ec_ok = _completar(execucoes.c.raiz, pool, emb, amostra)
    return {"ec_ok": ec_ok, "base": "Execução " + ident, "proteinas": len(rows), "grupos": len(tam),
            "selecao": "Todos os grupos da execução (maiores primeiro).", "pool": pool}


def representantes(executor, ident, n, cor):
    exigir(n in QUANTIDADES, "Escolha 10, 50 ou 100 representantes por categoria.")
    exigir(cor in CATEGORIAS, "Agrupe por tipo nutricional ou por classe EC.")
    ident = ident or "original"
    with _trava:
        if ident == "original":
            dados = _milhao(executor.c)
        else:
            row, _ = executor.execucoes.obter(ident)
            banco = Path(row["pasta"]) / "banco.sqlite3"
            chave = (ident, banco.stat().st_mtime if banco.is_file() else 0)
            if chave not in _memoria:
                _memoria.clear()
                _memoria[chave] = _execucao(executor.execucoes, ident)
            dados = _memoria[chave]
    exigir(cor != "ec" or dados["ec_ok"], "Modelo EC indisponível neste PC (PyTorch ou modelo_ec.pt ausente). Use o tipo nutricional.")
    campo = "tipo" if cor == "tipo" else "ec"
    categorias, pontos = [], []
    for nome in CATEGORIAS[cor]:
        itens = [p for p in dados["pool"] if p.get(campo) == nome]
        categorias.append({"nome": nome, "rotulo": EXIBICAO_EC.get(nome, nome) if cor == "ec" else nome,
                           "no_conjunto": len(itens), "exibidos": min(n, len(itens))})
        pontos += [dict(p, categoria=nome) for p in itens[:n]]
    return {"ok": True, "base": dados["base"], "proteinas": dados["proteinas"], "grupos": dados["grupos"],
            "conjunto": len(dados["pool"]), "selecao": dados["selecao"], "cor": cor, "quantidade": n,
            "ec_disponivel": dados["ec_ok"], "categorias": categorias, "pontos": pontos, "limites": LIMITES}
