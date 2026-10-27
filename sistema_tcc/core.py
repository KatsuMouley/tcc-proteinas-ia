from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import uuid

ETAPAS = ("embeddings", "auditoria", "consolidar", "agrupar", "separar", "treinar")
NOMES = dict(zip(ETAPAS, ("Embeddings ESM-2", "Auditoria dos lotes", "Base consolidada",
    "Grupos globais MMseqs2", "Treino, validação e teste", "Classificador MLP")))
NOMES["fluxo"] = "Fluxo completo"
TIPOS = dict(zip(ETAPAS, ("embeddings_base_ncbi_em_lotes", "auditoria_tecnica_embeddings",
    "base_ia_consolidada", "agrupamento_global_mmseqs2", "particoes_por_grupos_globais",
    "treino_classificador_regra_aa_esm2")))
ARQUIVOS = {"embeddings": "relatorio_execucao.json", "auditoria": "relatorio.json",
    "consolidar": "relatorio_consolidacao.json", "agrupar": "relatorio_agrupamento.json",
    "separar": "relatorio_particoes.json", "treinar": "relatorio_treino.json"}
PASTAS = dict(zip(ETAPAS, ("embeddings", "auditorias", "base", "grupos", "particoes", "modelo")))
SCRIPTS = {"embeddings": "processar_base_gpu.py", "auditoria": "validar_base_embeddings.py",
    "consolidar": "preparar_base_ia.py", "agrupar": "preparar_base_ia.py",
    "separar": "preparar_base_ia.py", "treinar": "treinar_classificador_gpu.py"}
MODELO_ESM = "facebook/esm2_t6_8M_UR50D"
REVISAO_ESM = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
ESSENCIAIS = "HILKMFTWV"
ALFABETO = frozenset("ACDEFGHIKLMNPQRSTVWYBXZUO")
ATIVOS = ("pendente", "executando", "recuperacao")
CONFIG_LOCAL = "config_local.json"
AJUSTES_LOCAIS = {"dispositivo": "Processamento (auto, cuda ou cpu)", "threads_pytorch": "Threads do PyTorch (1 a 4)",
    "threads_mmseqs": "Threads do MMseqs2 (1 a 12)", "wsl": "Distribuição WSL com MMseqs2", "reserva_gib": "Espaço livre mínimo em disco (GiB)",
    "mmseqs_modo": "MMseqs2: auto, wsl ou nativo (Windows)",
    "pasta_nuvem": "Pasta na nuvem (Google Drive, OneDrive…)", "salvar_fontes": "Salvar os .gz e CSVs do NCBI na pasta na nuvem",
    "copiar_resultados": "Copiar execuções e treinos EC7 para a pasta na nuvem ao terminar"}


def agora():
    return datetime.now(timezone.utc).isoformat()


def serial(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def exigir(condicao, mensagem):
    if not condicao:
        raise ValueError(mensagem)


def modelo_portatil(config):
    """Modelo da regra versionado no git, usado quando a base do milhao nao esta neste PC.

    Vale so se o relatorio de treino estiver concluido e o modelo.pt tiver exatamente o hash registrado nele.
    """
    pasta = config.caminhos["modelo"]
    try:
        r = ler_json(pasta / "relatorio_treino.json")
        if r.get("ok") is True and (pasta / "modelo.pt").is_file() and sha(pasta / "modelo.pt") == r["hashes_arquivos"]["modelo.pt"]:
            return r
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        pass
    return None


def ler_json(path):
    path = Path(path)
    exigir(path.stat().st_size <= 5 * 1024**2, "Relatório JSON excede 5 MiB.")
    valor = json.loads(path.read_text(encoding="utf-8-sig"))
    exigir(isinstance(valor, dict), "Relatório precisa ser um objeto JSON.")
    return valor


def validar_sequencia(valor):
    exigir(isinstance(valor, str) and valor.isascii(), "Informe uma sequência em letras de aminoácidos.")
    seq = valor.strip().upper()
    exigir(1 <= len(seq) <= 512, "Use entre 1 e 512 resíduos.")
    exigir(set(seq) <= ALFABETO, "Remova espaços internos, cabeçalhos FASTA e caracteres inválidos.")
    return seq


def regra_direta(seq):
    presentes = [x for x in ESSENCIAIS if x in seq]
    ausentes = [x for x in ESSENCIAIS if x not in seq]
    return {"regra_direta": "Incompleta" if ausentes else "Completa", "residuos": len(seq),
        "aminoacidos_essenciais_presentes": presentes, "aminoacidos_essenciais_ausentes": ausentes}


def conferir_npy(path, formato, tipo):
    """Cabeçalho e tamanho, sem carregar a matriz ou repetir sua auditoria."""
    with Path(path).open("rb") as f:
        exigir(f.read(6) == b"\x93NUMPY", f"NPY inválido: {Path(path).name}.")
        versao = tuple(f.read(2))
        exigir(versao in ((1, 0), (2, 0), (3, 0)), "Versão NPY desconhecida.")
        n = 2 if versao == (1, 0) else 4
        bruto = f.read(n)
        exigir(len(bruto) == n, "Cabeçalho NPY incompleto.")
        tamanho = int.from_bytes(bruto, "little")
        exigir(0 < tamanho <= 65536, "Cabeçalho NPY excessivo.")
        cab = ast.literal_eval(f.read(tamanho).decode("utf-8" if versao == (3, 0) else "latin1"))
        exigir(cab.get("shape") == tuple(formato) and cab.get("descr") in ("<" + tipo, "=" + tipo),
            f"Formato NPY incompatível: {Path(path).name}.")
        esperado = f.tell() + math.prod(formato) * int(tipo[1:])
    exigir(Path(path).stat().st_size == esperado, f"NPY incompleto ou tamanho alterado: {Path(path).name}.")


@dataclass(frozen=True)
class Config:
    raiz: Path
    valores: dict
    caminhos: dict

    @classmethod
    def carregar(cls, raiz, arquivo=None):
        raiz = Path(raiz).resolve()
        valores = ler_json(arquivo or raiz / "sistema_tcc/config.json")
        exigir(valores.get("schema") == 1, "Configuração incompatível.")
        local = raiz / CONFIG_LOCAL
        if arquivo is None and local.is_file():
            # Ajustes deste computador (tela Configurações); o config.json versionado fica intacto.
            ajustes = ler_json(local)
            exigir(isinstance(ajustes, dict) and set(ajustes) <= set(AJUSTES_LOCAIS), "config_local.json inválido.")
            valores = {**valores, **ajustes}
        valores.setdefault("dispositivo", "auto")
        exigir(valores["dispositivo"] in ("auto", "cuda", "cpu"), "Dispositivo inválido: use auto, cuda ou cpu.")
        for chave, minimo, maximo in (("esperado", 1, 100000000), ("threads_pytorch", 1, 4),
                ("threads_mmseqs", 1, 12), ("semente", 0, 2147483647), ("intervalo_segundos", 2, 3600)):
            x = valores.get(chave)
            exigir(type(x) is int and minimo <= x <= maximo, f"Configuração inválida: {chave}.")
        exigir(type(valores.get("automatico_inicial")) is bool, "automatico_inicial deve ser booleano.")
        reserva = valores.get("reserva_gib")
        exigir(type(reserva) in (int, float) and math.isfinite(reserva) and reserva >= 0, "Reserva de disco inválida.")
        exigir(isinstance(valores.get("wsl"), str) and len(valores["wsl"]) <= 100, "Distribuição WSL inválida.")
        exigir(valores.setdefault("mmseqs_modo", "auto") in ("auto", "wsl", "nativo"), "MMseqs2: use auto, wsl ou nativo.")
        nuvem = valores.get("pasta_nuvem") or ""
        exigir(isinstance(nuvem, str) and len(nuvem) <= 260 and (not nuvem or Path(nuvem).is_absolute()), "Pasta na nuvem inválida.")
        for chave in ("salvar_fontes", "copiar_resultados"):
            exigir(type(valores.get(chave, False)) is bool, f"{chave} deve ser verdadeiro ou falso.")
        def caminho(valor):
            exigir(isinstance(valor, str) and valor, "Caminho vazio na configuração.")
            p = (raiz / valor).resolve()
            exigir(p.is_relative_to(raiz) and p != raiz, "Todos os caminhos precisam estar dentro do projeto.")
            return p
        orig = valores["caminhos"]
        nomes = {"fontes", "embeddings", "auditorias", "base", "grupos", "particoes", "modelo", "cache", "sistema"}
        exigir(set(orig) == nomes, "Caminhos da configuração incompletos.")
        exigir(isinstance(orig["fontes"], list) and 1 <= len(orig["fontes"]) <= 5, "Informe as pastas de fontes.")
        caminhos = {k: [caminho(x) for x in v] if k == "fontes" else caminho(v) for k, v in orig.items()}
        saidas = [caminhos[k] for k in ("embeddings", "auditorias", "base", "grupos", "particoes", "modelo", "sistema")]
        for i, a in enumerate(saidas):
            for b in saidas[i+1:]:
                exigir(not a.is_relative_to(b) and not b.is_relative_to(a), "Pastas de saída não podem se sobrepor.")
        for saida in saidas:
            for fonte in [*caminhos["fontes"], caminhos["cache"], raiz / "etapas", raiz / "sistema_tcc"]:
                exigir(not saida.is_relative_to(fonte) and not fonte.is_relative_to(saida),
                    "Pastas de saída não podem se sobrepor às fontes, ao cache ou ao código.")
        if nuvem and valores.get("salvar_fontes") is True:  # fontes na nuvem primeiro; as do projeto continuam lidas
            caminhos["fontes"] = [Path(nuvem) / "arquivos .gz", Path(nuvem) / "arquivos csv", *caminhos["fontes"]]
        return cls(raiz, valores, caminhos)

    @property
    def esperado(self):
        return self.valores["esperado"]

    def script(self, etapa):
        return self.raiz / "etapas" / SCRIPTS[etapa]


@contextmanager
def instancia_unica(pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    with (pasta / "sistema.lock").open("a+b") as f:
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise RuntimeError("O sistema já está aberto usando esta fila.") from e
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def pid_ativo(pid):
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.OpenProcess.restype = wintypes.HANDLE
        k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return ctypes.get_last_error() == 5  # Acesso negado: considerar ocupado.
        try:
            codigo = wintypes.DWORD()
            return not k.GetExitCodeProcess(handle, ctypes.byref(codigo)) or codigo.value == 259
        finally:
            k.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Store:
    def __init__(self, pasta):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        (self.pasta / "logs").mkdir(exist_ok=True)
        self.path = self.pasta / "controle.sqlite3"
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tarefas(
                    id INTEGER PRIMARY KEY, etapa TEXT NOT NULL, chave TEXT NOT NULL,
                    estado TEXT NOT NULL, origem TEXT NOT NULL, parametros TEXT NOT NULL,
                    criado TEXT NOT NULL, inicio TEXT, fim TEXT, pid INTEGER,
                    codigo INTEGER, erro TEXT, resultado TEXT, log TEXT, log_extra TEXT,
                    comando TEXT, progresso TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS unica_ativa ON tarefas(chave)
                    WHERE estado IN ('pendente','executando','recuperacao');
                CREATE TABLE IF NOT EXISTS artefatos(
                    etapa TEXT PRIMARY KEY, assinatura TEXT NOT NULL, observado TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eventos(id INTEGER PRIMARY KEY, criado TEXT, mensagem TEXT);
            """)
            db.execute("UPDATE tarefas SET estado='recuperacao', erro=? WHERE estado='executando'",
                ("O sistema foi encerrado durante esta tarefa. Concilie antes de continuar.",))
            if db.execute("SELECT 1 FROM tarefas WHERE estado='recuperacao'").fetchone():
                self._set(db, "pausado", True)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _set(self, db, chave, valor):
        db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (chave, serial(valor)))

    def get(self, chave, padrao=None):
        with self.db() as db:
            r = db.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
            return json.loads(r[0]) if r else padrao

    def set(self, chave, valor):
        with self.db() as db:
            self._set(db, chave, valor)

    def evento(self, mensagem):
        with self.db() as db:
            db.execute("INSERT INTO eventos(criado,mensagem) VALUES(?,?)", (agora(), mensagem))

    def observar(self, etapa, assinatura, relatorio, caminho, log=None):
        with self.db() as db:
            antigo = db.execute("SELECT assinatura FROM artefatos WHERE etapa=?", (etapa,)).fetchone()
            if antigo:
                exigir(antigo[0] == assinatura, "Artefato mudou desde a importação. Preserve esta versão e confira os arquivos antes de continuar.")
                return
            db.execute("INSERT INTO artefatos VALUES(?,?,?)", (etapa, assinatura, agora()))
            ativo = db.execute("SELECT 1 FROM tarefas WHERE etapa=? AND estado='executando'", (etapa,)).fetchone()
            if not ativo:
                db.execute("""INSERT INTO tarefas(etapa,chave,estado,origem,parametros,criado,resultado,log)
                    VALUES(?,?,'concluido','importado','{}',?,?,?)""",
                    (etapa, "importado:" + etapa + ":" + assinatura, agora(),
                     serial({"importado": True, "relatorio": str(caminho), "ok": True}), str(log) if log and log.is_file() else None))

    def atualizar(self, ident, **valores):
        permitidas = {"estado", "inicio", "fim", "pid", "codigo", "erro", "resultado", "log", "log_extra", "comando", "progresso", "parametros"}
        exigir(set(valores) <= permitidas, "Atualização de tarefa inválida.")
        for k in ("resultado", "comando", "progresso", "parametros"):
            if k in valores and valores[k] is not None:
                valores[k] = serial(valores[k])
        with self.db() as db:
            db.execute("UPDATE tarefas SET " + ",".join(k + "=?" for k in valores) + " WHERE id=?",
                (*valores.values(), ident))

    def _tarefa(self, row):
        if row is None:
            return None
        r = dict(row)
        for k in ("parametros", "resultado", "comando", "progresso"):
            r[k] = json.loads(r[k]) if r[k] else None
        return r

    def tarefa(self, ident):
        with self.db() as db:
            return self._tarefa(db.execute("SELECT * FROM tarefas WHERE id=?", (ident,)).fetchone())

    def tarefas(self, limite=100):
        with self.db() as db:
            return [self._tarefa(x) for x in db.execute("SELECT * FROM tarefas ORDER BY CASE WHEN estado IN ('executando','recuperacao') THEN 0 ELSE 1 END,id DESC LIMIT ?", (limite,))]

    def ultimo(self, etapa, chave=None):
        with self.db() as db:
            sql = "SELECT * FROM tarefas WHERE etapa=? AND origem!='importado'"
            args = [etapa]
            if chave:
                sql += " AND chave=?"
                args.append(chave)
            return self._tarefa(db.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone())

    def criar(self, etapa, chave, parametros, origem, repetir=False):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            antigo = db.execute("SELECT * FROM tarefas WHERE chave=? ORDER BY id DESC LIMIT 1", (chave,)).fetchone()
            if antigo and (antigo["estado"] in ATIVOS or not repetir):
                return self._tarefa(antigo), False
            exigir(db.execute("SELECT COUNT(*) FROM tarefas WHERE estado='pendente'").fetchone()[0] < 100,
                "Fila cheia. Aguarde ou cancele solicitações pendentes.")
            c = db.execute("""INSERT INTO tarefas(etapa,chave,estado,origem,parametros,criado)
                VALUES(?,?,'pendente',?,?,?)""", (etapa, chave, origem, serial(parametros), agora()))
            ident = c.lastrowid
        return self.tarefa(ident), True

    def proxima(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            pausado = db.execute("SELECT valor FROM meta WHERE chave='pausado'").fetchone()
            if (pausado and json.loads(pausado[0])) or db.execute("SELECT 1 FROM tarefas WHERE estado IN ('executando','recuperacao')").fetchone():
                return None
            row = db.execute("SELECT * FROM tarefas WHERE estado='pendente' ORDER BY id LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE tarefas SET estado='executando',inicio=? WHERE id=?", (agora(), row["id"]))
        return self.tarefa(row["id"]) if row else None


class Catalogo:
    def __init__(self, config, store, escopo="original"):
        self.c, self.store = config, store
        self.escopo = escopo
        self.trava = threading.RLock()
        self.atualizado = 0
        self.estados, self.relatorios = {}, {}
        self.arquivos_auditoria = []

    def _auditoria(self, rels):
        candidatos = []
        r = rels.get("consolidar", {})
        if r.get("auditoria"):
            p = Path(r["auditoria"]).resolve()
            if p.is_relative_to(self.c.caminhos["auditorias"]):
                candidatos.append(p)
        candidatos.extend(sorted(self.c.caminhos["auditorias"].glob("auditoria_*/relatorio.json"), reverse=True))
        for p in dict.fromkeys(candidatos):
            try:
                x = ler_json(p)
                if x.get("ok") is True and x.get("esperado") == self.c.esperado and Path(x.get("base", "")).resolve() == self.c.caminhos["embeddings"]:
                    return p, x
            except (OSError, ValueError, TypeError):
                continue
        return None, None

    def refresh(self, forcar=False):
        with self.trava:
            if not forcar and time.monotonic() - self.atualizado < 5:
                return self.estados
            rels, paths, estados = {}, {}, {}
            for etapa in ETAPAS:
                if etapa == "auditoria":
                    continue
                path = self.c.caminhos[PASTAS[etapa]] / ARQUIVOS[etapa]
                paths[etapa] = path
                if path.is_file():
                    try:
                        rels[etapa] = ler_json(path)
                    except (OSError, ValueError, UnicodeError) as e:
                        estados[etapa] = {"estado": "bloqueado", "motivo": "Relatório ilegível: " + str(e)}
            paths["auditoria"], audit = self._auditoria(rels)
            if audit:
                rels["auditoria"] = audit
            for etapa in ETAPAS:
                if etapa in estados:
                    continue
                if etapa not in rels:
                    pasta = self.c.caminhos[PASTAS[etapa]]
                    tem_saida = etapa not in ("embeddings", "auditoria") and pasta.exists()
                    estados[etapa] = {"estado": "bloqueado" if tem_saida else "pendente",
                        "motivo": "A pasta de saída existe sem relatório concluído. Confira esta versão." if tem_saida else "Etapa ainda não registrada."}
                    continue
                try:
                    for anterior in ETAPAS[:ETAPAS.index(etapa)]:
                        exigir(estados[anterior]["estado"] == "concluido", "Dependência pendente ou inválida: " + NOMES[anterior] + ". " + estados[anterior]["motivo"])
                    artefatos = self.validar(etapa, rels, paths)
                    assinatura = hashlib.sha256(serial({"relatorio": sha(paths[etapa]),
                        "arquivos": [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in artefatos]}).encode()).hexdigest()
                    log = self.c.caminhos[PASTAS[etapa]] / ("mmseqs.log" if etapa == "agrupar" else "treino.log") if etapa in ("agrupar", "treinar") else None
                    if self.escopo == "original":
                        self.store.observar(etapa, assinatura, rels[etapa], paths[etapa], log)
                    else:
                        with self.store.db() as db:
                            chave = self.escopo + ":" + etapa
                            r = db.execute("SELECT assinatura FROM artefatos WHERE etapa=?", (chave,)).fetchone()
                            exigir(not r or r[0] == assinatura, "Saída desta execução mudou desde o registro.")
                            if not r:
                                db.execute("INSERT INTO artefatos VALUES(?,?,?)", (chave, assinatura, agora()))
                    estados[etapa] = {"estado": "concluido", "motivo": "Relatório compatível e arquivos presentes.", "relatorio": str(paths[etapa])}
                except (OSError, ValueError, KeyError, TypeError, SyntaxError) as e:
                    # Um recorte parcial só pode retomar a geração enquanto não há uma base final.
                    parcial = etapa == "embeddings" and rels[etapa].get("ok") is True and type(rels[etapa].get("embeddings_total")) is int and rels[etapa]["embeddings_total"] < self.c.esperado and "consolidar" not in rels
                    estados[etapa] = {"estado": "pendente" if parcial else "bloqueado", "motivo": str(e),
                        "relatorio": str(paths[etapa]) if paths.get(etapa) else None}
            if estados["embeddings"]["estado"] == "pendente" and "consolidar" in rels:
                estados["embeddings"] = {"estado": "bloqueado", "motivo": "Há uma base consolidada, mas o registro de geração está ausente. Confira os arquivos existentes."}
            self.relatorios, self.estados, self.paths = rels, estados, paths
            self.atualizado = time.monotonic()
            return estados

    def validar(self, etapa, rels, paths):
        r = rels[etapa]
        n, p = self.c.esperado, self.c.caminhos
        exigir(r.get("tipo") == TIPOS[etapa] and r.get("ok") is True, "Etapa não tem relatório aprovado do tipo esperado.")
        def arquivos(pasta, nomes):
            arr = [pasta / nome for nome in nomes]
            exigir(all(x.is_file() and x.stat().st_size > 0 for x in arr), "Faltam arquivos de saída desta etapa.")
            return arr
        if etapa == "embeddings":
            exigir(r.get("modelo") == MODELO_ESM and r.get("revisao") == REVISAO_ESM and r.get("max_residuos") == 512,
                "Modelo, revisão ou limite de resíduos incompatível.")
            exigir(r.get("embeddings_total") == n and r.get("formato_total_embeddings") == [n, 320], "O total de embeddings difere do objetivo configurado.")
            exigir(r.get("rotulos_vetores_unicos", {}).get("Completa", 0) + r.get("rotulos_vetores_unicos", {}).get("Incompleta", 0) == n, "Contagem de rótulos inconsistente.")
            return arquivos(p["embeddings"], ("fontes.json",)) + [paths[etapa]]
        if etapa == "auditoria":
            exigir(r.get("esperado") == n and r.get("erros_total") == 0 and r.get("formato_total_observado") == [n, 320]
                and r.get("totais_examinados", {}).get("vetores") == n, "Auditoria não aprova este recorte.")
            exigir(Path(r["base"]).resolve() == p["embeddings"], "Auditoria pertence a outra base.")
            exigir(r.get("rotulos_vetores") == rels.get("embeddings", {}).get("rotulos_vetores_unicos"), "Auditoria e geração divergem nos rótulos.")
            return [paths[etapa]]
        if etapa == "consolidar":
            exigir(r.get("schema") == 1 and r.get("modelo") == MODELO_ESM and r.get("revisao") == REVISAO_ESM
                and r.get("proteinas") == n and r.get("formato_embeddings") == [n, 320]
                and r.get("config_original", {}).get("regra_aminoacidos") == ESSENCIAIS, "Consolidação incompatível com o protocolo.")
            exigir(Path(r["base_original"]).resolve() == p["embeddings"], "A consolidação pertence a outra geração.")
            exigir(r.get("relatorio_original_sha256") == sha(paths["embeddings"]), "O relatório da geração mudou após a consolidação.")
            exigir(paths.get("auditoria") and r.get("auditoria_sha256") == sha(paths["auditoria"]), "A auditoria referenciada pela consolidação não está disponível ou mudou.")
            arr = arquivos(p["base"], ("indice.csv", "sequencias.fasta", "embeddings.npy"))
            conferir_npy(p["base"] / "embeddings.npy", (n, 320), "f4")
            return arr + [paths[etapa]]
        if etapa == "agrupar":
            exigir(r.get("proteinas") == n and Path(r["base"]).resolve() == p["base"]
                and r.get("fasta_sha256") == rels.get("consolidar", {}).get("hashes_arquivos", {}).get("sequencias.fasta"), "Agrupamento pertence a outra base.")
            protocolo = r.get("parametros", {})
            exigir(all(protocolo.get(k) == v for k, v in {"identidade_minima": 0.5, "cobertura_minima": 0.8,
                "cov_mode": 0, "cluster_mode": 1, "alignment_mode": 3, "kmer_per_seq": 80, "evalue": 0.001}.items()), "Parâmetros do agrupamento diferem do protocolo.")
            exigir(type(r.get("grupos")) is int and 3 <= r["grupos"] <= n, "Quantidade de grupos inválida.")
            return arquivos(p["grupos"], ("global_cluster.tsv",)) + [paths[etapa]]
        if etapa == "separar":
            exigir(r.get("proteinas") == n and r.get("semente") == self.c.valores["semente"]
                and r.get("grupos_compartilhados_entre_particoes") == 0, "Partições incompatíveis com o objetivo ou a semente.")
            exigir(Path(r["base_consolidada"]).resolve() == p["base"] and Path(r["agrupamento"]).resolve() == p["grupos"]
                and r.get("tsv_sha256") == rels.get("agrupar", {}).get("tsv_sha256"), "As partições pertencem a outro agrupamento.")
            particoes = r["particoes"]
            exigir(sum(particoes[k]["proteinas"] for k in ("treino", "validacao", "teste")) == n, "Contagens das partições não cobrem a base.")
            arr = arquivos(p["particoes"], ("particoes.csv", "grupos_por_linha.npy", "treino_indices.npy", "validacao_indices.npy", "teste_indices.npy"))
            conferir_npy(p["particoes"] / "grupos_por_linha.npy", (n,), "i8")
            for k in ("treino", "validacao", "teste"):
                exigir(particoes[k]["proteinas"] > 0 and all(particoes[k]["rotulos"].get(classe, 0) > 0 for classe in ("Completa", "Incompleta")), "Uma partição ou classe está vazia.")
                conferir_npy(p["particoes"] / (k + "_indices.npy"), (particoes[k]["proteinas"],), "i8")
            return arr + [paths[etapa]]
        if etapa == "treinar":
            prov = r["proveniencia"]
            exigir(Path(prov["base"]).resolve() == p["base"] and Path(prov["particoes"]).resolve() == p["particoes"]
                and prov.get("relatorio_consolidacao_sha256") == sha(paths["consolidar"])
                and prov.get("relatorio_particoes_sha256") == sha(paths["separar"]), "O modelo foi treinado com outra base ou partições.")
            exigir(r.get("arquitetura") == [320, 64, 2] and r.get("classes") == ["Incompleta", "Completa"], "Classificador incompatível.")
            exigir(r.get("teste_mlp", {}).get("proteinas") == rels.get("separar", {}).get("particoes", {}).get("teste", {}).get("proteinas"), "Quantidade de teste inconsistente.")
            return arquivos(p["modelo"], ("modelo.pt", "historico.csv", "predicoes_teste.csv", "configuracao.json")) + [paths[etapa]]
        raise ValueError("Etapa desconhecida.")

    def bloqueio(self, etapa):
        estados = self.refresh()
        indice = ETAPAS.index(etapa)
        for anterior in ETAPAS[:indice]:
            if estados[anterior]["estado"] != "concluido":
                return "Aguardando " + NOMES[anterior] + ": " + estados[anterior]["motivo"]
        if estados[etapa]["estado"] == "bloqueado":
            return estados[etapa]["motivo"]
        if not self.c.script(etapa).is_file():
            return "Script ausente: etapas/" + SCRIPTS[etapa]
        if etapa == "embeddings" and (not (self.c.raiz / "piloto_esm_gpu.py").is_file() or not all(x.is_dir() for x in self.c.caminhos["fontes"])):
            return "Faltam o piloto ou as pastas com os pares GZ/CSV."
        return None

    def chave(self, etapa):
        self.refresh()
        anteriores = ETAPAS[:ETAPAS.index(etapa)]
        obj = {"etapa": etapa, "esperado": self.c.esperado, "semente": self.c.valores["semente"],
            "caminhos": self.c.valores["caminhos"], "script": sha(self.c.script(etapa)),
            "entradas": {k: sha(self.paths[k]) for k in anteriores if self.paths.get(k) and self.paths[k].is_file()}}
        return hashlib.sha256(serial(obj).encode()).hexdigest()


def comando(config, etapa, parametros):
    """Somente programas e argumentos fixos; não aceita comandos de shell."""
    c, p = config, config.caminhos
    args = [sys.executable, "-u", str(c.script(etapa))]
    reserva = str(c.valores["reserva_gib"])
    if etapa == "embeddings":
        args += ["--limite", str(c.esperado), "--saida", str(p["embeddings"]), "--cache", str(p["cache"]),
            "--threads", str(c.valores["threads_pytorch"]), "--max-residuos", "512", "--reserva-gb", reserva,
            "--fontes", *map(str, p["fontes"])]
    elif etapa == "auditoria":
        args += ["--base", str(p["embeddings"]), "--esperado", str(c.esperado), "--saida", parametros["saida_auditoria"]]
    elif etapa == "consolidar":
        args += ["consolidar", "--base", str(p["embeddings"]), "--esperado", str(c.esperado),
            "--saida", str(p["base"]), "--auditoria", parametros["auditoria"], "--reserva-gib", reserva]
    elif etapa == "agrupar":
        args += ["agrupar", "--base", str(p["base"]), "--saida", str(p["grupos"]),
            "--threads", str(parametros["threads_mmseqs"]), "--reserva-gib", reserva]
        if os.name == "nt":
            args += ["--wsl", c.valores["wsl"]]
    elif etapa == "separar":
        args += ["separar", "--base", str(p["base"]), "--agrupamento", str(p["grupos"]),
            "--saida", str(p["particoes"]), "--semente", str(c.valores["semente"]), "--reserva-gib", reserva]
    elif etapa == "treinar":
        args += ["treinar", "--base", str(p["base"]), "--particoes", str(p["particoes"]),
            "--saida", str(p["modelo"]), "--threads", str(c.valores["threads_pytorch"]), "--dispositivo", c.valores.get("dispositivo", "auto"),
            "--semente", str(c.valores["semente"])]
    else:
        raise ValueError("Etapa desconhecida.")
    return args


class Executor:
    def __init__(self, config, store, catalogo, servico_factory=None):
        self.c, self.store, self.catalogo = config, store, catalogo
        self.parar = threading.Event()
        self.acordar = threading.Event()
        self.trava_planejar = threading.RLock()
        self.servico, self.servico_factory = None, servico_factory
        self.modelo_carregado = None
        self.ativo = None
        self.thread = None
        from .execucoes import Execucoes
        self.execucoes = Execucoes(config, store)
        self.catalogos_execucoes = {}
        if store.get("automatico") is None:
            store.set("automatico", config.valores["automatico_inicial"])
        if store.get("pausado") is None:
            store.set("pausado", False)

    def start(self):
        self.catalogo.refresh(True)
        self.thread = threading.Thread(target=self.loop, name="executor-tcc", daemon=True)
        self.thread.start()

    def agendar(self, etapa, origem="manual", repetir=False):
        exigir(etapa in ETAPAS, "Etapa desconhecida.")
        with self.trava_planejar:
            estados = self.catalogo.refresh(True)
            if estados[etapa]["estado"] == "concluido":
                return {"reutilizado": True, "etapa": etapa, "relatorio": estados[etapa]["relatorio"]}
            erro = self.catalogo.bloqueio(etapa)
            exigir(not erro, erro)
            exigir(not any(x["estado"] == "recuperacao" for x in self.store.tarefas()), "Concilie a tarefa interrompida antes de agendar.")
            p = {"threads_mmseqs": self.store.get("threads_mmseqs", self.c.valores["threads_mmseqs"])}
            if etapa == "auditoria":
                p["saida_auditoria"] = str(self.c.caminhos["auditorias"] / ("auditoria_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")))
            if etapa == "consolidar":
                p["auditoria"] = str(self.catalogo.paths["auditoria"])
            chave = self.catalogo.chave(etapa)
            task, criada = self.store.criar(etapa, chave, p, origem, repetir=repetir)
            if criada:
                self.store.evento(NOMES[etapa] + " adicionada à fila.")
            self.acordar.set()
            return {"tarefa": task, "nova": criada}

    def catalogo_execucao(self, ident):
        if ident == "original":
            return self.catalogo, self.c
        config = self.execucoes.config_execucao(ident)
        antigo = self.catalogos_execucoes.get(ident)
        if not antigo or antigo.c.esperado != config.esperado:
            antigo = Catalogo(config, self.store, escopo=ident)
            self.catalogos_execucoes[ident] = antigo
        return antigo, config

    def iniciar_fluxo(self, limite=1000, fonte="todas"):
        with self.trava_planejar:
            exigir(not any(t["estado"] == "recuperacao" for t in self.store.tarefas()), "Concilie a execução anterior antes de iniciar outra.")
            ident = self.execucoes.criar(limite, fonte)
            self.store.set("automatico", False)  # O novo fluxo encadeia seu treino; não usa o agendador antigo.
            self.store.set("execucao_selecionada", ident)
            self.controles(pausado=False)
            return self.retomar_fluxo(ident)

    def retomar_fluxo(self, ident):
        with self.trava_planejar:
            row, m = self.execucoes.obter(ident)
            banco = Path(row["pasta"]) / "banco.sqlite3"
            if banco.is_file():
                with sqlite3.connect(banco.as_uri()+"?mode=ro", uri=True, timeout=2) as db:
                    ativos = db.execute("SELECT pid FROM etapas WHERE pid IS NOT NULL").fetchall()
                    exigir(not any(pid_ativo(x[0]) for x in ativos), "Um subprocesso desta execução ainda está ativo.")
            ultimo = self.store.ultimo("fluxo", "fluxo:"+ident)
            if ultimo and ultimo["estado"] == "concluido":
                return {"ok": True, "execucao": ident, "reutilizado": True, "tarefa": ultimo}
            exigir(not any(t["estado"] == "recuperacao" for t in self.store.tarefas()), "Concilie a execução interrompida antes de retomar.")
            task, novo = self.store.criar("fluxo", "fluxo:"+ident, {"execucao": ident}, "automatico", repetir=True)
            self.acordar.set()
            return {"ok": True, "execucao": ident, "tarefa": task, "nova": novo}

    def prever(self, sequencia, execucao="original"):
        seq = validar_sequencia(sequencia)
        cat, config = self.catalogo_execucao(execucao)
        exigir(cat.refresh(True)["treinar"]["estado"] == "concluido" or (execucao == "original" and modelo_portatil(config) is not None),
               "O modelo concluído ainda não está disponível. Consulte os arquivos indicados no painel.")
        exigir(not any(x["estado"] == "recuperacao" for x in self.store.tarefas()), "Concilie a tarefa interrompida antes de consultar.")
        tarefa, _ = self.store.criar("prever", "prever:" + uuid.uuid4().hex, {"sequencia": seq, "execucao": execucao}, "consulta")
        self.acordar.set()
        return tarefa

    def planejar(self):
        if not self.store.get("automatico") or self.store.get("pausado"):
            return
        if any(x["estado"] in ATIVOS for x in self.store.tarefas()):
            return
        estados = self.catalogo.refresh(True)
        for etapa in ETAPAS[:-1]:  # Treino é um experimento explícito.
            if estados[etapa]["estado"] == "concluido":
                continue
            if self.catalogo.bloqueio(etapa):
                return
            ultimo = self.store.ultimo(etapa, self.catalogo.chave(etapa))
            if ultimo and ultimo["estado"] in ("falhou", "bloqueado", "interrompido", "recuperacao", "cancelado", "concluido"):
                return
            self.agendar(etapa, "automatico")
            return

    def loop(self):
        proxima = 0
        while not self.parar.is_set():
            try:
                if time.monotonic() >= proxima:
                    self.planejar()
                    proxima = time.monotonic() + self.c.valores["intervalo_segundos"]
                task = self.store.proxima()
                if task:
                    self.executar(task)
                    proxima = 0
                    continue
            except Exception as e:
                self.store.evento("Executor: " + type(e).__name__ + ": " + str(e))
                proxima = time.monotonic() + self.c.valores["intervalo_segundos"]
            self.acordar.wait(0.5)
            self.acordar.clear()
        self.liberar_gpu()

    def liberar_gpu(self):
        if self.servico is not None:
            torch = getattr(self.servico, "torch", None)
            self.servico = None
            self.modelo_carregado = None
            gc.collect()
            if torch and torch.cuda.is_available():
                torch.cuda.empty_cache()

    def carregar_servico(self, config=None):
        config = config or self.c
        modelo = config.caminhos["modelo"] / "modelo.pt"
        if self.servico is not None and self.modelo_carregado != str(modelo):
            self.liberar_gpu()
        if self.servico is None:
            if self.servico_factory:
                self.servico = self.servico_factory()
            else:
                from argparse import Namespace
                from .inferencia import Servico
                sys.path.insert(0, str(self.c.raiz / "etapas"))
                self.servico = Servico(Namespace(modelo=modelo,
                    cache=config.caminhos["cache"], threads=config.valores["threads_pytorch"]))
            self.modelo_carregado = str(modelo)
        return self.servico

    def executar(self, task):
        ident, etapa = task["id"], task["etapa"]
        proc = None
        self.ativo = ident
        log_path = self.store.pasta / "logs" / f"tarefa_{ident:06d}.log"
        self.store.atualizar(ident, log=str(log_path))
        try:
            with log_path.open("w", encoding="utf-8", buffering=1) as log:
                log.write(agora() + " · Início: " + NOMES.get(etapa, "Consulta de proteína") + "\n")
                if etapa == "prever":
                    cat, config = self.catalogo_execucao(task["parametros"].get("execucao", "original"))
                    portatil = task["parametros"].get("execucao", "original") == "original" and modelo_portatil(config) is not None
                    exigir(cat.refresh(True)["treinar"]["estado"] == "concluido" or portatil, "Modelo indisponível ou alterado.")
                    if portatil and cat.estados["treinar"]["estado"] != "concluido":
                        log.write("Base do milhão ausente: usando o modelo versionado no git (hash conferido).\n")
                    log.write("Carregando/reutilizando ESM-2 e MLP locais, sem download.\n")
                    resultado = self.carregar_servico(config).prever(task["parametros"]["sequencia"])
                    resultado.update(regra_direta(task["parametros"]["sequencia"]))
                    exigir(resultado.get("ok") is True, "A inferência não retornou resultado válido.")
                    exigir(resultado.get("predicao_mlp") in ("Incompleta", "Completa"), "Classificador retornou uma classe desconhecida.")
                    resultado["concorda_com_regra_direta"] = resultado["predicao_mlp"] == resultado["regra_direta"]
                    log.write("Consulta concluída: " + str(resultado["residuos"]) + " resíduos.\n")
                    resultado["execucao"] = task["parametros"].get("execucao", "original")
                    self.store.atualizar(ident, resultado=resultado, parametros={"residuos": resultado["residuos"], "execucao": resultado["execucao"]})
                elif etapa == "fluxo":
                    self.liberar_gpu()
                    row, m = self.execucoes.obter(task["parametros"]["execucao"])
                    cmd = [sys.executable, "-u", "-m", "sistema_tcc.fluxo", "--projeto", str(self.c.raiz), "--execucao", row["pasta"]]
                    self.store.atualizar(ident, comando=cmd)
                    env = os.environ.copy()
                    env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
                    kwargs = {"cwd": str(self.c.raiz), "env": env, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                        "text": True, "encoding": "utf-8", "errors": "replace", "bufsize": 1}
                    if os.name == "nt":
                        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                    else:
                        kwargs["start_new_session"] = True
                    proc = subprocess.Popen(cmd, **kwargs)
                    self.store.atualizar(ident, pid=proc.pid)
                    try:
                        for linha in proc.stdout:
                            log.write(linha)
                            self.progresso(ident, etapa, linha)
                    finally:
                        proc.stdout.close()
                    codigo = proc.wait()
                    self.store.atualizar(ident, codigo=codigo, pid=None)
                    if codigo == 75:
                        self.store.atualizar(ident, estado="interrompido", fim=agora(), erro="Pausado entre etapas. Use Retomar execução para continuar.")
                        log.write("Etapas confirmadas preservadas. Fluxo pausado entre etapas.\n")
                        return
                    exigir(codigo == 0, f"O fluxo encerrou com código {codigo}. Consulte a etapa e o log.")
                    resultado = ler_json(Path(row["pasta"]) / "relatorio_fluxo.json")
                    exigir(resultado.get("ok") is True, "O fluxo não produziu relatório aprovado.")
                    cat, _ = self.catalogo_execucao(task["parametros"]["execucao"])
                    exigir(all(x["estado"] == "concluido" for x in cat.refresh(True).values()), "Uma saída científica do fluxo não foi aprovada.")
                    self.store.atualizar(ident, resultado=resultado)
                    from .pastas import copiar_resultado
                    copiar_resultado(row["pasta"], "execucoes_tcc/" + Path(row["pasta"]).name, self.c.raiz, log.write)
                else:
                    self.catalogo.refresh(True)
                    erro = self.catalogo.bloqueio(etapa)
                    exigir(not erro, erro)
                    if self.catalogo.estados[etapa]["estado"] == "concluido":
                        log.write("Resultado existente reutilizado; nenhum comando científico executado.\n")
                    else:
                        exigir(task["chave"] == self.catalogo.chave(etapa), "Entradas ou script mudaram desde o agendamento. Revise esta tarefa antes de tentar novamente.")
                        self.liberar_gpu()
                        cmd = comando(self.c, etapa, task["parametros"])
                        self.store.atualizar(ident, comando=cmd)
                        env = os.environ.copy()
                        env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
                        kwargs = {"cwd": str(self.c.raiz), "env": env, "stdout": subprocess.PIPE,
                            "stderr": subprocess.STDOUT, "text": True, "encoding": "utf-8", "errors": "replace", "bufsize": 1}
                        if os.name == "nt":
                            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                        else:
                            kwargs["start_new_session"] = True
                        proc = subprocess.Popen(cmd, **kwargs)
                        self.store.atualizar(ident, pid=proc.pid)
                        try:
                            for linha in proc.stdout:
                                log.write(linha)
                                self.progresso(ident, etapa, linha)
                        finally:
                            proc.stdout.close()
                        codigo = proc.wait()
                        self.store.atualizar(ident, codigo=codigo, pid=None)
                        exigir(codigo == 0, f"O script encerrou com código {codigo}. Consulte o log.")
                        estados = self.catalogo.refresh(True)
                        exigir(estados[etapa]["estado"] == "concluido", "Saída não aprovada: " + estados[etapa]["motivo"])
                    self.store.atualizar(ident, resultado={"ok": True, "relatorio": self.catalogo.estados[etapa].get("relatorio")})
                self.store.atualizar(ident, estado="concluido", fim=agora(), erro=None)
                log.write(agora() + " · Tarefa concluída.\n")
        except Exception as e:
            vivo = proc is not None and proc.poll() is None
            if vivo:
                self.store.set("pausado", True)
            if etapa == "fluxo":
                self.store.set("pausado", True)
            self.store.atualizar(ident, estado="recuperacao" if vivo else "falhou", fim=agora(),
                erro=type(e).__name__ + ": " + str(e), pid=proc.pid if vivo else None)
            with log_path.open("a", encoding="utf-8") as log:
                log.write("ERRO: " + type(e).__name__ + ": " + str(e) + "\n")
            if etapa == "prever":
                self.store.atualizar(ident, parametros={"sequencia_removida": True})
                self.liberar_gpu()
            self.store.evento(NOMES.get(etapa, "Consulta") + " falhou: " + str(e))
        finally:
            self.ativo = None

    def progresso(self, ident, etapa, linha):
        valor = None
        if etapa == "fluxo":
            atual = self.store.tarefa(ident)["progresso"] or {}
            if linha.startswith("TCC_EVENT:"):
                evento = json.loads(linha[len("TCC_EVENT:"):])
                valor = {"fase": evento["fase"], "nome": evento["nome"], "estado_fase": evento["estado"],
                    "atual": evento["numero"], "total": evento["total_fases"], "unidade": "etapas"}
                if atual.get("historico_parcial"):
                    valor["historico_parcial"] = atual["historico_parcial"]
                self.store.atualizar(ident, progresso=valor)
            else:
                fase = atual.get("fase")
                m = re.search(r"(?:Entrada: |total confirmado )(\d+)(?:/(\d+))?", linha)
                e = re.search(r"Epoca (\d+)/(\d+):", linha)
                if m or e:
                    r = e or m
                    atual["detalhe"] = r[1] + ("/"+r[2] if r[2] else "") + (" épocas" if e else " proteínas")
                    metricas = re.search(r"Epoca (\d+)/(\d+): perda treino ([0-9]+(?:\.[0-9]+)?); acuracia balanceada validacao ([0-9]+(?:\.[0-9]+)?); F1 macro ([0-9]+(?:\.[0-9]+)?)", linha)
                    if metricas:
                        hist = atual.setdefault("historico_parcial", [])
                        hist.append({"epoca": int(metricas[1]), "perda_treino_ponderada": float(metricas[3]),
                            "acuracia_balanceada_validacao": float(metricas[4]), "f1_macro_validacao": float(metricas[5])})
                        atual["historico_parcial"] = hist[-100:]
                    self.store.atualizar(ident, progresso=atual)
            return
        if etapa == "embeddings":
            m = re.search(r"total confirmado (\d+)", linha)
            if m:
                valor = {"atual": int(m[1]), "total": self.c.esperado, "unidade": "vetores confirmados"}
        elif etapa in ("auditoria", "consolidar", "separar"):
            m = re.search(r"(\d+)/(\d+) (?:proteinas|lotes)", linha)
            if m:
                valor = {"atual": int(m[1]), "total": int(m[2]), "unidade": "proteínas" if "proteinas" in m[0] else "lotes"}
        elif etapa == "treinar":
            m = re.search(r"Epoca (\d+)/(\d+):", linha)
            if m:
                valor = {"atual": int(m[1]), "total": int(m[2]), "unidade": "épocas"}
        if valor:
            self.store.atualizar(ident, progresso=valor)
        if etapa == "agrupar" and linha.strip().startswith("Log detalhado:"):
            path = Path(linha.split(":", 1)[1].strip()).resolve()
            if path.is_relative_to(self.c.caminhos["grupos"].parent) and path.name == "mmseqs.log":
                self.store.atualizar(ident, log_extra=str(path))

    def cancelar(self, ident):
        with self.store.db() as db:
            r = db.execute("SELECT estado FROM tarefas WHERE id=?", (ident,)).fetchone()
            exigir(r and r[0] == "pendente", "Só é possível cancelar uma tarefa que ainda está na fila.")
            db.execute("UPDATE tarefas SET estado='cancelado',fim=?,parametros='{}' WHERE id=?", (agora(), ident))

    def recuperar(self, ident):
        with self.trava_planejar:
            t = self.store.tarefa(ident)
            exigir(t and t["estado"] == "recuperacao", "Tarefa não precisa de conciliação.")
            exigir(not pid_ativo(t["pid"]), "O processo anterior ainda parece ativo. Aguarde seu encerramento; a fila permanece pausada.")
            if t["etapa"] == "fluxo":
                try:
                    row, _ = self.execucoes.obter(t["parametros"]["execucao"])
                    path = Path(row["pasta"]) / "banco.sqlite3"
                except OSError:
                    # A pasta da execução foi removida: não há subprocesso nem saída a conferir.
                    path = None
                if path and path.is_file():
                    with sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=2) as db:
                        exigir(not any(pid_ativo(r[0]) for r in db.execute("SELECT pid FROM etapas WHERE pid IS NOT NULL")), "Um subprocesso da execução ainda está ativo.")
            completo = t["etapa"] in ETAPAS and self.catalogo.refresh(True)[t["etapa"]]["estado"] == "concluido"
            if t["etapa"] == "agrupar" and not completo:
                cmd = ["pgrep", "-x", "mmseqs"]
                if os.name == "nt":
                    cmd = ["wsl.exe", "--distribution", self.c.valores["wsl"], "--exec", *cmd]
                try:
                    p = subprocess.run(cmd, capture_output=True, timeout=10)
                    exigir(p.returncode == 1, "MMseqs2 pode continuar ativo ou sua situação não pôde ser conferida. Confira o WSL antes de conciliar.")
                except (OSError, subprocess.TimeoutExpired) as e:
                    raise ValueError("Não foi possível verificar os processos MMseqs2. Confira o WSL antes de conciliar.") from e
            self.store.atualizar(ident, estado="concluido" if completo else "interrompido", fim=agora(), pid=None,
                erro=None if completo else "Saída incompleta. Confira o log e solicite uma nova tentativa.",
                parametros={} if t["etapa"] == "prever" else t["parametros"])
            self.store.evento("Tarefa " + str(ident) + " conciliada. A fila continua pausada até você retomá-la.")

    def controles(self, automatico=None, pausado=None, threads_mmseqs=None):
        if automatico is not None:
            exigir(type(automatico) is bool, "automatico deve ser booleano.")
        if pausado is not None:
            exigir(type(pausado) is bool, "pausado deve ser booleano.")
            exigir(pausado or not any(t["estado"] == "recuperacao" for t in self.store.tarefas()), "Concilie a execução anterior antes de retomar.")
        if threads_mmseqs is not None:
            exigir(type(threads_mmseqs) is int and 1 <= threads_mmseqs <= 12, "Use de 1 a 12 threads para MMseqs2.")
        with self.store.db() as db:
            for chave, valor in (("automatico", automatico), ("pausado", pausado), ("threads_mmseqs", threads_mmseqs)):
                if valor is not None:
                    self.store._set(db, chave, valor)
        self.acordar.set()

    def estado(self, execucao=None):
        selecionada = execucao or self.store.get("execucao_selecionada", "original")
        if not execucao and selecionada != "original":
            try:
                self.execucoes.obter(selecionada)
            except (ValueError, OSError):
                # A pasta da execução salva foi removida: volta para a base original em vez de travar o painel.
                selecionada = "original"
                self.store.set("execucao_selecionada", selecionada)
        cat, config = self.catalogo_execucao(selecionada)
        etapas = cat.refresh()
        tarefas = self.store.tarefas()
        expostas = []
        for tarefa in tarefas:
            x = dict(tarefa)
            x["parametros"] = {k: v for k, v in (x["parametros"] or {}).items() if k != "sequencia"}
            x["nome"] = "Fluxo completo" if x["etapa"] == "fluxo" else NOMES.get(x["etapa"], "Consulta de proteína")
            expostas.append(x)
        rels = cat.relatorios
        treinado = rels.get("treinar", {}) if etapas["treinar"]["estado"] == "concluido" else {}
        base = rels.get("consolidar", {}) if etapas["consolidar"]["estado"] == "concluido" else {}
        part = rels.get("separar", {}) if etapas["separar"]["estado"] == "concluido" else {}
        portatil = False
        if not treinado and selecionada == "original":
            treinado = modelo_portatil(config) or {}
            portatil = bool(treinado)
            if portatil and not part:
                part = {"particoes": treinado.get("proveniencia", {}).get("distribuicao_particoes", {})}
        geracao = rels.get("embeddings", {})
        return {"ok": True, "versao": "2.0.0", "nome": config.valores["nome"], "projeto": str(self.c.raiz),
            "execucao_selecionada": selecionada, "execucoes": self.execucoes.lista(),
            "fluxo": self.execucoes.status(selecionada) if selecionada != "original" else None,
            "esperado": config.esperado, "automatico": self.store.get("automatico"), "pausado": self.store.get("pausado"),
            "threads_mmseqs": self.store.get("threads_mmseqs", self.c.valores["threads_mmseqs"]),
            "threads_pytorch": self.c.valores["threads_pytorch"], "dispositivo": self.c.valores.get("dispositivo", "auto"), "ativo": self.ativo,
            "gpu_modelo_carregado": self.servico is not None,
            "espaco_livre_gib": round(shutil.disk_usage(self.c.raiz).free / 1024**3, 2),
            "etapas": [{"id": e, "nome": NOMES[e], **etapas[e], "dependencia": cat.bloqueio(e) if etapas[e]["estado"] != "concluido" else None} for e in ETAPAS],
            "resumo": {"vetores": base.get("proteinas", geracao.get("embeddings_total")), "dimensao": 320,
                "rotulos": base.get("rotulos", geracao.get("rotulos_vetores_unicos", {})),
                "grupos": rels.get("agrupar", {}).get("grupos") if etapas["agrupar"]["estado"] == "concluido" else None,
                "base_inteira": geracao.get("base_completa"), "particoes": part.get("particoes", {}),
                "teste": treinado.get("teste_mlp", {}), "baseline": treinado.get("teste_baseline_classe_mais_frequente", {}),
                "regra": treinado.get("teste_regra_direta", {}), "historico": treinado.get("historico", []),
                "gpu_treino": treinado.get("gpu"), "melhor_epoca": treinado.get("melhor_epoca")},
            "tarefas": expostas, "consulta_disponivel": bool(treinado), "modo_portatil": portatil,
            "limite_rotulos": "Completa/Incompleta indica a presença literal de HILKMFTWV. Não mede digestibilidade, qualidade nutricional ou função biológica."}

    def encerrar(self):
        anterior = self.store.get("pausado", False)
        self.store.set("pausado", True)
        self.parar.set()
        self.acordar.set()
        if self.thread:
            # A tarefa ativa termina normalmente; etapas científicas não recebem kill.
            self.thread.join()
        if not any(t["estado"] == "recuperacao" for t in self.store.tarefas()):
            self.store.set("pausado", anterior)
