"""Execução científica completa: GZ -> MMseqs2 -> ESM-2 -> MLP -> SQLite.

Usa cópias dos scripts existentes por execução e saídas novas. Não importa
PyTorch no dashboard nem baixa modelos. Invocado como subprocesso da fila.
"""
from __future__ import annotations
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

from .core import agora, exigir, ler_json, pid_ativo, serial, sha
from .execucoes import FASES, NOMES_FASES
from .pastas import raizes_permitidas


class Pausado(Exception):
    pass


class Fluxo:
    def __init__(self, projeto, pasta):
        self.projeto, self.pasta = Path(projeto).resolve(), Path(pasta).resolve()
        exigir(self.pasta.is_relative_to(self.projeto / "dados/execucoes_tcc"), "Execução fora da pasta reservada.")
        self.m = ler_json(self.pasta / "execucao.json")
        exigir(self.m.get("schema") == 2 and Path(self.m["projeto"]).resolve() == self.projeto
            and Path(self.m["pasta"]).resolve() == self.pasta, "Manifesto da execução incompatível.")
        self.codigo = self.pasta / "codigo"
        self.bd_path = self.pasta / "banco.sqlite3"
        self.modulos = {}
        self.proc = None
        self.fase = None
        self.verificar_codigo()
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS etapas(id TEXT PRIMARY KEY, ordem INTEGER NOT NULL,
                    estado TEXT NOT NULL, inicio TEXT, fim TEXT, erro TEXT, resultado TEXT, pid INTEGER);
                CREATE TABLE IF NOT EXISTS proteinas(uid TEXT PRIMARY KEY, id_original TEXT,
                    descricao TEXT, origem TEXT, sequencia TEXT NOT NULL, comprimento INTEGER,
                    sha256 TEXT NOT NULL UNIQUE, rotulo TEXT NOT NULL, grupo_inicial TEXT,
                    indice_embedding INTEGER, uid_base TEXT, grupo_global TEXT, particao TEXT);
                CREATE TABLE IF NOT EXISTS experimentos(id TEXT PRIMARY KEY, modelo TEXT,
                    base TEXT, particoes TEXT, metricas TEXT, proveniencia TEXT, criado TEXT);
                CREATE INDEX IF NOT EXISTS idx_proteinas_grupo ON proteinas(grupo_inicial);
                CREATE INDEX IF NOT EXISTS idx_proteinas_particao ON proteinas(particao);
            """)
            for i, fase in enumerate(FASES):
                db.execute("INSERT OR IGNORE INTO etapas(id,ordem,estado) VALUES(?,?,'pendente')", (fase, i))

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.bd_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def meta(self, chave, valor=None, gravar=False):
        with self.db() as db:
            if gravar:
                db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (chave, serial(valor)))
            row = db.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
            return json.loads(row[0]) if row else None

    def evento(self, fase, estado, **outros):
        print("TCC_EVENT:" + serial({"fase": fase, "nome": NOMES_FASES[fase], "estado": estado,
            "numero": FASES.index(fase)+1, "total_fases": len(FASES), **outros}), flush=True)

    def verificar_codigo(self):
        for nome, digest in self.m["codigo_sha256"].items():
            p = (self.codigo / nome).resolve()
            exigir(p.is_relative_to(self.codigo) and sha(p) == digest, "Código desta execução foi alterado: " + nome)

    def modulo(self, nome):
        if nome not in self.modulos:
            path = self.codigo / nome
            spec = importlib.util.spec_from_file_location("tcc_" + hashlib.sha256(str(path).encode()).hexdigest()[:16], path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            self.modulos[nome] = mod
        return self.modulos[nome]

    def pausado(self):
        path = Path(self.m["controle_fila"])
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            row = db.execute("SELECT valor FROM meta WHERE chave='pausado'").fetchone()
            return bool(row and json.loads(row[0]))
        finally:
            db.close()

    def espaco(self):
        exigir(shutil.disk_usage(self.projeto).free / 1024**3 >= self.m["reserva_gib"], "Disco abaixo da reserva configurada.")

    def executar_cmd(self, cmd):
        self.verificar_codigo()
        self.espaco()
        env = os.environ.copy()
        env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        log = self.pasta / "logs" / (self.fase + ".log")
        log.parent.mkdir(exist_ok=True)
        print("Comando: " + serial(cmd), flush=True)
        with log.open("a", encoding="utf-8", buffering=1) as f:
            self.proc = subprocess.Popen(cmd, cwd=self.projeto, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
            with self.db() as db:
                db.execute("UPDATE etapas SET pid=? WHERE id=?", (self.proc.pid, self.fase))
            try:
                for linha in self.proc.stdout:
                    f.write(linha)
                    print(linha, end="", flush=True)
            finally:
                self.proc.stdout.close()
            codigo = self.proc.wait()
            with self.db() as db:
                db.execute("UPDATE etapas SET pid=NULL WHERE id=?", (self.fase,))
            self.proc = None
            exigir(codigo == 0, f"{NOMES_FASES[self.fase]} encerrou com código {codigo}. Consulte o log.")

    def script(self, nome, *args):
        self.executar_cmd([sys.executable, "-u", str(self.codigo / "etapas" / nome), *map(str, args)])

    def etapa(self, fase, func):
        self.fase = fase
        with self.db() as db:
            row = db.execute("SELECT * FROM etapas WHERE id=?", (fase,)).fetchone()
        if row["estado"] == "concluido":
            registro = json.loads(row["resultado"])
            for nome, digest in registro["hashes"].items():
                path = (self.pasta / nome).resolve()
                exigir(path.is_relative_to(self.pasta) and path.is_file() and sha(path) == digest,
                    "Saída concluída foi alterada: " + nome)
            self.evento(fase, "concluido", reutilizado=True)
            return registro.get("dados", {})
        exigir(not pid_ativo(row["pid"]), "Um processo anterior desta etapa ainda está ativo.")
        if self.pausado():
            self.evento(fase, "pausado")
            raise Pausado("Fila pausada antes da próxima etapa.")
        self.verificar_codigo()
        self.espaco()
        with self.db() as db:
            db.execute("UPDATE etapas SET estado='executando',inicio=?,fim=NULL,erro=NULL,pid=NULL WHERE id=?", (agora(), fase))
        self.evento(fase, "executando")
        try:
            dados, arquivos = func()
            hashes = {str(p.relative_to(self.pasta)): sha(p) for p in arquivos}
            with self.db() as db:
                db.execute("UPDATE etapas SET estado='concluido',fim=?,resultado=?,pid=NULL WHERE id=?",
                    (agora(), serial({"dados": dados, "hashes": hashes}), fase))
            self.evento(fase, "concluido", dados=dados)
            return dados
        except Exception as e:
            vivo = self.proc is not None and self.proc.poll() is None
            with self.db() as db:
                db.execute("UPDATE etapas SET estado=?,fim=?,erro=? WHERE id=?",
                    ("recuperacao" if vivo else "falhou", agora(), type(e).__name__ + ": " + str(e), fase))
            self.evento(fase, "falhou", erro=str(e))
            raise

    def extrair(self):
        destino = self.pasta / "entrada"
        exigir(not destino.exists(), "A entrada desta execução já existe sem etapa aprovada. Preserve-a e crie outra execução.")
        tmp = Path(tempfile.mkdtemp(prefix=".entrada_", dir=self.pasta))
        piloto = self.modulo("piloto_esm_gpu.py")
        total, lidas, descartadas, repetidas = 0, 0, 0, 0
        fontes_lidas = []
        try:
            with self.db() as db, (tmp / "sequencias.fasta").open("w", encoding="ascii", newline="\n") as fasta:
                db.execute("DELETE FROM proteinas")
                for fonte in self.m["fontes"]:
                    p = Path(fonte["arquivo"])
                    st = p.stat()
                    exigir(any(p.is_relative_to(r) for r in raizes_permitidas(self.projeto)) and st.st_size == fonte["bytes_arquivo"] and st.st_mtime_ns == fonte["mtime_ns"], "Fonte alterada desde a criação da execução.")
                    f = piloto.Fonte(p, fonte["membro"], fonte["bytes_gz"])
                    print("Lendo GZ: " + f.local, flush=True)
                    ate_fim = True
                    with f.texto() as entrada:
                        # O parser guarda no máximo 512 caracteres por sequência.
                        for desc, seq, tamanho, valida in fasta_limitado(entrada):
                            lidas += 1
                            if not valida or not 1 <= tamanho <= 512:
                                descartadas += 1
                                continue
                            digest = hashlib.sha256(seq.encode("ascii")).hexdigest()
                            if db.execute("SELECT 1 FROM proteinas WHERE sha256=?", (digest,)).fetchone():
                                repetidas += 1
                                continue
                            uid = f"p{total:09d}"
                            rotulo = "Completa" if set("HILKMFTWV") <= set(seq) else "Incompleta"
                            db.execute("INSERT INTO proteinas(uid,id_original,descricao,origem,sequencia,comprimento,sha256,rotulo) VALUES(?,?,?,?,?,?,?,?)",
                                (uid, desc.split()[0], desc, f.local, seq, len(seq), digest, rotulo))
                            fasta.write(f">{uid}\n{seq}\n")
                            total += 1
                            if total % 100 == 0:
                                print(f"Entrada: {total}/{self.m['limite_candidatos']} proteínas elegíveis selecionadas.", flush=True)
                            if total >= self.m["limite_candidatos"]:
                                ate_fim = False
                                break
                    fontes_lidas.append({"fonte": f.local, "leitura_ate_fim": ate_fim})
                    if total >= self.m["limite_candidatos"]:
                        break
                exigir(total >= 3, "Menos de três sequências únicas elegíveis. Escolha outra fonte ou todas as fontes.")
                contagem = {r[0]: r[1] for r in db.execute("SELECT rotulo,COUNT(*) FROM proteinas GROUP BY rotulo")}
            r = {"ok": True, "tipo": "entrada_execucao_completa", "quantidade": total,
                "limite_candidatos": self.m["limite_candidatos"], "lidas": lidas, "descartadas": descartadas,
                "repetidas": repetidas, "rotulos": contagem, "fontes_lidas": fontes_lidas,
                "recorte": "Primeiras sequências únicas elegíveis; não é amostra aleatória da coleção.",
                "fasta_sha256": sha(tmp / "sequencias.fasta")}
            (tmp / "relatorio.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.rename(destino)
            self.meta("entrada", r, True)
            return r, [destino / "relatorio.json", destino / "sequencias.fasta"]
        except Exception:
            print("Entrada parcial preservada em: " + str(tmp), flush=True)
            raise

    def backend(self):
        p = self.modulo("etapas/preparar_base_ia.py")
        from .mmseqs import distro_wsl, exe_nativo
        distro = distro_wsl(self.m, self.projeto)
        # O módulo vem da cópia do código desta execução: o executável nativo precisa ser informado.
        exe = None if distro else exe_nativo(self.projeto)
        return p.Backend(distro, str(exe) if exe else None)

    def mmseqs_inicial(self):
        p = self.modulo("etapas/preparar_base_ia.py")
        b = self.backend()
        versao = b.version()
        entrada = self.pasta / "entrada/sequencias.fasta"
        n = self.meta("entrada")["quantidade"]
        destino = self.pasta / "mmseqs_inicial"
        exigir(not destino.exists(), "Saída inicial do MMseqs2 já existe sem etapa aprovada.")
        tmp = Path(tempfile.mkdtemp(prefix=".mmseqs_inicial_", dir=self.pasta))
        temporario = str(tmp / "temporario")
        if b.distro:
            code, out, err = p.executar_curto(b.prefixo + ["mktemp", "-d", "-p", "/var/tmp", "tcc_fluxo.XXXXXXXX"])
            exigir(code == 0 and out.strip().startswith("/var/tmp/tcc_fluxo."), "Não foi possível criar temporário no WSL.")
            temporario = out.strip()
        cmd = b.cmd("easy-linclust", b.path(entrada), b.path(tmp / "inicial"), temporario,
            "--min-seq-id", "0.5", "-c", "0.8", "--cov-mode", "0", "--cluster-mode", "1",
            "--alignment-mode", "3", "--kmer-per-seq", "80", "--split-memory-limit", "8G",
            "-e", "0.001", "--threads", str(self.m["threads_mmseqs"]), "--remove-tmp-files", "1")
        self.executar_cmd(cmd)
        tsv = tmp / "inicial_cluster.tsv"
        grupos, reps, tamanhos = p.ler_grupos(tsv, n)
        with self.db() as db:
            db.executemany("UPDATE proteinas SET grupo_inicial=? WHERE uid=?",
                ((f"p{int(grupos[i]):09d}", f"p{i:09d}") for i in range(n)))
            contagem = {r[0]: r[1] for r in db.execute("SELECT rotulo,COUNT(*) FROM proteinas WHERE uid=grupo_inicial GROUP BY rotulo")}
        r = {"ok": True, "tipo": "agrupamento_inicial_mmseqs2", "proteinas_entrada": n,
            "representantes": len(reps), "maior_grupo": int(tamanhos.max()), "rotulos_representantes": contagem,
            "versao_mmseqs2": versao, "comando": cmd, "tsv_sha256": sha(tsv), "fasta_sha256": sha(entrada),
            "limite": "Linclust heurístico, identidade 0,5 e cobertura 0,8."}
        (tmp / "relatorio.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(destino)
        self.meta("mmseqs_inicial", r, True)
        exigir(len(reps) >= 3 and all(contagem.get(c, 0) > 0 for c in ("Completa", "Incompleta")),
            "Representantes insuficientes ou só uma classe. Amplie o recorte e crie outra execução.")
        return r, [destino / "relatorio.json", destino / "inicial_cluster.tsv"]

    def rotular(self):
        destino = self.pasta / "fontes"
        exigir(not destino.exists(), "CSV/GZ desta execução já existem sem etapa aprovada.")
        tmp = Path(tempfile.mkdtemp(prefix=".fontes_", dir=self.pasta))
        with (self.pasta / "entrada/sequencias.fasta").open("rb") as f, gzip.open(tmp / "entrada.fsa_aa.gz", "wb") as out:
            shutil.copyfileobj(f, out)
        with self.db() as db, (tmp / "entrada.fsa_aa.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(("Arquivo_Origem", "Grupo_Similaridade", "ID_da_Proteina", "Tipo_Nutricional"))
            for row in db.execute("SELECT uid,grupo_inicial,rotulo FROM proteinas ORDER BY uid"):
                exigir(row[1], "MMseqs2 não atribuiu grupo a uma proteína.")
                w.writerow(("entrada.fsa_aa.gz", "Grupo_" + row[1], row[0], row[2]))
        tmp.rename(destino)
        self.meta("rotulos", "Presença literal de HILKMFTWV, calculada por sequência; grupo não define o rótulo.", True)
        return {"ok": True}, [destino / "entrada.fsa_aa.gz", destino / "entrada.fsa_aa.csv"]

    def n(self):
        return self.meta("mmseqs_inicial")["representantes"]

    def embeddings(self):
        self.script("processar_base_gpu.py", "--limite", self.n(), "--fontes", self.pasta / "fontes",
            "--saida", self.pasta / "embeddings", "--cache", self.m["cache"],
            "--threads", self.m["threads_pytorch"], "--max-residuos", 512, "--reserva-gb", self.m["reserva_gib"])
        p = self.pasta / "embeddings/relatorio_execucao.json"
        r = ler_json(p)
        exigir(r.get("ok") is True and r.get("embeddings_total") == self.n(), "Não foram gerados todos os vetores dos representantes.")
        self.meta("embeddings", {"quantidade": self.n(), "dimensao": 320, "rotulos": r["rotulos_vetores_unicos"]}, True)
        return {"quantidade": self.n()}, [p]

    def auditoria(self):
        destino = self.pasta / "auditorias/auditoria_fluxo"
        self.script("validar_base_embeddings.py", "--base", self.pasta / "embeddings", "--esperado", self.n(), "--saida", destino)
        p = destino / "relatorio.json"
        r = ler_json(p)
        exigir(r.get("ok") is True and r.get("erros_total") == 0, "Auditoria não aprovou os embeddings.")
        return {"erros": 0}, [p]

    def consolidar(self):
        self.script("preparar_base_ia.py", "consolidar", "--base", self.pasta / "embeddings", "--saida", self.pasta / "base",
            "--esperado", self.n(), "--auditoria", self.pasta / "auditorias/auditoria_fluxo/relatorio.json", "--reserva-gib", self.m["reserva_gib"])
        p = self.pasta / "base/relatorio_consolidacao.json"
        r = ler_json(p)
        exigir(r.get("ok") is True and r.get("proteinas") == self.n(), "Consolidação não aprovada.")
        return {"proteinas": self.n()}, [p, *[self.pasta / "base" / x for x in ("indice.csv", "sequencias.fasta", "embeddings.npy")]]

    def agrupar(self):
        args = ["agrupar", "--base", self.pasta / "base", "--saida", self.pasta / "grupos",
            "--threads", self.m["threads_mmseqs"], "--reserva-gib", self.m["reserva_gib"]]
        from .mmseqs import distro_wsl, exe_nativo
        if distro_wsl(self.m, self.projeto):
            args += ["--wsl", self.m["wsl"]]
        elif exe_nativo(self.projeto):
            args += ["--executavel", str(exe_nativo(self.projeto))]
        self.script("preparar_base_ia.py", *args)
        p = self.pasta / "grupos/relatorio_agrupamento.json"
        r = ler_json(p)
        exigir(r.get("ok") is True and r.get("proteinas") == self.n(), "Agrupamento global não aprovado.")
        return {"grupos": r["grupos"]}, [p, self.pasta / "grupos/global_cluster.tsv"]

    def separar(self):
        self.script("preparar_base_ia.py", "separar", "--base", self.pasta / "base", "--agrupamento", self.pasta / "grupos",
            "--saida", self.pasta / "particoes", "--semente", self.m["semente"], "--reserva-gib", self.m["reserva_gib"])
        p = self.pasta / "particoes/relatorio_particoes.json"
        r = ler_json(p)
        exigir(r.get("ok") is True and r.get("grupos_compartilhados_entre_particoes") == 0, "Partições não aprovadas.")
        for nome in ("treino", "validacao", "teste"):
            exigir(all(r["particoes"][nome]["rotulos"].get(c, 0) > 0 for c in ("Completa", "Incompleta")),
                "Uma classe está ausente em " + nome + ". Crie outro recorte maior; a semente não é ajustada pelo teste.")
        arquivos = [p, self.pasta / "particoes/particoes.csv", self.pasta / "particoes/grupos_por_linha.npy"]
        arquivos += [self.pasta / "particoes" / (x + "_indices.npy") for x in ("treino", "validacao", "teste")]
        return r["particoes"], arquivos

    def treinar(self):
        self.script("treinar_classificador_gpu.py", "treinar", "--base", self.pasta / "base", "--particoes", self.pasta / "particoes",
            "--saida", self.pasta / "modelo", "--threads", self.m["threads_pytorch"], "--dispositivo", os.environ.get("TCC_DISPOSITIVO", "auto"),
            "--semente", self.m["semente"], "--epocas", self.m["epocas"])
        p = self.pasta / "modelo/relatorio_treino.json"
        r = ler_json(p)
        exigir(r.get("ok") is True and r.get("treinamento_realizado") is True and r.get("esm2_retreinado") is False,
            "Treinamento não concluído ou alvo incompatível.")
        self.meta("metricas_teste", r["teste_mlp"], True)
        return {"melhor_epoca": r["melhor_epoca"], "teste_mlp": r["teste_mlp"]}, [p, self.pasta / "modelo/modelo.pt"]

    def banco(self):
        indice = self.pasta / "base/indice.csv"
        particoes = self.pasta / "particoes/particoes.csv"
        atualizadas = 0
        with self.db() as db, indice.open(encoding="utf-8-sig", newline="") as fi, particoes.open(encoding="utf-8-sig", newline="") as fp:
            ri, rp = csv.DictReader(fi, delimiter=";"), csv.DictReader(fp, delimiter=";")
            for a, b in zip(ri, rp):
                exigir(a["uid"] == b["uid"] and a["indice_global"] == b["indice_global"], "Índice e partições não estão alinhados.")
                cur = db.execute("UPDATE proteinas SET indice_embedding=?,uid_base=?,grupo_global=?,particao=? WHERE uid=?",
                    (int(a["indice_global"]), a["uid"], b["grupo_global"], b["particao"], a["id_original"]))
                exigir(cur.rowcount == 1, "O representante não foi localizado no banco.")
                atualizadas += 1
            exigir(atualizadas == self.n() and next(ri, None) is None and next(rp, None) is None, "Banco não cobre toda a base de embeddings.")
            treino = ler_json(self.pasta / "modelo/relatorio_treino.json")
            db.execute("INSERT OR REPLACE INTO experimentos VALUES(?,?,?,?,?,?,?)", (self.m["id"],
                str(self.pasta / "modelo/modelo.pt"), str(self.pasta / "base"), str(self.pasta / "particoes"),
                serial(treino["teste_mlp"]), serial(treino["proveniencia"]), agora()))
        r = {"ok": True, "tipo": "fluxo_completo_proteinas", "id": self.m["id"], "pasta": str(self.pasta),
            "banco": str(self.bd_path), "candidatos": self.meta("entrada")["quantidade"],
            "representantes_com_embedding": atualizadas, "modelo": str(self.pasta / "modelo/modelo.pt"),
            "teste_mlp": treino["teste_mlp"], "concluido": agora(), "regra_rotulo": self.m["regra_rotulo"],
            "pipeline": list(FASES), "base_anterior_alterada": False}
        p = self.pasta / "relatorio_fluxo.json"
        p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        self.meta("resultado", r, True)
        return r, [p]

    def executar(self):
        for fase in FASES:
            self.etapa(fase, getattr(self, fase))
        return ler_json(self.pasta / "relatorio_fluxo.json")


def fasta_limitado(entrada):
    """Normalização compatível com o gerador; não acumula sequências longas."""
    desc = None
    seq, tamanho, invalida, stops = [], 0, False, 0
    alfabeto = set("ACDEFGHIKLMNPQRSTVWYBXZUO")
    def registro():
        return desc, "".join(seq), tamanho, not invalida
    for linha in entrada:
        linha = linha.rstrip("\r\n")
        if linha.startswith(">"):
            if desc is not None:
                yield registro()
            desc = linha[1:].strip()
            exigir(desc and len(desc) <= 65536, "Cabeçalho FASTA vazio ou excessivo.")
            seq, tamanho, invalida, stops = [], 0, False, 0
        elif linha:
            exigir(desc is not None, "FASTA sem cabeçalho inicial.")
            for aa in linha.upper():
                if aa == "*":
                    stops += 1
                    continue
                if stops:
                    invalida = True  # Stop interno; apenas stops finais são removidos.
                    stops = 0
                tamanho += 1
                if aa not in alfabeto:
                    invalida = True
                if tamanho <= 512:
                    seq.append(aa)
    if desc is not None:
        yield registro()


def main():
    from argparse import ArgumentParser
    p = ArgumentParser(description=__doc__)
    p.add_argument("--projeto", type=Path, required=True)
    p.add_argument("--execucao", type=Path, required=True)
    args = p.parse_args()
    try:
        r = Fluxo(args.projeto, args.execucao).executar()
        print(json.dumps(r, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Pausado as e:
        print(str(e), flush=True)
        return 75
    except (Exception, KeyboardInterrupt) as e:
        print(json.dumps({"ok": False, "erro": type(e).__name__ + ": " + str(e)}, ensure_ascii=False), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
