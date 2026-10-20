"""Estatísticas descritivas e testes sobre o conjunto de teste (somente leitura).

Gráficos do painel: boxplot + Mann-Whitney, histogramas, matriz de correlação de Pearson
e dispersão com reta ajustada. Sem SciPy: postos médios e aproximação normal com
correção de empates. Com dezenas de milhares de proteínas, quase toda diferença dá
p < 0,001; por isso o tamanho do efeito (delta de Cliff) acompanha cada teste.
"""
from __future__ import annotations

import csv
import json
import math
import threading
from pathlib import Path

import numpy as np

from .core import exigir

VERSAO = 1
ESSENCIAIS = "HILKMFTWV"
AMOSTRA_PONTOS = 300     # pontos sobrepostos em cada caixa
AMOSTRA_DISPERSAO = 1500
LIMITES = [
    "Dados: conjunto de teste (grupos nunca vistos no treino).",
    "Mann-Whitney com aproximação normal; delta de Cliff: |d| < 0,15 desprezível, < 0,33 pequeno, < 0,47 médio, maior = grande.",
    "Correlação não indica causa. O rótulo Completa/Incompleta é definido pela presença dos 9 aminoácidos, então a composição se relaciona com ele por construção.",
]

_trava = threading.Lock()
_memoria = {}


def _postos(x):
    _, inv, cont = np.unique(x, return_inverse=True, return_counts=True)
    fim = np.cumsum(cont)
    return ((fim - cont + 1 + fim) / 2.0)[inv], cont


def mann_whitney(a, b):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    n1, n2 = len(a), len(b)
    if not n1 or not n2:
        return None
    r, empates = _postos(np.concatenate([a, b]))
    u1 = float(r[:n1].sum() - n1 * (n1 + 1) / 2)
    n = n1 + n2
    var = n1 * n2 / 12.0 * ((n + 1) - float((empates ** 3 - empates).sum()) / (n * (n - 1))) if n > 1 else 0
    z = (u1 - n1 * n2 / 2.0) / math.sqrt(var) if var > 0 else 0.0
    delta = 2.0 * u1 / (n1 * n2) - 1.0
    d = abs(delta)
    efeito = "desprezível" if d < .147 else "pequeno" if d < .33 else "médio" if d < .474 else "grande"
    return {"u": u1, "z": round(z, 3), "p": math.erfc(abs(z) / math.sqrt(2)), "delta_cliff": round(delta, 4),
            "efeito": efeito, "n": [n1, n2]}


def _caixa(v, rng):
    v = np.asarray(v, np.float64)
    q1, med, q3 = np.percentile(v, [25, 50, 75])
    iqr = q3 - q1
    dentro = v[(v >= q1 - 1.5 * iqr) & (v <= q3 + 1.5 * iqr)]
    amostra = rng.choice(v, min(AMOSTRA_PONTOS, len(v)), replace=False) if len(v) else v
    return {"n": int(len(v)), "q1": float(q1), "mediana": float(med), "q3": float(q3), "media": float(v.mean()),
            "dp": float(v.std(ddof=1)) if len(v) > 1 else 0.0,
            "min": float(dentro.min()), "max": float(dentro.max()),
            "pontos": [round(float(x), 4) for x in amostra]}


def _histograma(v, mascara, bordas, nomes):
    return {"bordas": [float(x) for x in bordas],
            "series": [{"nome": nome, "n": int(m.sum()), "contagens": np.histogram(v[m], bordas)[0].tolist()}
                       for nome, m in zip(nomes, mascara)]}


def calcular(base: Path, particoes: Path, predicoes: Path, nome: str):
    exigir(predicoes.is_file(), "Esta base ainda não tem predições de teste. Conclua o treino primeiro.")
    idx, rotulo, escore, correto = [], [], [], []
    with open(predicoes, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            idx.append(int(row["indice_global"]))
            rotulo.append(row["rotulo_regra"] == "Completa")
            escore.append(float(row["escore_completa"]))
            correto.append(row["correto"] == "True")
    exigir(len(idx) >= 10, "Poucas predições de teste para estatística.")
    idx = np.asarray(idx)
    pos = {i: k for k, i in enumerate(idx.tolist())}
    rotulo, escore, correto = np.asarray(rotulo), np.asarray(escore), np.asarray(correto)
    comp = np.zeros(len(idx))
    uid_pos = {}
    with open(base / "indice.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            k = pos.get(int(row["indice_global"]))
            if k is not None:
                comp[k] = int(row["tamanho"])
                uid_pos[row["uid"]] = k
    frac = np.zeros((len(idx), len(ESSENCIAIS)))
    with open(base / "sequencias.fasta", encoding="utf-8") as f:
        atual, partes = None, []

        def fechar():
            if atual is not None:
                s = "".join(partes)
                if s:
                    frac[atual] = [100.0 * s.count(a) / len(s) for a in ESSENCIAIS]
        for linha in f:
            if linha.startswith(">"):
                fechar()
                atual, partes = uid_pos.get(linha[1:].split()[0]), []
            elif atual is not None:
                partes.append(linha.strip())
        fechar()
    g = np.asarray(np.load(particoes / "grupos_por_linha.npy", mmap_mode="r"))
    _, inv, cont = np.unique(g, return_inverse=True, return_counts=True)
    tam_grupo = cont[inv][idx].astype(np.float64)
    confianca = np.maximum(escore, 1 - escore)
    rng = np.random.default_rng(42)
    comp_c, comp_i = comp[rotulo], comp[~rotulo]
    caixas = {
        "comprimento": {"titulo": "Comprimento (resíduos) por tipo nutricional", "unidade": "resíduos",
                        "grupos": [dict(_caixa(comp_c, rng), nome="Completa"), dict(_caixa(comp_i, rng), nome="Incompleta")],
                        "teste": mann_whitney(comp_c, comp_i)},
        "confianca": {"titulo": "Confiança do MLP: acertos × erros", "unidade": "confiança (0,5 a 1)",
                      "grupos": [dict(_caixa(confianca[correto], rng), nome="Acertos"),
                                 dict(_caixa(confianca[~correto], rng), nome="Erros")],
                      "teste": mann_whitney(confianca[correto], confianca[~correto])},
    }
    hist = {
        "comprimento": dict(_histograma(comp, [rotulo, ~rotulo], np.arange(0, 513, 16), ["Completa", "Incompleta"]),
                            titulo="Comprimento por tipo nutricional", eixo="resíduos"),
        "escore": dict(_histograma(escore, [rotulo, ~rotulo], np.linspace(0, 1, 21), ["Completa", "Incompleta"]),
                       titulo="Escore 'Completa' do MLP por rótulo real", eixo="escore do MLP"),
    }
    nomes = ["comprimento"] + ["% " + a for a in ESSENCIAIS] + ["escore MLP", "log10 tam. grupo"]
    matriz_dados = np.column_stack([comp, frac, escore, np.log10(tam_grupo)])
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(matriz_dados, rowvar=False)
    corr = np.nan_to_num(corr)
    sel = rng.choice(len(idx), min(AMOSTRA_DISPERSAO, len(idx)), replace=False)
    inclinacao, intercepto = np.polyfit(comp, escore, 1)
    pares = [(abs(corr[i, j]), i, j) for i in range(len(nomes)) for j in range(i + 1, len(nomes))]
    forte = max(pares)
    return {"assinatura": None, "base": nome, "n": int(len(idx)), "acuracia": float(correto.mean()),
            "caixas": caixas, "histogramas": hist,
            "correlacao": {"variaveis": nomes, "matriz": [[round(float(x), 3) for x in l] for l in corr],
                           "par_mais_forte": [nomes[forte[1]], nomes[forte[2]], round(float(corr[forte[1], forte[2]]), 3)]},
            "dispersao": {"x": "comprimento (resíduos)", "y": "escore 'Completa' do MLP",
                          "pontos": [[int(comp[k]), round(float(escore[k]), 4), bool(rotulo[k])] for k in sel.tolist()],
                          "reta": [float(inclinacao), float(intercepto)],
                          "r": round(float(np.corrcoef(comp, escore)[0, 1]), 3)},
            "limites": LIMITES}


def _assinatura(*arquivos):
    return [VERSAO] + [[a.name, a.stat().st_size, int(a.stat().st_mtime)] for a in arquivos]


def obter(executor, ident):
    ident = ident or "original"
    with _trava:
        if ident == "original":
            c = executor.c
            base, part, pred = c.caminhos["base"], c.caminhos["particoes"], c.caminhos["modelo"] / "predicoes_teste.csv"
            exigir(pred.is_file(), "Predições de teste do milhão não encontradas.")
            assinatura = _assinatura(pred, part / "grupos_por_linha.npy", base / "indice.csv")
            cache = c.raiz / "dados/sistema_tcc/estatisticas_original.json"
            if cache.is_file():
                try:
                    dados = json.loads(cache.read_text(encoding="utf-8"))
                    if dados.get("assinatura") == assinatura:
                        return dados
                except (ValueError, OSError):
                    pass
            dados = calcular(base, part, pred, "Base original · 1 milhão (teste)")
            dados["assinatura"] = assinatura
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache.with_suffix(".tmp")
                tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
                tmp.replace(cache)
            except OSError:
                pass
            return dados
        row, _ = executor.execucoes.obter(ident)
        pasta = Path(row["pasta"])
        pred = pasta / "modelo/predicoes_teste.csv"
        chave = (ident, pred.stat().st_mtime if pred.is_file() else 0)
        if chave not in _memoria:
            _memoria.clear()
            _memoria[chave] = calcular(pasta / "base", pasta / "particoes", pred, "Execução " + ident + " (teste)")
        return _memoria[chave]
