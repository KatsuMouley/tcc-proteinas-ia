"""Testa selecao e isolamento em bases sinteticas temporarias, sem rede/GPU."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

RAIZ = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sondagem_testada", RAIZ / "etapas/preparar_sondagem_ec.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def gravar_csv(path, linhas):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=";")
        w.writeheader()
        w.writerows(linhas)


class BaseSintetica:
    def __init__(self, raiz, total=60):
        self.raiz = raiz
        self.base = raiz / "dados/base_ia/base_1m"
        self.part = raiz / "dados/base_ia/particoes_1m"
        self.base.mkdir(parents=True)
        self.part.mkdir(parents=True)
        self.indice, self.particoes = [], []
        for i in range(total):
            nome = ("treino", "validacao", "teste")[(i // 2) % 3]
            uid = f"p{i:09d}"
            self.indice.append({"indice_global": i, "uid": uid,
                "id_original": f"CAA{i:08d}.1", "grupo_por_arquivo": "Grupo_" + uid,
                "arquivo_origem": "sintetico.fsa_aa.gz", "tamanho": i % 512 + 1,
                "sha256_sequencia": hashlib.sha256(str(i).encode()).hexdigest(),
                "Tipo_Nutricional": "Completa", "lote_original": 1, "indice_embedding_original": i})
            self.particoes.append({"indice_global": i, "uid": uid,
                "grupo_global": f"p{i // 2 * 2:09d}", "particao": nome, "Tipo_Nutricional": "Completa"})
        self.consolidacao = {"ok": True, "tipo": "base_ia_consolidada", "proteinas": total,
            "modelo": p.MODELO, "revisao": p.REVISAO, "formato_embeddings": [total, 320],
            "hashes_arquivos": {}}
        self.separacao = {"ok": True, "tipo": "particoes_por_grupos_globais", "proteinas": total,
            "base_consolidada": str(self.base), "grupos_compartilhados_entre_particoes": 0,
            "particoes": {n: {"proteinas": sum(x["particao"] == n for x in self.particoes)} for n in p.CONJUNTOS},
            "hashes_arquivos": {}}
        # Conteudos deliberadamente invalidos: a preparacao nao deve abri-los.
        (self.base / "embeddings.npy").write_bytes(b"NAO E UM NPY")
        (self.base / "sequencias.fasta").write_bytes(b"NAO E FASTA")
        self.gravar()

    def gravar(self):
        gravar_csv(self.base / "indice.csv", self.indice)
        gravar_csv(self.part / "particoes.csv", self.particoes)
        self.consolidacao["hashes_arquivos"]["indice.csv"] = p.sha_arquivo(self.base / "indice.csv")
        self.separacao["hashes_arquivos"]["particoes.csv"] = p.sha_arquivo(self.part / "particoes.csv")
        for path, obj in ((self.base / "relatorio_consolidacao.json", self.consolidacao),
                          (self.part / "relatorio_particoes.json", self.separacao)):
            path.write_text(json.dumps(obj), encoding="utf-8")

    def preparar(self, quantidade=10, semente=42):
        return p.preparar(self.raiz, quantidade, semente, progresso=lambda texto: None)


def candidatos(relatorio):
    with Path(relatorio["arquivo_candidatos"]).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


class TestSondagemEC(unittest.TestCase):
    def test_seleciona_so_treino_validacao_e_preserva_vinculos(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseSintetica(Path(d))
            r = b.preparar()
            self.assertEqual(r["selecionados"], 10)
            self.assertEqual(r["selecionados_por_particao"]["teste"], 0)
            for x in candidatos(r):
                i = int(x["indice_global"])
                self.assertEqual(x["id_original"], b.indice[i]["id_original"])
                self.assertEqual(x["grupo_global"], b.particoes[i]["grupo_global"])
                self.assertEqual(x["particao"], b.particoes[i]["particao"])
                self.assertIn(x["particao"], ("treino", "validacao"))
            self.assertIsNone(r["resultados_ec2_ec3"])
            self.assertIsNone(r["enzimas_ec_descartadas_mais_512"])

    def test_mesma_semente_mesmos_candidatos_e_saidas_separadas(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseSintetica(Path(d))
            a, c = b.preparar(), b.preparar()
            self.assertNotEqual(a["pasta_saida"], c["pasta_saida"])
            self.assertEqual(Path(a["arquivo_candidatos"]).read_bytes(), Path(c["arquivo_candidatos"]).read_bytes())
            self.assertTrue(Path(a["arquivo_candidatos"]).is_file())

    def test_nao_altera_originais_nem_precisa_de_vetores_validos(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseSintetica(Path(d))
            antes = {x: x.read_bytes() for x in (b.raiz / "dados/base_ia").rglob("*") if x.is_file()}
            r = b.preparar()
            self.assertEqual({x: x.read_bytes() for x in antes}, antes)
            self.assertFalse(r["embeddings_lidos"])
            self.assertFalse(r["consulta_uniprot_realizada"])
            self.assertFalse(r["treinamento_realizado"])

    def test_amostra_independe_dos_rotulos_antigos(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseSintetica(Path(d))
            a = candidatos(b.preparar())
            for linha in b.indice + b.particoes:
                linha["Tipo_Nutricional"] = "IGNORAR ESTE ROTULO"
            b.gravar()
            self.assertEqual(a, candidatos(b.preparar()))

    def test_ids_mantem_versao_e_texto_exportado_corresponde_ao_csv(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseSintetica(Path(d))
            r = b.preparar()
            ids = Path(r["arquivo_ids"]).read_text().splitlines()
            self.assertEqual(ids, [x["id_original"] for x in candidatos(r)])
            self.assertTrue(all(x.endswith(".1") for x in ids))

    def test_hash_adulterado_bloqueia_antes_de_criar_saida(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseSintetica(Path(d))
            with (b.base / "indice.csv").open("a") as f:
                f.write("\n")
            with self.assertRaisesRegex(ValueError, "hash da consolidacao"):
                b.preparar()
            self.assertFalse((b.raiz / "dados/piloto_ec2_ec3").exists())

    def test_uid_trocado_ou_csv_incompleto_bloqueiam_saida(self):
        for erro in ("uid", "tamanho"):
            with self.subTest(erro=erro), tempfile.TemporaryDirectory() as d:
                b = BaseSintetica(Path(d))
                if erro == "uid":
                    b.particoes[4]["uid"] = "p000000005"
                else:
                    b.particoes.pop()
                b.gravar()
                with self.assertRaises(ValueError):
                    b.preparar()
                self.assertFalse((b.raiz / "dados/piloto_ec2_ec3").exists())

    def test_amostra_menor_e_declarada_sem_incluir_teste(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseSintetica(Path(d), total=6)
            r = b.preparar(quantidade=500)
            self.assertEqual(r["selecionados"], 4)
            self.assertFalse(r["amostra_completa"])
            self.assertEqual(r["selecionados_por_particao"]["teste"], 0)

    def test_quantidade_invalida_e_modelo_incompativel_bloqueiam(self):
        with tempfile.TemporaryDirectory() as d:
            b = BaseSintetica(Path(d))
            for n in (0, -1, 5001):
                with self.subTest(n=n), self.assertRaises(ValueError):
                    b.preparar(quantidade=n)
            b.consolidacao["revisao"] = "outra revisao"
            b.gravar()
            with self.assertRaisesRegex(ValueError, "modelo, revisao"):
                b.preparar()
            self.assertFalse((b.raiz / "dados/piloto_ec2_ec3").exists())


if __name__ == "__main__":
    unittest.main()
