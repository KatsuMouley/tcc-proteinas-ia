"""Auditoria tecnica, somente leitura, dos lotes de processar_base_gpu.py.

Nao importa PyTorch, nao usa GPU, nao baixa modelo, nao treina e nao consolida
os vetores. Depende apenas de NumPy, ja presente no ambiente do projeto.
Execute com o gerador encerrado. Relatorios sao escritos fora da base original.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

import numpy as np

PROJETO = Path(__file__).resolve().parents[1]
MODELO = "facebook/esm2_t6_8M_UR50D"
REVISAO = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
ARQUIVOS = {"amostra.csv", "amostra.fasta", "embeddings.npy", "repetidos.csv", "descartes.csv"}
ESSENCIAIS = set("HILKMFTWV")


def json_ler(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def csv_ler(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";", strict=True))


def fasta_ler(path):
    descricao, seq = None, []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.startswith(">"):
                if descricao is not None:
                    yield descricao, "".join(seq)
                descricao, seq = line[1:], []
            elif line:
                if descricao is None:
                    raise ValueError("FASTA sem cabecalho inicial.")
                seq.append(line)
        if descricao is not None:
            yield descricao, "".join(seq)


class Auditoria:
    def __init__(self, base, esperado, progresso=500):
        self.base, self.esperado, self.progresso = base.resolve(), esperado, progresso
        self.erros, self.exemplos = 0, []
        self.totais, self.rotulos, self.descartes, self.comprimentos = Counter(), Counter(), Counter(), Counter()

    def verificar(self, condicao, codigo, detalhe):
        if not condicao:
            self.erros += 1
            if len(self.exemplos) < 50:
                self.exemplos.append({"codigo": codigo, "detalhe": detalhe})
        return bool(condicao)

    def executar(self):
        inicio = time.perf_counter()
        rel_path, db_path = self.base / "relatorio_execucao.json", self.base / "controle.sqlite3"
        rel = {}
        db = None
        try:
            rel = json_ler(rel_path)
            inicial = (digest(rel_path), db_path.stat().st_mtime_ns, db_path.stat().st_size)
            self.verificar(rel.get("ok") is True, "execucao_nao_concluida", "O relatorio_execucao.json precisa registrar encerramento normal.")
            self.verificar(rel.get("modelo") == MODELO and rel.get("revisao") == REVISAO,
                           "modelo_incompativel", "Modelo/revisao diferentes do ESM-2 usado neste projeto.")
            db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
            versao_inicial = db.execute("PRAGMA data_version").fetchone()[0]
            self.verificar(db.execute("PRAGMA quick_check").fetchall() == [("ok",)],
                           "sqlite_inconsistente", "PRAGMA quick_check nao retornou ok.")
            config = json.loads(db.execute("SELECT valor FROM meta WHERE chave='config'").fetchone()[0])
            self.verificar(config.get("schema") == 1 and config.get("modelo") == MODELO and
                           config.get("revisao") == REVISAO and config.get("regra_aminoacidos") == "HILKMFTWV",
                           "config_incompativel", "Configuracao do controle diferente do protocolo.")
            self.verificar(config.get("max_residuos") == rel.get("max_residuos"), "comprimento_config", "Limites de comprimento do controle e do relatorio diferem.")
            fontes = json_ler(self.base / "fontes.json")
            assinatura = hashlib.sha256(json.dumps(fontes, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            self.verificar(assinatura == config.get("fontes_sha256"), "fontes_alteradas", "O inventario fontes.json nao corresponde ao controle.")
            controle = {r[0]: r[1:] for r in db.execute("SELECT numero, novos, repetidos, descartes, completas, incompletas FROM lotes")}
            pastas = sorted(p for p in (self.base / "lotes").glob("lote_*") if p.is_dir())
            self.verificar(bool(pastas), "sem_lotes", "Nenhuma pasta lote_* encontrada.")
            self.verificar({p.name for p in pastas} == {f"lote_{n:06d}" for n in controle},
                           "lotes_controle_divergentes", "Pastas existentes e lotes registrados no SQLite diferem.")
            refs_cursor = db.execute("SELECT sha, lote, linha FROM vetores ORDER BY lote, linha")
            ref = refs_cursor.fetchone()
            for ordinal, pasta in enumerate(pastas, 1):
                try:
                    numero = int(pasta.name.removeprefix("lote_"))
                    self.verificar(pasta.name == f"lote_{numero:06d}", "nome_lote", pasta.name)
                    refs = []
                    while ref is not None and ref[1] < numero:
                        self.verificar(False, "vetor_sem_pasta", f"Referencia no SQLite para lote {ref[1]} nao encontrado.")
                        ref = refs_cursor.fetchone()
                    while ref is not None and ref[1] == numero:
                        refs.append((ref[0], ref[2]))
                        ref = refs_cursor.fetchone()
                    self.auditar_lote(pasta, numero, config, controle.get(numero), refs, db)
                except (ValueError, KeyError, IndexError, TypeError, UnicodeError, OSError, csv.Error, sqlite3.Error) as error:
                    self.verificar(False, "lote_nao_auditado", f"{pasta.name}: {type(error).__name__}: {error}")
                if self.progresso and ordinal % self.progresso == 0:
                    print(f"Auditoria: {ordinal}/{len(pastas)} lotes; {self.totais['vetores']} linhas de vetores examinadas.", flush=True)
            self.verificar(ref is None, "referencias_restantes", "Existem vetores no SQLite sem uma pasta auditada correspondente.")
            refs_cursor.close()
            quantidade_db = db.execute("SELECT COUNT(*) FROM vetores").fetchone()[0]
            self.verificar(quantidade_db == self.totais["vetores"], "contagem_vetores_sqlite", "Quantidade de vetores no SQLite difere das linhas NPY.")
            self.verificar(sum(self.rotulos.values()) == self.totais["vetores"], "contagem_rotulos", "Quantidade de rotulos difere das linhas de vetores.")
            self.verificar(self.totais["vetores"] == self.esperado, "total_esperado", f"Esperados {self.esperado}; encontrados {self.totais['vetores']}.")
            comparacoes = {"embeddings_total": "vetores", "representantes_repetidos": "repetidos", "representantes_descartados": "descartados", "checkpoints_total": "lotes"}
            for campo, total in comparacoes.items():
                self.verificar(rel.get(campo) == self.totais[total], "relatorio_contagem", f"Campo {campo} difere da auditoria dos arquivos.")
            self.verificar(rel.get("formato_total_embeddings") == [self.totais["vetores"], 320], "relatorio_formato", "Formato total declarado incompativel.")
            self.verificar(rel.get("rotulos_vetores_unicos") == {nome: self.rotulos[nome] for nome in ("Completa", "Incompleta")}, "relatorio_rotulos", "Contagens de rotulos diferem do relatorio final.")
            atual = (digest(rel_path), db_path.stat().st_mtime_ns, db_path.stat().st_size)
            self.verificar(inicial == atual and versao_inicial == db.execute("PRAGMA data_version").fetchone()[0],
                           "base_mudou_durante_auditoria", "A base foi modificada durante a leitura. Encerre o gerador e repita.")
        except (ValueError, KeyError, IndexError, TypeError, UnicodeError, OSError, csv.Error, sqlite3.Error) as error:
            self.verificar(False, "auditoria_incompleta", f"{type(error).__name__}: {error}")
        finally:
            if db is not None:
                db.close()
        return {"tipo": "auditoria_tecnica_embeddings", "ok": self.erros == 0,
                "base": str(self.base), "criado_utc": datetime.now(timezone.utc).isoformat(),
                "esperado": self.esperado, "totais_examinados": dict(self.totais),
                "formato_total_observado": [self.totais["vetores"], 320] if self.erros == 0 else None,
                "rotulos_vetores": {nome: self.rotulos[nome] for nome in ("Completa", "Incompleta")}, "descartes_por_motivo": dict(self.descartes),
                "comprimento_minimo": min(self.comprimentos, default=None),
                "comprimento_maximo": max(self.comprimentos, default=None),
                "base_ncbi_inteira_processada": rel.get("base_completa"),
                "pares_concluidos_integridade_declarados": rel.get("pares_concluidos_integridade"),
                "pares_pendentes_declarados": rel.get("pares_pendentes"),
                "erros_total": self.erros, "exemplos_erros": self.exemplos,
                "segundos_auditoria": round(time.perf_counter() - inicio, 3),
                "gpu_utilizada": False, "embeddings_regenerados": False, "treinamento_realizado": False,
                "limites": ["Auditoria dos lotes salvos, nao leitura integral dos GZ/ZIP originais.",
                    "Hashes detectam mudancas em relacao aos registros existentes; nao sao assinatura externa de autenticidade.",
                    "Alinhamento confere indices, sequencias, hashes e referencias. Nao recalcula o modelo nem avalia o significado biologico dos vetores.",
                    "Completa/Incompleta significa presenca literal dos nove aminoacidos, nao funcao nem qualidade nutricional.",
                    "Agrupamento global por homologia e separacao entre treino e teste continuam pendentes."]}

    def auditar_lote(self, pasta, numero, config, registro_db, refs, db):
        r = json_ler(pasta / "relatorio.json")
        self.verificar(r.get("ok") is True and r.get("numero_lote") == numero, "relatorio_lote", pasta.name)
        self.verificar(r.get("config") == config, "config_lote", pasta.name)
        hashes = r["hashes_arquivos"]
        self.verificar(set(hashes) == ARQUIVOS, "inventario_arquivos", pasta.name)
        for nome in sorted(ARQUIVOS):
            path = pasta / nome
            self.verificar(path.is_file() and digest(path) == hashes.get(nome), "hash_arquivo", f"{pasta.name}/{nome}")
        rows = csv_ler(pasta / "amostra.csv")
        repetidos = csv_ler(pasta / "repetidos.csv")
        descartados = csv_ler(pasta / "descartes.csv")
        vetores = np.load(pasta / "embeddings.npy", mmap_mode="r", allow_pickle=False)
        self.verificar(vetores.shape == (len(rows), 320) and vetores.dtype == np.float32, "formato_npy", f"{pasta.name}: shape={vetores.shape}, dtype={vetores.dtype}")
        # Checagem em blocos mesmo se o NPY tiver sido substituido por um arquivo grande.
        finitos = all(np.isfinite(vetores[i:i + 1000]).all() for i in range(0, len(vetores), 1000))
        self.verificar(finitos, "valores_nao_finitos", pasta.name)
        self.totais.update({"lotes": 1, "vetores": len(vetores), "csv_amostra": len(rows),
                            "repetidos": len(repetidos), "descartados": len(descartados)})
        self.verificar([len(rows), len(repetidos), len(descartados)] == [r["novos"], r["repetidos"], r["descartes"]],
                       "contagens_lote", pasta.name)
        self.verificar(r.get("formato_embeddings") == list(vetores.shape), "formato_declarado_lote", pasta.name)
        self.verificar(len(refs) == len(rows), "referencias_lote", pasta.name)
        fastas = list(fasta_ler(pasta / "amostra.fasta"))
        self.verificar(len(fastas) == len(rows), "fasta_contagem", pasta.name)
        contagem = Counter()
        for indice, row in enumerate(rows):
            ident = f"{pasta.name}, linha {indice}, ID {row.get('id', '')}"
            seq = row["sequencia"]
            sha = hashlib.sha256(seq.encode("ascii")).hexdigest()
            self.verificar(int(row["indice_embedding"]) == indice, "indice_csv", ident)
            self.verificar(row["sha256_sequencia"] == sha, "hash_sequencia", ident)
            self.verificar(indice < len(refs) and refs[indice] == (sha, indice), "vinculo_sqlite", ident)
            self.verificar(indice < len(fastas) and fastas[indice] == (row["descricao"], seq), "vinculo_fasta", ident)
            self.verificar(int(row["tamanho"]) == len(seq) and 0 < len(seq) <= config["max_residuos"], "comprimento_sequencia", ident)
            self.verificar(row["grupo"] == "Grupo_" + row["id"], "grupo_id", ident)
            esperado = "Completa" if ESSENCIAIS <= set(seq) else "Incompleta"
            self.verificar(row["Tipo_Nutricional"] == esperado, "regra_rotulo", ident)
            contagem[row["Tipo_Nutricional"]] += 1
            self.comprimentos[len(seq)] += 1
        self.rotulos.update(contagem)
        esperado_db = (len(rows), len(repetidos), len(descartados), contagem["Completa"], contagem["Incompleta"])
        self.verificar(registro_db == esperado_db, "contagens_sqlite_lote", pasta.name)
        for inicio in range(0, len(repetidos), 200):
            bloco = repetidos[inicio:inicio + 200]
            valores = list({row["sha256_sequencia"] for row in bloco})
            referencias = {row[0]: (row[1], row[2]) for row in db.execute(
                "SELECT sha,lote,linha FROM vetores WHERE sha IN (" + ",".join("?" for _ in valores) + ")", valores)}
            for row in bloco:
                ref = (int(row["lote_referencia"]), int(row["indice_embedding_referencia"]))
                self.verificar(referencias.get(row["sha256_sequencia"]) == ref, "referencia_repetido", f"{pasta.name}, ID {row['id']}")
        motivos = Counter(row["motivo"] for row in descartados)
        self.descartes.update(motivos)
        self.verificar(dict(motivos) == r.get("descartes_por_motivo"), "motivos_descartes_lote", pasta.name)
        del vetores


def salvar(saida, rel):
    saida.parent.mkdir(parents=True, exist_ok=True)
    temporaria = Path(tempfile.mkdtemp(prefix=".auditoria_", dir=saida.parent))
    try:
        (temporaria / "relatorio.json").write_text(json.dumps(rel, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        texto = ["# Auditoria tecnica da base de embeddings", "", f"Resultado: **{'APROVADA' if rel['ok'] else 'PENDENTE / COM ERROS'}**.", "",
                 f"Vetores examinados: {rel['totais_examinados'].get('vetores', 0):,}. Lotes: {rel['totais_examinados'].get('lotes', 0):,}.",
                 f"Erros registrados: {rel['erros_total']}.", "", "## Limites da conclusao", ""]
        texto += ["- " + x for x in rel["limites"]]
        if rel["exemplos_erros"]:
            texto += ["", "## Exemplos de erros", ""] + [f"- {e['codigo']}: {e['detalhe']}" for e in rel["exemplos_erros"]]
        (temporaria / "relatorio.md").write_text("\n".join(texto) + "\n", encoding="utf-8")
        if saida.exists():
            raise ValueError("A pasta de saida foi criada durante a auditoria. Nenhum relatorio anterior sera substituido.")
        temporaria.rename(saida)
    finally:
        if temporaria.exists():
            shutil.rmtree(temporaria)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=PROJETO / "dados/embeddings/base_ncbi_gpu")
    parser.add_argument("--esperado", type=int, default=1000000)
    parser.add_argument("--saida", type=Path)
    args = parser.parse_args(argv)
    if args.esperado < 1:
        parser.error("--esperado deve ser positivo.")
    base = args.base.resolve()
    saida = (args.saida or PROJETO / "dados/validacao/base_ncbi_gpu" / datetime.now(timezone.utc).strftime("auditoria_%Y%m%dT%H%M%S%fZ")).resolve()
    if saida.exists() or saida.is_relative_to(base) or base.is_relative_to(saida):
        print(json.dumps({"ok": False, "erro": "Use uma pasta de saida nova e fora da base original."}, ensure_ascii=False))
        return 2
    print("Auditoria somente leitura: execute com o gerador encerrado. Nao usa GPU.", flush=True)
    rel = Auditoria(base, args.esperado).executar()
    try:
        salvar(saida, rel)
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "erro": str(error), "auditoria": rel}, ensure_ascii=False))
        return 2
    resumo = {k: rel[k] for k in ("tipo", "ok", "esperado", "totais_examinados", "formato_total_observado", "rotulos_vetores", "descartes_por_motivo", "erros_total", "exemplos_erros", "segundos_auditoria", "gpu_utilizada", "treinamento_realizado")}
    resumo["pasta_relatorios"] = str(saida)
    print(json.dumps(resumo, indent=2, ensure_ascii=False))
    return 0 if rel["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
