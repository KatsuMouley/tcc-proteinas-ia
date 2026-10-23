"""Integra o experimento EC7 (experimentos/ec7) ao painel, sem alterar o modelo EC 2 x EC 3.

- localiza o treino EC7 concluido mais recente em dados/experimento_ec7/;
- resume suas metricas para a tela Explorar e analisar;
- roda as etapas do experimento em segundo plano (uma por vez), com log;
- fornece os pesos em NumPy para colorir o mapa pelas 7 classes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .core import exigir

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "dados/experimento_ec7"
SCRIPT = RAIZ / "experimentos/ec7/rodar_ec7.py"
LOG = SAIDA / "ultima_execucao_painel.log"
ACOES = ("coletar", "preparar", "treinar", "continuar", "tudo")
ROTULOS = {"Oxidorredutase": "EC 1", "Transferase": "EC 2", "Hidrolase": "EC 3", "Liase": "EC 4",
           "Isomerase": "EC 5", "Ligase": "EC 6", "Translocase": "EC 7"}
LIMITES = [
    "Experimento separado do modelo EC 2 × EC 3: 3.500 enzimas revisadas do Swiss-Prot (500 por classe), até 512 resíduos.",
    "Proteínas com mais de uma classe EC foram excluídas. O modelo sempre escolhe uma das 7 e não reconhece proteínas que não são enzimas.",
    "Acaso com 7 classes = 14,3%. Compare a acurácia balanceada com esse valor, não com os 86% do modelo binário.",
]


def _ler(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def ultimo_treino():
    """(pasta, relatorio) do treino EC7 concluido mais recente, ou (None, None)."""
    if not SAIDA.is_dir():
        return None, None
    candidatos = sorted(SAIDA.glob("swissprot_*/preparacao_ec_*/treino_ec_*"), key=lambda p: p.name, reverse=True)
    for pasta in candidatos:
        r = _ler(pasta / "relatorio_treino_ec.json")
        if r.get("ok") is True and (pasta / "modelo_ec7.pt").is_file() and len(r.get("classes", [])) == 7:
            return pasta, r
    return None, None


def resumo():
    pasta, r = ultimo_treino()
    if not r:
        return {"disponivel": False}
    t, cv = r["particao_fixa"]["teste_mlp"], r["validacao_cruzada_5_dobras_por_grupo"]
    return {"disponivel": True, "pasta": str(pasta.relative_to(RAIZ)), "classes": r["classes"],
            "codigos": [ROTULOS.get(c, "") for c in r["classes"]], "proteinas": r["proteinas"],
            "rotulos": r["rotulos"], "acaso": r.get("acaso", 1 / 7), "segundos": r.get("segundos"),
            "teste": {k: t[k] for k in ("n", "acuracia", "acuracia_balanceada", "f1_macro",
                                        "matriz_confusao_linhas_reais_colunas_previstas", "sensibilidade_por_classe")},
            "cv": {k: cv[k] for k in ("acuracia_balanceada_media", "acuracia_balanceada_dp", "f1_macro_media", "f1_macro_dp")},
            "cv_dobras": [d["acuracia_balanceada"] for d in cv["dobras"]],
            "melhor_epoca": r["particao_fixa"]["melhor_epoca"], "limites": LIMITES}


def carregar_torch(torch, dispositivo):
    """Modelo EC7 para a consulta (PyTorch). None se nao houver treino concluido."""
    pasta, r = ultimo_treino()
    if not r:
        return None
    cp = torch.load(pasta / "modelo_ec7.pt", map_location="cpu", weights_only=True)
    exigir(list(cp.get("classes", [])) == r["classes"] and list(cp.get("arquitetura", [])) == [320, 64, 7],
           "Checkpoint EC7 incompativel.")
    mlp = torch.nn.Sequential(torch.nn.Linear(320, 64), torch.nn.ReLU(), torch.nn.Linear(64, 7)).to(dispositivo)
    mlp.load_state_dict(cp["estado"])
    mlp.eval()
    s = resumo()
    return {"mlp": mlp, "media": cp["media"].float().to(dispositivo), "dp": cp["dp"].float().to(dispositivo),
            "classes": r["classes"], "metricas": {"cv_media": s["cv"]["acuracia_balanceada_media"],
            "cv_dp": s["cv"]["acuracia_balanceada_dp"], "teste": s["teste"]["acuracia_balanceada"], "acaso": s["acaso"]},
            "pasta": s["pasta"]}


def pesos_numpy():
    """(classes, (w0, b0, w2, b2, media, dp)) em float64 para o mapa; None sem treino ou sem PyTorch."""
    pasta, r = ultimo_treino()
    if not r:
        return None
    try:
        import numpy as np
        import torch
        cp = torch.load(pasta / "modelo_ec7.pt", map_location="cpu", weights_only=True)
        e = cp["estado"]
        return r["classes"], tuple(t.detach().float().numpy().astype(np.float64)
                                   for t in (e["0.weight"], e["0.bias"], e["2.weight"], e["2.bias"], cp["media"], cp["dp"]))
    except Exception:
        return None


def assinatura():
    pasta, _ = ultimo_treino()
    return pasta.name if pasta else None


class Gerenciador:
    """Roda uma acao do experimento EC7 por vez, em segundo plano."""

    def __init__(self):
        self.proc = None
        self.acao = None
        self.trava = threading.Lock()

    def rodando(self):
        return self.proc is not None and self.proc.poll() is None

    def iniciar(self, obj):
        with self.trava:
            exigir(not self.rodando(), "Já há uma etapa do experimento EC7 em andamento.")
            exigir(set(obj) == {"acao"} and obj["acao"] in ACOES, "Ação EC7 inválida.")
            exigir(SCRIPT.is_file(), "experimentos/ec7/rodar_ec7.py não encontrado.")
            SAIDA.mkdir(parents=True, exist_ok=True)
            log = LOG.open("w", encoding="utf-8")
            log.write(time.strftime("%d/%m/%Y %H:%M:%S") + " · EC7 " + obj["acao"] + "\n")
            log.flush()
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            self.proc = subprocess.Popen([sys.executable, "-u", str(SCRIPT), obj["acao"]], cwd=RAIZ, stdout=log,
                                         stderr=subprocess.STDOUT, env=env,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.acao = obj["acao"]
            return {"ok": True, "acao": self.acao}

    def estado(self):
        linhas = LOG.read_text(encoding="utf-8", errors="replace").splitlines() if LOG.is_file() else []
        # Os embeddings imprimem uma linha a cada 10 proteinas; mostra so a ultima delas.
        compacto = []
        for l in linhas:
            if l.startswith("GPU: ") and compacto and compacto[-1].startswith("GPU: "):
                compacto[-1] = l
            else:
                compacto.append(l)
        return {"ok": True, "rodando": self.rodando(), "acao": self.acao,
                "codigo_saida": None if self.proc is None or self.rodando() else self.proc.returncode,
                "log": compacto[-60:], "acoes": ACOES, "resultado": resumo()}
