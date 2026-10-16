"""Consolidar embeddings auditados, agrupar com MMseqs2 e separar por grupos.

Salvar em C:\\ai_tcc\\etapas. Usa somente a biblioteca padrao e NumPy.
Subcomandos: consolidar, diagnosticar, agrupar e separar.
Nao importa PyTorch, nao baixa modelos nem treina um classificador.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

import numpy as np

PROJETO = Path(__file__).resolve().parents[1]
ORIGINAL = PROJETO / "dados/embeddings/base_ncbi_gpu"
BASE = PROJETO / "dados/base_ia/base_1m"
GRUPOS = PROJETO / "dados/base_ia/agrupamento_global_1m"
PARTICOES = PROJETO / "dados/base_ia/particoes_1m"
MODELO = "facebook/esm2_t6_8M_UR50D"
REVISAO = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
ESSENCIAIS = set("HILKMFTWV")
ROTULOS = ("Completa", "Incompleta")
NOMES_PARTICOES = ("treino", "validacao", "teste")
COLUNAS = ("indice_global", "uid", "id_original", "grupo_por_arquivo",
           "arquivo_origem", "tamanho", "sha256_sequencia", "Tipo_Nutricional",
           "lote_original", "indice_embedding_original")


def exigir(condicao, mensagem):
    if not condicao:
        raise ValueError(mensagem)


def ler_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def salvar_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha_arquivo(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def uid(indice):
    return f"p{indice:09d}"


def indice_uid(value, total):
    exigir(re.fullmatch(r"p[0-9]{9}", value) is not None, f"UID desconhecido: {value!r}")
    indice = int(value[1:])
    exigir(indice < total, f"UID fora da base: {value}")
    return indice


def espaco(path, reserva, adicional=0):
    livre = shutil.disk_usage(path).free
    exigir(livre >= reserva * 1024**3 + adicional,
           f"Espaco insuficiente em {path}: {livre / 1024**3:.2f} GiB livres; "
           f"reserva {reserva:g} GiB mais {adicional / 1024**3:.2f} GiB estimados.")
    return round(livre / 1024**3, 2)


@contextmanager
def saida_nova(destino, entradas=(), preservar_falha=False):
    destino = destino.resolve()
    for entrada in entradas:
        entrada = entrada.resolve()
        exigir(not destino.is_relative_to(entrada) and not entrada.is_relative_to(destino),
               "A saida precisa ficar fora das entradas e de suas pastas ancestrais.")
    exigir(not destino.exists(), f"A saida ja existe: {destino}. Preserve-a e use outra --saida.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporaria = Path(tempfile.mkdtemp(prefix=f".{destino.name}_parcial_", dir=destino.parent))
    try:
        yield temporaria
        exigir(not destino.exists(), "A saida foi criada por outra execucao. Nada sera sobrescrito.")
        temporaria.rename(destino)
    except BaseException:
        if preservar_falha:
            print(f"Arquivos da execucao incompleta preservados em: {temporaria}", flush=True)
        elif temporaria.exists():
            # Apenas a pasta privada criada por esta chamada; nunca uma entrada.
            shutil.rmtree(temporaria)
        raise


def escolher_auditoria(base, esperado, especificada=None):
    if especificada is not None:
        arquivos = [especificada.resolve()]
    else:
        raiz = PROJETO / "dados/validacao/base_ncbi_gpu"
        arquivos = sorted(raiz.glob("auditoria_*/relatorio.json"), reverse=True)
    for path in arquivos:
        try:
            r = ler_json(path)
            if (r.get("tipo") == "auditoria_tecnica_embeddings" and r.get("ok") is True
                    and r.get("erros_total") == 0 and r.get("esperado") == esperado
                    and r.get("formato_total_observado") == [esperado, 320]
                    and Path(r.get("base", "")).resolve() == base):
                return path, r
        except (OSError, ValueError, TypeError):
            continue
    raise ValueError("Nao foi localizada auditoria aprovada desta base. "
                     "Use --auditoria CAMINHO_DO_RELATORIO_JSON.")


def assinatura_controle(base):
    db = base / "controle.sqlite3"
    return sha_arquivo(base / "relatorio_execucao.json"), db.stat().st_size, db.stat().st_mtime_ns


def consolidar(args):
    inicio = time.perf_counter()
    base, destino = args.base.resolve(), args.saida.resolve()
    auditoria_path, auditoria = escolher_auditoria(base, args.esperado, args.auditoria)
    rel = ler_json(base / "relatorio_execucao.json")
    exigir(rel.get("ok") is True and rel.get("embeddings_total") == args.esperado,
           "O relatorio de geracao nao corresponde ao total esperado.")
    exigir(rel.get("modelo") == MODELO and rel.get("revisao") == REVISAO, "Modelo/revisao incompatíveis.")
    inicial = assinatura_controle(base)
    db = sqlite3.connect((base / "controle.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        versao_db = db.execute("PRAGMA data_version").fetchone()[0]
        config = json.loads(db.execute("SELECT valor FROM meta WHERE chave='config'").fetchone()[0])
        exigir(config.get("modelo") == MODELO and config.get("revisao") == REVISAO
               and config.get("schema") == 1 and config.get("regra_aminoacidos") == "HILKMFTWV",
               "Configuracao do SQLite incompatível.")
        lotes = db.execute("SELECT numero,novos,completas,incompletas FROM lotes ORDER BY numero").fetchall()
        total = sum(x[1] for x in lotes)
        exigir(total == args.esperado == db.execute("SELECT COUNT(*) FROM vetores").fetchone()[0],
               "Contagens do controle divergentes.")
        exigir(len(lotes) == auditoria["totais_examinados"]["lotes"], "Numero de lotes mudou apos auditoria.")
        exigir({p.name for p in (base / "lotes").glob("lote_*") if p.is_dir()}
               == {f"lote_{x[0]:06d}" for x in lotes}, "Pastas de lotes e controle divergem.")
        max_residuos = int(config["max_residuos"])
        contagem, comprimentos, offset = Counter(), Counter(), 0
        with saida_nova(destino, (base, auditoria_path)) as tmp:
            espaco(tmp, args.reserva_gib, total * (320 * 4 + max_residuos + 600) + 1024**2)
            matriz = np.lib.format.open_memmap(tmp / "embeddings.npy", mode="w+",
                                              dtype=np.float32, shape=(total, 320))
            try:
                with (tmp / "indice.csv").open("w", encoding="utf-8-sig", newline="") as tabela, \
                        (tmp / "sequencias.fasta").open("w", encoding="ascii", newline="\n") as fasta:
                    escritor = csv.DictWriter(tabela, fieldnames=COLUNAS, delimiter=";")
                    escritor.writeheader()
                    for ordinal, (numero, quantidade, completas, incompletas) in enumerate(lotes, 1):
                        pasta = base / "lotes" / f"lote_{numero:06d}"
                        r = ler_json(pasta / "relatorio.json")
                        exigir(r.get("ok") is True and r.get("numero_lote") == numero
                               and r.get("config") == config and r.get("novos") == quantidade,
                               f"Metadados invalidos em {pasta.name}.")
                        arquivos = {}
                        for nome, limite in (("amostra.csv", max(65536, quantidade * (max_residuos + 8192))),
                                             ("embeddings.npy", quantidade * 320 * 4 + 65536)):
                            path = pasta / nome
                            exigir(path.stat().st_size <= limite, f"Arquivo excede o formato esperado: {path}")
                            dados = path.read_bytes()
                            exigir(hashlib.sha256(dados).hexdigest() == r["hashes_arquivos"][nome],
                                   f"Arquivo alterado desde o registro do lote: {path}")
                            arquivos[nome] = dados
                        rows = list(csv.DictReader(io.StringIO(arquivos["amostra.csv"].decode("utf-8-sig")),
                                                   delimiter=";", strict=True))
                        vetores = np.load(io.BytesIO(arquivos["embeddings.npy"]), allow_pickle=False)
                        exigir(vetores.shape == (quantidade, 320) and vetores.dtype == np.float32
                               and np.isfinite(vetores).all(), f"Vetores invalidos no lote {numero}.")
                        exigir(len(rows) == quantidade and offset + quantidade <= total,
                               f"Contagem invalida no lote {numero}.")
                        refs = {}
                        for k in range(0, quantidade, 200):
                            hashes = [x["sha256_sequencia"] for x in rows[k:k + 200]]
                            refs.update((h, (l, i)) for h, l, i in db.execute(
                                "SELECT sha,lote,linha FROM vetores WHERE sha IN (" + ",".join("?" for _ in hashes) + ")", hashes))
                        locais = Counter()
                        for indice, row in enumerate(rows):
                            seq = row["sequencia"]
                            h = hashlib.sha256(seq.encode("ascii")).hexdigest()
                            exigir(int(row["indice_embedding"]) == indice and row["sha256_sequencia"] == h
                                   and refs.get(h) == (numero, indice), f"Vinculo alterado no lote {numero}, linha {indice}.")
                            exigir(0 < len(seq) <= max_residuos and int(row["tamanho"]) == len(seq),
                                   f"Comprimento invalido no lote {numero}, linha {indice}.")
                            rotulo = "Completa" if ESSENCIAIS <= set(seq) else "Incompleta"
                            exigir(row["Tipo_Nutricional"] == rotulo, "Rotulo diverge da regra de presenca dos aminoacidos.")
                            global_i = offset + indice
                            identificador = uid(global_i)
                            fasta.write(f">{identificador}\n{seq}\n")
                            escritor.writerow(dict(zip(COLUNAS, (global_i, identificador, row["id"], row["grupo"],
                                row["arquivo_origem"], len(seq), h, rotulo, numero, indice))))
                            locais[rotulo] += 1
                            comprimentos[len(seq)] += 1
                        exigir((locais["Completa"], locais["Incompleta"]) == (completas, incompletas),
                               f"Contagem de rotulos diverge no lote {numero}.")
                        matriz[offset:offset + quantidade] = vetores
                        offset += quantidade
                        contagem.update(locais)
                        if ordinal % 500 == 0 or ordinal == len(lotes):
                            matriz.flush()
                            espaco(tmp, args.reserva_gib)
                            print(f"Consolidacao: {ordinal}/{len(lotes)} lotes; {offset}/{total} proteinas copiadas.", flush=True)
                exigir(offset == total and assinatura_controle(base) == inicial
                       and db.execute("PRAGMA data_version").fetchone()[0] == versao_db,
                       "A base mudou durante a consolidacao. Encerre o gerador antes de repetir.")
                exigir({x: contagem[x] for x in ROTULOS} == auditoria["rotulos_vetores"], "Rotulos diferem da auditoria.")
                matriz.flush()
            finally:
                del matriz  # Fecha o mmap antes do rename no Windows.
            hashes = {nome: sha_arquivo(tmp / nome) for nome in ("sequencias.fasta", "indice.csv", "embeddings.npy")}
            resultado = {"tipo": "base_ia_consolidada", "schema": 1, "ok": True, "modelo": MODELO, "revisao": REVISAO,
                         "base_original": str(base), "auditoria": str(auditoria_path),
                         "auditoria_sha256": sha_arquivo(auditoria_path), "relatorio_original_sha256": inicial[0],
                         "config_original": config, "proteinas": total, "lotes_originais": len(lotes),
                         "formato_embeddings": [total, 320], "precisao": "float32",
                         "rotulos": {x: contagem[x] for x in ROTULOS}, "comprimento_minimo": min(comprimentos),
                         "comprimento_maximo": max(comprimentos), "hashes_arquivos": hashes,
                         "ordem": "Linha i do NPY = linha de dados i do indice.csv = registro FASTA p seguido de i em 9 digitos; i comeca em zero.",
                         "originais_alterados": False, "embeddings_regenerados": False, "gpu_utilizada": False,
                         "treinamento_realizado": False, "agrupamento_global": "pendente",
                         "recorte_ncbi": "Primeiro milhao de sequencias unicas elegiveis na ordem do processamento; nao amostra aleatoria de todo NCBI.",
                         "regra_rotulo": "Presenca literal de HILKMFTWV; nao mede qualidade nutricional nem digestibilidade.",
                         "pasta_saida": str(destino), "segundos": round(time.perf_counter() - inicio, 3)}
            salvar_json(tmp / "relatorio_consolidacao.json", resultado)
        return resultado
    finally:
        db.close()


def ler_base(base):
    r = ler_json(base / "relatorio_consolidacao.json")
    exigir(r.get("ok") is True and r.get("tipo") == "base_ia_consolidada"
           and r.get("schema") == 1 and r.get("formato_embeddings") == [r.get("proteinas"), 320],
           "A base consolidada nao foi concluida corretamente.")
    return r


def executar_curto(comando, timeout=30):
    p = subprocess.run(comando, capture_output=True, timeout=timeout, check=False)
    def texto(b):
        return b.decode("utf-16", errors="replace") if b.startswith((b"\xff\xfe", b"\xfe\xff")) or b.count(b"\0") > len(b) / 5 else b.decode("utf-8", errors="replace")
    return p.returncode, texto(p.stdout), texto(p.stderr)


class Backend:
    def __init__(self, distro=None, executavel=None):
        self.distro = distro
        if distro:
            exigir(os.name == "nt" and shutil.which("wsl.exe"), "--wsl requer Windows com WSL instalado.")
            self.prefixo = ["wsl.exe", "--distribution", distro, "--exec"]
            self.programa = executavel or "mmseqs"
        else:
            exigir(os.name != "nt", "No Windows, escolha a distribuicao com --wsl NOME apos o diagnostico.")
            self.prefixo = []
            self.programa = executavel or shutil.which("mmseqs")
            exigir(self.programa, "MMseqs2 nao foi encontrado no PATH deste Linux.")

    def cmd(self, *args):
        return self.prefixo + [str(self.programa)] + list(args)

    def path(self, path):
        if not self.distro:
            return str(path.resolve())
        code, out, err = executar_curto(self.prefixo + ["wslpath", "-u", str(path.resolve())])
        exigir(code == 0 and out.strip().startswith("/"), f"Nao foi possivel converter o caminho para WSL: {err}")
        return out.strip()

    def version(self):
        code, out, err = executar_curto(self.cmd("version"))
        exigir(code == 0 and out.strip(), f"MMseqs2 indisponivel neste ambiente: {err or out}")
        return out.strip()


def diagnosticar(args):
    resultado = {"tipo": "diagnostico_mmseqs2", "ok": True, "sistema": sys.platform,
                 "mmseqs_no_path": shutil.which("mmseqs"), "distribuicoes_wsl": [],
                 "mmseqs_disponivel": False, "instalacoes_realizadas": False}
    if os.name != "nt":
        try:
            resultado["versao_mmseqs2"] = Backend().version()
            resultado["mmseqs_disponivel"] = True
        except (ValueError, OSError, subprocess.TimeoutExpired) as e:
            resultado["aviso"] = str(e)
        return resultado
    if not shutil.which("wsl.exe"):
        resultado["aviso"] = "WSL nao encontrado. O MMseqs2 existente pode estar em uma VM ou em outra maquina."
        return resultado
    try:
        code, out, err = executar_curto(["wsl.exe", "--list", "--quiet"])
        exigir(code == 0, err or out)
        for nome in out.replace("\0", "").splitlines():
            nome = nome.strip()
            if not nome or "docker" in nome.casefold():
                continue
            item = {"nome": nome, "mmseqs_disponivel": False}
            try:
                item["versao_mmseqs2"] = Backend(nome).version()
                item["mmseqs_disponivel"] = True
                resultado["mmseqs_disponivel"] = True
            except (ValueError, OSError, subprocess.TimeoutExpired) as e:
                item["aviso"] = str(e)
            resultado["distribuicoes_wsl"].append(item)
    except (ValueError, OSError, subprocess.TimeoutExpired) as e:
        resultado["aviso"] = str(e)
    return resultado


def ler_grupos(path, total):
    grupos = np.full(total, -1, dtype=np.int64)
    with path.open(encoding="utf-8", newline="") as f:
        for numero, row in enumerate(csv.reader(f, delimiter="\t"), 1):
            exigir(len(row) == 2, f"TSV: linha {numero} precisa conter representante e membro, sem cabecalho.")
            rep, membro = (indice_uid(x, total) for x in row)
            exigir(grupos[membro] == -1, f"Proteina duplicada no TSV: {uid(membro)}")
            grupos[membro] = rep
    exigir(np.all(grupos >= 0), "O TSV nao cobre todas as proteinas da base consolidada.")
    representantes, tamanhos = np.unique(grupos, return_counts=True)
    exigir(np.all(grupos[representantes] == representantes), "Um representante pertence a outro grupo no TSV.")
    return grupos, representantes, tamanhos


def agrupar(args):
    inicio = time.perf_counter()
    base, destino = args.base.resolve(), args.saida.resolve()
    rel = ler_base(base)
    fasta = base / "sequencias.fasta"
    exigir(sha_arquivo(fasta) == rel["hashes_arquivos"]["sequencias.fasta"], "FASTA consolidado foi alterado.")
    backend = Backend(args.wsl, args.executavel)
    versao = backend.version()
    code, ajuda, err = executar_curto(backend.cmd("easy-linclust", "-h"))
    for flag in ("--cluster-mode", "--alignment-mode", "--kmer-per-seq", "--split-memory-limit"):
        exigir(flag in ajuda + err, f"A versao instalada nao anunciou {flag}. Envie o diagnostico antes de prosseguir.")
    parametros = ["--min-seq-id", "0.5", "-c", "0.8", "--cov-mode", "0", "--cluster-mode", "1",
                  "--alignment-mode", "3", "--kmer-per-seq", "80", "--split-memory-limit", "8G",
                  "-e", "0.001", "--threads", str(args.threads), "--remove-tmp-files", "1"]
    with saida_nova(destino, (base,), preservar_falha=True) as tmp:
        espaco(tmp, args.reserva_gib)
        temporario = tmp / "temporario_mmseqs"
        temporario.mkdir()
        # Temporario em Linux nativo para evitar muitas operacoes pequenas em /mnt/c.
        if args.wsl:
            code, out, err = executar_curto(backend.prefixo + ["mktemp", "-d", "-p", "/var/tmp", "tcc_mmseqs.XXXXXXXX"])
            exigir(code == 0 and re.fullmatch(r"/var/tmp/tcc_mmseqs\.[A-Za-z0-9]+", out.strip()),
                   "Nao foi possivel criar pasta privada temporaria no Linux.")
            tmp_mmseqs = out.strip()
            code, out, err = executar_curto(backend.prefixo + ["df", "-Pk", tmp_mmseqs])
            exigir(code == 0 and int(out.splitlines()[-1].split()[3]) * 1024 >= args.reserva_gib * 1024**3,
                   "O sistema de arquivos temporario do WSL nao tem a reserva livre solicitada.")
        else:
            tmp_mmseqs = str(temporario)
        comando = backend.cmd("easy-linclust", backend.path(fasta), backend.path(tmp / "global"), tmp_mmseqs, *parametros)
        if args.wsl:
            comando = backend.prefixo + ["env", f"MMSEQS_NUM_THREADS={args.threads}"] + comando[len(backend.prefixo):]
        env = os.environ.copy()
        env["MMSEQS_NUM_THREADS"] = str(args.threads)
        registro = {"tipo": "agrupamento_global_mmseqs2", "ok": False, "base": str(base),
                    "fasta_sha256": rel["hashes_arquivos"]["sequencias.fasta"], "proteinas": rel["proteinas"],
                    "versao_mmseqs2": versao, "comando": comando, "temporario_mmseqs": tmp_mmseqs,
                    "threads_cpu": args.threads, "gpu_utilizada": False, "treinamento_realizado": False}
        salvar_json(tmp / "execucao.json", registro)
        print(f"MMseqs2 {versao}: agrupamento GLOBAL de {rel['proteinas']} proteinas; {args.threads} threads CPU.", flush=True)
        print(f"Log detalhado: {tmp / 'mmseqs.log'}", flush=True)
        processo = None
        try:
            with (tmp / "mmseqs.log").open("w", encoding="utf-8") as log:
                processo = subprocess.Popen(comando, stdout=log, stderr=subprocess.STDOUT, env=env)
                proximo_aviso = time.monotonic() + 60
                while processo.poll() is None:
                    time.sleep(1)
                    if time.monotonic() >= proximo_aviso:
                        print(f"MMseqs2 em execucao ha {int(time.perf_counter() - inicio)} s; acompanhe mmseqs.log.", flush=True)
                        proximo_aviso = time.monotonic() + 60
                exigir(processo.returncode == 0, f"MMseqs2 encerrou com codigo {processo.returncode}. Consulte mmseqs.log.")
            tsv = tmp / "global_cluster.tsv"
            grupos, representantes, tamanhos = ler_grupos(tsv, rel["proteinas"])
            exigir(sha_arquivo(fasta) == registro["fasta_sha256"], "FASTA mudou durante o agrupamento.")
            registro.update({"ok": True, "grupos": len(representantes), "maior_grupo": int(tamanhos.max()),
                             "tsv_sha256": sha_arquivo(tsv), "parametros": {"identidade_minima": 0.5,
                             "cobertura_minima": 0.8, "cov_mode": 0, "cluster_mode": 1,
                             "alignment_mode": 3, "kmer_per_seq": 80, "split_memory_limit": "8G", "evalue": 0.001},
                             "pasta_saida": str(destino), "segundos": round(time.perf_counter() - inicio, 3),
                             "limites": "Linclust e heuristico. Grupos disjuntos nao provam ausencia de toda homologia entre conjuntos; limiares e sensibilidade devem ser relatados."})
            del grupos
            salvar_json(tmp / "relatorio_agrupamento.json", registro)
            if args.wsl:
                # rmdir so remove a pasta privada se estiver vazia; nao apaga arquivos.
                executar_curto(backend.prefixo + ["rmdir", "--", tmp_mmseqs])
            return registro
        except BaseException as e:
            if processo is not None and processo.poll() is None:
                processo.terminate()
                try:
                    processo.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    processo.kill()
                    processo.wait(timeout=10)
            registro["erro"] = f"{type(e).__name__}: {e}"
            salvar_json(tmp / "relatorio_erro.json", registro)
            raise


def destinos_dos_grupos(grupos, representantes, total, semente, fracoes):
    destino_rep = np.full(total, 255, dtype=np.uint8)
    for rep in representantes:
        numero = int.from_bytes(hashlib.sha256(f"{semente}:{uid(int(rep))}".encode()).digest()[:8], "big") / 2**64
        destino_rep[rep] = 0 if numero < fracoes[0] else (1 if numero < fracoes[0] + fracoes[1] else 2)
    return destino_rep[grupos], destino_rep


def separar(args):
    inicio = time.perf_counter()
    base, agrupamento, destino = args.base.resolve(), args.agrupamento.resolve(), args.saida.resolve()
    r = ler_base(base)
    ag = ler_json(agrupamento / "relatorio_agrupamento.json")
    exigir(ag.get("ok") is True and ag.get("tipo") == "agrupamento_global_mmseqs2"
           and ag.get("proteinas") == r["proteinas"]
           and ag.get("fasta_sha256") == r["hashes_arquivos"]["sequencias.fasta"],
           "O agrupamento nao corresponde a esta base completa.")
    tsv = agrupamento / "global_cluster.tsv"
    exigir(sha_arquivo(tsv) == ag["tsv_sha256"], "TSV de grupos alterado.")
    exigir(sha_arquivo(base / "indice.csv") == r["hashes_arquivos"]["indice.csv"], "Indice consolidado alterado.")
    total = r["proteinas"]
    grupos, representantes, tamanhos = ler_grupos(tsv, total)
    exigir(len(representantes) >= 3 and len(representantes) == ag["grupos"], "Sao necessarios ao menos tres grupos confirmados.")
    particoes, destino_rep = destinos_dos_grupos(grupos, representantes, total, args.semente, args.fracoes)
    contagens = [Counter() for _ in NOMES_PARTICOES]
    indices = [np.flatnonzero(particoes == i).astype(np.int64) for i in range(3)]
    exigir(all(len(x) for x in indices), "Uma particao ficou vazia. Preserve os grupos; revise a semente ou as fracoes.")
    with saida_nova(destino, (base, agrupamento)) as tmp:
        espaco(tmp, args.reserva_gib)
        for nome, arr in zip(NOMES_PARTICOES, indices):
            np.save(tmp / f"{nome}_indices.npy", arr, allow_pickle=False)
        np.save(tmp / "grupos_por_linha.npy", grupos, allow_pickle=False)
        colunas = ("indice_global", "uid", "grupo_global", "particao", "Tipo_Nutricional")
        examinados = 0
        with (base / "indice.csv").open(encoding="utf-8-sig", newline="") as entrada, \
                (tmp / "particoes.csv").open("w", encoding="utf-8-sig", newline="") as saida:
            escritor = csv.DictWriter(saida, fieldnames=colunas, delimiter=";")
            escritor.writeheader()
            for i, row in enumerate(csv.DictReader(entrada, delimiter=";", strict=True)):
                exigir(i < total and int(row["indice_global"]) == i and row["uid"] == uid(i), "Ordem do indice invalida.")
                exigir(row["Tipo_Nutricional"] in ROTULOS, "Rotulo inesperado no indice.")
                particao = int(particoes[i])
                contagens[particao][row["Tipo_Nutricional"]] += 1
                escritor.writerow(dict(zip(colunas, (i, uid(i), uid(int(grupos[i])),
                                   NOMES_PARTICOES[particao], row["Tipo_Nutricional"]))))
                examinados += 1
                if examinados % 100000 == 0:
                    print(f"Separacao por grupos: {examinados}/{total} proteinas.", flush=True)
        exigir(examinados == total, "Indice nao cobre a base completa.")
        exigir({x: sum(c[x] for c in contagens) for x in ROTULOS} == r["rotulos"], "Contagens de rotulos divergentes.")
        grupos_particao = [representantes[destino_rep[representantes] == i] for i in range(3)]
        exigir(sum(len(x) for x in grupos_particao) == len(representantes), "Particao de grupos incompleta.")
        exigir(not any(np.intersect1d(grupos_particao[i], grupos_particao[j]).size for i, j in ((0, 1), (0, 2), (1, 2))),
               "Um grupo aparece em mais de uma particao.")
        resultado = {"tipo": "particoes_por_grupos_globais", "ok": True, "proteinas": total,
                     "base_consolidada": str(base), "agrupamento": str(agrupamento), "tsv_sha256": ag["tsv_sha256"],
                     "semente": args.semente, "fracoes_solicitadas": dict(zip(NOMES_PARTICOES, args.fracoes)),
                     "metodo": "SHA256(semente:UID_representante) determina a particao de cada grupo inteiro; proporcoes aproximadas, sem estratificacao forcada.",
                     "particoes": {nome: {"proteinas": len(indices[i]), "grupos": len(grupos_particao[i]),
                                  "fracao_observada": round(len(indices[i]) / total, 6),
                                  "rotulos": {x: contagens[i][x] for x in ROTULOS}}
                                  for i, nome in enumerate(NOMES_PARTICOES)},
                     "maior_grupo": int(tamanhos.max()), "grupos_compartilhados_entre_particoes": 0,
                     "arquivos_indices": "Indices int64 comecando em zero, relativos ao embeddings.npy e indice.csv da base consolidada.",
                     "embeddings_duplicados": False, "gpu_utilizada": False, "treinamento_realizado": False,
                     "avaliacao_biologica_concluida": False,
                     "limites": "Ausencia de grupos compartilhados verificada; Linclust pode perder homologos. Proporcoes e classes devem ser inspecionadas antes do treino. Rótulos de funcao biologica precisam de anotacao propria.",
                     "pasta_saida": str(destino), "segundos": round(time.perf_counter() - inicio, 3)}
        arquivos = ["particoes.csv", "grupos_por_linha.npy"] + [f"{x}_indices.npy" for x in NOMES_PARTICOES]
        resultado["hashes_arquivos"] = {nome: sha_arquivo(tmp / nome) for nome in arquivos}
        salvar_json(tmp / "relatorio_particoes.json", resultado)
        return resultado


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    comandos = parser.add_subparsers(dest="etapa", required=True)
    c = comandos.add_parser("consolidar", help="Reune as sequencias e copia os embeddings auditados.")
    c.add_argument("--base", type=Path, default=ORIGINAL)
    c.add_argument("--saida", type=Path, default=BASE)
    c.add_argument("--esperado", type=int, default=1000000)
    c.add_argument("--auditoria", type=Path)
    c.set_defaults(func=consolidar)
    d = comandos.add_parser("diagnosticar", help="Procura MMseqs2 em Linux/WSL, sem instalar nada.")
    d.set_defaults(func=diagnosticar)
    a = comandos.add_parser("agrupar", help="Executa Linclust global com duas threads CPU por padrao.")
    a.add_argument("--base", type=Path, default=BASE)
    a.add_argument("--saida", type=Path, default=GRUPOS)
    a.add_argument("--wsl", help="Nome EXATO de uma distribuicao com MMseqs2 instalado, informado pelo diagnostico.")
    a.add_argument("--executavel", help="Caminho do MMseqs2 no Linux/WSL, se nao estiver no PATH.")
    a.add_argument("--threads", type=int, choices=range(1, 13), default=2,
                   help="Threads CPU de 1 a 12; padrao: 2. Escolha conforme a CPU e o uso do PC.")
    a.set_defaults(func=agrupar)
    s = comandos.add_parser("separar", help="Cria indices de treino/validacao/teste com grupos disjuntos.")
    s.add_argument("--base", type=Path, default=BASE)
    s.add_argument("--agrupamento", type=Path, default=GRUPOS)
    s.add_argument("--saida", type=Path, default=PARTICOES)
    s.add_argument("--semente", type=int, default=42)
    s.add_argument("--fracoes", type=float, nargs=3, default=(0.8, 0.1, 0.1))
    s.set_defaults(func=separar)
    for sub in (c, a, s):
        sub.add_argument("--reserva-gib", type=float, default=10)
    args = parser.parse_args(argv)
    if getattr(args, "esperado", 1) < 1 or getattr(args, "reserva_gib", 0) < 0:
        parser.error("Total precisa ser positivo e reserva nao negativa.")
    if hasattr(args, "fracoes") and (not all(0 < x < 1 for x in args.fracoes) or abs(sum(args.fracoes) - 1) > 1e-9):
        parser.error("Use tres fracoes positivas com soma 1, por exemplo 0.8 0.1 0.1.")
    try:
        resultado = args.func(args)
    except (Exception, KeyboardInterrupt) as e:
        print(json.dumps({"ok": False, "etapa": args.etapa, "erro": f"{type(e).__name__}: {e}",
                          "originais_alterados": False, "treinamento_realizado": False}, indent=2, ensure_ascii=False))
        return 2
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
