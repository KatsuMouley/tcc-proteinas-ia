"""Inferencia interna reaproveitada da API local ja validada com fixtures.

Reutiliza treinar_classificador_gpu.py, o checkpoint e o cache do projeto.
Nao treina, nao baixa modelos e nao grava sequencias recebidas.
"""

from argparse import ArgumentParser, Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
import sys
import threading
import traceback

PROJETO = Path(__file__).resolve().parents[1]
MODELO = PROJETO / "dados/modelos/classificador_regra_aa_esm2/modelo.pt"
MODELO_EC = PROJETO / "dados/modelos/classificador_ec2_ec3/modelo_ec.pt"
CACHE = PROJETO / "cache/huggingface"
ESSENCIAIS = "HILKMFTWV"
ALFABETO = frozenset("ACDEFGHIKLMNPQRSTVWYBXZUO")
MAX_CORPO = 4096


class Ocupado(Exception):
    pass


def sequencia_valida(valor):
    if not isinstance(valor, str) or not valor.isascii():
        raise ValueError("O campo sequencia deve ser texto com letras de aminoacidos.")
    seq = valor.strip().upper()
    if not 1 <= len(seq) <= 512:
        raise ValueError("Use uma sequencia com 1 a 512 residuos.")
    if not set(seq) <= ALFABETO:
        raise ValueError("Use letras de aminoacidos, sem espacos internos ou cabecalho FASTA. Alfabeto: ACDEFGHIKLMNPQRSTVWYBXZUO.")
    return seq


def pares_unicos(pares):
    objeto = {}
    for chave, valor in pares:
        if chave in objeto:
            raise ValueError("O JSON contem um campo repetido.")
        objeto[chave] = valor
    return objeto


def constante_invalida(_):
    raise ValueError("Use JSON valido, sem NaN ou Infinity.")


class Servico:
    def __init__(self, args):
        import treinar_classificador_gpu as p

        self.p = p
        self.trava = threading.Lock()
        self.relatorio = p.ler_json(args.modelo.parent / "relatorio_treino.json")
        p.exigir(self.relatorio.get("ok") is True, "O treino precisa estar concluido.")
        p.conferir_hash(args.modelo, self.relatorio["hashes_arquivos"]["modelo.pt"])
        self.torch, self.dispositivo = p.configurar_torch(Namespace(
            threads=args.threads, dispositivo=os.environ.get("TCC_DISPOSITIVO", "auto"), semente=42))
        torch = self.torch
        cp = torch.load(args.modelo, map_location="cpu", weights_only=True)
        p.exigir(cp.get("schema") == 1 and cp.get("tipo") == "mlp_regra_nove_aa"
                 and cp.get("classes") == list(p.CLASSES)
                 and cp.get("dimensao") == p.DIMENSAO and cp.get("oculta") == p.OCULTA
                 and cp.get("modelo_esm") == p.MODELO_ESM
                 and cp.get("revisao_esm") == p.REVISAO_ESM, "Checkpoint incompativel.")
        for chave in ("media", "desvio"):
            tensor = cp[chave]
            p.exigir(isinstance(tensor, torch.Tensor) and tensor.shape == (p.DIMENSAO,)
                     and tensor.dtype == torch.float32 and bool(torch.isfinite(tensor).all()),
                     "Estatisticas de normalizacao invalidas.")
        p.exigir(bool((cp["desvio"] > 0).all()), "Desvio de normalizacao invalido.")
        self.media = cp["media"].to(self.dispositivo)
        self.desvio = cp["desvio"].to(self.dispositivo)
        self.mlp = p.criar_modelo(torch).to(self.dispositivo)
        self.mlp.load_state_dict(cp["estado"])
        self.mlp.eval()
        self.ec = self.carregar_ec(MODELO_EC)

        from transformers import AutoTokenizer, EsmModel
        comum = {"revision": p.REVISAO_ESM, "cache_dir": str(args.cache),
                 "local_files_only": True, "trust_remote_code": False}
        self.tokenizador = AutoTokenizer.from_pretrained(p.MODELO_ESM, **comum)
        self.esm = EsmModel.from_pretrained(p.MODELO_ESM, add_pooling_layer=False,
            attn_implementation="eager", use_safetensors=True, **comum).float().to(self.dispositivo).eval()
        self.informacoes = {"ok": True, "dispositivo": str(self.dispositivo),
            "gpu": torch.cuda.get_device_name(self.dispositivo) if self.dispositivo.type == "cuda" else None,
            "modelo_esm": p.MODELO_ESM, "revisao_esm": p.REVISAO_ESM,
            "dimensao_embedding": p.DIMENSAO, "melhor_epoca": cp["melhor_epoca"],
            "threads_cpu_pytorch": args.threads, "download_permitido": False,
            "treinamento_realizado_nesta_execucao": False, "limites": p.LIMITE}

    def carregar_ec(self, caminho):
        """Classificador EC 2 x EC 3 (piloto Swiss-Prot). Opcional: sem o arquivo, a consulta segue so com a regra."""
        if not caminho.is_file():
            return None
        p, torch = self.p, self.torch
        manifesto = p.ler_json(caminho.parent / "manifesto_ec.json")
        p.conferir_hash(caminho, manifesto["hashes"]["modelo_ec.pt"])
        p.exigir(manifesto.get("modelo_esm") == p.MODELO_ESM and manifesto.get("revisao_esm") == p.REVISAO_ESM,
                 "Modelo EC gerado com outro ESM-2.")
        cp = torch.load(caminho, map_location="cpu", weights_only=True)
        p.exigir(list(cp.get("classes", [])) == ["Hidrolase", "Transferase"] and list(cp.get("arquitetura", [])) == [320, 64, 2],
                 "Checkpoint EC incompativel.")
        for chave in ("media", "dp"):
            t = cp[chave]
            p.exigir(isinstance(t, torch.Tensor) and t.shape == (p.DIMENSAO,) and bool(torch.isfinite(t).all()),
                     "Normalizacao do modelo EC invalida.")
        mlp = p.criar_modelo(torch).to(self.dispositivo)
        mlp.load_state_dict(cp["estado"])
        mlp.eval()
        return {"mlp": mlp, "media": cp["media"].float().to(self.dispositivo), "dp": cp["dp"].float().to(self.dispositivo),
                "classes": ["Hidrolase", "Transferase"], "exibicao": manifesto["rotulos_exibicao"],
                "metricas": manifesto["metricas"], "limites": manifesto["limites"]}

    def saude(self):
        return dict(self.informacoes)

    def metricas(self):
        r = self.relatorio
        return {"ok": True, "tipo": "metricas_experimento", "alvo": r["alvo"],
            "selecao_modelo": r["selecao_modelo"], "melhor_epoca": r["melhor_epoca"],
            "particoes": r["proveniencia"]["distribuicao_particoes"],
            "validacao_mlp": r["validacao_melhor_modelo"], "teste_mlp": r["teste_mlp"],
            "referencia_classe_mais_frequente": r["teste_baseline_classe_mais_frequente"],
            "referencia_regra_direta": r["teste_regra_direta"], "limites": r["limites"]}

    def prever(self, valor):
        seq = sequencia_valida(valor)
        if not self.trava.acquire(blocking=False):
            raise Ocupado("A GPU esta processando outra sequencia. Tente novamente.")
        try:
            p, torch = self.p, self.torch
            entradas = self.tokenizador(seq, return_tensors="pt",
                return_special_tokens_mask=True, return_token_type_ids=False, truncation=False)
            especiais = entradas.pop("special_tokens_mask").to(self.dispositivo)
            entradas = {k: v.to(self.dispositivo) for k, v in entradas.items()}
            mascara = (entradas["attention_mask"] * (1 - especiais)).bool()
            p.exigir(int(mascara.sum().item()) == len(seq), "Tokenizacao alterou a quantidade de residuos.")
            with torch.inference_mode():
                vetor = self.esm(**entradas).last_hidden_state[0, mascara[0]].mean(dim=0).unsqueeze(0)
                p.exigir(vetor.shape == (1, p.DIMENSAO) and bool(torch.isfinite(vetor).all()), "Embedding invalido.")
                escores = self.mlp((vetor - self.media) / self.desvio).softmax(dim=1)[0]
                p.exigir(bool(torch.isfinite(escores).all()), "Escores invalidos.")
                escores = escores.cpu().tolist()
                ec = None
                if self.ec:
                    e = self.ec
                    esc = e["mlp"]((vetor - e["media"]) / e["dp"]).softmax(dim=1)[0]
                    p.exigir(bool(torch.isfinite(esc).all()), "Escores EC invalidos.")
                    esc = esc.cpu().tolist()
                    classe = e["classes"][max(range(2), key=esc.__getitem__)]
                    ec = {"classe": classe, "predicao": e["exibicao"][classe],
                          "confianca": max(esc), "escores_softmax_nao_calibrados": dict(zip(e["classes"], esc)),
                          "metricas_modelo": e["metricas"], "limites": e["limites"]}
            presentes = [aa for aa in ESSENCIAIS if aa in seq]
            ausentes = [aa for aa in ESSENCIAIS if aa not in seq]
            regra = "Incompleta" if ausentes else "Completa"
            predicao = p.CLASSES[max(range(len(escores)), key=escores.__getitem__)]
            return {"ok": True, "tipo": "predicao_regra_aa_api", "residuos": len(seq),
                "regra_direta": regra, "aminoacidos_essenciais_presentes": presentes,
                "aminoacidos_essenciais_ausentes": ausentes, "predicao_mlp": predicao,
                "escores_softmax_nao_calibrados": dict(zip(p.CLASSES, escores)),
                "concorda_com_regra_direta": predicao == regra,
                "dispositivo": str(self.dispositivo), "modelo_esm": p.MODELO_ESM,
                "download_permitido": False, "limites": p.LIMITE, "ec": ec}
        finally:
            self.trava.release()

