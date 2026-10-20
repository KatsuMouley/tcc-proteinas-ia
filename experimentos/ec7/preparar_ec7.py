"""EXPERIMENTO EC7: confere, agrupa (MMseqs2) e separa por grupos a coleta das 7 classes EC.

Copia generalizada de etapas/preparar_piloto_ec.py (o original nao e alterado). Nao gera vetores nem treina.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import time
import uuid

import numpy as np
import sys as _sys
_AQUI = Path(__file__).resolve().parent
_sys.path.insert(0, str(_AQUI))
_sys.path.insert(1, str(_AQUI.parents[1] / "etapas"))
import ec7_comum  # noqa: E402  (aplica os rotulos das 7 classes ao cliente UniProt)
import consultar_sondagem_ec as api
from preparar_base_ia import Backend, executar_curto

PARTICOES = ("treino", "validacao", "teste")
ALFABETO = frozenset("ACDEFGHIKLMNPQRSTVWYBXZUO")
PARAMETROS = ["--min-seq-id", "0.5", "-c", "0.8", "--cov-mode", "0", "--cluster-mode", "1",
              "--alignment-mode", "3", "--kmer-per-seq", "80", "--split-memory-limit", "8G", "-e", "0.001"]


def exigir(condicao, mensagem):
    if not condicao:
        raise ValueError(mensagem)


def ler_fasta(path):
    cabecalho, partes = None, []
    with path.open(encoding="utf-8") as f:
        for numero, linha in enumerate(f, 1):
            linha = linha.strip()
            if not linha:
                continue
            if linha.startswith(">"):
                if cabecalho is not None:
                    yield cabecalho, "".join(partes)
                cabecalho, partes = linha[1:], []
                exigir(re.fullmatch(r"ec\d{9}", cabecalho), f"Cabecalho FASTA invalido na linha {numero}.")
            else:
                exigir(cabecalho is not None, "Sequencia antes do primeiro cabecalho FASTA.")
                partes.append(linha)
    if cabecalho is not None:
        yield cabecalho, "".join(partes)


def conferir_coleta(pasta, esperado=None):
    pasta = Path(pasta).resolve()
    manifesto = pasta / "relatorio_coleta.json"
    r = json.loads(manifesto.read_text(encoding="utf-8-sig"))
    exigir(r.get("ok") is True and r.get("tipo") == "coleta_swissprot_ec7" and r.get("schema") == 1,
           "A coleta EC7 nao foi concluida.")
    total = r.get("total_selecionado")
    exigir(type(total) is int and (esperado is None or total == esperado) and 2 <= total <= 14000,
           "Quantidade da coleta divergente ou fora do limite de 2 a 14000.")
    exigir(r.get("modelo_embeddings_planejado") == api.MODELO
           and r.get("revisao_embeddings_planejada") == api.REVISAO,
           "Modelo ESM-2 ou revisao planejada divergente.")
    marcas = {"relatorio_coleta.json": api.sha(manifesto)}
    for nome in ("candidatos_auditados.csv", "piloto_rotulado.csv", "sequencias.fasta"):
        marcas[nome] = api.sha(pasta / nome)
        exigir(marcas[nome] == r["hashes_saidas"][nome], f"Hash divergente: {nome}. Nenhuma saida criada.")
    with (pasta / "piloto_rotulado.csv").open(encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";", strict=True))
    exigir(len(linhas) == total, "Quantidade do CSV nao corresponde ao relatorio.")
    ids, hashes, contagens = set(), set(), Counter()
    for i, x in enumerate(linhas):
        exigir(x["uid"] == f"ec{i:09d}" and int(x["indice_global"]) == i,
               "UID ou indice fora da ordem da coleta.")
        exigir(x["id_original"] not in ids and x["sha256_sequencia"] not in hashes,
               "Accession ou sequencia repetida na selecao.")
        ids.add(x["id_original"])
        hashes.add(x["sha256_sequencia"])
        classe = x["classe_ec"]
        ecs = x["ecs_uniprot"].split("|")
        exigir(classe in api.ROTULOS and x["rotulo_ec"] == api.ROTULOS[classe]
               and x["revisado"] == "True" and x["status_coleta"] == "selecionado"
               and x["motivos_exclusao"] == "" and all(api.EC_VALIDO.fullmatch(ec) for ec in ecs)
               and {ec.split(".")[0] for ec in ecs} == {classe},
               f"Rotulo EC sem correspondencia com os criterios na linha {i}.")
        seq = x["sequencia"]
        exigir(1 <= len(seq) <= 512 and len(seq) == int(x["tamanho"]) and set(seq) <= ALFABETO
               and hashlib.sha256(seq.encode("utf-8")).hexdigest() == x["sha256_sequencia"],
               f"Sequencia/comprimento/hash divergente na linha {i}.")
        contagens[x["rotulo_ec"]] += 1
    exigir(dict(contagens) == r["rotulos_selecionados"], "As classes divergem da contagem registrada.")
    registros = list(ler_fasta(pasta / "sequencias.fasta"))
    exigir(registros == [(x["uid"], x["sequencia"]) for x in linhas],
           "FASTA e CSV divergem em sequencia, UID, quantidade ou ordem.")
    exigir(all(api.sha(pasta / n) == h for n, h in marcas.items()), "Uma entrada mudou durante a conferencia.")
    return linhas, r, marcas


def ler_grupos(tsv, linhas):
    esperados = {x["uid"] for x in linhas}
    grupos = {}
    with tsv.open(encoding="utf-8", newline="") as f:
        for numero, par in enumerate(csv.reader(f, delimiter="\t"), 1):
            exigir(len(par) == 2, f"TSV: linha {numero} precisa ter representante e membro.")
            rep, membro = par
            exigir(rep in esperados and membro in esperados, "O TSV contem UID de outra base.")
            exigir(membro not in grupos, f"UID repetido no TSV: {membro}")
            grupos[membro] = rep
    exigir(set(grupos) == esperados, "O TSV nao cobre todas as proteinas do piloto.")
    exigir(all(grupos[rep] == rep for rep in set(grupos.values())),
           "Um representante foi atribuido a outro grupo.")
    return grupos


def separar(linhas, grupos, semente=42):
    destino = {}
    for rep in sorted(set(grupos.values())):
        numero = int.from_bytes(hashlib.sha256(f"{semente}:{rep}".encode()).digest()[:8], "big") / 2**64
        destino[rep] = "treino" if numero < 0.8 else "validacao" if numero < 0.9 else "teste"
    particoes = [{"indice_global": int(x["indice_global"]), "uid": x["uid"], "id_original": x["id_original"],
        "grupo_global": grupos[x["uid"]], "particao": destino[grupos[x["uid"]]],
        "classe_ec": x["classe_ec"], "rotulo_ec": x["rotulo_ec"]} for x in linhas]
    conjuntos = {p: {x["grupo_global"] for x in particoes if x["particao"] == p} for p in PARTICOES}
    exigir(not any(conjuntos[a] & conjuntos[b] for a, b in (("treino", "validacao"),
           ("treino", "teste"), ("validacao", "teste"))), "Um grupo foi dividido entre particoes.")
    resumo = {p: {"proteinas": sum(x["particao"] == p for x in particoes),
        "grupos": len(conjuntos[p]), "rotulos": {r: sum(x["particao"] == p and x["rotulo_ec"] == r
                                                     for x in particoes) for r in api.ROTULOS.values()}}
        for p in PARTICOES}
    return particoes, resumo


def executar_mmseqs(backend, pasta_coleta, saida, threads, progresso=print):
    versao = backend.version()
    _, ajuda, err = executar_curto(backend.cmd("easy-linclust", "-h"))
    exigir(all(flag in ajuda + err for flag in ("--cluster-mode", "--alignment-mode", "--kmer-per-seq",
                                               "--split-memory-limit")), "MMseqs2 nao anunciou os parametros necessarios.")
    if backend.distro:
        code, out, err = executar_curto(backend.prefixo + ["mktemp", "-d", "-p", "/var/tmp", "tcc_ec7_mmseqs.XXXXXXXX"])
        exigir(code == 0 and re.fullmatch(r"/var/tmp/tcc_ec7_mmseqs\.[A-Za-z0-9]+", out.strip()),
               "Falha ao criar temporario privado em /var/tmp do WSL.")
        temporario = out.strip()
    else:
        temp = saida / "temporario_mmseqs"
        temp.mkdir()
        temporario = str(temp)
    parametros = [*PARAMETROS, "--threads", str(threads), "--remove-tmp-files", "1"]
    comando = backend.cmd("easy-linclust", backend.path(pasta_coleta / "sequencias.fasta"),
                          backend.path(saida / "global"), temporario, *parametros)
    if backend.distro:
        comando = backend.prefixo + ["env", f"MMSEQS_NUM_THREADS={threads}"] + comando[len(backend.prefixo):]
    registro = {"versao_mmseqs2": versao, "comando": comando, "temporario_mmseqs": temporario,
                "threads_cpu": threads, "gpu_utilizada": False}
    api.salvar_json(saida / "execucao_mmseqs.json", registro)
    progresso(f"MMseqs2 {versao}: piloto EC; {threads} threads CPU. Log: {saida / 'mmseqs.log'}")
    env = os.environ.copy()
    env["MMSEQS_NUM_THREADS"] = str(threads)
    processo = None
    try:
        with (saida / "mmseqs.log").open("w", encoding="utf-8") as log:
            processo = subprocess.Popen(comando, stdout=log, stderr=subprocess.STDOUT, env=env)
            while processo.poll() is None:
                time.sleep(1)
            exigir(processo.returncode == 0, f"MMseqs2 terminou com codigo {processo.returncode}; consulte mmseqs.log.")
    except BaseException:
        if processo is not None and processo.poll() is None:
            processo.terminate()
            try:
                processo.wait(timeout=10)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.wait(timeout=10)
        raise
    if backend.distro:
        executar_curto(backend.prefixo + ["rmdir", "--", temporario])
    return registro


def preparar(coleta, esperado=None, wsl=None, threads=8, semente=42, progresso=print,
             backend_factory=Backend, executor=executar_mmseqs):
    exigir(type(threads) is int and 1 <= threads <= 12, "Use de 1 a 12 threads CPU.")
    coleta = Path(coleta).resolve()
    linhas, original, marcas = conferir_coleta(coleta, esperado)
    exigir(shutil.disk_usage(coleta).free >= 1024**3, "Ha menos de 1 GiB livre no disco do piloto.")
    backend = backend_factory(wsl)
    saida = coleta / (datetime.now(timezone.utc).strftime("preparacao_ec_%Y%m%dT%H%M%S%fZ_") + uuid.uuid4().hex[:6])
    saida.mkdir()
    inicio = time.perf_counter()
    r = {"tipo": "preparacao_swissprot_ec7", "schema": 1, "ok": False,
         "status": "agrupamento_em_andamento", "coleta": str(coleta), "pasta_saida": str(saida),
         "proteinas": len(linhas), "rotulos": original["rotulos_selecionados"], "hashes_entradas": marcas,
         "semente": semente, "fracoes_solicitadas": {"treino": 0.8, "validacao": 0.1, "teste": 0.1},
         "metodo_particoes": "Primeiros 8 bytes de SHA256(semente:UID_representante), divididos por 2**64; "
                             "limiares 0.8 e 0.9; grupo inteiro na mesma particao; sem reajuste de semente.",
         "parametros_mmseqs": {"identidade_minima": 0.5, "cobertura_minima": 0.8, "cov_mode": 0,
             "cluster_mode": 1, "alignment_mode": 3, "kmer_per_seq": 80,
             "split_memory_limit": "8G", "evalue": 0.001},
         "modelo_embeddings_planejado": api.MODELO, "revisao_embeddings_planejada": api.REVISAO,
         "embeddings_gerados": False, "gpu_utilizada": False, "treinamento_realizado": False,
         "treinamento_liberado": False, "teste_avaliado": False, "historico_1m_alterado": False,
         "limites": "Linclust e heuristico: zero grupos compartilhados nao prova ausencia de toda homologia. "
                    "Esta preparacao pertence somente ao experimento EC7; a selecao nao representa todo o banco."}
    api.salvar_json(saida / "relatorio_preparacao_ec.json", r)
    try:
        execucao = executor(backend, coleta, saida, threads, progresso)
        grupos = ler_grupos(saida / "global_cluster.tsv", linhas)
        particoes, resumo = separar(linhas, grupos, semente)
        tamanhos = list(Counter(grupos.values()).values())
        r.update(execucao_mmseqs=execucao, grupos=len(tamanhos), maior_grupo=max(tamanhos),
                 singletons=sum(t == 1 for t in tamanhos), mediana_tamanho_grupos=statistics.median(tamanhos),
                 particoes=resumo, grupos_compartilhados_entre_particoes=0)
        exigir(all(resumo[p]["proteinas"] for p in PARTICOES),
               "Uma particao ficou vazia. Preparacao preservada; nao alterar a semente automaticamente.")
        exigir(all(resumo[p]["rotulos"][r] for p in ("treino", "validacao") for r in api.ROTULOS.values()),
               "Treino ou validacao ficou sem uma das classes. Preparacao preservada; protocolo requer revisao antes do treino.")
        exigir(all(api.sha(coleta / n) == h for n, h in marcas.items()), "Uma entrada mudou durante o agrupamento.")
        api.salvar_csv(saida / "particoes.csv", particoes, list(particoes[0]))
        for nome in PARTICOES:
            indices = np.array([x["indice_global"] for x in particoes if x["particao"] == nome], dtype=np.int64)
            np.save(saida / (nome + "_indices.npy"), indices, allow_pickle=False)
        np.save(saida / "grupos_por_linha.npy", np.array([int(grupos[x["uid"]][2:]) for x in linhas],
                                                        dtype=np.int64), allow_pickle=False)
        nomes = ["global_cluster.tsv", "particoes.csv", "grupos_por_linha.npy",
                 *[p + "_indices.npy" for p in PARTICOES]]
        r.update(ok=True, status="grupos_e_particoes_prontos_embeddings_pendentes",
                 segundos=round(time.perf_counter() - inicio, 3),
                 ordem_indices="Indices int64, base zero, relativos as linhas do piloto_rotulado.csv; "
                               "grupos_por_linha guarda o indice da representante nesse CSV.",
                 hashes_saidas={n: api.sha(saida / n) for n in nomes})
        api.salvar_json(saida / "relatorio_preparacao_ec.json", r)
        return r
    except KeyboardInterrupt:
        r.update(status="interrompida_preparacao_inconclusiva")
        api.salvar_json(saida / "relatorio_preparacao_ec.json", r)
        raise
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
        r.update(status="falha_preparacao_inconclusiva", erro=str(e))
        api.salvar_json(saida / "relatorio_preparacao_ec.json", r)
        raise ValueError(f"{e}\nArquivos preservados em: {saida}") from e


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--coleta", required=True, type=Path)
    p.add_argument("--esperado", type=int, default=None)
    p.add_argument("--wsl", help="Distribuicao que ja tem MMseqs2 instalado, ex.: Ubuntu.")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--semente", type=int, default=42)
    args = p.parse_args(argv)
    try:
        r = preparar(args.coleta, args.esperado, args.wsl, args.threads, args.semente)
    except KeyboardInterrupt:
        print("Preparacao interrompida; nenhum treino iniciado.")
        return 130
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
        print(json.dumps({"ok": False, "erro": str(e), "treinamento_realizado": False},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
