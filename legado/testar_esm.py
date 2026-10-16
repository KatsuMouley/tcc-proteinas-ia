"""Teste de inferencia do ESM pequeno. Nao treina nem mede classificacao biologica."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

MODEL_ID = "facebook/esm2_t6_8M_UR50D"
MODEL_REVISION = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Usa apenas o modelo ja baixado.")
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    results = project / "resultados"
    results.mkdir(parents=True, exist_ok=True)
    cache = project / "cache" / "huggingface"
    cache.mkdir(parents=True, exist_ok=True)
    report = {"tipo": "teste_tecnico_sintetico", "modelo": MODEL_ID,
              "revisao": MODEL_REVISION, "dispositivo": "cpu", "ok": False}
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        start = time.perf_counter()
        common = {"revision": MODEL_REVISION, "cache_dir": str(cache),
                  "local_files_only": args.offline, "trust_remote_code": False}
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **common)
        model = AutoModel.from_pretrained(MODEL_ID, use_safetensors=True,
                                         add_pooling_layer=False, **common).to("cpu")
        model.eval()
        report["segundos_carregamento_inclui_download_se_necessario"] = round(time.perf_counter() - start, 3)
        # Sequencia artificial para verificar o funcionamento, nao e exemplo do TCC.
        batch = tokenizer("ACDEFGHIKLMNPQRSTVWY", return_tensors="pt",
                          return_special_tokens_mask=True, return_token_type_ids=False)
        special = batch.pop("special_tokens_mask").bool()
        residue_mask = batch["attention_mask"].bool() & ~special
        start = time.perf_counter()
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
            mask = residue_mask.unsqueeze(-1).to(hidden.dtype)
            embedding = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)
        assert tuple(embedding.shape) == (1, 320), tuple(embedding.shape)
        assert torch.isfinite(embedding).all().item()
        report.update({"ok": True, "residuos_teste": 20, "dimensao_embedding": 320,
                       "segundos_inferencia": round(time.perf_counter() - start, 3)})
    except Exception as exc:
        report["erro"] = f"{type(exc).__name__}: {exc}"
    (results / "teste_esm.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
