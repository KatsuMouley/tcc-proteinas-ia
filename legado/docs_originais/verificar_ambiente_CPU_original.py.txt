"""Verifica dependencias e operacoes tecnicas; nao avalia um modelo biologico."""
from __future__ import annotations

import importlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys


PACKAGES = {
    "torch": "torch", "transformers": "transformers", "numpy": "numpy",
    "pandas": "pandas", "scikit-learn": "sklearn", "joblib": "joblib",
    "biopython": "Bio", "matplotlib": "matplotlib",
}


def main() -> int:
    project = Path(__file__).resolve().parent
    for folder in ("dados/brutos", "dados/amostra", "dados/rotulos", "dados/embeddings", "modelos", "resultados", "cache/huggingface"):
        (project / folder).mkdir(parents=True, exist_ok=True)
    report = {
        "tipo": "teste_tecnico_de_ambiente",
        "python": platform.python_version(), "arquitetura_python_bits": 64 if sys.maxsize > 2**32 else 32,
        "sistema": platform.platform(), "nucleos_logicos": os.cpu_count(),
        "pacotes": {}, "erros": [], "testes": {},
    }
    modules = {}
    for package, module in PACKAGES.items():
        try:
            modules[module] = importlib.import_module(module)
            report["pacotes"][package] = importlib.metadata.version(package)
        except Exception as exc:
            report["erros"].append(f"{package}: {type(exc).__name__}: {exc}")
    if sys.version_info[:2] not in ((3, 11), (3, 12), (3, 13)) or sys.maxsize <= 2**32:
        report["erros"].append("Utilize Python 3.11, 3.12 ou 3.13 de 64 bits nesta configuracao.")
    if not report["erros"]:
        try:
            np = modules["numpy"]
            torch = modules["torch"]
            report["cuda_disponivel_na_instalacao"] = torch.cuda.is_available()
            report["observacao_cuda"] = "False e esperado na instalacao CPU; nao informa se existe uma GPU fisica."
            with sqlite3.connect(":memory:") as db:
                assert db.execute("SELECT 1").fetchone() == (1,)
            report["testes"]["sqlite"] = "ok"
            assert torch.ones((2, 3)).sum().item() == 6
            report["testes"]["torch_cpu"] = "ok"
            from transformers import AutoModel, AutoTokenizer  # verifica a importacao; nao baixa o modelo
            assert AutoModel is not None and AutoTokenizer is not None
            report["testes"]["classes_transformers"] = "ok"
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
            from sklearn.linear_model import LogisticRegression
            # Valores artificiais apenas para conferir treino e serializacao das bibliotecas.
            x = np.array([[0, 0], [0, 1], [3, 3], [3, 4]], dtype=float)
            estimator = make_pipeline(StandardScaler(), LogisticRegression(random_state=42))
            estimator.fit(x, ["teste_a", "teste_a", "teste_b", "teste_b"])
            buffer = io.BytesIO()
            modules["joblib"].dump(estimator, buffer)
            buffer.seek(0)
            loaded = modules["joblib"].load(buffer)
            assert np.array_equal(estimator.predict(x), loaded.predict(x))
            report["testes"]["classificador_e_serializacao_sinteticos"] = "ok"
            from Bio import SeqIO
            assert len(list(SeqIO.parse(io.StringIO(">teste_tecnico\nACDEFGHIKLMNPQRSTVWY\n"), "fasta"))) == 1
            report["testes"]["leitura_fasta"] = "ok"
        except Exception as exc:
            report["erros"].append(f"Teste: {type(exc).__name__}: {exc}")
    report["ok"] = not report["erros"]
    output = project / "resultados" / "verificacao_ambiente.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
