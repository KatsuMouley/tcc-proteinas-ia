"""Embeddings dos representantes da sua base NCBI, com rótulos e retomada.

Salvar este arquivo em C:\\ai_tcc\\etapas\\processar_base_gpu.py.
Depende do piloto_esm_gpu.py já instalado em C:\\ai_tcc e do ESM-2 em cache.

Primeira execução, até 1.000 vetores únicos neste processamento:
  .venv\\Scripts\\python.exe etapas\\processar_base_gpu.py --limite 1000
Ampliar o total, retomando a mesma saída:
  .venv\\Scripts\\python.exe etapas\\processar_base_gpu.py --limite 5000
Processar os demais representantes elegíveis:
  .venv\\Scripts\\python.exe etapas\\processar_base_gpu.py --completar

Lê GZ/CSV dentro de ZIP, sem extrair a base no SSD. Uma sequência por inferência,
float32, CUDA obrigatória, duas threads PyTorch por padrão. Não treina.
Até 512 resíduos por padrão; sequências maiores são registradas nos descartes.
Tipo_Nutricional = presença literal de H,I,L,K,M,F,T,W,V; não mede digestibilidade
ou qualidade nutricional. Rótulos de função biológica continuam sendo outra etapa.

A saída é separada do piloto de 100: dados/embeddings/base_ncbi_gpu.
Cada lote tem amostra.csv, amostra.fasta, embeddings.npy, repetidos.csv,
descartes.csv e relatorio.json. A linha indice_embedding do CSV aponta para a
mesma linha do NPY. Repetidos.csv preserva outros IDs/grupos de sequência idêntica,
apontando para o lote e a linha do vetor já gerado. Controle.sqlite3 registra
o progresso e os hashes; não remover durante a retomada. Não alterar as fontes
durante este processamento. Uma retomada relê o GZ que estava em andamento,
pulando os representantes já registrados; lotes confirmados não são recalculados.
Agrupamento global por homologia e separação treino/teste continuam pendentes.

--limite é o TOTAL desejado nesta saída, incluindo execuções anteriores; não é
limite por arquivo. Base completa significa todos os pares encontrados percorridos
e seus representantes registrados como aceitos, repetidos ou descartados.
Leituras interrompidas pelo limite ainda não validam a integridade integral do GZ.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
import hashlib
from itertools import chain
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

PROJETO = Path(__file__).resolve().parents[1]
MODELO = "facebook/esm2_t6_8M_UR50D"
REVISAO = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
ESSENCIAIS = frozenset("HILKMFTWV")
COLUNAS = ["id", "grupo", "arquivo_origem", "descricao", "tamanho",
           "sha256_sequencia", "stops_finais_removidos", "sequencia",
           "Tipo_Nutricional", "rotulo_csv", "verificacao_rotulo"]
COL_REPETIDOS = [c for c in COLUNAS if c != "sequencia"] + ["lote_referencia", "indice_embedding_referencia"]
COL_DESCARTES = ["id", "grupo", "arquivo_origem", "tamanho", "motivo", "rotulo_csv", "rotulo_calculado"]


def digest_arquivo(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def get_meta(db, key, default=None):
    row = db.execute("SELECT valor FROM meta WHERE chave=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_meta(db, key, value):
    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))


def espaco_livre(pasta, reserva_gb):
    livre = shutil.disk_usage(pasta).free / 1024**3
    if livre < reserva_gb:
        raise RuntimeError(f"SSD com {livre:.1f} GiB livres; reserva configurada de {reserva_gb:g} GiB. Progresso salvo.")
    return livre


@contextmanager
def uma_execucao(pasta):
    """Trava liberada pelo sistema mesmo se o processo for interrompido."""
    with (pasta / ".processamento.lock").open("a+b") as f:
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as e:
                raise RuntimeError("Já existe um processamento usando esta saída.") from e
        else:
            import fcntl
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as e:
                raise RuntimeError("Já existe um processamento usando esta saída.") from e
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def assinatura_fontes(pares):
    fontes = []
    for numero, (gz, tabela) in enumerate(pares, 1):
        def dados(f):
            st = f.caminho.stat()
            return {"local": f.local, "bytes_arquivo": st.st_size, "mtime_ns": st.st_mtime_ns}
        fontes.append({"par": numero, "gz": dados(gz), "csv": dados(tabela)})
    serial = json.dumps(fontes, ensure_ascii=False, sort_keys=True).encode()
    return fontes, hashlib.sha256(serial).hexdigest()


def ler_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def registrar_lote(db, pasta, config):
    """Confirma uma gravação completa; também recupera rename anterior a commit."""
    r = json.loads((pasta / "relatorio.json").read_text(encoding="utf-8"))
    numero = r["numero_lote"]
    if pasta.name != f"lote_{numero:06d}":
        raise ValueError("Nome e número do lote inconsistentes.")
    if db.execute("SELECT 1 FROM lotes WHERE numero=?", (numero,)).fetchone():
        if any(not (pasta / nome).is_file() for nome in r["hashes_arquivos"]):
            raise ValueError(f"Arquivos de lote removidos: {pasta}.")
        return
    if r["config"] != config or get_meta(db, "par_indexado") != r["indice_par"]:
        raise ValueError("Lote não registrado pertence a outra configuração ou fonte.")
    for nome, digest in r["hashes_arquivos"].items():
        if digest_arquivo(pasta / nome) != digest:
            raise ValueError(f"Arquivo de lote incompleto ou alterado: {pasta / nome}.")
    amostra = ler_csv(pasta / "amostra.csv")
    repetidos = ler_csv(pasta / "repetidos.csv")
    descartes = ler_csv(pasta / "descartes.csv")
    if [len(amostra), len(repetidos), len(descartes)] != [r["novos"], r["repetidos"], r["descartes"]]:
        raise ValueError("Contagens do lote inconsistentes.")
    with db:
        db.execute("INSERT INTO lotes VALUES (?,?,?,?,?,?,?)", (
            numero, len(amostra), len(repetidos), len(descartes),
            sum(x["Tipo_Nutricional"] == "Completa" for x in amostra),
            sum(x["Tipo_Nutricional"] == "Incompleta" for x in amostra),
            r.get("segundos_embeddings_apos_aquecimento", 0.0)))
        for indice, row in enumerate(amostra):
            if int(row["indice_embedding"]) != indice:
                raise ValueError("Ordem do lote inconsistente.")
            db.execute("INSERT INTO vetores VALUES (?,?,?)", (row["sha256_sequencia"], numero, indice))
        for row in repetidos:
            ref = db.execute("SELECT lote, linha FROM vetores WHERE sha=?", (row["sha256_sequencia"],)).fetchone()
            if ref != (int(row["lote_referencia"]), int(row["indice_embedding_referencia"])):
                raise ValueError("Referência de sequência repetida inconsistente.")
        db.executemany("UPDATE candidatos SET feito=1 WHERE id=?",
                       [(row["id"],) for row in amostra + repetidos + descartes])


def indexar_csv(piloto, db, fonte, nome_gz, indice, saida, reserva):
    if get_meta(db, "par_indexado", -1) == indice:
        return
    with db:
        db.execute("DELETE FROM candidatos")
        set_meta(db, "par_indexado", -1)
    lidos = 0
    print(f"Indexando os grupos do CSV de {nome_gz}.", flush=True)
    with fonte.texto() as entrada:
        primeira = entrada.readline()
        if not primeira:
            raise ValueError(f"CSV vazio: {fonte.local}.")
        try:
            sep = csv.Sniffer().sniff(primeira, delimiters=";,\t").delimiter
        except csv.Error:
            sep = ";"
        leitor = csv.DictReader(chain([primeira], entrada), delimiter=sep)
        obrigatorias = {"Arquivo_Origem", "Grupo_Similaridade", "ID_da_Proteina"}
        if not obrigatorias <= set(leitor.fieldnames or []):
            raise ValueError(f"CSV sem as colunas necessárias: {fonte.local}.")
        tem_rotulo = "Tipo_Nutricional" in leitor.fieldnames
        for row in leitor:
            if piloto.nome_base((row["Arquivo_Origem"] or "").strip()).casefold() != nome_gz.casefold():
                continue
            grupo = (row["Grupo_Similaridade"] or "").strip()
            if not grupo.startswith("Grupo_") or not grupo[6:]:
                raise ValueError(f"Grupo inválido em {fonte.local}: {grupo!r}.")
            ident = grupo[6:]
            mask = 0
            if (row["ID_da_Proteina"] or "").strip() == ident and tem_rotulo:
                mask = {"completa": 1, "incompleta": 2}.get((row.get("Tipo_Nutricional") or "").strip().casefold(), 4)
            db.execute("INSERT INTO candidatos VALUES (?,?,0) ON CONFLICT(id) DO UPDATE SET mascara=mascara|excluded.mascara", (ident, mask))
            lidos += 1
            if lidos % 10000 == 0:
                db.commit()
                espaco_livre(saida, reserva)
                print(f"CSV: {lidos:,} linhas examinadas neste par.", flush=True)
    if db.execute("SELECT COUNT(*) FROM candidatos").fetchone()[0] == 0:
        raise ValueError(f"Nenhum grupo do CSV corresponde a {nome_gz}.")
    with db:
        set_meta(db, "par_indexado", indice)


class Processamento:
    def __init__(self, piloto, db, saida, args, config):
        self.p, self.db, self.saida, self.args, self.config = piloto, db, saida, args, config
        self.modelo = None
        self.diag = {}
        self.novos, self.repetidos, self.descartes = [], [], []
        self.pendentes, self.hashes_pendentes = set(), {}
        self.indice = None
        self.gz = self.csv = None
        self.total_confirmado = db.execute("SELECT COALESCE(SUM(novos),0) FROM lotes").fetchone()[0]

    def total(self):
        return self.total_confirmado

    def atingiu_limite(self):
        return not self.args.completar and self.total() + len(self.novos) >= self.args.limite

    def numero_lote(self):
        return self.db.execute("SELECT COALESCE(MAX(numero),0)+1 FROM lotes").fetchone()[0]

    def registrar(self, descricao, sequencia, ident, mask):
        sequencia = sequencia.upper()
        stops = len(sequencia) - len(sequencia.rstrip("*"))
        sequencia = sequencia.rstrip("*")
        tipo = "Completa" if ESSENCIAIS <= set(sequencia) else "Incompleta"
        rotulo = {0: "", 1: "Completa", 2: "Incompleta"}.get(mask, "conflitante_ou_invalido")
        motivo = ""
        if not sequencia:
            motivo = "sequencia_vazia"
        elif len(sequencia) > self.args.max_residuos:
            motivo = f"mais_de_{self.args.max_residuos}_residuos"
        elif set(sequencia) - self.p.ALFABETO:
            motivo = "caracteres_nao_suportados"
        elif mask not in (0, 1, 2):
            motivo = "rotulo_csv_conflitante_ou_invalido"
        elif mask and tipo != rotulo:
            motivo = "divergencia_rotulo_nutricional"
        self.pendentes.add(ident)
        if motivo:
            self.descartes.append({"id": ident, "grupo": "Grupo_" + ident,
                "arquivo_origem": self.gz.nome, "tamanho": len(sequencia), "motivo": motivo,
                "rotulo_csv": rotulo, "rotulo_calculado": tipo})
            return
        digest = hashlib.sha256(sequencia.encode()).hexdigest()
        item = {"id": ident, "grupo": "Grupo_" + ident, "arquivo_origem": self.gz.nome,
                "descricao": descricao, "tamanho": len(sequencia), "sha256_sequencia": digest,
                "stops_finais_removidos": stops, "sequencia": sequencia,
                "Tipo_Nutricional": tipo, "rotulo_csv": rotulo,
                "verificacao_rotulo": "confirmado" if mask else "calculado_sem_rotulo_do_representante_no_csv"}
        ref = self.hashes_pendentes.get(digest)
        if ref is None:
            ref = self.db.execute("SELECT lote, linha FROM vetores WHERE sha=?", (digest,)).fetchone()
        if ref is not None:
            item.pop("sequencia")
            item.update({"lote_referencia": ref[0], "indice_embedding_referencia": ref[1]})
            self.repetidos.append(item)
        else:
            item["indice_embedding"] = len(self.novos)
            self.hashes_pendentes[digest] = (self.numero_lote(), len(self.novos))
            self.novos.append(item)

    def gravar(self):
        if not self.pendentes:
            return
        import numpy as np
        espaco_livre(self.saida, self.args.reserva_gb)
        numero = self.numero_lote()
        lotes = self.saida / "lotes"
        lotes.mkdir(exist_ok=True)
        destino = lotes / f"lote_{numero:06d}"
        if destino.exists():
            raise ValueError(f"Lote já existe sem registro recuperado: {destino}.")
        temporaria = Path(tempfile.mkdtemp(prefix=".gravando_", dir=lotes))
        try:
            desempenho = {}
            if self.novos:
                if self.modelo is None:
                    self.modelo = self.p.exigir_gpu(self.args.threads, self.args.cache)
                    self.diag = self.modelo[4]
                matriz, desempenho = self.p.gerar_embeddings(*self.modelo[:4], self.novos)
                if matriz.shape != (len(self.novos), 320) or matriz.dtype != np.float32 or not np.isfinite(matriz).all():
                    raise ValueError("Matriz incompatível: esperado N × 320 float32 com valores finitos.")
            else:
                matriz = np.empty((0, 320), dtype=np.float32)
            self.p.salvar_csv(temporaria / "amostra.csv", self.novos, ["indice_embedding"] + COLUNAS)
            self.p.salvar_csv(temporaria / "repetidos.csv", self.repetidos, COL_REPETIDOS)
            self.p.salvar_csv(temporaria / "descartes.csv", self.descartes, COL_DESCARTES)
            with (temporaria / "amostra.fasta").open("w", encoding="utf-8") as f:
                for row in self.novos:
                    f.write(f">{row['descricao']}\n{row['sequencia']}\n")
            np.save(temporaria / "embeddings.npy", matriz, allow_pickle=False)
            hashes = {name: digest_arquivo(temporaria / name) for name in
                      ("amostra.csv", "amostra.fasta", "embeddings.npy", "repetidos.csv", "descartes.csv")}
            report = {"ok": True, "treinamento_realizado": False, "numero_lote": numero,
                      "config": self.config, "indice_par": self.indice,
                      "fonte_gz": self.gz.local, "fonte_csv": self.csv.local,
                      "novos": len(self.novos), "repetidos": len(self.repetidos), "descartes": len(self.descartes),
                      "formato_embeddings": list(matriz.shape), "hashes_arquivos": hashes,
                      "descartes_por_motivo": dict(Counter(x["motivo"] for x in self.descartes)),
                      "rotulos_calculados_sem_anotacao_csv": sum(x["verificacao_rotulo"] != "confirmado" for x in self.novos + self.repetidos),
                      "integridade_gz_completa": "Consultar pares_concluidos_integridade no relatorio_execucao.json.",
                      "threads_cpu_pytorch": self.args.threads, **self.diag, **desempenho}
            (temporaria / "relatorio.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporaria, destino)
            registrar_lote(self.db, destino, self.config)
            self.total_confirmado += len(self.novos)
            print(f"Lote {numero}: {len(self.novos)} vetores; total confirmado {self.total()}.", flush=True)
        finally:
            if temporaria.exists():
                shutil.rmtree(temporaria)
        self.novos, self.repetidos, self.descartes = [], [], []
        self.pendentes, self.hashes_pendentes = set(), {}


def executar(piloto, db, args, pares, config):
    processamento = Processamento(piloto, db, args.saida, args, config)
    cursor = get_meta(db, "proximo_par", 0)
    for indice in range(cursor, len(pares)):
        if processamento.atingiu_limite():
            break
        gz, tabela = pares[indice]
        print(f"Par {indice + 1}/{len(pares)}: {gz.nome}", flush=True)
        indexar_csv(piloto, db, tabela, gz.nome, indice, args.saida, args.reserva_gb)
        processamento.indice, processamento.gz, processamento.csv = indice, gz, tabela
        interrompido = False
        with gz.texto() as entrada:
            for lidos, (descricao, sequencia) in enumerate(piloto.registros_fasta(entrada), 1):
                if lidos % 25000 == 0:
                    print(f"FASTA: {lidos:,} registros lidos neste par.", flush=True)
                ident = descricao.split()[0]
                if ident in processamento.pendentes:
                    continue
                candidato = db.execute("SELECT mascara, feito FROM candidatos WHERE id=?", (ident,)).fetchone()
                if not candidato or candidato[1]:
                    continue
                processamento.registrar(descricao, sequencia, ident, candidato[0])
                if len(processamento.pendentes) >= args.lote or processamento.atingiu_limite():
                    processamento.gravar()
                if processamento.atingiu_limite():
                    interrompido = True
                    break
        if interrompido:
            break
        processamento.gravar()
        # IDs não recuperados só podem ser classificados assim após EOF do FASTA.
        while True:
            faltantes = db.execute("SELECT id FROM candidatos WHERE feito=0 LIMIT ?", (args.lote,)).fetchall()
            if not faltantes:
                break
            for (ident,) in faltantes:
                processamento.pendentes.add(ident)
                processamento.descartes.append({"id": ident, "grupo": "Grupo_" + ident,
                    "arquivo_origem": gz.nome, "tamanho": "", "motivo": "representante_nao_encontrado_no_fasta",
                    "rotulo_csv": "", "rotulo_calculado": ""})
            processamento.gravar()
        with db:
            set_meta(db, "proximo_par", indice + 1)
            set_meta(db, "par_indexado", -1)
            db.execute("DELETE FROM candidatos")
    return processamento.diag


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--limite", type=int, default=1000, help="Total de vetores únicos desejado nesta saída.")
    grupo.add_argument("--completar", action="store_true", help="Percorre os demais pares da base, sem limite de vetores.")
    parser.add_argument("--fontes", type=Path, nargs="+", default=[PROJETO / "arquivos .gz", PROJETO / "arquivos csv"])
    parser.add_argument("--saida", type=Path, default=PROJETO / "dados" / "embeddings" / "base_ncbi_gpu")
    parser.add_argument("--cache", type=Path, default=PROJETO / "cache" / "huggingface")
    parser.add_argument("--lote", type=int, default=100, help="Máximo de representantes pendentes por checkpoint; GPU usa lote 1.")
    parser.add_argument("--max-residuos", type=int, default=512)
    parser.add_argument("--threads", type=int, choices=(1, 2, 3, 4), default=2)
    parser.add_argument("--reserva-gb", type=float, default=10, help="Interrompe se o SSD tiver menos que esta reserva em GiB.")
    args = parser.parse_args(argv)
    if args.limite < 1 or not 1 <= args.lote <= 1000 or not 1 <= args.max_residuos <= 1022 or args.reserva_gb < 0:
        parser.error("Use limite positivo, lote 1..1000, resíduos 1..1022 e reserva não negativa.")
    args.saida = args.saida.expanduser().resolve()
    rel = {"tipo": "embeddings_base_ncbi_em_lotes", "ok": False, "treinamento_realizado": False,
           "modelo": MODELO, "revisao": REVISAO, "download_modelo_permitido": False,
           "limite_total_solicitado": None if args.completar else args.limite,
           "threads_cpu_pytorch": args.threads, "max_residuos": args.max_residuos,
           "pasta_saida": str(args.saida), "agrupamento_global_para_treino_teste": "pendente"}
    db = None
    escrita_autorizada = False
    etapa = "localizar_piloto"
    inicio = time.perf_counter()
    try:
        sys.path.insert(0, str(PROJETO))
        import piloto_esm_gpu as piloto
        if piloto.MODELO != MODELO or piloto.REVISAO != REVISAO:
            raise ValueError("O piloto instalado usa outro modelo/revisão.")
        etapa = "localizar_pares"
        pares, avisos = piloto.encontrar_pares(args.fontes)
        for aviso in avisos:
            print("Aviso:", aviso, flush=True)
        if avisos:
            raise ValueError("Existem avisos na localização das fontes; corrija-os para processar esta base.")
        if not pares:
            raise ValueError("Nenhum par GZ + CSV localizado.")
        fontes, assinatura = assinatura_fontes(pares)
        config = {"schema": 1, "modelo": MODELO, "revisao": REVISAO, "max_residuos": args.max_residuos,
                  "regra_aminoacidos": "HILKMFTWV", "fontes_sha256": assinatura}
        rel["pares_encontrados"] = len(pares)
        etapa = "abrir_progresso"
        if args.saida.exists() and any(args.saida.iterdir()) and not (args.saida / "controle.sqlite3").is_file():
            raise ValueError("A saída contém arquivos de outro processamento. Escolha outra --saida.")
        args.saida.mkdir(parents=True, exist_ok=True)
        espaco_livre(args.saida, args.reserva_gb)
        with uma_execucao(args.saida):
            db = sqlite3.connect(args.saida / "controle.sqlite3")
            db.executescript("""
              CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS candidatos(id TEXT PRIMARY KEY, mascara INTEGER NOT NULL, feito INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS vetores(sha TEXT PRIMARY KEY, lote INTEGER NOT NULL, linha INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS lotes(numero INTEGER PRIMARY KEY, novos INTEGER, repetidos INTEGER,
                descartes INTEGER, completas INTEGER, incompletas INTEGER, segundos REAL);
            """)
            anterior = get_meta(db, "config")
            if anterior is not None and anterior != config:
                raise ValueError("Fontes ou critérios mudaram. Preserve esta saída e use outra --saida.")
            if anterior is None:
                with db:
                    set_meta(db, "config", config)
                    set_meta(db, "proximo_par", 0)
                    set_meta(db, "par_indexado", -1)
                (args.saida / "fontes.json").write_text(json.dumps(fontes, ensure_ascii=False, indent=2), encoding="utf-8")
            escrita_autorizada = True
            etapa = "recuperar_lotes"
            for pasta in sorted((args.saida / "lotes").glob("lote_*")):
                if pasta.is_dir():
                    registrar_lote(db, pasta, config)
            for (numero,) in db.execute("SELECT numero FROM lotes"):
                if not (args.saida / "lotes" / f"lote_{numero:06d}").is_dir():
                    raise ValueError(f"Pasta do lote {numero} foi removida ou renomeada. Restaure-a antes de retomar.")
            anteriores = db.execute("SELECT COUNT(*) FROM vetores").fetchone()[0]
            etapa = "processar_fontes_e_embeddings"
            rel.update(executar(piloto, db, args, pares, config))
            soma = db.execute("SELECT COALESCE(SUM(novos),0), COALESCE(SUM(repetidos),0), COALESCE(SUM(descartes),0),"
                              "COALESCE(SUM(completas),0), COALESCE(SUM(incompletas),0), COALESCE(SUM(segundos),0), COUNT(*) FROM lotes").fetchone()
            concluido = get_meta(db, "proximo_par", 0)
            rel.update({"ok": True, "base_completa": concluido == len(pares),
                        "pares_concluidos_integridade": concluido, "pares_pendentes": len(pares) - concluido,
                        "embeddings_total": soma[0], "embeddings_gerados_nesta_execucao": soma[0] - anteriores,
                        "representantes_repetidos": soma[1], "representantes_descartados": soma[2],
                        "rotulos_vetores_unicos": {"Completa": soma[3], "Incompleta": soma[4]},
                        "segundos_embeddings_acumulados": round(soma[5], 3), "checkpoints_total": soma[6],
                        "formato_total_embeddings": [soma[0], 320], "precisao": "float32", "lote_gpu": 1,
                        "espaco_livre_ssd_gib": round(shutil.disk_usage(args.saida).free / 1024**3, 2)})
            rel["segundos_execucao"] = round(time.perf_counter() - inicio, 3)
            (args.saida / "relatorio_execucao.json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    except (Exception, KeyboardInterrupt) as erro:
        rel.update({"etapa_erro": etapa, "erro": f"{type(erro).__name__}: {erro}",
                    "segundos_execucao": round(time.perf_counter() - inicio, 3)})
        if db is not None:
            db.rollback()
        if escrita_autorizada:
            (args.saida / "relatorio_erro.json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        if db is not None:
            db.close()
    print(json.dumps(rel, ensure_ascii=False, indent=2))
    return 0 if rel["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
