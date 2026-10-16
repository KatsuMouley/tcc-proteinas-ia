"""Auditoria e coleta com respostas sinteticas: sem internet, GPU ou treino."""
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "etapas"))
spec = importlib.util.spec_from_file_location("coleta_swissprot_testada", RAIZ / "etapas/baixar_piloto_swissprot_ec.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def entrada(acc="P00001", seq="AMKT", ec="2.7.1.1", revisado=True):
    return {"primaryAccession": acc, "entryType": p.api.REVISADO if revisado else p.api.NAO_REVISADO,
        "sequence": {"value": seq, "length": len(seq)},
        "proteinDescription": {"recommendedName": {"fullName": {"value": "Nome sintetico"},
            "ecNumbers": [] if ec is None else [{"value": ec, "evidences": [{"evidenceCode": "ECO:0000250"}]}]}},
        "organism": {"scientificName": "Organismo sintetico", "taxonId": 1}}


def cliente_fake(classes, releases=("SINTETICO",)):
    c = Mock()
    c.metadados = [{"headers": {"x-uniprot-release": r}} for r in releases]
    c.pedir.side_effect = [({"results": classes[k]}, {"x-total-results": str(len(classes[k]))})
                          for k in ("2", "3")]
    return c


class TestAuditoria(unittest.TestCase):
    def test_rotulos_vem_do_ec_explicito_e_revisado(self):
        classes = {"2": [entrada()], "3": [entrada("P00002", "VIGK", "3.1.1.1")]}
        a, s = p.auditar_e_selecionar(classes, 10, 42)
        self.assertEqual({x["rotulo_ec"] for x in s}, {"Transferase", "Hidrolase"})
        self.assertEqual(len(a), 2)
        self.assertTrue(all(x["revisado"] for x in s))

    def test_sem_ec_ou_so_palavra_chave_nao_recebe_rotulo(self):
        e = entrada(ec=None)
        e["proteinDescription"]["recommendedName"]["fullName"]["value"] = "Transferase"
        a, s = p.auditar_e_selecionar({"2": [e], "3": []}, 1, 42)
        self.assertEqual(s, [])
        self.assertIn("sem_ec_explicito", a[0]["motivos_exclusao"])

    def test_nao_revisado_parcial_e_ec_fora_alvo(self):
        classes = {"2": [entrada(revisado=False), entrada("P00002", "AAAK", "2.7.1.-"),
                          entrada("P00003", "VIGK", "4.1.1.1")], "3": []}
        a, s = p.auditar_e_selecionar(classes, 3, 42)
        self.assertEqual([x["id_original"] for x in s], ["P00002"])
        self.assertTrue(s[0]["ec_parcial"])
        self.assertIn("ECO:0000250", s[0]["evidencias_ec_json"])
        self.assertIn("entrada_nao_revisada", a[0]["motivos_exclusao"])
        self.assertIn("ec_fora_do_alvo", a[2]["motivos_exclusao"])

    def test_ec_em_atividade_catalitica_e_considerado(self):
        e = entrada(ec=None)
        e["comments"] = [{"commentType": "CATALYTIC ACTIVITY", "reaction": {"ecNumber": "3.1.1.1"}}]
        _, s = p.auditar_e_selecionar({"2": [], "3": [e]}, 1, 42)
        self.assertEqual(s[0]["rotulo_ec"], "Hidrolase")

    def test_512_aceito_513_descartado_sem_cortar_sequencia(self):
        e = entrada(seq="A" * 512)
        f = entrada("P00002", "A" * 513)
        a, s = p.auditar_e_selecionar({"2": [e, f], "3": []}, 2, 42)
        self.assertEqual(len(s), 1)
        self.assertEqual(len(s[0]["sequencia"]), 512)
        self.assertEqual(a[1]["tamanho"], 513)
        self.assertEqual(a[1]["sequencia"], "A" * 513)
        self.assertIn("mais_de_512_residuos", a[1]["motivos_exclusao"])

    def test_alfabeto_compativel_e_caracteres_invalidos_auditados(self):
        a, s = p.auditar_e_selecionar({"2": [entrada(seq="ABXZUO"),
            entrada("P00002", "AMKT*")], "3": []}, 2, 42)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["sequencia"], "ABXZUO")
        self.assertIn("caracteres_nao_suportados", a[1]["motivos_exclusao"])

    def test_mesma_sequencia_mesma_classe_deduplicada_com_rastreabilidade(self):
        a, s = p.auditar_e_selecionar({"2": [entrada(), entrada("P00002")], "3": []}, 2, 42)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["id_original"], "P00001")
        self.assertEqual(s[0]["accessions_mesma_sequencia"], "P00001|P00002")
        self.assertIn("sequencia_duplicada", a[1]["motivos_exclusao"])

    def test_mesma_sequencia_classes_conflitantes_sao_excluidas(self):
        a, s = p.auditar_e_selecionar({"2": [entrada()],
            "3": [entrada("P00002", ec="3.1.1.1")]}, 2, 42)
        self.assertEqual(s, [])
        self.assertTrue(all("classes_conflitantes" in x["motivos_exclusao"] for x in a))

    def test_multiclasse_e_accession_repetida_em_consultas_nao_duplicam_contagem(self):
        e = entrada()
        e["proteinDescription"]["recommendedName"]["ecNumbers"].append({"value": "3.1.1.1"})
        a, s = p.auditar_e_selecionar({"2": [e], "3": [e]}, 1, 42)
        self.assertEqual(len(a), 1)
        self.assertEqual(s, [])
        self.assertEqual(a[0]["consultas_ec_origem"], "2|3")
        self.assertIn("ec_multiclasse", a[0]["motivos_exclusao"])

    def test_accession_mudou_entre_consultas_bloqueia(self):
        with self.assertRaisesRegex(ValueError, "mudou entre consultas"):
            p.auditar_e_selecionar({"2": [entrada()], "3": [entrada(ec="3.1.1.1")]}, 1, 42)

    def test_mesma_semente_mesma_amostra_independente_da_ordem_dos_dados(self):
        classes = {"2": [entrada(f"P{i:05d}", "M" + "A" * i + "K") for i in range(1, 9)],
                   "3": [entrada(f"Q{i:05d}", "M" + "V" * i + "K", "3.1.1.1") for i in range(1, 9)]}
        _, a = p.auditar_e_selecionar(classes, 3, 42)
        _, b = p.auditar_e_selecionar({k: list(reversed(v)) for k, v in classes.items()}, 3, 42)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 6)
        self.assertEqual([x["uid"] for x in a], [f"ec{i:09d}" for i in range(6)])

    def test_sequencia_ausente_nao_vira_descarte_biologico(self):
        e = entrada()
        e.pop("sequence")
        with self.assertRaisesRegex(ValueError, "resposta incompleta"):
            p.auditar_e_selecionar({"2": [e], "3": []}, 1, 42)


class TestPaginacao(unittest.TestCase):
    def test_respeita_limite_e_nao_aplica_filtro_512_na_consulta(self):
        c = Mock()
        c.pedir.return_value = ({"results": [entrada(), entrada("P00002", "A" * 513)]},
                                {"x-total-results": "100"})
        rows, m = p.buscar_classe(c, "2", 2, progresso=lambda t: None)
        self.assertEqual(len(rows), 2)
        self.assertFalse(m["consulta_esgotada"])
        self.assertEqual(m["total_reportado_api"], 100)
        url = c.pedir.call_args.args[0]
        self.assertNotIn("length", url)
        self.assertIn("size=2", url)
        self.assertEqual(c.pedir.call_count, 1)

    def test_paginacao_completa_segunda_pagina_e_header_total(self):
        c = Mock()
        c.pedir.side_effect = [({"results": [entrada()]}, {"x-total-results": "2",
            "link": '<https://rest.uniprot.org/uniprotkb/search?cursor=abc>; rel="next"'}),
            ({"results": [entrada("P00002", "VIGK")]}, {"x-total-results": "2"})]
        rows, m = p.buscar_classe(c, "2", 3, progresso=lambda t: None)
        self.assertEqual(len(rows), 2)
        self.assertTrue(m["consulta_esgotada"])
        self.assertEqual(m["paginas"], 2)
        self.assertIn("cursor=abc", c.pedir.call_args.args[0])

    def test_total_zero_so_com_header_e_lista_validos(self):
        c = Mock()
        c.pedir.return_value = ({"results": []}, {"x-total-results": "0"})
        rows, meta = p.buscar_classe(c, "3", 2, progresso=lambda t: None)
        self.assertEqual(rows, [])
        self.assertTrue(meta["consulta_esgotada"])
        for corpo, headers in (({}, {"x-total-results": "0"}), ({"results": []}, {})):
            c.pedir.return_value = (corpo, headers)
            with self.assertRaises(ValueError):
                p.buscar_classe(c, "3", 2, progresso=lambda t: None)

    def test_paginacao_truncada_duplicada_ou_fora_ordem_bloqueia(self):
        casos = [([entrada()], {"x-total-results": "2"}),
                 ([entrada(), entrada()], {"x-total-results": "2"}),
                 ([entrada("P00002"), entrada()], {"x-total-results": "2"})]
        for rows, headers in casos:
            with self.subTest(rows=rows):
                c = Mock()
                c.pedir.return_value = ({"results": rows}, headers)
                with self.assertRaises(ValueError):
                    p.buscar_classe(c, "2", 2, progresso=lambda t: None)

    def test_link_externo_bloqueado(self):
        c = Mock()
        c.pedir.return_value = ({"results": [entrada()]}, {"x-total-results": "2",
            "link": '<https://outro.example/search?cursor=abc>; rel="next"'})
        with self.assertRaisesRegex(ValueError, "fora de"):
            p.buscar_classe(c, "2", 2, progresso=lambda t: None)


class TestColeta(unittest.TestCase):
    def test_fluxo_http_ate_fasta_e_registro_do_release(self):
        class Resposta:
            def __init__(self, rows):
                self.corpo = json.dumps({"results": rows}).encode("utf-8")
                self.headers = {"X-Total-Results": str(len(rows)), "X-UniProt-Release": "SINTETICO"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return p.api.API + "/uniprotkb/search"

            def read(self):
                return self.corpo

        with tempfile.TemporaryDirectory() as d:
            opener = Mock()
            opener.open.side_effect = [Resposta([entrada()]), Resposta([entrada("Q00001", "VIGK", "3.1.1.1")])]
            with patch.object(p.api, "build_opener", return_value=opener):
                r = p.coletar(Path(d), 1, 1, timeout=17, progresso=lambda t: None)
            self.assertTrue(r["amostra_completa"])
            self.assertEqual(r["uniprot_releases"], ["SINTETICO"])
            self.assertEqual(len(r["respostas_http"]), 2)
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 17)
            self.assertEqual(len(list((Path(r["pasta_saida"]) / "respostas_api").glob("*.body.json"))), 2)
            self.assertEqual(r["rotulos_selecionados"], {"Transferase": 1, "Hidrolase": 1})

    def test_coleta_completa_preserva_historico_e_gera_fasta_sem_rotulo_no_cabecalho(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            antigo = raiz / "dados/base_ia/base_1m/embeddings.npy"
            antigo.parent.mkdir(parents=True)
            antigo.write_bytes(b"NPY deliberadamente invalido; nao deve ser aberto")
            classes = {"2": [entrada(), entrada("P00002", "A" * 513)],
                       "3": [entrada("Q00001", "VIGK", "3.1.1.1"), entrada("Q00002", "V" * 514, "3.1.1.2")]}
            c = cliente_fake(classes)
            r = p.coletar(raiz, 1, 2, cliente_factory=lambda *a, **k: c, progresso=lambda t: None)
            self.assertTrue(r["ok"] and r["amostra_completa"])
            self.assertEqual(r["rotulos_selecionados"], {"Transferase": 1, "Hidrolase": 1})
            self.assertEqual(r["exclusoes_comprimento"]["enzimas_revisadas_ec_exclusiva_mais_512"],
                             {"Transferase": 1, "Hidrolase": 1})
            self.assertIsNone(r["exclusoes_comprimento"]["enzimas_ec_nos_descartes_historicos_da_base_1m"])
            self.assertFalse(r["embeddings_gerados"] or r["particoes_criadas"] or r["treinamento_liberado"])
            self.assertEqual(antigo.read_bytes(), b"NPY deliberadamente invalido; nao deve ser aberto")
            saida = Path(r["pasta_saida"])
            with (saida / "piloto_rotulado.csv").open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f, delimiter=";"))
            fasta = (saida / "sequencias.fasta").read_text(encoding="utf-8")
            self.assertEqual(fasta.splitlines()[::2], [">" + x["uid"] for x in rows])
            self.assertEqual(fasta.splitlines()[1::2], [x["sequencia"] for x in rows])
            for nome, h in r["hashes_saidas"].items():
                self.assertEqual(p.api.sha(saida / nome), h)

    def test_meta_incompleta_e_declarada_sem_inventar_proteinas(self):
        with tempfile.TemporaryDirectory() as d:
            c = cliente_fake({"2": [entrada()], "3": []})
            r = p.coletar(Path(d), 2, 2, cliente_factory=lambda *a, **k: c, progresso=lambda t: None)
            self.assertTrue(r["ok"])
            self.assertFalse(r["amostra_completa"])
            self.assertEqual(r["total_selecionado"], 1)
            self.assertEqual(r["rotulos_selecionados"]["Hidrolase"], 0)

    def test_falha_de_rede_nao_conclui_coleta_nem_inventa_contagem(self):
        with tempfile.TemporaryDirectory() as d:
            c = cliente_fake({"2": [], "3": []})
            c.pedir.side_effect = p.api.FalhaConsulta("HTTP 503")
            with self.assertRaises(p.api.FalhaConsulta):
                p.coletar(Path(d), 1, 2, cliente_factory=lambda *a, **k: c)
            relatorio = next(Path(d).rglob("relatorio_coleta.json"))
            r = json.loads(relatorio.read_text(encoding="utf-8"))
            self.assertFalse(r["ok"])
            self.assertIsNone(r["rotulos_selecionados"])
            self.assertIsNone(r["exclusoes_comprimento"])
            self.assertFalse((relatorio.parent / "piloto_rotulado.csv").exists())

    def test_mudanca_de_release_bloqueia(self):
        with tempfile.TemporaryDirectory() as d:
            c = cliente_fake({"2": [], "3": []}, releases=("A", "B"))
            with self.assertRaisesRegex(p.api.FalhaConsulta, "release UniProt mudou"):
                p.coletar(Path(d), 1, 2, cliente_factory=lambda *a, **k: c, progresso=lambda t: None)

    def test_parametros_invalidos_e_cliente_antigo_bloqueiam_antes_da_saida(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            for n, limite in ((0, 2), (2001, 3000), (2, 1), (1, 5001)):
                with self.subTest(n=n, limite=limite), self.assertRaises(ValueError):
                    p.coletar(raiz, n, limite)
            with patch.object(p.api, "REVISAO_CLIENTE", 1), self.assertRaisesRegex(ValueError, "revisao 2"):
                p.coletar(raiz, 1, 2)
            self.assertFalse((raiz / "dados").exists())

    def test_nova_execucao_preserva_saida_anterior(self):
        with tempfile.TemporaryDirectory() as d:
            factory = lambda *a, **k: cliente_fake({"2": [entrada()], "3": []})
            a = p.coletar(Path(d), 1, 1, cliente_factory=factory, progresso=lambda t: None)
            antes = {f: f.read_bytes() for f in Path(a["pasta_saida"]).rglob("*") if f.is_file()}
            b = p.coletar(Path(d), 1, 1, cliente_factory=factory, progresso=lambda t: None)
            self.assertNotEqual(a["pasta_saida"], b["pasta_saida"])
            self.assertEqual({f: f.read_bytes() for f in antes}, antes)

    def test_cli_timeout_invalido_bloqueia(self):
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            p.main(["--timeout", "nan"])


if __name__ == "__main__":
    unittest.main()
