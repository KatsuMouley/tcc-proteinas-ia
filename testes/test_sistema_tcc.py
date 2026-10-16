"""Testes do controlador com bases pequenas e inferência simulada.

Não executam treinamento, ESM-2, CUDA ou MMseqs2 reais.
As verificações dos argumentos usam os parsers dos scripts existentes.
"""
import argparse
import ast
import copy
import http.client
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest

from sistema_tcc.core import (ARQUIVOS, Catalogo, Config, ETAPAS, Executor, MODELO_ESM,
    PASTAS, REVISAO_ESM, SCRIPTS, Store, comando, conferir_npy, regra_direta, serial, sha, validar_sequencia)
from sistema_tcc.web import pagina_log, servidor

ORIGEM = Path(__file__).resolve().parents[1]


def salvar(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def npy(path, shape, dtype):
    path.parent.mkdir(parents=True, exist_ok=True)
    cab = repr({"descr": "<" + dtype, "fortran_order": False, "shape": tuple(shape)})
    cab += " " * ((64 - (10 + len(cab) + 1) % 64) % 64) + "\n"
    n = 1
    for x in shape:
        n *= x
    path.write_bytes(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(cab)) + cab.encode("latin1") + b"\0" * (n * int(dtype[1:])))


class BaseTeste:
    def __init__(self, root, ate="treinar"):
        self.root = root
        conf = json.loads((ORIGEM / "sistema_tcc/config.json").read_text())
        conf["esperado"] = 6
        conf["intervalo_segundos"] = 2
        salvar(root / "sistema_tcc/config.json", conf)
        self.c = Config.carregar(root)
        self.p = self.c.caminhos
        (root / "etapas").mkdir()
        for name in set(SCRIPTS.values()):
            (root / "etapas" / name).write_text("raise SystemExit('Nenhuma etapa científica real neste teste')\n")
        (root / "piloto_esm_gpu.py").write_text("# Fixture\n")
        for p in self.p["fontes"]:
            p.mkdir()
        self.rels = {}
        self.paths = {}
        for k in ETAPAS:
            self.p[PASTAS[k]].mkdir(parents=True, exist_ok=True)
        self.audit = self.p["auditorias"] / "auditoria_fixture/relatorio.json"
        gen = {"tipo": "embeddings_base_ncbi_em_lotes", "ok": True, "modelo": MODELO_ESM,
            "revisao": REVISAO_ESM, "max_residuos": 512, "embeddings_total": 6,
            "formato_total_embeddings": [6, 320], "rotulos_vetores_unicos": {"Completa": 3, "Incompleta": 3},
            "base_completa": False, "pares_pendentes": 2}
        salvar(self.p["embeddings"] / "fontes.json", [])
        self.add("embeddings", gen)
        audit = {"tipo": "auditoria_tecnica_embeddings", "ok": True, "esperado": 6, "erros_total": 0,
            "formato_total_observado": [6, 320], "base": str(self.p["embeddings"]),
            "totais_examinados": {"vetores": 6, "lotes": 1}, "rotulos_vetores": gen["rotulos_vetores_unicos"]}
        self.add("auditoria", audit)
        npy(self.p["base"] / "embeddings.npy", (6, 320), "f4")
        for name in ("indice.csv", "sequencias.fasta"):
            (self.p["base"] / name).write_text("Dados pequenos de teste\n")
        base = {"tipo": "base_ia_consolidada", "schema": 1, "ok": True, "modelo": MODELO_ESM,
            "revisao": REVISAO_ESM, "proteinas": 6, "formato_embeddings": [6, 320],
            "config_original": {"regra_aminoacidos": "HILKMFTWV"}, "base_original": str(self.p["embeddings"]),
            "relatorio_original_sha256": sha(self.paths["embeddings"]), "auditoria": str(self.audit),
            "auditoria_sha256": sha(self.audit), "rotulos": gen["rotulos_vetores_unicos"],
            "hashes_arquivos": {n: sha(self.p["base"] / n) for n in ("indice.csv", "sequencias.fasta", "embeddings.npy")}}
        self.add("consolidar", base)
        (self.p["grupos"] / "global_cluster.tsv").write_text("p000000000\tp000000000\n")
        group = {"tipo": "agrupamento_global_mmseqs2", "ok": True, "proteinas": 6, "grupos": 3,
            "base": str(self.p["base"]), "fasta_sha256": base["hashes_arquivos"]["sequencias.fasta"],
            "tsv_sha256": sha(self.p["grupos"] / "global_cluster.tsv"), "parametros": {
                "identidade_minima": 0.5, "cobertura_minima": 0.8, "cov_mode": 0, "cluster_mode": 1,
                "alignment_mode": 3, "kmer_per_seq": 80, "evalue": 0.001}}
        self.add("agrupar", group)
        (self.p["particoes"] / "particoes.csv").write_text("Partições de teste\n")
        npy(self.p["particoes"] / "grupos_por_linha.npy", (6,), "i8")
        for nome in ("treino", "validacao", "teste"):
            npy(self.p["particoes"] / (nome + "_indices.npy"), (2,), "i8")
        part = {"tipo": "particoes_por_grupos_globais", "ok": True, "proteinas": 6, "semente": 42,
            "grupos_compartilhados_entre_particoes": 0, "base_consolidada": str(self.p["base"]),
            "agrupamento": str(self.p["grupos"]), "tsv_sha256": group["tsv_sha256"],
            "particoes": {nome: {"proteinas": 2, "grupos": 1, "rotulos": {"Completa": 1, "Incompleta": 1}}
                for nome in ("treino", "validacao", "teste")}}
        self.add("separar", part)
        for nome in ("modelo.pt", "historico.csv", "predicoes_teste.csv", "configuracao.json"):
            (self.p["modelo"] / nome).write_text("Fixture, não um modelo de IA\n")
        train = {"tipo": "treino_classificador_regra_aa_esm2", "ok": True, "arquitetura": [320, 64, 2],
            "classes": ["Incompleta", "Completa"], "teste_mlp": {"proteinas": 2, "acuracia": 0.5,
                "acuracia_balanceada": 0.5, "f1_macro": 0.5}, "proveniencia": {
                "base": str(self.p["base"]), "particoes": str(self.p["particoes"]),
                "relatorio_consolidacao_sha256": sha(self.paths["consolidar"]),
                "relatorio_particoes_sha256": sha(self.paths["separar"])}}
        self.add("treinar", train)
        if ate != "treinar":
            for etapa in ETAPAS[ETAPAS.index(ate)+1:]:
                shutil.rmtree(self.p[PASTAS[etapa]])

    def add(self, etapa, rel):
        path = self.audit if etapa == "auditoria" else self.p[PASTAS[etapa]] / ARQUIVOS[etapa]
        salvar(path, rel)
        self.paths[etapa], self.rels[etapa] = path, rel


class SistemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = BaseTeste(self.root)
        self.store = Store(self.base.p["sistema"])
        self.cat = Catalogo(self.base.c, self.store)
        self.ex = Executor(self.base.c, self.store, self.cat)

    def tearDown(self):
        if self.ex.thread and self.ex.thread.is_alive():
            self.ex.encerrar()
        self.tmp.cleanup()

    def test_importa_seis_etapas_sem_reexecutar(self):
        self.assertTrue(all(x["estado"] == "concluido" for x in self.cat.refresh(True).values()))
        for _ in range(5):
            self.ex.planejar()
        self.assertEqual(len(self.store.tarefas()), 6)
        self.assertTrue(all(t["origem"] == "importado" and not t["comando"] for t in self.store.tarefas()))
        self.assertTrue(self.ex.agendar("treinar")["reutilizado"])

    def test_bloqueia_modificacao_de_artefato_importado(self):
        self.cat.refresh(True)
        with (self.base.p["base"] / "embeddings.npy").open("ab") as f:
            f.write(b"alterado")
        self.assertEqual(self.cat.refresh(True)["consolidar"]["estado"], "bloqueado")
        with self.assertRaises(ValueError):
            self.ex.agendar("separar")

    def test_mudanca_de_metadata_exige_revisao(self):
        self.cat.refresh(True)
        p = self.base.p["base"] / "indice.csv"
        p.write_text(p.read_text() + "outro registro\n")
        self.assertIn("mudou", self.cat.refresh(True)["consolidar"]["motivo"])

    def test_detecta_proveniencia_incompativel(self):
        rel = self.base.rels["treinar"]
        rel["proveniencia"]["relatorio_particoes_sha256"] = "incorreto"
        self.base.add("treinar", rel)
        self.assertEqual(self.cat.refresh(True)["treinar"]["estado"], "bloqueado")
        with self.assertRaises(ValueError):
            self.ex.prever("HILKMFTWV")

    def test_rejeita_saida_parcial_sem_sobrescrever(self):
        (self.base.p["modelo"] / "relatorio_treino.json").unlink()
        self.assertEqual(self.cat.refresh(True)["treinar"]["estado"], "bloqueado")
        with self.assertRaises(ValueError):
            self.ex.agendar("treinar")
        self.assertTrue((self.base.p["modelo"] / "modelo.pt").is_file())

    def test_regra_e_entrada_completa_incompleta(self):
        self.assertEqual(regra_direta(validar_sequencia(" hIlkMftwv "))["regra_direta"], "Completa")
        self.assertEqual(regra_direta("ACDE")["regra_direta"], "Incompleta")
        for seq in ("", "A" * 513, "H I", ">fasta\nA", "Ａ", 5):
            with self.assertRaises(ValueError):
                validar_sequencia(seq)

    def test_pausa_preserva_solicitacao(self):
        self.cat.refresh(True)
        self.ex.controles(pausado=True)
        task = self.ex.prever("HILKMFTWV")
        self.assertIsNone(self.store.proxima())
        self.assertEqual(self.store.tarefa(task["id"])["estado"], "pendente")
        self.ex.controles(pausado=False)
        self.assertEqual(self.store.proxima()["id"], task["id"])

    def test_controle_invalido_nao_aplica_parcialmente(self):
        self.ex.controles(automatico=True)
        with self.assertRaises(ValueError):
            self.ex.controles(automatico=False, threads_mmseqs=99)
        self.assertTrue(self.store.get("automatico"))

    def test_consultas_serializadas_e_modelo_reutilizado(self):
        contador = {"carregamentos": 0, "ativo": 0, "pico": 0}
        class Fake:
            def prever(_, seq):
                contador["ativo"] += 1
                contador["pico"] = max(contador["pico"], contador["ativo"])
                time.sleep(0.015)
                contador["ativo"] -= 1
                return {"ok": True, "residuos": len(seq), "regra_direta": "Completa",
                    "predicao_mlp": "Incompleta", "concorda_com_regra_direta": False,
                    "teste_simulado": True, "escores_softmax_nao_calibrados": {"Incompleta": 0.9, "Completa": 0.1}}
        def factory():
            contador["carregamentos"] += 1
            return Fake()
        self.ex.servico_factory = factory
        tarefas = [self.ex.prever("HILKMFTWV") for _ in range(3)]
        self.ex.start()
        fim = time.monotonic() + 5
        while time.monotonic() < fim and any(self.store.tarefa(t["id"])["estado"] != "concluido" for t in tarefas):
            time.sleep(0.02)
        self.assertTrue(all(self.store.tarefa(t["id"])["estado"] == "concluido" for t in tarefas))
        self.assertEqual(contador["pico"], 1)
        self.assertEqual(contador["carregamentos"], 1)
        self.assertNotIn("sequencia", self.store.tarefa(tarefas[0]["id"])["parametros"])
        self.assertFalse(self.store.tarefa(tarefas[0]["id"])["resultado"]["concorda_com_regra_direta"])

    def test_reinicio_exige_conciliacao(self):
        self.cat.refresh(True)
        t = self.ex.prever("HILKMFTWV")
        self.store.proxima()
        self.store.atualizar(t["id"], pid=None)
        novo = Store(self.base.p["sistema"])
        self.assertEqual(novo.tarefa(t["id"])["estado"], "recuperacao")
        self.assertTrue(novo.get("pausado"))
        ex = Executor(self.base.c, novo, self.cat)
        with self.assertRaises(ValueError):
            ex.controles(pausado=False)
        ex.recuperar(t["id"])
        self.assertEqual(novo.tarefa(t["id"])["estado"], "interrompido")
        ex.controles(pausado=False)

    def test_cancelar_so_antes_de_executar(self):
        self.cat.refresh(True)
        t = self.ex.prever("HILKMFTWV")
        self.ex.cancelar(t["id"])
        self.assertEqual(self.store.tarefa(t["id"])["estado"], "cancelado")
        with self.assertRaises(ValueError):
            self.ex.cancelar(t["id"])

    def test_paginas_de_log_limitadas_e_cursor(self):
        self.cat.refresh(True)
        t = self.ex.prever("HILKMFTWV")
        p = self.base.p["sistema"] / "logs/grande.log"
        p.write_text("A" * 70000)
        self.store.atualizar(t["id"], log=str(p))
        r = pagina_log(self.ex, t["id"], 0)
        self.assertEqual(len(r["texto"]), 65536)
        self.assertFalse(r["fim"])
        self.assertEqual(len(pagina_log(self.ex, t["id"], r["cursor"])["texto"]), 4464)

    def test_importado_nao_inventa_logs(self):
        self.cat.refresh(True)
        r = pagina_log(self.ex, self.store.tarefas()[0]["id"])
        self.assertEqual(r["texto"], "")
        self.assertIn("histórico", r["mensagem"])

    def test_config_rejeita_sobreposicao_e_fuga(self):
        for chave, valor in (("sistema", "dados/base_ia"), ("embeddings", "../../outra-pasta"), ("cache", "dados/base_ia/base_1m")):
            conf = copy.deepcopy(self.base.c.valores)
            conf["caminhos"][chave] = valor
            path = self.root / "config_invalida.json"
            salvar(path, conf)
            with self.assertRaises(ValueError):
                Config.carregar(self.root, path)

    def test_npy_incompleto_rejeitado(self):
        p = self.root / "incompleto.npy"
        npy(p, (2, 320), "f4")
        p.write_bytes(p.read_bytes()[:-4])
        with self.assertRaises(ValueError):
            conferir_npy(p, (2, 320), "f4")

    def test_http_protege_execucao_e_nao_serve_projeto(self):
        self.cat.refresh(True)
        server = servidor(self.ex, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host = f"127.0.0.1:{server.server_port}"
            def request(method, path, body=None, headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                conn.request(method, path, body, headers or {})
                r = conn.getresponse()
                data, status = r.read(), r.status
                conn.close()
                return status, data
            status, raw = request("GET", "/api/estado")
            self.assertEqual(status, 200)
            token = json.loads(raw)["token"]
            body = json.dumps({"etapa": "treinar"})
            headers = {"Content-Type": "application/json", "X-TCC-Token": token, "Origin": "http://" + host}
            self.assertEqual(request("POST", "/api/etapas", body, {"Content-Type": "application/json"})[0], 403)
            self.assertEqual(request("POST", "/api/etapas", body, {**headers, "Origin": "https://outro.site"})[0], 403)
            self.assertEqual(request("POST", "/api/etapas", body, headers)[0], 200)
            self.assertEqual(request("POST", "/api/etapas", '{"etapa":"auditoria","etapa":"treinar"}', headers)[0], 400)
            self.assertEqual(request("POST", "/api/etapas", json.dumps({"etapa": "comando.exe"}), headers)[0], 400)
            self.assertEqual(request("GET", "/../dados/modelos/modelo.pt")[0], 404)
            self.assertEqual(request("GET", "/", headers={"Host": "outro.site"})[0], 400)
            self.assertEqual(request("GET", "/")[0], 200)
            self.assertEqual(request("POST", "/api/encerrar", "{}", headers)[0], 202)
            self.assertTrue(self.ex.parar.is_set())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class AutomacaoTest(unittest.TestCase):
    def test_script_modificado_apos_agendamento_nao_executa(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseTeste(Path(d), ate="embeddings")
            store = Store(b.p["sistema"])
            cat = Catalogo(b.c, store)
            ex = Executor(b.c, store, cat)
            ex.agendar("auditoria")
            task = store.proxima()
            b.c.script("auditoria").write_text("print('Codigo novo, nao executar')\n")
            ex.executar(task)
            t = store.tarefa(task["id"])
            self.assertEqual(t["estado"], "falhou")
            self.assertIn("mudaram", t["erro"])
            self.assertIsNone(t["comando"])

    def test_encerramento_preserva_opcao_anterior_de_pausa(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseTeste(Path(d))
            store = Store(b.p["sistema"])
            ex = Executor(b.c, store, Catalogo(b.c, store))
            ex.controles(pausado=False)
            ex.encerrar()
            self.assertFalse(store.get("pausado"))
            ex.controles(pausado=True)
            ex.encerrar()
            self.assertTrue(store.get("pausado"))

    def test_subprocesso_sucesso_e_sem_treino_automatico(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseTeste(Path(d), ate="embeddings")
            script = b.c.script("auditoria")
            script.write_text('''import argparse,json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--base');p.add_argument('--esperado',type=int);p.add_argument('--saida')
a=p.parse_args()
s=Path(a.saida);s.mkdir(parents=True)
r={'tipo':'auditoria_tecnica_embeddings','ok':True,'esperado':a.esperado,'erros_total':0,
'base':str(Path(a.base).resolve()),'formato_total_observado':[a.esperado,320],
'totais_examinados':{'vetores':a.esperado},'rotulos_vetores':{'Completa':3,'Incompleta':3}}
(s/'relatorio.json').write_text(json.dumps(r))
print('Auditoria: 1/1 lotes; 6 linhas de vetores examinadas.',flush=True)
''')
            store = Store(b.p["sistema"])
            cat = Catalogo(b.c, store)
            ex = Executor(b.c, store, cat)
            ex.planejar()
            task = store.proxima()
            self.assertEqual(task["etapa"], "auditoria")
            ex.executar(task)
            self.assertEqual(store.tarefa(task["id"])["estado"], "concluido")
            self.assertIn("6 linhas", Path(store.tarefa(task["id"])["log"]).read_text())
            self.assertEqual(cat.refresh(True)["auditoria"]["estado"], "concluido")
            self.assertEqual(store.tarefa(task["id"])["progresso"]["atual"], 1)
            self.assertFalse(any(t["etapa"] == "treinar" for t in store.tarefas()))

    def test_subprocesso_falha_nao_entra_em_loop(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseTeste(Path(d), ate="embeddings")
            b.c.script("auditoria").write_text("print('Erro real de fixture',flush=True)\nraise SystemExit(7)\n")
            store = Store(b.p["sistema"])
            cat = Catalogo(b.c, store)
            ex = Executor(b.c, store, cat)
            ex.planejar()
            task = store.proxima()
            ex.executar(task)
            self.assertEqual(store.tarefa(task["id"])["codigo"], 7)
            self.assertEqual(store.tarefa(task["id"])["estado"], "falhou")
            for _ in range(5):
                ex.planejar()
            self.assertEqual(len([t for t in store.tarefas() if t["origem"] == "automatico"]), 1)
            ex.agendar("auditoria", repetir=True)
            self.assertEqual(len([t for t in store.tarefas() if t["etapa"] == "auditoria"]), 2)

    def test_requisicoes_concorrentes_deduplicadas(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseTeste(Path(d), ate="embeddings")
            store = Store(b.p["sistema"])
            ex = Executor(b.c, store, Catalogo(b.c, store))
            respostas = []
            ts = [threading.Thread(target=lambda: respostas.append(ex.agendar("auditoria"))) for _ in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(len({x["tarefa"]["id"] for x in respostas}), 1)

    def test_cli_gerado_aceito_pelos_parsers_originais(self):
        def caminho_script(nome):
            return ORIGEM / "etapas" / nome
        with tempfile.TemporaryDirectory() as d:
            b = BaseTeste(Path(d))
            parametros = {"threads_mmseqs": 8, "saida_auditoria": str(b.p["auditorias"] / "auditoria_nova"),
                "auditoria": str(b.audit)}
            for etapa in ETAPAS:
                with self.subTest(etapa=etapa):
                    path = caminho_script(SCRIPTS[etapa])
                    if not path.is_file():
                        self.fail("Script existente não encontrado para verificar seu contrato: " + str(path))
                    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                    f = copy.deepcopy(next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "main"))
                    parte = []
                    for node in f.body:
                        parte.append(node)
                        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == "args" for x in node.targets):
                            parte.append(ast.Return(value=ast.Name(id="args", ctx=ast.Load())))
                            break
                    f.body = parte
                    module = ast.fix_missing_locations(ast.Module(body=[f], type_ignores=[]))
                    scope = {"argparse": argparse, "sys": sys, "Path": Path, "__doc__": "Contrato original",
                        "PROJETO": b.root, "BASE": b.p["base"], "ORIGINAL": b.p["embeddings"],
                        "GRUPOS": b.p["grupos"], "PARTICOES": b.p["particoes"], "SAIDA": b.p["modelo"],
                        "consolidar": lambda x: x, "diagnosticar": lambda x: x, "agrupar": lambda x: x,
                        "separar": lambda x: x, "treinar": lambda x: x, "prever": lambda x: x}
                    exec(compile(module, str(path), "exec"), scope)
                    cmd = comando(b.c, etapa, parametros)
                    parsed = scope["main"](cmd[3:])
                    self.assertIsInstance(parsed, argparse.Namespace)


if __name__ == "__main__":
    unittest.main()
