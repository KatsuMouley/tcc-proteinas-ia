import types
import unittest

import numpy as np

from sistema_tcc import estatisticas, explorar


class TesteExplorar(unittest.TestCase):
    def test_pca_deterministico_e_2d(self):
        rng = np.random.default_rng(0)
        a = rng.normal(size=(200, 320))
        mu, v = explorar._pca(a)
        self.assertEqual(v.shape, (2, 320))
        mu2, v2 = explorar._pca(a.copy())
        np.testing.assert_allclose(v, v2)

    def test_parametros_validados(self):
        exe = types.SimpleNamespace(c=None, execucoes=None)
        with self.assertRaises(ValueError):
            explorar.representantes(exe, "original", 7, "tipo")
        with self.assertRaises(ValueError):
            explorar.representantes(exe, "original", 10, "cor_invalida")

    def test_selecao_por_categoria(self):
        pool = [{"uid": "p%d" % i, "tipo": "Completa" if i % 3 else "Incompleta", "ec": None} for i in range(30)]
        dados = {"ec_ok": False, "base": "t", "proteinas": 30, "grupos": 30, "selecao": "t", "pool": pool}
        explorar._memoria.clear()
        exe = types.SimpleNamespace(c=None, execucoes=types.SimpleNamespace(
            obter=lambda i: ({"pasta": "/nao/existe"}, {})))
        explorar._memoria[("x", 0, explorar._ec7.assinatura())] = dados
        r = explorar.representantes(exe, "x", 10, "tipo")
        self.assertEqual([c["exibidos"] for c in r["categorias"]], [10, 10])
        self.assertEqual(len(r["pontos"]), 20)
        with self.assertRaises(ValueError):
            explorar.representantes(exe, "x", 10, "ec")
        with self.assertRaises(ValueError):  # sem treino EC7 no pool
            explorar.representantes(exe, "x", 10, "ec7")
        classes = explorar.CATEGORIAS["ec7"]
        for i, item in enumerate(pool):
            item["ec7"] = classes[i % 7]
        r = explorar.representantes(exe, "x", 10, "ec7")
        self.assertEqual(len(r["categorias"]), 7)
        self.assertTrue(r["categorias"][0]["rotulo"].startswith("EC 1"))
        self.assertEqual(sum(c["exibidos"] for c in r["categorias"]), 30)


class TesteEstatisticas(unittest.TestCase):
    def test_mann_whitney_separacao_total(self):
        r = estatisticas.mann_whitney([4, 5, 6], [1, 2, 3])
        self.assertEqual(r["u"], 9.0)
        self.assertEqual(r["delta_cliff"], 1.0)
        self.assertEqual(r["efeito"], "grande")
        self.assertAlmostEqual(r["p"], 0.0495, places=3)  # aproximacao normal de z = 1,964

    def test_mann_whitney_grupos_iguais(self):
        r = estatisticas.mann_whitney([1, 2, 3, 4], [1, 2, 3, 4])
        self.assertEqual(r["delta_cliff"], 0.0)
        self.assertAlmostEqual(r["p"], 1.0)
        self.assertEqual(r["efeito"], "desprezível")

    def test_postos_com_empate(self):
        r, cont = estatisticas._postos(np.array([10, 20, 20, 30]))
        self.assertEqual(r.tolist(), [1.0, 2.5, 2.5, 4.0])


if __name__ == "__main__":
    unittest.main()
