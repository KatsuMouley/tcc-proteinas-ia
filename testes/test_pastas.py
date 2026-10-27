import json, tempfile, unittest
from pathlib import Path
from sistema_tcc import pastas


class PastasTest(unittest.TestCase):
    def _raiz(self, ajustes):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        raiz = Path(d.name) / "proj"; raiz.mkdir()
        (raiz / "config_local.json").write_text(json.dumps(ajustes), encoding="utf-8")
        return raiz

    def test_sem_nuvem_usa_projeto(self):
        raiz = self._raiz({})
        self.assertEqual(pastas.pastas_fontes(raiz), (raiz / "arquivos .gz", raiz / "arquivos csv"))
        self.assertIsNone(pastas.copiar_resultado(raiz, "x", raiz))

    def test_fontes_na_nuvem_so_se_escolhido(self):
        nuvem = Path(tempfile.mkdtemp())
        raiz = self._raiz({"pasta_nuvem": str(nuvem), "salvar_fontes": False})
        self.assertEqual(pastas.pastas_fontes(raiz)[0], raiz / "arquivos .gz")
        raiz = self._raiz({"pasta_nuvem": str(nuvem), "salvar_fontes": True})
        self.assertEqual(pastas.pastas_fontes(raiz)[0], nuvem / "arquivos .gz")
        self.assertIn(nuvem.resolve(), pastas.raizes_permitidas(raiz))

    def test_copia_resultado_e_tolera_falha(self):
        nuvem = Path(tempfile.mkdtemp())
        raiz = self._raiz({"pasta_nuvem": str(nuvem), "copiar_resultados": True})
        origem = raiz / "run"; origem.mkdir(); (origem / "a.txt").write_text("1")
        pastas.copiar_resultado(origem, "execucoes_tcc/run", raiz, log=lambda *_: None)
        self.assertTrue((nuvem / "resultados_tcc/execucoes_tcc/run/a.txt").is_file())
        self.assertIsNone(pastas.copiar_resultado(raiz / "inexistente", "y", raiz, log=lambda *_: None))

    def test_validar_pasta(self):
        with self.assertRaises(ValueError):
            pastas.validar_pasta("relativa")
        self.assertTrue(pastas.validar_pasta(tempfile.gettempdir()))


if __name__ == "__main__":
    unittest.main()
