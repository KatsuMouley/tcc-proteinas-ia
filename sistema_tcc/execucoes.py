"""Inventário de GZ e registro de execuções completas, isoladas da base antiga."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import uuid
import zipfile

from .core import Config, ETAPAS, SCRIPTS, exigir, ler_json, serial, sha

FASES = ("extrair", "mmseqs_inicial", "rotular", "embeddings", "auditoria", "consolidar", "agrupar", "separar", "treinar", "banco")
TITULOS = ("Ler e selecionar proteínas dos GZ", "MMseqs2 sobre a entrada", "Preparar CSV e rótulos",
    "ESM-2 na GPU", "Auditar embeddings", "Consolidar base", "MMseqs2 global para partições",
    "Separar treino, validação e teste", "Treinar e avaliar MLP na GPU", "Registrar resultado no banco")
NOMES_FASES = dict(zip(FASES, TITULOS))


class Execucoes:
    def __init__(self, config, store):
        self.c, self.store = config, store
        self.trava = threading.RLock()
        self.fontes_cache = None
        self.cache_tempo = 0
        with store.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS execucoes(
                id TEXT PRIMARY KEY, pasta TEXT NOT NULL, criado TEXT NOT NULL,
                limite INTEGER NOT NULL, fonte TEXT NOT NULL, manifest_sha TEXT NOT NULL)""")

    def inventario(self, forcar=False):
        with self.trava:
            if self.fontes_cache is not None and not forcar and time.monotonic()-self.cache_tempo < 60:
                return self.fontes_cache
            fontes, arquivos = [], set()
            for pasta in self.c.caminhos["fontes"]:
                if not pasta.is_dir():
                    continue
                for path in sorted(pasta.rglob("*")):
                    if not path.is_file() or path.resolve() in arquivos:
                        continue
                    path = path.resolve()
                    exigir(path.is_relative_to(self.c.raiz), "Fonte aponta para fora do projeto.")
                    arquivos.add(path)
                    if path.suffix.lower() == ".gz":
                        fontes.append(self.fonte(path))
                    elif path.suffix.lower() == ".zip":
                        with zipfile.ZipFile(path) as z:
                            for info in z.infolist():
                                if not info.is_dir() and info.filename.lower().endswith(".gz"):
                                    fontes.append(self.fonte(path, info.filename, info.file_size, info.CRC))
            fontes.sort(key=lambda x: (x["bytes_gz"], x["nome"], x["arquivo"], x["membro"] or ""))
            self.fontes_cache, self.cache_tempo = fontes, time.monotonic()
            return fontes

    def fonte(self, path, membro=None, tamanho=None, crc=None):
        st = path.stat()
        identidade = {"arquivo": str(path), "membro": membro, "bytes_arquivo": st.st_size,
            "mtime_ns": st.st_mtime_ns, "bytes_gz": tamanho if tamanho is not None else st.st_size, "crc_zip": crc}
        ident = hashlib.sha256(serial(identidade).encode()).hexdigest()[:24]
        return {"id": ident, "nome": Path(membro or path.name).name, **identidade}

    def obter(self, ident):
        exigir(isinstance(ident, str), "ID da execução inválido.")
        with self.store.db() as db:
            row = db.execute("SELECT * FROM execucoes WHERE id=?", (ident,)).fetchone()
        exigir(row is not None, "Execução não encontrada.")
        path = Path(row["pasta"]).resolve()
        exigir(path.is_relative_to(self.c.raiz / "dados/execucoes_tcc"), "Pasta da execução inválida.")
        manifest_path = path / "execucao.json"
        exigir(sha(manifest_path) == row["manifest_sha"], "A configuração desta execução mudou. Preserve-a e crie outra execução.")
        return dict(row), ler_json(manifest_path)

    def criar(self, limite=1000, fonte="todas"):
        exigir(type(limite) is int and 100 <= limite <= 1000000, "Escolha de 100 a 1.000.000 sequências candidatas.")
        exigir(isinstance(fonte, str), "Fonte inválida.")
        inventario = self.inventario(forcar=True)
        selecionadas = inventario if fonte == "todas" else [x for x in inventario if x["id"] == fonte]
        exigir(selecionadas, "Nenhum GZ encontrado nas pastas configuradas.")
        originais = {"piloto_esm_gpu.py": self.c.raiz / "piloto_esm_gpu.py"}
        for nome in set(SCRIPTS.values()):
            originais["etapas/" + nome] = self.c.raiz / "etapas" / nome
        exigir(all(x.is_file() for x in originais.values()), "Faltam os scripts científicos ou o piloto no projeto.")
        exigir(shutil.disk_usage(self.c.raiz).free / 1024**3 >= self.c.valores["reserva_gib"], "Espaço livre abaixo da reserva configurada.")
        ident = datetime.now(timezone.utc).strftime("exp_%Y%m%dT%H%M%S_") + uuid.uuid4().hex[:8]
        pasta = self.c.raiz / "dados/execucoes_tcc" / ident
        pasta.mkdir(parents=True, exist_ok=False)
        hashes = {}
        for nome, path in originais.items():
            destino = pasta / "codigo" / nome
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destino)
            hashes[nome] = sha(destino)
        manifest = {"schema": 2, "id": ident, "projeto": str(self.c.raiz), "pasta": str(pasta),
            "criado": datetime.now(timezone.utc).isoformat(), "limite_candidatos": limite,
            "fontes": selecionadas, "semente": self.c.valores["semente"],
            "threads_pytorch": self.c.valores["threads_pytorch"],
            "threads_mmseqs": self.store.get("threads_mmseqs", self.c.valores["threads_mmseqs"]),
            "wsl": self.c.valores["wsl"], "reserva_gib": self.c.valores["reserva_gib"],
            "cache": str(self.c.caminhos["cache"]), "controle_fila": str(self.store.path),
            "codigo_sha256": hashes, "epocas": 10,
            "regra_rotulo": "Presença literal de HILKMFTWV; não mede qualidade nutricional.",
            "metodo": "Primeiras sequências únicas elegíveis da seleção; MMseqs2 inicial e embeddings dos representantes."}
        manifest_path = pasta / "execucao.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with self.store.db() as db:
            db.execute("INSERT INTO execucoes VALUES(?,?,?,?,?,?)", (ident, str(pasta), manifest["criado"], limite,
                "Todas as fontes" if fonte == "todas" else selecionadas[0]["nome"], sha(manifest_path)))
        return ident

    def config_execucao(self, ident):
        row, m = self.obter(ident)
        pasta = Path(row["pasta"])
        esperado = m["limite_candidatos"]
        inicial = pasta / "mmseqs_inicial/relatorio.json"
        if inicial.is_file():
            r = ler_json(inicial)
            if r.get("ok") is True:
                esperado = r["representantes"]
        v = dict(self.c.valores)
        v.update(esperado=esperado, semente=m["semente"], nome="Execução " + ident)
        v["caminhos"] = {**self.c.valores["caminhos"], "fontes": [str(pasta / "fontes")],
            "embeddings": str(pasta / "embeddings"), "auditorias": str(pasta / "auditorias"),
            "base": str(pasta / "base"), "grupos": str(pasta / "grupos"),
            "particoes": str(pasta / "particoes"), "modelo": str(pasta / "modelo")}
        paths = {**self.c.caminhos, "fontes": [pasta / "fontes"], "embeddings": pasta / "embeddings",
            "auditorias": pasta / "auditorias", "base": pasta / "base", "grupos": pasta / "grupos",
            "particoes": pasta / "particoes", "modelo": pasta / "modelo"}
        return Config(self.c.raiz, v, paths)

    def lista(self):
        with self.store.db() as db:
            rows = [dict(x) for x in db.execute("SELECT * FROM execucoes ORDER BY criado DESC LIMIT 100")]
        tarefas = self.store.tarefas()
        for row in rows:
            t = next((x for x in tarefas if x["etapa"] == "fluxo" and x["parametros"].get("execucao") == row["id"]), None)
            row["tarefa_id"] = t["id"] if t else None
            row["estado"] = t["estado"] if t else "registrado"
        return rows

    def status(self, ident):
        row, m = self.obter(ident)
        path = Path(row["pasta"]) / "banco.sqlite3"
        etapas, meta = [], {}
        if path.is_file():
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
            try:
                etapas = [dict(zip(("id", "estado", "inicio", "fim", "erro", "resultado"), r))
                    for r in db.execute("SELECT id,estado,inicio,fim,erro,resultado FROM etapas ORDER BY ordem")]
                meta = {k: json.loads(v) for k, v in db.execute("SELECT chave,valor FROM meta")}
            except sqlite3.OperationalError:
                pass
            finally:
                db.close()
        mapa = {x["id"]: x for x in etapas}
        fases = [{"id": k, "nome": NOMES_FASES[k], "estado": mapa.get(k, {}).get("estado", "pendente"),
            "erro": mapa.get(k, {}).get("erro")} for k in FASES]
        return {"id": ident, "pasta": str(Path(row["pasta"])), "limite_candidatos": m["limite_candidatos"],
            "fases": fases, "banco": str(path), "meta": meta, "fonte": row["fonte"]}

    def proteinas(self, ident, busca=""):
        exigir(isinstance(busca, str) and len(busca) <= 100, "Busca deve ter até 100 caracteres.")
        row, m = self.obter(ident)
        path = Path(row["pasta"]) / "banco.sqlite3"
        if not path.is_file():
            return []
        db = sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            campos = "uid,id_original,origem,sequencia,comprimento,rotulo,grupo_inicial,indice_embedding,uid_base,grupo_global,particao"
            if busca:
                rows = db.execute("SELECT " + campos + " FROM proteinas WHERE uid=? OR uid_base=? OR id_original LIKE ? ORDER BY uid LIMIT 50",
                    (busca, busca, "%"+busca+"%"))
            else:
                rows = db.execute("SELECT " + campos + " FROM proteinas ORDER BY uid LIMIT 50")
            return [dict(x) for x in rows]
        except sqlite3.OperationalError:
            return []
        finally:
            db.close()
