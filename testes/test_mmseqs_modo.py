import tempfile, types, unittest
from pathlib import Path
from unittest import mock
from sistema_tcc import mmseqs


class ModoTest(unittest.TestCase):
    def test_auto_prefere_nativo_se_instalado(self):
        raiz = Path(tempfile.mkdtemp())
        with mock.patch.object(mmseqs, "os", types.SimpleNamespace(name="nt")):
            self.assertEqual(mmseqs.modo({"mmseqs_modo": "auto"}, raiz), "wsl")
            self.assertEqual(mmseqs.distro_wsl({"wsl": "Ubuntu"}, raiz), "Ubuntu")
            (raiz / "ferramentas/mmseqs/mmseqs-win64").mkdir(parents=True)
            (raiz / "ferramentas/mmseqs/mmseqs-win64/mmseqs.bat").write_text("@echo off")
            self.assertEqual(mmseqs.modo({"mmseqs_modo": "auto"}, raiz), "nativo")
            self.assertIsNone(mmseqs.distro_wsl({"wsl": "Ubuntu"}, raiz))
            self.assertEqual(mmseqs.distro_wsl({"wsl": "Ubuntu", "mmseqs_modo": "wsl"}, raiz), "Ubuntu")

    def test_linux_ignora_modo(self):
        with mock.patch.object(mmseqs, "os", types.SimpleNamespace(name="posix")):
            self.assertEqual(mmseqs.modo({"mmseqs_modo": "wsl"}, Path(".")), "linux")


if __name__ == "__main__":
    unittest.main()
