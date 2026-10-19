import types
import unittest

import numpy as np

from sistema_tcc import explorar


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
        explorar._memoria[("x", 0)] = dados
        r = explorar.representantes(exe, "x", 10, "tipo")
        self.assertEqual([c["exibidos"] for c in r["categorias"]], [10, 10])
        self.assertEqual(len(r["pontos"]), 20)
        with self.assertRaises(ValueError):
            explorar.representantes(exe, "x", 10, "ec")


if __name__ == "__main__":
    unittest.main()
