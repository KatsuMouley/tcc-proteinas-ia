"""Garante o ESM-2 (facebook/esm2_t6_8M_UR50D) na revisao fixa do projeto em cache/huggingface.

Se o cache ja veio no pacote de dados do Drive, so confere. Senao, baixa ~30 MB uma unica vez.
"""
from pathlib import Path
import sys

RAIZ = Path(__file__).resolve().parents[1]
CACHE = RAIZ / "cache/huggingface"
MODELO = "facebook/esm2_t6_8M_UR50D"
REVISAO = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"

from transformers import AutoTokenizer, EsmModel

comum = {"revision": REVISAO, "cache_dir": str(CACHE), "trust_remote_code": False}
snap = CACHE / ("models--" + MODELO.replace("/", "--")) / "snapshots" / REVISAO
if not snap.is_dir():
    print("Baixando o ESM-2 (revisao fixa) para cache/huggingface ...", flush=True)
    AutoTokenizer.from_pretrained(MODELO, **comum)
    EsmModel.from_pretrained(MODELO, add_pooling_layer=False, use_safetensors=True, **comum)
tok = AutoTokenizer.from_pretrained(MODELO, local_files_only=True, **comum)
m = EsmModel.from_pretrained(MODELO, add_pooling_layer=False, use_safetensors=True, local_files_only=True, **comum)
assert m.config.hidden_size == 320, "ESM-2 inesperado."
print("ESM-2 pronto em cache/huggingface (uso offline).")
sys.exit(0)
