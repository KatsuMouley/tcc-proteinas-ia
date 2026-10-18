"""Treinar um MLP sobre embeddings ESM-2 fixos para reproduzir a regra de nove AA.

Requer apenas NumPy e PyTorch do ambiente existente. CUDA e o padrao.
O alvo e presenca literal de HILKMFTWV, sem interpretacao nutricional clinica.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import time

import numpy as np

PROJETO = Path(__file__).resolve().parents[1]
BASE = PROJETO / "dados/base_ia/base_1m"
PARTICOES = PROJETO / "dados/base_ia/particoes_1m"
SAIDA = PROJETO / "dados/modelos/classificador_regra_aa_esm2"
MODELO_ESM = "facebook/esm2_t6_8M_UR50D"
REVISAO_ESM = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
CLASSES = ("Incompleta", "Completa")
ESSENCIAIS = frozenset("HILKMFTWV")
ALFABETO = frozenset("ACDEFGHIKLMNPQRSTVWYBXZUO")
CONJUNTOS = ("treino", "validacao", "teste")
DIMENSAO = 320
OCULTA = 64
LIMITE = "Rotulo calculado pela presenca literal de HILKMFTWV; nao avalia digestibilidade, qualidade nutricional ou funcao biologica."


def exigir(condicao, mensagem):
    if not condicao:
        raise ValueError(mensagem)


def ler_json(caminho):
    return json.loads(caminho.read_text(encoding="utf-8-sig"))


def salvar_json(caminho, objeto):
    caminho.write_text(json.dumps(objeto, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def sha(caminho):
    h = hashlib.sha256()
    with caminho.open("rb") as entrada:
        for bloco in iter(lambda: entrada.read(4 * 1024**2), b""):
            h.update(bloco)
    return h.hexdigest()


def conferir_hash(caminho, esperado):
    exigir(sha(caminho) == esperado, f"Arquivo alterado ou incompleto: {caminho}")


def registrar(pasta, mensagem):
    print(mensagem, flush=True)
    with (pasta / "treino.log").open("a", encoding="utf-8") as arquivo:
        arquivo.write(mensagem + "\n")


def ler_fasta(caminho):
    cabecalho, partes = None, []
    with caminho.open(encoding="utf-8-sig") as entrada:
        for linha in entrada:
            linha = linha.strip()
            if not linha:
                continue
            if linha.startswith(">"):
                if cabecalho is not None:
                    yield cabecalho, "".join(partes)
                cabecalho, partes = linha[1:], []
            else:
                exigir(cabecalho is not None, "FASTA sem cabecalho inicial.")
                partes.append(linha)
        if cabecalho is not None:
            yield cabecalho, "".join(partes)


def conferir_particoes(indices, grupos, total):
    exigir(grupos.dtype == np.int64 and grupos.shape == (total,), "Mapa de grupos invalido.")
    exigir(bool(((grupos >= 0) & (grupos < total)).all()), "Grupo fora da base.")
    dono = np.full(total, -1, dtype=np.int8)
    grupos_conjuntos = []
    for numero, nome in enumerate(CONJUNTOS):
        ix = indices[nome]
        exigir(ix.dtype == np.int64 and ix.ndim == 1 and len(ix) > 0, f"Indices invalidos: {nome}.")
        exigir(bool(((ix >= 0) & (ix < total)).all()), f"Indice fora da base: {nome}.")
        exigir(np.unique(ix).size == ix.size and bool((dono[ix] == -1).all()), "Proteina repetida nas particoes.")
        dono[ix] = numero
        grupos_conjuntos.append(np.unique(grupos[ix]))
    exigir(bool((dono >= 0).all()), "Particoes nao cobrem a base inteira.")
    for i, j in ((0, 1), (0, 2), (1, 2)):
        exigir(np.intersect1d(grupos_conjuntos[i], grupos_conjuntos[j], assume_unique=True).size == 0,
               "Ha grupos compartilhados entre as particoes.")
    return dono, grupos_conjuntos


def preparar_dados(base, particoes):
    r = ler_json(base / "relatorio_consolidacao.json")
    s = ler_json(particoes / "relatorio_particoes.json")
    exigir(r.get("ok") is True and r.get("tipo") == "base_ia_consolidada" and r.get("schema") == 1,
           "Consolidacao nao aprovada.")
    total = r["proteinas"]
    exigir(r.get("modelo") == MODELO_ESM and r.get("revisao") == REVISAO_ESM
           and r.get("formato_embeddings") == [total, DIMENSAO], "Modelo ou formato ESM incompatível.")
    exigir(r["config_original"].get("regra_aminoacidos") == "HILKMFTWV", "Regra dos rotulos incompativel.")
    exigir(s.get("ok") is True and s.get("tipo") == "particoes_por_grupos_globais"
           and s.get("proteinas") == total and Path(s["base_consolidada"]).resolve() == base,
           "Particoes nao correspondem a esta base.")
    ag_pasta = Path(s["agrupamento"]).resolve()
    ag = ler_json(ag_pasta / "relatorio_agrupamento.json")
    exigir(ag.get("ok") is True and ag.get("proteinas") == total
           and ag.get("fasta_sha256") == r["hashes_arquivos"]["sequencias.fasta"]
           and ag.get("tsv_sha256") == s.get("tsv_sha256"), "Agrupamento nao corresponde a base e particoes.")
    print("Conferindo os arquivos consolidados e as particoes existentes...", flush=True)
    for nome in ("indice.csv", "sequencias.fasta", "embeddings.npy"):
        conferir_hash(base / nome, r["hashes_arquivos"][nome])
    for nome in ("particoes.csv", "grupos_por_linha.npy", *[f"{n}_indices.npy" for n in CONJUNTOS]):
        conferir_hash(particoes / nome, s["hashes_arquivos"][nome])
    conferir_hash(ag_pasta / "global_cluster.tsv", s["tsv_sha256"])
    x = np.load(base / "embeddings.npy", mmap_mode="r", allow_pickle=False)
    exigir(x.dtype == np.float32 and x.shape == (total, DIMENSAO), "Embeddings precisam ser float32 N x 320.")
    indices = {n: np.load(particoes / f"{n}_indices.npy", allow_pickle=False) for n in CONJUNTOS}
    grupos = np.load(particoes / "grupos_por_linha.npy", allow_pickle=False)
    dono, grupos_conjuntos = conferir_particoes(indices, grupos, total)
    exigir(sum(len(g) for g in grupos_conjuntos) == ag["grupos"], "Contagem global de grupos divergente.")
    y = np.empty(total, dtype=np.int64)
    tamanhos = np.empty(total, dtype=np.int32)
    originais_teste = {}
    lidas = 0
    with (base / "indice.csv").open(encoding="utf-8-sig", newline="") as entrada:
        for i, linha in enumerate(csv.DictReader(entrada, delimiter=";", strict=True)):
            exigir(i < total and int(linha["indice_global"]) == i and linha["uid"] == f"p{i:09d}", "Ordem do indice invalida.")
            exigir(linha["Tipo_Nutricional"] in CLASSES, "Rotulo desconhecido.")
            y[i] = CLASSES.index(linha["Tipo_Nutricional"])
            tamanhos[i] = int(linha["tamanho"])
            if dono[i] == 2:
                originais_teste[i] = linha["id_original"]
            lidas += 1
    exigir(lidas == total, "Quantidade de linhas do indice divergente.")
    regra = np.empty(total, dtype=np.int64)
    lidas = 0
    for i, (uid, sequencia) in enumerate(ler_fasta(base / "sequencias.fasta")):
        exigir(i < total and uid == f"p{i:09d}" and len(sequencia) == tamanhos[i]
               and 1 <= len(sequencia) <= 512, "FASTA e indice fora de ordem ou comprimento invalido.")
        regra[i] = int(ESSENCIAIS <= set(sequencia))
        exigir(regra[i] == y[i], f"Rotulo divergente da regra literal: {uid}.")
        lidas += 1
        if lidas % 100000 == 0:
            print(f"Rotulos conferidos com as sequencias: {lidas}/{total}.", flush=True)
    exigir(lidas == total, "Quantidade de sequencias divergente.")
    for i, nome in enumerate(CONJUNTOS):
        contagem = {n: int((y[indices[nome]] == j).sum()) for j, n in enumerate(CLASSES)}
        registrado = s["particoes"][nome]
        exigir(len(indices[nome]) == registrado["proteinas"] and contagem == registrado["rotulos"]
               and len(grupos_conjuntos[i]) == registrado["grupos"], f"Contagens divergentes: {nome}.")
        exigir(all(contagem.values()), f"Uma classe esta ausente de {nome}.")
    histograma = {"1_a_9": int((tamanhos <= 9).sum()),
                 "10_a_29": int(((tamanhos >= 10) & (tamanhos <= 29)).sum()),
                 "30_a_99": int(((tamanhos >= 30) & (tamanhos <= 99)).sum()),
                 "100_a_512": int((tamanhos >= 100).sum())}
    proveniencia = {"base": str(base), "particoes": str(particoes), "agrupamento": str(ag_pasta),
                   "relatorio_consolidacao_sha256": sha(base / "relatorio_consolidacao.json"),
                   "relatorio_particoes_sha256": sha(particoes / "relatorio_particoes.json"),
                   "hashes_base": r["hashes_arquivos"], "hashes_particoes": s["hashes_arquivos"],
                   "tsv_sha256": s["tsv_sha256"], "semente_particoes": s["semente"],
                   "distribuicao_particoes": s["particoes"], "histograma_comprimentos": histograma,
                   "recorte_ncbi": r.get("recorte_ncbi", "Recorte da consolidacao fornecida.")}
    return x, y, indices, grupos, regra, originais_teste, proveniencia


def normalizacao_treino(x, indices, bloco=16384):
    soma, quadrados = np.zeros(DIMENSAO), np.zeros(DIMENSAO)
    for inicio in range(0, len(indices), bloco):
        valores = np.asarray(x[indices[inicio:inicio + bloco]], dtype=np.float64)
        exigir(bool(np.isfinite(valores).all()), "Valor nao finito nos embeddings de treino.")
        soma += valores.sum(axis=0)
        quadrados += np.square(valores).sum(axis=0)
    media = soma / len(indices)
    desvio = np.sqrt(np.maximum(quadrados / len(indices) - media**2, 0))
    desvio = np.maximum(desvio, 1e-6)
    return media.astype(np.float32), desvio.astype(np.float32)


def metricas(real, previsto):
    exigir(real.ndim == previsto.ndim == 1 and len(real) == len(previsto) and len(real) > 0,
           "Vetores de avaliacao invalidos.")
    exigir(bool(((real >= 0) & (real < 2) & (previsto >= 0) & (previsto < 2)).all()), "Classe invalida na avaliacao.")
    matriz = np.bincount(real * 2 + previsto, minlength=4).reshape(2, 2)
    por_classe, recalls, f1s = {}, [], []
    for i, nome in enumerate(CLASSES):
        tp, suporte, preditos = int(matriz[i, i]), int(matriz[i].sum()), int(matriz[:, i].sum())
        precisao = tp / preditos if preditos else 0.0
        recall = tp / suporte if suporte else 0.0
        f1 = 2 * precisao * recall / (precisao + recall) if precisao + recall else 0.0
        por_classe[nome] = {"suporte": suporte, "precisao": precisao, "sensibilidade": recall, "f1": f1}
        recalls.append(recall)
        f1s.append(f1)
    return {"proteinas": len(real), "acuracia": float(np.trace(matriz) / len(real)),
            "acuracia_balanceada": float(np.mean(recalls)), "f1_macro": float(np.mean(f1s)),
            "ordem_classes": list(CLASSES), "matriz_confusao_linhas_reais_colunas_previstas": matriz.tolist(),
            "por_classe": por_classe, "divisao_por_zero": "Resultado 0 quando nao ha previsoes da classe."}


def configurar_torch(args):
    for nome in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[nome] = str(args.threads)
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    try:
        import torch
    except ImportError as e:
        raise RuntimeError("Execute com o Python do ambiente .venv que ja possui PyTorch.") from e
    torch.set_num_threads(args.threads)
    if args.dispositivo == "auto":
        args.dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    if args.dispositivo == "cuda":
        exigir(torch.cuda.is_available(), "CUDA indisponivel. Use .venv\\Scripts\\python.exe; CPU exige --dispositivo cpu explicito.")
        dispositivo = torch.device("cuda:0")
        torch.cuda.set_device(dispositivo)
        exigir(torch.arange(4, device=dispositivo).sum().item() == 6, "Teste CUDA falhou.")
        torch.cuda.reset_peak_memory_stats(dispositivo)
    else:
        dispositivo = torch.device("cpu")
    random.seed(args.semente)
    np.random.seed(args.semente)
    torch.manual_seed(args.semente)
    if dispositivo.type == "cuda":
        torch.cuda.manual_seed_all(args.semente)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    return torch, dispositivo


def criar_modelo(torch):
    return torch.nn.Sequential(torch.nn.Linear(DIMENSAO, OCULTA), torch.nn.ReLU(), torch.nn.Linear(OCULTA, 2))


def avaliar(torch, modelo, dispositivo, x, y, indices, media, desvio, lote):
    modelo.eval()
    probabilidades = np.empty(len(indices), dtype=np.float32)
    previstos = np.empty(len(indices), dtype=np.int64)
    perda = 0.0
    with torch.inference_mode():
        for inicio in range(0, len(indices), lote):
            ix = indices[inicio:inicio + lote]
            valores = np.asarray(x[ix], dtype=np.float32)
            exigir(bool(np.isfinite(valores).all()), "Embedding de avaliacao nao finito.")
            entradas = torch.from_numpy(valores).to(dispositivo)
            alvos = torch.from_numpy(y[ix]).to(dispositivo)
            logits = modelo((entradas - media) / desvio)
            exigir(bool(torch.isfinite(logits).all().item()), "Predicao nao finita.")
            perda += torch.nn.functional.cross_entropy(logits, alvos, reduction="sum").item()
            probabilidades[inicio:inicio + len(ix)] = logits.softmax(dim=1)[:, 1].cpu().numpy()
            previstos[inicio:inicio + len(ix)] = logits.argmax(dim=1).cpu().numpy()
    resultado = metricas(y[indices], previstos)
    resultado["perda_sem_pesos"] = perda / len(indices)
    return resultado, previstos, probabilidades


def treinar(args):
    inicio = time.perf_counter()
    base, particoes, destino = args.base.resolve(), args.particoes.resolve(), args.saida.resolve()
    exigir(not destino.exists(), f"A saida ja existe: {destino}. Preserve os resultados; use outra --saida para um novo experimento.")
    for entrada in (base, particoes):
        exigir(not destino.is_relative_to(entrada) and not entrada.is_relative_to(destino), "Saida precisa ficar fora das entradas.")
    torch, dispositivo = configurar_torch(args)
    x, y, indices, grupos, regra, ids_teste, proveniencia = preparar_dados(base, particoes)
    agrupamento = Path(proveniencia["agrupamento"])
    exigir(not destino.is_relative_to(agrupamento) and not agrupamento.is_relative_to(destino),
           "Saida precisa ficar fora das entradas de agrupamento.")
    media_np, desvio_np = normalizacao_treino(x, indices["treino"])
    media = torch.from_numpy(media_np).to(dispositivo)
    desvio = torch.from_numpy(desvio_np).to(dispositivo)
    modelo = criar_modelo(torch).to(dispositivo)
    counts = np.bincount(y[indices["treino"]], minlength=2)
    pesos_np = (len(indices["treino"]) / (2 * counts)).astype(np.float32)
    pesos = torch.from_numpy(pesos_np).to(dispositivo)
    criterio = torch.nn.CrossEntropyLoss(weight=pesos, reduction="sum")
    otimizador = torch.optim.Adam(modelo.parameters(), lr=0.001, weight_decay=0.0001)
    rng = np.random.default_rng(args.semente)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{destino.name}_parcial_", dir=destino.parent))
    passos, epocas, melhor, melhor_epoca, sem_melhora = 0, 0, -1.0, 0, 0
    historico = []
    try:
        registrar(tmp, f"Treino MLP 320 -> 64 -> 2 em {dispositivo}; CPU limitada a {args.threads} threads.")
        registrar(tmp, f"Treino: {len(indices['treino'])}; validacao: {len(indices['validacao'])}; teste: {len(indices['teste'])}.")
        registrar(tmp, f"Progresso e pesos parciais: {tmp}")
        salvar_json(tmp / "configuracao.json", {"alvo": "presenca_literal_nove_aminoacidos", "limites": LIMITE,
            "epocas_maximas": args.epocas, "paciencia": args.paciencia, "lote": args.lote,
            "semente_treino": args.semente, "threads_cpu": args.threads, "dispositivo": str(dispositivo),
            "normalizacao": "Media e desvio populacional calculados somente no treino; desvio minimo 1e-6.",
            "pesos_classes_somente_treino": {c: float(pesos_np[i]) for i, c in enumerate(CLASSES)},
            "proveniencia": proveniencia})
        for epoca in range(1, args.epocas + 1):
            inicio_epoca = time.perf_counter()
            ordem = rng.permutation(indices["treino"])
            modelo.train()
            numerador_total, denominador_total = 0.0, 0.0
            ultimo_aviso = time.monotonic()
            for pos in range(0, len(ordem), args.lote):
                ix = ordem[pos:pos + args.lote]
                entradas = torch.from_numpy(np.asarray(x[ix], dtype=np.float32)).to(dispositivo)
                alvos = torch.from_numpy(y[ix]).to(dispositivo)
                otimizador.zero_grad(set_to_none=True)
                logits = modelo((entradas - media) / desvio)
                numerador = criterio(logits, alvos)
                denominador = pesos[alvos].sum()
                perda = numerador / denominador
                exigir(bool(torch.isfinite(perda).item()), "Perda nao finita.")
                perda.backward()
                otimizador.step()
                passos += 1
                numerador_total += numerador.detach().item()
                denominador_total += denominador.item()
                if time.monotonic() - ultimo_aviso >= 30:
                    registrar(tmp, f"Epoca {epoca}: {min(pos + args.lote, len(ordem))}/{len(ordem)} exemplos de treino.")
                    ultimo_aviso = time.monotonic()
            epocas = epoca
            val, _, _ = avaliar(torch, modelo, dispositivo, x, y, indices["validacao"], media, desvio, args.lote)
            score = val["acuracia_balanceada"]
            historico.append({"epoca": epoca, "perda_treino_ponderada": numerador_total / denominador_total,
                "perda_validacao": val["perda_sem_pesos"], "acuracia_balanceada_validacao": score,
                "f1_macro_validacao": val["f1_macro"], "segundos": time.perf_counter() - inicio_epoca})
            registrar(tmp, f"Epoca {epoca}/{args.epocas}: perda treino {historico[-1]['perda_treino_ponderada']:.4f}; "
                f"acuracia balanceada validacao {score:.4f}; F1 macro {val['f1_macro']:.4f}.")
            with (tmp / "historico.csv").open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(historico[0]), delimiter=";")
                w.writeheader()
                w.writerows(historico)
            if score > melhor + 1e-8:
                melhor, melhor_epoca, sem_melhora = score, epoca, 0
                checkpoint = {"schema": 1, "tipo": "mlp_regra_nove_aa", "classes": list(CLASSES),
                    "dimensao": DIMENSAO, "oculta": OCULTA, "modelo_esm": MODELO_ESM, "revisao_esm": REVISAO_ESM,
                    "media": media.detach().cpu().clone(), "desvio": desvio.detach().cpu().clone(),
                    "estado": {k: v.detach().cpu().clone() for k, v in modelo.state_dict().items()},
                    "melhor_epoca": epoca, "acuracia_balanceada_validacao": melhor}
                provisoria = tmp / "modelo.provisorio.pt"
                torch.save(checkpoint, provisoria)
                os.replace(provisoria, tmp / "modelo.pt")
            else:
                sem_melhora += 1
            if sem_melhora >= args.paciencia:
                registrar(tmp, "Parada antecipada: criterio de validacao sem melhora.")
                break
        checkpoint = torch.load(tmp / "modelo.pt", map_location="cpu", weights_only=True)
        modelo.load_state_dict(checkpoint["estado"])
        val, _, _ = avaliar(torch, modelo, dispositivo, x, y, indices["validacao"], media, desvio, args.lote)
        teste, previsto, probabilidades = avaliar(torch, modelo, dispositivo, x, y, indices["teste"], media, desvio, args.lote)
        maioritaria = int(counts.argmax())
        ix_teste = indices["teste"]
        baseline = metricas(y[ix_teste], np.full(len(ix_teste), maioritaria, dtype=np.int64))
        regra_direta = metricas(y[ix_teste], regra[ix_teste])
        with (tmp / "predicoes_teste.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(("indice_global", "uid", "id_original", "grupo_global", "rotulo_regra", "predicao_mlp", "escore_completa", "correto"))
            for indice, pred, prob in zip(ix_teste, previsto, probabilidades):
                i = int(indice)
                w.writerow((i, f"p{i:09d}", ids_teste[i], f"p{int(grupos[i]):09d}", CLASSES[y[i]], CLASSES[pred], float(prob), bool(pred == y[i])))
        gpu = torch.cuda.get_device_name(dispositivo) if dispositivo.type == "cuda" else None
        relatorio = {"tipo": "treino_classificador_regra_aa_esm2", "schema": 1, "ok": True,
            "treinamento_realizado": True, "esm2_retreinado": False, "embeddings_regenerados": False,
            "dispositivo": str(dispositivo), "gpu_utilizada": dispositivo.type == "cuda", "gpu": gpu,
            "threads_cpu_pytorch": args.threads, "pytorch": str(torch.__version__), "numpy": np.__version__,
            "cuda_compilada": torch.version.cuda, "python": sys.version.split()[0],
            "memoria_pico_pytorch_mb": round(torch.cuda.max_memory_allocated(dispositivo) / 1024**2, 1) if gpu else None,
            "arquitetura": [DIMENSAO, OCULTA, 2], "parametros_treinaveis": sum(p.numel() for p in modelo.parameters()),
            "alvo": "Presenca literal dos nove aminoacidos HILKMFTWV", "classes": list(CLASSES),
            "epocas_executadas": epocas, "melhor_epoca": melhor_epoca, "passos_otimizacao": passos,
            "selecao_modelo": "Maior acuracia balanceada na validacao; empate preserva a epoca anterior; paciencia fixa.",
            "teste_usado_para_ajuste": False, "normalizacao_calculada_somente_no_treino": True,
            "grupos_identificados_compartilhados": 0, "validacao_melhor_modelo": val, "teste_mlp": teste,
            "teste_baseline_classe_mais_frequente": {"classe_escolhida_no_treino": CLASSES[maioritaria], **baseline},
            "teste_regra_direta": regra_direta, "historico": historico, "proveniencia": proveniencia,
            "limites": [LIMITE, "Regra direta e o proprio criterio que gerou os rotulos; sua exatidao e esperada por construcao.",
                "Linclust pode perder homologos; grupos identificados disjuntos nao provam independencia biologica total.",
                "Escores softmax nao foram calibrados. Metricas sao por sequencia, sem intervalo de confianca por grupo.",
                "Inclui o recorte de comprimentos 1 a 512 da base fornecida; nao equivale a amostragem aleatoria de todo NCBI."],
            "pasta_saida": str(destino), "segundos": round(time.perf_counter() - inicio, 3),
            "hashes_arquivos": {n: sha(tmp / n) for n in ("modelo.pt", "historico.csv", "predicoes_teste.csv", "configuracao.json")}}
        salvar_json(tmp / "relatorio_treino.json", relatorio)
        registrar(tmp, f"Treino concluido. Teste: acuracia balanceada {teste['acuracia_balanceada']:.4f}; F1 macro {teste['f1_macro']:.4f}.")
        exigir(not destino.exists(), "Pasta de saida surgiu durante o treino; nada sera sobrescrito.")
        tmp.rename(destino)
        return relatorio
    except BaseException as e:
        salvar_json(tmp / "relatorio_erro.json", {"ok": False, "erro": f"{type(e).__name__}: {e}",
            "treinamento_realizado": passos > 0, "passos_otimizacao": passos, "epocas_completas": epocas})
        print(f"Resultados parciais preservados em: {tmp}", flush=True)
        raise


def prever(args):
    torch, dispositivo = configurar_torch(args)
    modelo_path = args.modelo.resolve()
    rel = ler_json(modelo_path.parent / "relatorio_treino.json")
    exigir(rel.get("ok") is True, "Treino nao concluido.")
    conferir_hash(modelo_path, rel["hashes_arquivos"]["modelo.pt"])
    cp = torch.load(modelo_path, map_location="cpu", weights_only=True)
    exigir(cp.get("schema") == 1 and cp.get("tipo") == "mlp_regra_nove_aa" and cp.get("classes") == list(CLASSES)
           and cp.get("dimensao") == DIMENSAO and cp.get("oculta") == OCULTA
           and cp.get("modelo_esm") == MODELO_ESM and cp.get("revisao_esm") == REVISAO_ESM, "Modelo incompativel.")
    resultado = {"tipo": "predicao_regra_aa", "ok": True, "modelo": str(modelo_path), "dispositivo": str(dispositivo), "limites": LIMITE}
    if args.sequencia is not None:
        sequencia = args.sequencia.strip().upper()
        exigir(1 <= len(sequencia) <= 512 and set(sequencia) <= ALFABETO, "Use 1 a 512 residuos do alfabeto suportado, sem espacos internos.")
        exigir(dispositivo.type == "cuda", "Para sequencia nova, o ESM-2 deste fluxo exige CUDA.")
        from transformers import AutoTokenizer, EsmModel
        comum = {"revision": REVISAO_ESM, "cache_dir": str(args.cache.resolve()), "local_files_only": True, "trust_remote_code": False}
        tokenizador = AutoTokenizer.from_pretrained(MODELO_ESM, **comum)
        esm = EsmModel.from_pretrained(MODELO_ESM, add_pooling_layer=False, attn_implementation="eager", use_safetensors=True, **comum).float().to(dispositivo).eval()
        entradas = tokenizador(sequencia, return_tensors="pt", return_special_tokens_mask=True, return_token_type_ids=False, truncation=False)
        especiais = entradas.pop("special_tokens_mask").to(dispositivo)
        entradas = {k: v.to(dispositivo) for k, v in entradas.items()}
        mascara = (entradas["attention_mask"] * (1 - especiais)).bool()
        exigir(int(mascara.sum().item()) == len(sequencia), "Tokenizacao alterou a quantidade de residuos.")
        with torch.inference_mode():
            vetor = esm(**entradas).last_hidden_state[0, mascara[0]].mean(dim=0).unsqueeze(0)
        resultado.update({"residuos": len(sequencia), "regra_direta": CLASSES[int(ESSENCIAIS <= set(sequencia))], "download_permitido": False})
    else:
        arr = np.load(args.embedding.resolve(), allow_pickle=False)
        exigir(arr.shape in ((DIMENSAO,), (1, DIMENSAO)) and arr.dtype == np.float32, "Embedding deve ser float32 com 320 valores.")
        vetor = torch.from_numpy(arr.reshape(1, DIMENSAO)).to(dispositivo)
    exigir(bool(torch.isfinite(vetor).all().item()), "Embedding nao finito.")
    modelo = criar_modelo(torch).to(dispositivo)
    modelo.load_state_dict(cp["estado"])
    modelo.eval()
    media, desvio = cp["media"].to(dispositivo), cp["desvio"].to(dispositivo)
    with torch.inference_mode():
        escores = modelo((vetor - media) / desvio).softmax(dim=1)[0].cpu().numpy()
    exigir(bool(np.isfinite(escores).all()), "Escores nao finitos.")
    resultado.update({"predicao_mlp": CLASSES[int(escores.argmax())], "escores_softmax_nao_calibrados": {c: float(escores[i]) for i, c in enumerate(CLASSES)}})
    if "regra_direta" in resultado:
        resultado["concorda_com_regra_direta"] = resultado["predicao_mlp"] == resultado["regra_direta"]
    return resultado


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    comandos = parser.add_subparsers(dest="etapa", required=True)
    t = comandos.add_parser("treinar", help="Treina somente o MLP sobre embeddings existentes.")
    t.add_argument("--base", type=Path, default=BASE)
    t.add_argument("--particoes", type=Path, default=PARTICOES)
    t.add_argument("--saida", type=Path, default=SAIDA)
    t.add_argument("--epocas", type=int, default=10)
    t.add_argument("--paciencia", type=int, default=3)
    t.add_argument("--lote", type=int, default=2048)
    t.set_defaults(func=treinar)
    p = comandos.add_parser("prever", help="Preve a regra para uma sequencia ou embedding individual.")
    p.add_argument("--modelo", type=Path, default=SAIDA / "modelo.pt")
    alvo = p.add_mutually_exclusive_group(required=True)
    alvo.add_argument("--sequencia")
    alvo.add_argument("--embedding", type=Path)
    p.add_argument("--cache", type=Path, default=PROJETO / "cache/huggingface")
    p.set_defaults(func=prever)
    for sub in (t, p):
        sub.add_argument("--threads", type=int, choices=range(1, 13), default=2)
        sub.add_argument("--dispositivo", choices=("auto", "cuda", "cpu"), default="cuda")
        sub.add_argument("--semente", type=int, default=42)
    args = parser.parse_args(argv)
    if args.etapa == "treinar" and not (1 <= args.epocas <= 100 and 1 <= args.paciencia <= 100 and 1 <= args.lote <= 8192):
        parser.error("Use epocas e paciencia de 1 a 100 e lote de 1 a 8192.")
    try:
        resultado = args.func(args)
    except (Exception, KeyboardInterrupt) as e:
        print(json.dumps({"ok": False, "etapa": args.etapa, "erro": f"{type(e).__name__}: {e}"}, indent=2, ensure_ascii=False))
        return 2
    print(json.dumps(resultado, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
