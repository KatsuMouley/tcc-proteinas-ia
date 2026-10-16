"""Teste sintetico do ESM-2 em CUDA. Nao treina nem modifica dados biologicos."""

import argparse
import json
import os
from pathlib import Path
import sys
import time

MODELO = "facebook/esm2_t6_8M_UR50D"
REVISAO = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
SEQUENCIA_TESTE = "ACDEFGHIKLMNPQRSTVWY"


def emitir(relatorio):
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))


def main(argv=None):
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=2,
                        help="Threads de CPU do PyTorch neste processo (padrao: 2).")
    parser.add_argument("--cache", type=Path,
                        default=Path(__file__).resolve().parents[2] / "cache" / "huggingface",
                        help="Cache existente do teste CPU.")
    parser.add_argument("--permitir-download", action="store_true",
                        help="Permite baixar somente componentes ausentes do modelo.")
    args = parser.parse_args(argv)
    if args.threads < 1:
        parser.error("--threads precisa ser pelo menos 1")

    # Afeta somente este processo; nao altera configuracoes globais do Windows.
    for variavel in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[variavel] = str(args.threads)

    relatorio = {
        "tipo": "teste_tecnico_sintetico_gpu",
        "modelo": MODELO,
        "revisao": REVISAO,
        "ok": False,
        "treinamento_realizado": False,
        "dispositivo": None,
        "threads_cpu_pytorch": args.threads,
        "download_permitido": args.permitir_download,
    }
    etapa = "importar_pytorch"
    try:
        import torch

        relatorio["pytorch"] = torch.__version__
        relatorio["cuda_compilada"] = torch.version.cuda
        relatorio["cuda_disponivel"] = torch.cuda.is_available()
        if not relatorio["cuda_disponivel"]:
            relatorio["erro"] = "CUDA indisponivel. O teste nao foi executado na CPU."
            relatorio["acao"] = (
                "Se cuda_compilada for null, consulte docs/DEPENDENCIAS.md antes de reinstalar PyTorch. "
                "Se uma versao CUDA aparecer, verifique o driver com nvidia-smi."
            )
            emitir(relatorio)
            return 2

        etapa = "verificar_operacao_cuda"
        torch.set_num_threads(args.threads)
        torch.set_num_interop_threads(1)
        dispositivo = torch.device("cuda:0")
        torch.cuda.set_device(dispositivo)
        propriedades = torch.cuda.get_device_properties(dispositivo)
        relatorio["gpu"] = propriedades.name
        relatorio["compute_capability"] = f"{propriedades.major}.{propriedades.minor}"
        relatorio["vram_total_mb"] = round(propriedades.total_memory / (1024 ** 2), 1)
        relatorio["arquiteturas_pytorch"] = torch.cuda.get_arch_list()

        # is_available() sozinho nao confirma que os kernels deste pacote funcionam.
        prova_cuda = torch.arange(4, device=dispositivo).sum().item()
        if prova_cuda != 6:
            raise RuntimeError("Operacao de verificacao CUDA produziu resultado inesperado.")

        etapa = "carregar_modelo_do_cache"
        from transformers import AutoTokenizer, EsmModel

        parametros_cache = {
            "revision": REVISAO,
            "cache_dir": str(args.cache.resolve()),
            "local_files_only": not args.permitir_download,
        }
        inicio = time.perf_counter()
        tokenizador = AutoTokenizer.from_pretrained(MODELO, **parametros_cache)
        modelo = EsmModel.from_pretrained(
            MODELO, add_pooling_layer=False, attn_implementation="eager",
            **parametros_cache,
        ).float().to(dispositivo).eval()
        torch.cuda.synchronize()
        relatorio["segundos_carregamento"] = round(time.perf_counter() - inicio, 3)

        etapa = "inferir_embedding_na_gpu"
        entradas = tokenizador(
            SEQUENCIA_TESTE, return_tensors="pt", return_special_tokens_mask=True
        )
        especiais = entradas.pop("special_tokens_mask").to(dispositivo)
        entradas = {nome: tensor.to(dispositivo) for nome, tensor in entradas.items()}
        mascara_residuos = (entradas["attention_mask"] * (1 - especiais)).bool()

        torch.cuda.reset_peak_memory_stats(dispositivo)
        with torch.inference_mode():
            # Aquecimento separado da medicao; nao realiza treinamento.
            aquecimento = modelo(**entradas).last_hidden_state
            del aquecimento
            torch.cuda.synchronize()
            inicio = time.perf_counter()
            estados = modelo(**entradas).last_hidden_state
            embedding = estados[0, mascara_residuos[0]].mean(dim=0)
            torch.cuda.synchronize()
            segundos = time.perf_counter() - inicio

        if next(modelo.parameters()).device.type != "cuda" or embedding.device.type != "cuda":
            raise RuntimeError("O modelo ou o embedding nao esta na GPU.")
        if embedding.numel() != 320 or not torch.isfinite(embedding).all().item():
            raise RuntimeError("Embedding invalido: esperado vetor finito de 320 valores.")

        relatorio.update({
            "ok": True,
            "dispositivo": str(embedding.device),
            "residuos_teste": len(SEQUENCIA_TESTE),
            "dimensao_embedding": embedding.numel(),
            "precisao": str(embedding.dtype),
            "lote": 1,
            "segundos_inferencia_apos_aquecimento": round(segundos, 6),
            "memoria_pico_pytorch_mb": round(
                torch.cuda.max_memory_allocated(dispositivo) / (1024 ** 2), 1
            ),
        })
        emitir(relatorio)
        return 0

    except Exception as erro:
        relatorio["etapa_erro"] = etapa
        relatorio["erro"] = f"{type(erro).__name__}: {erro}"
        if etapa == "importar_pytorch":
            relatorio["acao"] = "Execute com .venv\\Scripts\\python.exe nesta pasta."
        elif etapa == "verificar_operacao_cuda":
            relatorio["acao"] = "Confira driver NVIDIA e a compatibilidade do pacote PyTorch."
        elif etapa == "carregar_modelo_do_cache":
            relatorio["acao"] = (
                "Execute este teste em ferramentas/ambiente para reutilizar o cache do projeto. "
                "Para outro cache, use --cache CAMINHO. "
                "Para componentes ausentes, use --permitir-download."
            )
        emitir(relatorio)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
