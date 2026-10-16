"""Dados e processo MMseqs2 simulados; sem WSL real, rede, GPU ou treinamento."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "etapas"))
spec = importlib.util.spec_from_file_location("preparacao_ec_testada", RAIZ / "etapas/preparar_piloto_ec.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class Coleta:
    def __init__(self, pasta, total=120):
        self.pasta = pasta
        self.linhas = []
        for i in range(total):
            classe = "2" if i % 2 == 0 else "3"
            seq = "M" + "A" * (i + 1) + "K"
            self.linhas.append({"indice_global": i, "uid": f"ec{i:09d}", "id_original": f"P{i:05d}",
                "classe_ec": classe, "rotulo_ec": p.api.ROTULOS[classe], "ecs_uniprot": classe + ".1.1.1",
                "revisado": True, "status_coleta": "selecionado", "motivos_exclusao": "",
                "sequencia": seq, "tamanho": len(seq), "sha256_sequencia": hashlib.sha256(seq.encode()).hexdigest()})
        self.gravar()

    def gravar(self):
        p.api.salvar_csv(self.pasta / "piloto_rotulado.csv", self.linhas, list(self.linhas[0]))
        p.api.salvar_csv(self.pasta / "candidatos_auditados.csv", self.linhas, list(self.linhas[0]))
        (self.pasta / "sequencias.fasta").write_text("".join(
            f">{x['uid']}\n{x['sequencia']}\n" for x in self.linhas), encoding="utf-8")
        self.atualizar_relatorio()

    def atualizar_relatorio(self):
        r = {"tipo": "coleta_piloto_swissprot_ec2_ec3", "schema": 1, "ok": True, "amostra_completa": True,
            "total_selecionado": len(self.linhas), "modelo_embeddings_planejado": p.api.MODELO,
            "revisao_embeddings_planejada": p.api.REVISAO,
            "rotulos_selecionados": {r: sum(x["rotulo_ec"] == r for x in self.linhas) for r in p.api.ROTULOS.values()},
            "hashes_saidas": {n: p.api.sha(self.pasta / n) for n in (
                "piloto_rotulado.csv", "candidatos_auditados.csv", "sequencias.fasta")}}
        p.api.salvar_json(self.pasta / "relatorio_coleta.json", r)

    def grupos(self):
        return {x["uid"]: self.linhas[i // 2 * 2]["uid"] for i, x in enumerate(self.linhas)}

    def executar_fake(self, backend, coleta, saida, threads, progresso):
        (saida / "global_cluster.tsv").write_text("".join(
            f"{rep}\t{membro}\n" for membro, rep in self.grupos().items()), encoding="utf-8")
        return {"versao_mmseqs2": "SIMULADA", "threads_cpu": threads, "gpu_utilizada": False}


class TestConferencia(unittest.TestCase):
    def test_confere_rotulos_ordem_hashes_e_fasta(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d))
            linhas, _, marcas = p.conferir_coleta(c.pasta, len(c.linhas))
            self.assertEqual(len(linhas), 120)
            self.assertEqual({x["classe_ec"] for x in linhas}, {"2", "3"})
            self.assertEqual(len(marcas), 4)

    def test_hash_alterado_bloqueia_antes_de_criar_saida(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d))
            with (c.pasta / "piloto_rotulado.csv").open("a") as f:
                f.write("\n")
            backend = Mock()
            with self.assertRaisesRegex(ValueError, "Hash divergente"):
                p.preparar(c.pasta, 120, backend_factory=backend)
            backend.assert_not_called()
            self.assertEqual(list(c.pasta.glob("preparacao_ec_*")), [])

    def test_regra_aa_nao_e_aceita_como_rotulo_ec(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d))
            c.linhas[0]["rotulo_ec"] = "Completa"
            c.gravar()
            with self.assertRaisesRegex(ValueError, "Rotulo EC"):
                p.conferir_coleta(c.pasta, 120)

    def test_ec_multiclasse_ou_sem_revisao_bloqueia(self):
        for defeito in ("ec", "revisado"):
            with self.subTest(defeito=defeito), tempfile.TemporaryDirectory() as d:
                c = Coleta(Path(d))
                if defeito == "ec":
                    c.linhas[0]["ecs_uniprot"] += "|3.1.1.1"
                else:
                    c.linhas[0]["revisado"] = False
                c.gravar()
                with self.assertRaisesRegex(ValueError, "Rotulo EC"):
                    p.conferir_coleta(c.pasta, 120)

    def test_uid_trocado_ou_sequencia_repetida_bloqueia(self):
        for defeito in ("uid", "duplicata"):
            with self.subTest(defeito=defeito), tempfile.TemporaryDirectory() as d:
                c = Coleta(Path(d))
                if defeito == "uid":
                    c.linhas[1]["uid"] = c.linhas[0]["uid"]
                else:
                    for campo in ("sequencia", "tamanho", "sha256_sequencia"):
                        c.linhas[1][campo] = c.linhas[0][campo]
                c.gravar()
                with self.assertRaises(ValueError):
                    p.conferir_coleta(c.pasta, 120)

    def test_fasta_divergente_bloqueia_mesmo_com_hash_atualizado(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d))
            fasta = c.pasta / "sequencias.fasta"
            fasta.write_text(fasta.read_text(encoding="utf-8").replace("MAK", "MVK", 1), encoding="utf-8")
            c.atualizar_relatorio()
            with self.assertRaisesRegex(ValueError, "FASTA e CSV divergem"):
                p.conferir_coleta(c.pasta, 120)


class TestGrupos(unittest.TestCase):
    def test_tsv_completo_e_grupos_inteiros_por_particao(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d))
            c.executar_fake(None, c.pasta, c.pasta, 8, print)
            grupos = p.ler_grupos(c.pasta / "global_cluster.tsv", c.linhas)
            rows, resumo = p.separar(c.linhas, grupos)
            self.assertEqual(sum(v["proteinas"] for v in resumo.values()), 120)
            for rep in set(grupos.values()):
                self.assertEqual(len({x["particao"] for x in rows if x["grupo_global"] == rep}), 1)
            self.assertEqual(p.separar(c.linhas, grupos), (rows, resumo))

    def test_tsv_incompleto_duplicado_ou_de_outra_base_bloqueia(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d), 2)
            tsv = c.pasta / "global_cluster.tsv"
            for texto in ("ec000000000\tec000000000\n",
                          "ec000000000\tec000000000\nec000000000\tec000000000\n",
                          "ec000000000\tp000000000\n"):
                with self.subTest(texto=texto):
                    tsv.write_text(texto, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        p.ler_grupos(tsv, c.linhas)

    def test_representante_em_outro_grupo_bloqueia(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d), 2)
            tsv = c.pasta / "global_cluster.tsv"
            tsv.write_text("ec000000001\tec000000000\nec000000000\tec000000001\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "representante"):
                p.ler_grupos(tsv, c.linhas)

    def test_classe_da_proteina_nao_e_trocada_pela_classe_da_representante(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d), 2)
            rows, _ = p.separar(c.linhas, c.grupos())
            self.assertEqual(rows[0]["grupo_global"], rows[1]["grupo_global"])
            self.assertEqual([x["classe_ec"] for x in rows], ["2", "3"])


class TestPreparacao(unittest.TestCase):
    def test_fluxo_simulado_preserva_entradas_e_indices_correspondem_ao_csv(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d))
            antes = {f: f.read_bytes() for f in c.pasta.iterdir()}
            r = p.preparar(c.pasta, 120, backend_factory=Mock(), executor=c.executar_fake,
                           progresso=lambda t: None)
            self.assertTrue(r["ok"])
            self.assertEqual(r["grupos"], 60)
            self.assertEqual(r["grupos_compartilhados_entre_particoes"], 0)
            self.assertFalse(r["embeddings_gerados"] or r["treinamento_realizado"] or r["teste_avaliado"])
            self.assertEqual({f: f.read_bytes() for f in antes}, antes)
            saida = Path(r["pasta_saida"])
            with (saida / "particoes.csv").open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f, delimiter=";"))
            for nome in p.PARTICOES:
                arr = np.load(saida / (nome + "_indices.npy"), allow_pickle=False)
                self.assertEqual(arr.dtype, np.dtype("int64"))
                self.assertEqual(arr.tolist(), [int(x["indice_global"]) for x in rows if x["particao"] == nome])
            arr = np.load(saida / "grupos_por_linha.npy", allow_pickle=False)
            self.assertEqual(arr.tolist(), [i // 2 * 2 for i in range(120)])

    def test_falha_mmseqs_preserva_diagnostico_e_nao_cria_particoes_validas(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d))
            with self.assertRaisesRegex(ValueError, "Arquivos preservados"):
                p.preparar(c.pasta, 120, backend_factory=Mock(), executor=Mock(side_effect=ValueError("MMseqs falhou")))
            relatorio = next(c.pasta.glob("preparacao_ec_*/relatorio_preparacao_ec.json"))
            r = json.loads(relatorio.read_text(encoding="utf-8"))
            self.assertFalse(r["ok"])
            self.assertFalse((relatorio.parent / "particoes.csv").exists())

    def test_grupo_unico_nao_muda_semente_para_forcar_particoes(self):
        with tempfile.TemporaryDirectory() as d:
            c = Coleta(Path(d))

            def executor(backend, coleta, saida, threads, progresso):
                (saida / "global_cluster.tsv").write_text("".join(
                    f"ec000000000\t{x['uid']}\n" for x in c.linhas), encoding="utf-8")
                return {"versao_mmseqs2": "SIMULADA"}

            with self.assertRaisesRegex(ValueError, "nao alterar a semente automaticamente"):
                p.preparar(c.pasta, 120, backend_factory=Mock(), executor=executor)
            r = json.loads(next(c.pasta.glob("preparacao_ec_*/relatorio_preparacao_ec.json")).read_text(encoding="utf-8"))
            self.assertEqual(r["semente"], 42)
            self.assertFalse(r["ok"])

    def test_wsl_temporario_var_tmp_e_parametros_finais_preservados(self):
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            backend = Mock()
            backend.distro, backend.prefixo = "Ubuntu", ["wsl.exe", "--exec"]
            backend.version.return_value = "SIMULADA"
            backend.cmd.side_effect = lambda *a: backend.prefixo + ["mmseqs", *a]
            backend.path.side_effect = lambda path: "/mnt/c/piloto/" + path.name
            processo = Mock()
            processo.poll.return_value = processo.returncode = 0
            ajuda = "--cluster-mode --alignment-mode --kmer-per-seq --split-memory-limit"
            with patch.object(p, "executar_curto", side_effect=[(0, ajuda, ""),
                (0, "/var/tmp/tcc_ec_mmseqs.ABC12345\n", ""), (0, "", "")]), \
                 patch.object(p.subprocess, "Popen", return_value=processo):
                r = p.executar_mmseqs(backend, pasta, pasta, 8, progresso=lambda t: None)
            self.assertEqual(r["temporario_mmseqs"], "/var/tmp/tcc_ec_mmseqs.ABC12345")
            self.assertIn("MMSEQS_NUM_THREADS=8", r["comando"])
            self.assertEqual(r["comando"][r["comando"].index("--min-seq-id") + 1], "0.5")
            self.assertEqual(r["comando"][r["comando"].index("-c") + 1], "0.8")
            self.assertEqual(r["comando"][r["comando"].index("--threads") + 1], "8")


if __name__ == "__main__":
    unittest.main()
