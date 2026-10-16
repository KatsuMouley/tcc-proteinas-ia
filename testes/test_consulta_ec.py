"""Testes sinteticos de rotulagem e protocolo HTTP; nunca fazem consultas reais."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

RAIZ = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("consulta_ec_testada", RAIZ / "etapas/consultar_sondagem_ec.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def entrada(seq="AMKT", ec="2.7.1.1", revisado=True, acc="P00001"):
    return {"entryType": p.REVISADO if revisado else p.NAO_REVISADO,
            "primaryAccession": acc, "sequence": {"value": seq, "length": len(seq)},
            "proteinDescription": {"recommendedName": {"ecNumbers": [] if ec is None else [
                {"value": ec, "evidences": [{"evidenceCode": "ECO:0000269", "source": "PubMed", "id": "1"}]}]}}}


def linha(i=0, seq="AMKT", particao="treino"):
    return {"indice_global": str(i), "uid": f"p{i:09d}", "id_original": f"CAA{i:07d}.1",
            "grupo_global": f"p{i:09d}", "particao": particao, "tamanho": str(len(seq)),
            "sha256_sequencia": hashlib.sha256(seq.encode()).hexdigest(), "arquivo_origem": "sintetico.fsa_aa.gz"}


def mapeamento(x, e, modo="id_com_versao"):
    consultado = x["id_original"] if modo == "id_com_versao" else p.sem_versao(x["id_original"])
    return {"id_original": x["id_original"], "id_consultado": consultado,
            "id_retornado": consultado, "namespace": p.namespace(x["id_original"]),
            "modo": modo, "job_id": "job1", "entrada": e}


class Sondagem:
    def __init__(self, pasta):
        self.pasta = pasta
        self.linhas = [linha(0), linha(1, seq="VIGK", particao="validacao")]
        self.gravar()

    def gravar(self):
        with (self.pasta / "candidatos.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=p.COLUNAS, delimiter=";")
            w.writeheader()
            w.writerows(self.linhas)
        ids = list(dict.fromkeys(x["id_original"] for x in self.linhas))
        (self.pasta / "ids_ncbi.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
        r = {"ok": True, "tipo": "preparacao_sondagem_ec2_ec3", "schema": 1,
             "modelo_embeddings": p.MODELO, "revisao_embeddings": p.REVISAO,
             "selecionados": len(self.linhas), "ids_originais_unicos": len(ids),
             "grupos_distintos_selecionados": len({x["grupo_global"] for x in self.linhas}),
             "selecionados_por_particao": {n: sum(x["particao"] == n for x in self.linhas)
                                           for n in ("treino", "validacao", "teste")},
             "sha256_candidatos_csv": p.sha(self.pasta / "candidatos.csv")}
        (self.pasta / "relatorio_preparacao.json").write_text(json.dumps(r), encoding="utf-8")


class ClienteFake:
    def __init__(self, pasta, **kwargs):
        self.metadados = [{"headers": {"x-uniprot-release": "SINTETICO"}}]
        self.chamadas = []
        self.sugestoes = []
        self.resumos_jobs = []

    def mapear(self, origem, ids, modo):
        self.chamadas.append((origem, ids, modo))
        return []


class TestRotulagemEC(unittest.TestCase):
    def test_aceita_ec2_ec3_so_com_hash_e_comprimento_exatos(self):
        a, b = linha(), linha(1, "VIGK", "validacao")
        ds, _ = p.avaliar([a, b], [mapeamento(a, entrada()), mapeamento(b, entrada("VIGK", "3.1.1.1"))])
        self.assertEqual([x["rotulo_ec"] for x in ds], ["Transferase", "Hidrolase"])
        self.assertEqual([x["particao"] for x in ds], ["treino", "validacao"])

    def test_unreviewed_nunca_e_confundido_com_reviewed(self):
        a = linha()
        ds, _ = p.avaliar([a], [mapeamento(a, entrada(revisado=False))])
        self.assertEqual(ds[0]["status_ec"], "apenas_nao_revisado")
        self.assertEqual(ds[0]["rotulo_ec"], "")

    def test_mesmo_tamanho_com_hash_diferente_exclui_rotulo(self):
        a = linha()
        ds, _ = p.avaliar([a], [mapeamento(a, entrada("AMKA"))])
        self.assertEqual(ds[0]["status_ec"], "sequencia_divergente")

    def test_sem_anotacao_e_ec_fora_do_alvo_nao_viram_classes(self):
        for ec, status in ((None, "revisado_exato_sem_ec"), ("1.1.1.1", "ec_fora_do_alvo"),
                           ("2.7", "ec_nao_interpretavel")):
            with self.subTest(ec=ec):
                a = linha()
                ds, _ = p.avaliar([a], [mapeamento(a, entrada(ec=ec))])
                self.assertEqual(ds[0]["status_ec"], status)
                self.assertEqual(ds[0]["rotulo_ec"], "")

    def test_ec_de_atividade_catalitica_e_ec_parcial_preservam_evidencia(self):
        a, e = linha(), entrada(ec=None)
        e["comments"] = [{"commentType": "CATALYTIC ACTIVITY", "reaction": {
            "ecNumber": "2.7.1.-", "evidences": [{"evidenceCode": "ECO:0000250"}]}}]
        ds, pares = p.avaliar([a], [mapeamento(a, e)])
        self.assertEqual(ds[0]["classe_ec"], "2")
        self.assertTrue(ds[0]["ec_parcial"])
        self.assertIn("ECO:0000250", pares[0]["evidencias_ec_json"])

    def test_multiplas_accessions_mesma_classe_geram_um_rotulo_por_candidato(self):
        a = linha()
        ds, pares = p.avaliar([a], [mapeamento(a, entrada()),
            mapeamento(a, entrada(ec="2.7.11.1", acc="P00002"))])
        self.assertEqual(len(ds), 1)
        self.assertEqual(len(pares), 2)
        self.assertEqual(ds[0]["uniprot_accessions"], "P00001|P00002")
        self.assertEqual(ds[0]["classe_ec"], "2")

    def test_conflito_ec2_ec3_e_multifuncao_com_outra_classe_sao_excluidos(self):
        for ec in ("3.1.1.1", "4.1.1.1"):
            with self.subTest(ec=ec):
                a = linha()
                ds, _ = p.avaliar([a], [mapeamento(a, entrada()),
                    mapeamento(a, entrada(ec=ec, acc="P00002"))])
                self.assertEqual(ds[0]["status_ec"], "multiclasse_ec_excluida")
                self.assertEqual(ds[0]["classe_ec"], "")

    def test_descricao_com_palavra_chave_nao_e_rotulo(self):
        a, e = linha(), entrada(ec=None)
        e["proteinDescription"]["recommendedName"]["fullName"] = {"value": "Transferase"}
        ds, _ = p.avaliar([a], [mapeamento(a, e)])
        self.assertEqual(ds[0]["status_ec"], "revisado_exato_sem_ec")

    def test_entrada_incompleta_ou_inconsistente_e_falha_tecnica(self):
        a = linha()
        for campo in ("sequence", "entryType"):
            with self.subTest(campo=campo):
                e = entrada()
                e.pop(campo)
                with self.assertRaises(ValueError):
                    p.avaliar([a], [mapeamento(a, e)])
        with self.assertRaisesRegex(ValueError, "mesma accession"):
            p.avaliar([a], [mapeamento(a, entrada()), mapeamento(a, entrada(ec="3.1.1.1"))])

    def test_rotulo_revisado_exato_pode_coexistir_com_sugestao_uniparc(self):
        a = linha()
        sugestao = {"id_original": a["id_original"], "uniparc_id": "UPI000011A03D"}
        ds, _ = p.avaliar([a], [mapeamento(a, entrada())], [sugestao])
        self.assertEqual(ds[0]["classe_ec"], "2")
        self.assertTrue(ds[0]["tem_sugestao_uniparc"])
        self.assertEqual(ds[0]["uniparc_sugeridos"], "UPI000011A03D")


class TestEntradaESaida(unittest.TestCase):
    def test_bloqueia_teste_hash_adulterado_grupo_cruzado_e_ids_trocados(self):
        for defeito in ("teste", "hash", "grupo", "ids"):
            with self.subTest(defeito=defeito), tempfile.TemporaryDirectory() as d:
                b = Sondagem(Path(d))
                if defeito == "teste":
                    b.linhas[0]["particao"] = "teste"
                    b.gravar()
                elif defeito == "grupo":
                    b.linhas[1]["grupo_global"] = b.linhas[0]["grupo_global"]
                    b.gravar()
                elif defeito == "hash":
                    with (b.pasta / "candidatos.csv").open("a") as f:
                        f.write("\n")
                else:
                    (b.pasta / "ids_ncbi.txt").write_text("ID_TROCADO\n")
                cliente = Mock()
                with self.assertRaises(ValueError):
                    p.consultar(b.pasta, cliente_factory=cliente)
                cliente.assert_not_called()
                self.assertEqual(list(b.pasta.glob("consulta_uniprot_*")), [])

    def test_rotulagem_completa_preserva_entradas_e_nao_abre_modelos_ou_vetores(self):
        with tempfile.TemporaryDirectory() as d:
            b = Sondagem(Path(d))
            antes = {x: x.read_bytes() for x in b.pasta.iterdir()}
            cli = ClienteFake(None)
            cli.mapear = Mock(return_value=[mapeamento(b.linhas[0], entrada()),
                mapeamento(b.linhas[1], entrada("VIGK", "3.1.1.1"))])
            r = p.consultar(b.pasta, cliente_factory=lambda *a, **k: cli, progresso=lambda t: None)
            self.assertTrue(r["ok"])
            self.assertEqual(r["resultados_ec2_ec3"], {"Transferase": 1, "Hidrolase": 1})
            self.assertEqual(r["por_particao"]["teste"]["candidatos"], 0)
            self.assertIsNone(r["enzimas_ec_descartadas_mais_512"])
            self.assertFalse(r["embeddings_lidos"] or r["treinamento_realizado"])
            self.assertEqual({x: x.read_bytes() for x in antes}, antes)
            for n, h in r["hashes_saidas"].items():
                self.assertEqual(p.sha(Path(r["pasta_saida"]) / n), h)

    def test_fallback_remove_versao_mas_exige_hash_original(self):
        with tempfile.TemporaryDirectory() as d:
            b = Sondagem(Path(d))
            cli = ClienteFake(None)
            cli.mapear = Mock(side_effect=[[], [mapeamento(b.linhas[0], entrada(), "accession_sem_versao"),
                mapeamento(b.linhas[1], entrada("AMKA", "3.1.1.1"), "accession_sem_versao")]])
            r = p.consultar(b.pasta, cliente_factory=lambda *a, **k: cli, progresso=lambda t: None)
            self.assertEqual(cli.mapear.call_args_list[1].args[1], ["CAA0000000", "CAA0000001"])
            self.assertEqual(r["resultados_ec2_ec3"], {"Transferase": 1, "Hidrolase": 0})
            self.assertEqual(r["contagens_por_status"]["sequencia_divergente"], 1)

    def test_falha_de_rede_deixa_relatorio_inconclusivo_nunca_zero(self):
        with tempfile.TemporaryDirectory() as d:
            b = Sondagem(Path(d))
            cli = ClienteFake(None)
            cli.mapear = Mock(side_effect=p.FalhaConsulta("HTTP 503"))
            with self.assertRaisesRegex(p.FalhaConsulta, "Nao interpretar"):
                p.consultar(b.pasta, cliente_factory=lambda *a, **k: cli)
            saida = next(b.pasta.glob("consulta_uniprot_*"))
            r = json.loads((saida / "relatorio_consulta.json").read_text())
            self.assertFalse(r["ok"])
            self.assertIsNone(r["resultados_ec2_ec3"])
            self.assertFalse((saida / "rotulos_ec_confirmados.csv").exists())

    def test_sugestoes_geram_csv_sem_rotulo_e_preservam_ids_apos_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            b = Sondagem(Path(d))
            cli = ClienteFake(None)

            def mapear(origem, ids, modo):
                for identificador in ids:
                    cli.sugestoes.append({"id_consultado": identificador, "id_retornado": identificador,
                        "namespace": origem, "modo": modo, "job_id": "job1",
                        "uniparc_id": "UPI000011A03D"})
                return []

            cli.mapear = mapear
            r = p.consultar(b.pasta, cliente_factory=lambda *a, **k: cli, progresso=lambda t: None)
            self.assertEqual(r["revisao_cliente"], 2)
            self.assertEqual(r["resultados_ec2_ec3"], {"Transferase": 0, "Hidrolase": 0})
            self.assertEqual(r["contagens_por_status"], {"sugestao_uniparc_sem_rotulo": 2})
            self.assertEqual(r["cobertura_contagens"]["mapeado_uniprot"], 0)
            self.assertEqual(r["cobertura_contagens"]["tem_sugestao_uniparc"], 2)
            with (Path(r["pasta_saida"]) / "sugestoes_uniparc.csv").open(
                    encoding="utf-8-sig", newline="") as f:
                ss = list(csv.DictReader(f, delimiter=";"))
            self.assertEqual(len(ss), 4)  # Dois candidatos, consulta com/sem versao.
            self.assertEqual({x["id_original"] for x in ss}, {x["id_original"] for x in b.linhas})
            self.assertTrue(all(x["rotulo_ec_atribuido_pela_sugestao"] == "False" for x in ss))
            self.assertEqual({x["particao"] for x in ss}, {"treino", "validacao"})
            with (Path(r["pasta_saida"]) / "rotulos_ec_confirmados.csv").open(
                    encoding="utf-8-sig", newline="") as f:
                self.assertEqual(list(csv.DictReader(f, delimiter=";")), [])

    def test_nova_execucao_preserva_a_consulta_anterior(self):
        with tempfile.TemporaryDirectory() as d:
            b = Sondagem(Path(d))
            a = p.consultar(b.pasta, cliente_factory=ClienteFake, progresso=lambda t: None)
            antes = {f: f.read_bytes() for f in Path(a["pasta_saida"]).rglob("*") if f.is_file()}
            c = p.consultar(b.pasta, cliente_factory=ClienteFake, progresso=lambda t: None)
            self.assertNotEqual(a["pasta_saida"], c["pasta_saida"])
            self.assertEqual({f: f.read_bytes() for f in antes}, antes)

    def test_cli_rejeita_timeout_invalido_antes_de_criar_saida(self):
        for valor in ("0", "-1", "nan", "inf"):
            with self.subTest(valor=valor), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                p.main(["--sondagem", "nao-existe", "--timeout", valor])


class Resposta:
    def __init__(self, corpo, url=p.API + "/exemplo", headers=None):
        self.corpo = json.dumps(corpo).encode()
        self.url, self.headers = url, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def read(self):
        return self.corpo


class TestProtocoloHTTP(unittest.TestCase):
    def test_fluxo_http_com_sugestoes_apos_redirect_nao_atribui_rotulo_ao_upi(self):
        with tempfile.TemporaryDirectory() as d:
            b = Sondagem(Path(d))
            a, z = [x["id_original"] for x in b.linhas]
            par = {"from": a, "to": entrada()}
            sugestao = {"from": z, "to": "UPI000011A03D"}
            completo = {"results": [par], "failedIds": [], "suggestedIds": [sugestao], "obsoleteCount": 0}
            sg2 = {"results": [], "failedIds": [], "obsoleteCount": 0,
                   "suggestedIds": [{"from": p.sem_versao(z), "to": "UPI000011A03D"}]}
            respostas = [
                Resposta({"jobId": "job1"}),
                Resposta(completo, url=p.API + "/idmapping/uniprotkb/results/job1"),
                Resposta({"redirectURL": p.API + "/idmapping/uniprotkb/results/job1"}),
                Resposta(completo, headers={"X-Total-Results": "1"}),
                Resposta({"jobId": "job2"}),
                Resposta(sg2, url=p.API + "/idmapping/uniprotkb/results/job2"),
                Resposta({"redirectURL": p.API + "/idmapping/uniprotkb/results/job2"}),
                Resposta(sg2, headers={"X-Total-Results": "0"})]
            opener = Mock()
            opener.open.side_effect = respostas
            with patch.object(p, "build_opener", return_value=opener):
                r = p.consultar(b.pasta, progresso=lambda t: None)
            self.assertTrue(r["ok"])
            self.assertEqual(r["resultados_ec2_ec3"], {"Transferase": 1, "Hidrolase": 0})
            self.assertEqual(r["contagens_por_status"]["sugestao_uniparc_sem_rotulo"], 1)
            self.assertEqual(r["resumos_jobs"][0]["ids_contabilizados"], 2)
            self.assertEqual(r["resumos_jobs"][1]["ids_contabilizados"], 1)
            self.assertEqual(r["cobertura_contagens"]["tem_sugestao_uniparc"], 1)

    def test_regressao_formato_real_176_resultados_15_falhos_309_sugestoes(self):
        # Contagens e estrutura observadas no PC; entradas e sequencias sinteticas.
        ids = [f"CAA{i:07d}.1" for i in range(500)]
        ids[191:194] = ["AAB48809.1", "AAC28158.1", "AAF87660.1"]
        resultados = [{"from": i, "to": entrada(acc=f"P{n:05d}")}
                      for n, i in enumerate(ids[:176])]
        sugestoes = [{"from": i, "to": f"UPI{n:012X}"}
                     for n, i in enumerate(ids[191:])]
        sugestoes[:3] = [
            {"from": "AAB48809.1", "to": "UPI000011A03D"},
            {"from": "AAC28158.1", "to": "UPI0000080825"},
            {"from": "AAF87660.1", "to": "UPI000011854B"}]
        status = {"results": resultados[:25], "failedIds": ids[176:191],
                  "suggestedIds": sugestoes, "obsoleteCount": 0}
        pagina = {**status, "results": resultados}
        with tempfile.TemporaryDirectory() as d:
            c = p.ClienteUniProt(Path(d), progresso=lambda t: None)
            c.pedir = Mock(side_effect=[({"jobId": "job1"}, {}), (status, {}),
                ({"redirectURL": p.API + "/idmapping/uniprotkb/results/job1"}, {}),
                (pagina, {"x-total-results": "176"})])
            ms = c.mapear("EMBL-GenBank-DDBJ_CDS", ids, "id_com_versao")
            self.assertEqual(len(ms), 176)
            self.assertEqual(len(c.sugestoes), 309)  # Repetidas em status e pagina: deduplicar.
            self.assertEqual(c.sugestoes[0]["uniparc_id"], "UPI000011A03D")
            self.assertEqual(c.resumos_jobs[0]["ids_mapeados_uniprotkb"], 176)
            self.assertEqual(c.resumos_jobs[0]["ids_failedIds"], 15)
            self.assertEqual(c.resumos_jobs[0]["ids_com_sugestao_uniparc"], 309)
            self.assertEqual(c.resumos_jobs[0]["ids_contabilizados"], 500)

    def test_fluxo_http_ate_csv_com_fallback_e_sem_alterar_entradas(self):
        with tempfile.TemporaryDirectory() as d:
            b = Sondagem(Path(d))
            a, z = [x["id_original"] for x in b.linhas]
            respostas = [
                Resposta({"jobId": "job1"}),
                Resposta({"jobStatus": "FINISHED"}),
                Resposta({"redirectURL": p.API + "/idmapping/uniprotkb/results/job1"}),
                Resposta({"results": [{"from": a, "to": entrada()}], "failedIds": [z]},
                         headers={"X-Total-Results": "1", "X-UniProt-Release": "SINTETICO"}),
                Resposta({"jobId": "job2"}),
                Resposta({"jobStatus": "FINISHED"}),
                Resposta({"redirectURL": p.API + "/idmapping/uniprotkb/results/job2"}),
                Resposta({"results": [{"from": p.sem_versao(z),
                                       "to": entrada("VIGK", "3.1.1.1", acc="P00002")}]},
                         headers={"X-Total-Results": "1", "X-UniProt-Release": "SINTETICO"})]
            opener = Mock()
            opener.open.side_effect = respostas
            antes = {x: x.read_bytes() for x in b.pasta.iterdir()}
            with patch.object(p, "build_opener", return_value=opener):
                r = p.consultar(b.pasta, progresso=lambda t: None)
            self.assertEqual(r["resultados_ec2_ec3"], {"Transferase": 1, "Hidrolase": 1})
            self.assertEqual(r["uniprot_releases"], ["SINTETICO"])
            self.assertEqual(len(r["respostas_http"]), 8)
            self.assertEqual({x: x.read_bytes() for x in antes}, antes)
            with (Path(r["pasta_saida"]) / "rotulos_ec_confirmados.csv").open(
                    encoding="utf-8-sig", newline="") as f:
                rotulos = list(csv.DictReader(f, delimiter=";"))
            self.assertEqual([x["id_original"] for x in rotulos], [a, z])
            self.assertEqual([x["classe_ec"] for x in rotulos], ["2", "3"])

    def test_paginacao_status_finished_e_namespace_correto(self):
        with tempfile.TemporaryDirectory() as d, patch.object(p.time, "sleep"):
            c = p.ClienteUniProt(Path(d), timeout=19)
            ids = ["CAA0000000.1", "CAA0000001.1"]
            c.pedir = Mock(side_effect=[({"jobId": "job1"}, {}), ({"jobStatus": "RUNNING"}, {}),
                ({"jobStatus": "FINISHED"}, {}), ({"redirectURL": p.API + "/idmapping/uniprotkb/results/job1"}, {}),
                ({"results": [{"from": ids[0], "to": entrada()}]}, {"x-total-results": "2", "link":
                    '<https://rest.uniprot.org/idmapping/uniprotkb/results/job1?cursor=abc>; rel="next"'}),
                ({"results": [{"from": ids[1], "to": entrada("VIGK", "3.1.1.1", acc="P00002")}]},
                    {"x-total-results": "2"})])
            ms = c.mapear("EMBL-GenBank-DDBJ_CDS", ids, "id_com_versao")
            self.assertEqual(len(ms), 2)
            self.assertEqual(c.pedir.call_args_list[0].args[1], {
                "from": "EMBL-GenBank-DDBJ_CDS", "to": "UniProtKB", "ids": ",".join(ids)})
            self.assertIn("size=500", c.pedir.call_args_list[4].args[0])

    def job_com_resposta(self, ids, pagina, headers=None, status=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        c = p.ClienteUniProt(Path(temp.name), progresso=lambda t: None)
        c.pedir = Mock(side_effect=[({"jobId": "job1"}, {}),
            (status or {"jobStatus": "FINISHED"}, {}),
            ({"redirectURL": p.API + "/idmapping/uniprotkb/results/job1"}, {}),
            (pagina, headers or {})])
        return c.mapear("EMBL-GenBank-DDBJ_CDS", ids, "id_com_versao")

    def test_zero_so_e_valido_quando_api_explica_todos_os_ids(self):
        ids = ["CAA0000000.1", "CAA0000001.1"]
        self.assertEqual(self.job_com_resposta(ids, {"failedIds": ids}), [])
        with tempfile.TemporaryDirectory() as d:
            c = p.ClienteUniProt(Path(d), progresso=lambda t: None)
            c.pedir = Mock(side_effect=[({"jobId": "job1"}, {}),
                                       ({"results": [], "failedIds": ids}, {})])
            self.assertEqual(c.mapear("EMBL-GenBank-DDBJ_CDS", ids, "id_com_versao"), [])
            self.assertEqual(c.pedir.call_count, 2)
        for pagina in ({}, {"results": []}, {"failedIds": ids[:1]}):
            with self.subTest(pagina=pagina), self.assertRaises(ValueError):
                self.job_com_resposta(ids, pagina)

    def test_falha_se_paginacao_trunca_ou_id_nao_foi_solicitado(self):
        for origem, total in (("CAA0000000.1", "2"), ("AAA9999999.1", "1")):
            with self.subTest(origem=origem), self.assertRaises(ValueError):
                self.job_com_resposta(["CAA0000000.1"], {
                    "results": [{"from": origem, "to": entrada()}]}, {"x-total-results": total})

    def test_sugestao_com_formato_inesperado_bloqueia(self):
        for sugestao in ("UPI000011A03D", {"from": "CAA0000000.1"},
                         {"from": "CAA0000000.1", "to": "P00001"}):
            with self.subTest(sugestao=sugestao), self.assertRaises(ValueError):
                self.job_com_resposta(["CAA0000000.1"], {"suggestedIds": [sugestao]})

    def test_sugestao_de_id_nao_solicitado_bloqueia_mesmo_com_mapeamento_completo(self):
        with self.assertRaisesRegex(ValueError, "nao solicitado"):
            self.job_com_resposta(["CAA0000000.1"], {
                "results": [{"from": "CAA0000000.1", "to": entrada()}],
                "suggestedIds": [{"from": "AAA9999999.1", "to": "UPI000011A03D"}]})

    def test_sugestao_duplicada_nao_oculta_id_ausente(self):
        sg = {"from": "CAA0000000.1", "to": "UPI000011A03D"}
        with self.assertRaisesRegex(ValueError, "restantes=1"):
            self.job_com_resposta(["CAA0000000.1", "CAA0000001.1"], {"suggestedIds": [sg, sg]})

    def test_from_sem_versao_preserva_id_solicitado(self):
        ms = self.job_com_resposta(["CAA0000000.1"], {
            "results": [{"from": "CAA0000000", "to": entrada()}]})
        self.assertEqual(ms[0]["id_consultado"], "CAA0000000.1")
        self.assertEqual(ms[0]["id_retornado"], "CAA0000000")

    def test_to_so_com_accession_busca_entrada_completa(self):
        with tempfile.TemporaryDirectory() as d:
            c = p.ClienteUniProt(Path(d), progresso=lambda t: None)
            c.pedir = Mock(side_effect=[({"jobId": "job1"}, {}), ({"jobStatus": "FINISHED"}, {}),
                ({"redirectURL": p.API + "/idmapping/results/job1"}, {}),
                ({"results": [{"from": "CAA0000000.1", "to": "P00001"}]}, {}), (entrada(), {})])
            ms = c.mapear("EMBL-GenBank-DDBJ_CDS", ["CAA0000000.1"], "id_com_versao")
            self.assertEqual(ms[0]["entrada"]["primaryAccession"], "P00001")
            self.assertEqual(c.pedir.call_args.args[0], p.API + "/uniprotkb/P00001.json")

    def test_timeout_e_repassado_resposta_bruta_e_preservada(self):
        with tempfile.TemporaryDirectory() as d:
            c = p.ClienteUniProt(Path(d), timeout=17)
            c.opener = Mock()
            c.opener.open.return_value = Resposta({"results": []}, headers={"X-UniProt-Release": "SINTETICO"})
            _, h = c.pedir(p.API + "/exemplo")
            self.assertEqual(c.opener.open.call_args.kwargs["timeout"], 17)
            self.assertEqual(h["x-uniprot-release"], "SINTETICO")
            meta = json.loads((Path(d) / "resposta_0001.json").read_text())
            self.assertEqual(p.sha(Path(d) / "resposta_0001.body.json"), meta["sha256_corpo_http"])

    def test_get_repetido_post_nao_repetido_e_falha_nao_vira_resultado(self):
        with tempfile.TemporaryDirectory() as d, patch.object(p.time, "sleep"):
            c = p.ClienteUniProt(Path(d), timeout=9, progresso=lambda t: None)
            c.opener = Mock()
            c.opener.open.side_effect = [HTTPError(p.API + "/exemplo", 503, "indisponivel", {}, None),
                                         Resposta({"results": []})]
            c.pedir(p.API + "/exemplo")
            self.assertEqual(c.opener.open.call_count, 2)
            c.opener.open.reset_mock()
            c.opener.open.side_effect = URLError("offline")
            with self.assertRaisesRegex(p.FalhaConsulta, "Cobertura EC nao concluida"):
                c.pedir(p.API + "/idmapping/run", {"ids": "CAA0000000.1"})
            self.assertEqual(c.opener.open.call_count, 1)

    def test_recusa_redirecionamento_fora_da_api(self):
        for url in ("http://rest.uniprot.org/a", "https://outro.example/a",
                    "https://rest.uniprot.org@outro.example/a"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                p.url_segura(url)

    def test_job_running_respeita_limite_de_espera(self):
        with tempfile.TemporaryDirectory() as d, patch.object(p.time, "monotonic", side_effect=[0, 20]):
            c = p.ClienteUniProt(Path(d), espera_maxima=10, progresso=lambda t: None)
            c.pedir = Mock(side_effect=[({"jobId": "job1"}, {}), ({"jobStatus": "RUNNING"}, {})])
            with self.assertRaisesRegex(p.FalhaConsulta, "nao terminou em 10s"):
                c.mapear("EMBL-GenBank-DDBJ_CDS", ["CAA0000000.1"], "id_com_versao")


if __name__ == "__main__":
    unittest.main()
