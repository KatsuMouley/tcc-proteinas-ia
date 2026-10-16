"""Exporta o ambiente do Python usado, sem instalar pacotes ou usar a GPU."""
from argparse import ArgumentParser
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import uuid

PROJETO = Path(__file__).resolve().parents[2]


def main(argv=None):
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = ArgumentParser(description=__doc__)
    p.add_argument("--saida", type=Path, default=PROJETO / "dados/diagnosticos")
    args = p.parse_args(argv)
    report = {"tipo": "exportacao_ambiente_instalado", "ok": False,
              "python": platform.python_version(), "executavel": sys.executable,
              "sistema": platform.platform(), "versoes": {},
              "gpu_utilizada": False, "pacotes_instalados_nesta_execucao": False}
    try:
        for nome in ("numpy", "torch", "transformers", "huggingface-hub", "tokenizers", "safetensors"):
            try:
                report["versoes"][nome] = importlib.metadata.version(nome)
            except importlib.metadata.PackageNotFoundError:
                report["versoes"][nome] = None
        r = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
        if r.returncode:
            raise RuntimeError("pip freeze falhou: " + r.stderr.strip())
        nome = datetime.now(timezone.utc).strftime("ambiente_%Y%m%dT%H%M%S%fZ_") + uuid.uuid4().hex[:6]
        dest = args.saida / nome
        dest.mkdir(parents=True, exist_ok=False)
        (dest / "requirements.instaladas.txt").write_text(r.stdout, encoding="utf-8")
        report.update(ok=True, pasta_saida=str(dest.resolve()))
        (dest / "ambiente.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        report["erro"] = f"{type(e).__name__}: {e}"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
