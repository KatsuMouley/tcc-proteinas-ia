"""Piloto: representantes reais do MMseqs2 -> embeddings ESM-2 em CUDA.

Le arquivos .gz e .csv diretamente, inclusive dentro de .zip. Nao treina.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from dataclasses import dataclass
import gzip
import hashlib
import io
from itertools import chain
import json
import os
from pathlib import Path
import sys
import time
import zipfile

MODELO = "facebook/esm2_t6_8M_UR50D"
REVISAO = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
ALFABETO = frozenset("ACDEFGHIKLMNPQRSTVWYBXZUO")
PROJETO = Path(__file__).resolve().parent


def nome_base(nome):
    return str(nome).replace("\\", "/").rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Fonte:
    caminho: Path
    membro: str | None = None
    tamanho: int = 0

    @property
    def nome(self):
        return nome_base(self.membro or self.caminho.name)

    @property
    def local(self):
        return f"{self.caminho} :: {self.membro}" if self.membro else str(self.caminho)

    @contextmanager
    def binario(self):
        if self.membro is None:
            with self.caminho.open("rb") as entrada:
                yield entrada
        else:
            with zipfile.ZipFile(self.caminho) as pacote:
                with pacote.open(self.membro) as entrada:
                    yield entrada

    @contextmanager
    def texto(self):
        with self.binario() as entrada:
            if self.nome.lower().endswith(".gz"):
                with gzip.GzipFile(fileobj=entrada, mode="rb") as descomprimido:
                    with io.TextIOWrapper(descomprimido, encoding="utf-8-sig") as texto:
                        yield texto
            else:
                with io.TextIOWrapper(entrada, encoding="utf-8-sig", newline="") as texto:
                    yield texto


def pasta_downloads():
    if sys.platform == "win32":
        try:
            import winreg
            chave = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave) as handle:
                valor, _ = winreg.QueryValueEx(handle, "{374DE290-123F-4565-9164-39C4925E467B}")
            return Path(os.path.expandvars(valor))
        except (OSError, ValueError):
            pass
    return Path.home() / "Downloads"


def encontrar_pares(pastas):
    fontes = []
    avisos = []
    visitados = set()
    for pasta in pastas:
        pasta = pasta.expanduser().resolve()
        if not pasta.is_dir():
            avisos.append(f"Pasta nao encontrada: {pasta}")
            continue
        for caminho in sorted(pasta.rglob("*")):
            if not caminho.is_file() or caminho.suffix.lower() not in {".gz", ".csv", ".zip"}:
                continue
            identidade = str(caminho.resolve()).casefold()
            if identidade in visitados:
                continue
            visitados.add(identidade)
            if caminho.suffix.lower() != ".zip":
                fontes.append(Fonte(caminho, tamanho=caminho.stat().st_size))
                continue
            try:
                with zipfile.ZipFile(caminho) as pacote:
                    nomes = set()
                    for item in pacote.infolist():
                        if item.is_dir() or not item.filename.lower().endswith((".gz", ".csv")):
                            continue
                        if item.flag_bits & 1:
                            raise ValueError("ZIP com senha nao e suportado")
                        if item.filename in nomes:
                            raise ValueError("ZIP contem nomes de arquivos repetidos")
                        nomes.add(item.filename)
                        fontes.append(Fonte(caminho, item.filename, item.file_size))
            except (OSError, ValueError, zipfile.BadZipFile) as erro:
                fontes = [fonte for fonte in fontes if fonte.caminho != caminho]
                avisos.append(f"Nao foi possivel listar {caminho.name}: {erro}")

    # Prefere arquivos diretos a copias dentro de ZIP; nao carrega seu conteudo.
    fontes.sort(key=lambda f: (f.membro is not None, str(f.caminho).casefold(), f.membro or ""))
    por_nome = {}
    for fonte in fontes:
        por_nome.setdefault(fonte.nome.casefold(), fonte)
    pares = []
    for nome, fonte in por_nome.items():
        if nome.endswith(".gz"):
            correspondente = por_nome.get(nome[:-3] + ".csv")
            if correspondente:
                pares.append((fonte, correspondente))
    pares.sort(key=lambda par: (par[0].tamanho, par[0].nome.casefold()))
    return pares, avisos


def carregar_candidatos(fonte_csv, nome_gz, limite):
    candidatos = {}
    with fonte_csv.texto() as entrada:
        primeira = entrada.readline()
        if not primeira:
            raise ValueError("O CSV esta vazio.")
        try:
            delimitador = csv.Sniffer().sniff(primeira, delimiters=";,\t").delimiter
        except csv.Error:
            delimitador = ";"
        leitor = csv.DictReader(chain([primeira], entrada), delimiter=delimitador)
        obrigatorias = {"Arquivo_Origem", "Grupo_Similaridade", "ID_da_Proteina"}
        if not obrigatorias.issubset(leitor.fieldnames or []):
            raise ValueError("CSV incompatível: esperadas as colunas Arquivo_Origem, "
                             "Grupo_Similaridade e ID_da_Proteina.")
        for linha in leitor:
            origem = (linha.get("Arquivo_Origem") or "").strip()
            if nome_base(origem).casefold() != nome_gz.casefold():
                continue
            grupo = (linha.get("Grupo_Similaridade") or "").strip()
            if not grupo.startswith("Grupo_") or not grupo[6:]:
                raise ValueError(f"Grupo inesperado: {grupo!r}; esperado Grupo_ID_DO_REPRESENTANTE.")
            representante = grupo[6:]
            candidatos.setdefault(representante, grupo)
            if len(candidatos) >= limite:
                break
    if not candidatos:
        raise ValueError("Nao ha representantes para este .gz no CSV. Confira Arquivo_Origem.")
    return candidatos


def registros_fasta(entrada):
    cabecalho = None
    partes = []
    for linha in entrada:
        if not linha.strip():
            continue
        if linha.startswith(">"):
            if cabecalho is not None:
                yield cabecalho, "".join(partes)
            cabecalho = linha[1:].strip()
            if not cabecalho:
                raise ValueError("FASTA possui um cabecalho vazio.")
            partes = []
        else:
            if cabecalho is None:
                raise ValueError("O .gz nao parece conter um FASTA: falta cabecalho >.")
            partes.append("".join(linha.split()))
    if cabecalho is not None:
        yield cabecalho, "".join(partes)


def preparar_amostra(fonte_gz, candidatos, quantidade, max_residuos):
    amostra = []
    descartes = []
    pendentes = set(candidatos)
    hashes = set()
    lidos = 0
    avaliados = 0
    leitura_completa = False
    inicio = time.perf_counter()
    with fonte_gz.texto() as entrada:
        for descricao, sequencia in registros_fasta(entrada):
            lidos += 1
            if lidos % 25000 == 0:
                print(f"Preparacao: {lidos:,} sequencias lidas; {len(amostra)} representantes aceitos.", flush=True)
            identificador = descricao.split()[0]
            if identificador not in pendentes:
                continue
            pendentes.remove(identificador)
            avaliados += 1
            sequencia = sequencia.upper()
            stops_removidos = len(sequencia) - len(sequencia.rstrip("*"))
            sequencia = sequencia.rstrip("*")
            digest = hashlib.sha256(sequencia.encode("utf-8")).hexdigest()
            motivo = ""
            if not sequencia:
                motivo = "sequencia_vazia"
            elif len(sequencia) > max_residuos:
                motivo = f"mais_de_{max_residuos}_residuos"
            elif not set(sequencia).issubset(ALFABETO):
                motivo = "caracteres_nao_suportados:" + "".join(sorted(set(sequencia) - ALFABETO))
            elif digest in hashes:
                motivo = "sequencia_identica_a_outro_representante_da_amostra"
            if motivo:
                descartes.append({"id": identificador, "motivo": motivo, "tamanho": len(sequencia)})
            else:
                hashes.add(digest)
                amostra.append({
                    "id": identificador,
                    "grupo": candidatos[identificador],
                    "arquivo_origem": fonte_gz.nome,
                    "descricao": descricao,
                    "tamanho": len(sequencia),
                    "sha256_sequencia": digest,
                    "stops_finais_removidos": stops_removidos,
                    "sequencia": sequencia,
                })
            if len(amostra) >= quantidade or not pendentes:
                break
        else:
            leitura_completa = True
    if not amostra:
        raise ValueError("Nenhum representante utilizavel foi recuperado. Confira os IDs e os descartes: "
                         + json.dumps(descartes[:5], ensure_ascii=False))
    ordem = {identificador: i for i, identificador in enumerate(candidatos)}
    amostra.sort(key=lambda item: ordem[item["id"]])
    estatisticas = {
        "candidatos_csv": len(candidatos),
        "representantes_avaliados": avaliados,
        "candidatos_nao_avaliados": len(pendentes),
        "sequencias_fasta_lidas": lidos,
        "sequencias_descartadas": len(descartes),
        "leitura_gz_ate_fim": leitura_completa,
        "integridade_gz_e_membro_zip_validada": leitura_completa,
        "segundos_preparacao": round(time.perf_counter() - inicio, 3),
    }
    return amostra, descartes, estatisticas


def salvar_csv(caminho, linhas, colunas):
    with caminho.open("w", encoding="utf-8-sig", newline="") as saida:
        escritor = csv.DictWriter(saida, fieldnames=colunas, delimiter=";")
        escritor.writeheader()
        escritor.writerows(linhas)


def exigir_gpu(threads, cache):
    for nome in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[nome] = str(threads)
    import torch
    from transformers import AutoTokenizer, EsmModel
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA indisponivel. Execute com .venv\\Scripts\\python.exe. Nao ha fallback para CPU.")
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)
    dispositivo = torch.device("cuda:0")
    torch.cuda.set_device(dispositivo)
    if torch.arange(4, device=dispositivo).sum().item() != 6:
        raise RuntimeError("A verificacao CUDA falhou.")
    comum = {"revision": REVISAO, "cache_dir": str(cache.resolve()),
             "local_files_only": True, "trust_remote_code": False}
    print("Carregando o ESM-2 existente na GPU; nenhum download sera feito.", flush=True)
    inicio = time.perf_counter()
    tokenizador = AutoTokenizer.from_pretrained(MODELO, **comum)
    modelo = EsmModel.from_pretrained(MODELO, add_pooling_layer=False,
                                    attn_implementation="eager", use_safetensors=True,
                                    **comum).float().to(dispositivo).eval()
    torch.cuda.synchronize()
    if next(modelo.parameters()).device.type != "cuda":
        raise RuntimeError("O modelo nao esta na GPU.")
    diagnostico = {"pytorch": torch.__version__, "cuda_compilada": torch.version.cuda,
                  "dispositivo": str(dispositivo), "gpu": torch.cuda.get_device_name(dispositivo),
                  "vram_total_mb": round(torch.cuda.get_device_properties(dispositivo).total_memory / 1024**2, 1),
                  "segundos_carregamento_modelo": round(time.perf_counter() - inicio, 3)}
    return torch, tokenizador, modelo, dispositivo, diagnostico


def gerar_embeddings(torch, tokenizador, modelo, dispositivo, amostra):
    import numpy as np
    vetores = []

    def inferir(sequencia):
        entradas = tokenizador(sequencia, return_tensors="pt", return_special_tokens_mask=True,
                               return_token_type_ids=False, truncation=False)
        especiais = entradas.pop("special_tokens_mask").to(dispositivo)
        entradas = {nome: valor.to(dispositivo) for nome, valor in entradas.items()}
        mascara = (entradas["attention_mask"] * (1 - especiais)).bool()
        if int(mascara.sum().item()) != len(sequencia):
            raise RuntimeError("O tokenizer nao preservou um token por residuo.")
        estados = modelo(**entradas).last_hidden_state
        vetor = estados[0, mascara[0]].mean(dim=0)
        if vetor.device.type != "cuda" or vetor.numel() != 320 or not torch.isfinite(vetor).all().item():
            raise RuntimeError("Embedding invalido; esperado vetor finito de 320 valores na GPU.")
        return vetor.detach().cpu().numpy().astype(np.float32, copy=False)

    torch.cuda.reset_peak_memory_stats(dispositivo)
    with torch.inference_mode():
        inferir(amostra[0]["sequencia"])  # Aquecimento excluido do tempo medido.
        torch.cuda.synchronize()
        inicio = time.perf_counter()
        for indice, item in enumerate(amostra, 1):
            vetores.append(inferir(item["sequencia"]))
            if indice % 10 == 0 or indice == len(amostra):
                print(f"GPU: {indice}/{len(amostra)} embeddings gerados.", flush=True)
        torch.cuda.synchronize()
        segundos = time.perf_counter() - inicio
    matriz = np.stack(vetores)
    return matriz, {"segundos_embeddings_apos_aquecimento": round(segundos, 3),
                    "memoria_pico_pytorch_mb": round(torch.cuda.max_memory_allocated(dispositivo) / 1024**2, 1),
                    "dimensao_embedding": int(matriz.shape[1]), "precisao": "float32", "lote": 1}


def main(argv=None):
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listar", action="store_true", help="Lista os pares disponiveis; nao executa o modelo.")
    parser.add_argument("--fontes", nargs="+", type=Path, default=[PROJETO / "dados", pasta_downloads()],
                        help="Pastas a pesquisar; padrao: dados do projeto e Downloads do Windows.")
    parser.add_argument("--par", type=int, help="Numero do par mostrado por --listar.")
    parser.add_argument("--gz", type=Path, help="Alternativa: caminho de um .gz ja extraido do ZIP.")
    parser.add_argument("--csv", type=Path, help="Alternativa: caminho do CSV correspondente ja extraido do ZIP.")
    parser.add_argument("--saida", type=Path, default=PROJETO / "dados" / "amostra" / "piloto_gpu_01")
    parser.add_argument("--max-representantes", type=int, default=100)
    parser.add_argument("--max-candidatos", type=int, default=1000,
                        help="Limite de grupos a considerar no CSV, para manter memoria limitada.")
    parser.add_argument("--max-residuos", type=int, default=512,
                        help="Descarta sequencias maiores; nao corta sequencias silenciosamente.")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--cache", type=Path, default=PROJETO / "cache" / "huggingface")
    args = parser.parse_args(argv)
    if (args.gz is None) != (args.csv is None):
        parser.error("Use --gz e --csv juntos.")
    if args.gz is not None and (args.par is not None or args.listar):
        parser.error("Use caminhos --gz/--csv ou --par/--listar, sem mistura-los.")
    if not 1 <= args.max_representantes <= 1000:
        parser.error("Este piloto aceita de 1 a 1000 representantes.")
    if not args.max_representantes <= args.max_candidatos <= 10000:
        parser.error("--max-candidatos deve estar entre --max-representantes e 10000.")
    if not 1 <= args.max_residuos <= 1022 or not 1 <= args.threads <= 4:
        parser.error("Use --max-residuos entre 1 e 1022 e --threads entre 1 e 4.")

    relatorio = {"tipo": "piloto_embeddings_proteinas_reais", "ok": False,
                 "treinamento_realizado": False, "modelo": MODELO, "revisao": REVISAO,
                 "threads_cpu_pytorch": args.threads, "max_residuos": args.max_residuos,
                 "representantes_solicitados": args.max_representantes}
    pasta_saida = None
    etapa = "localizar_dados"
    try:
        if args.gz is None:
            pares, avisos = encontrar_pares(args.fontes)
            for aviso in avisos:
                print("Aviso:", aviso, flush=True)
            if not pares:
                raise ValueError("Nenhum par encontrado. Procure .gz e .csv de mesmo nome-base em "
                                 "dados/Downloads, ou use --fontes PASTA. Tambem pode usar --gz e --csv.")
            if args.listar or args.par is None:
                print("Pares encontrados (menor .gz primeiro):", flush=True)
                for numero, (gz, tabela) in enumerate(pares, 1):
                    print(f"\nPar {numero}: {gz.nome} ({gz.tamanho / 1024**2:.1f} MiB comprimidos)")
                    print("  GZ :", gz.local)
                    print("  CSV:", tabela.local)
                print("\nExecute novamente com --par NUMERO para gerar a amostra e os embeddings.")
                return 0
            if not 1 <= args.par <= len(pares):
                raise ValueError(f"Par invalido: escolha de 1 a {len(pares)}.")
            fonte_gz, fonte_csv = pares[args.par - 1]
        else:
            gz = args.gz.expanduser().resolve()
            tabela = args.csv.expanduser().resolve()
            if not gz.is_file() or not tabela.is_file():
                raise FileNotFoundError("O .gz ou o CSV indicado nao existe.")
            if gz.suffix.lower() != ".gz" or tabela.suffix.lower() != ".csv":
                raise ValueError("--gz e --csv devem apontar para arquivos .gz e .csv.")
            fonte_gz = Fonte(gz, tamanho=gz.stat().st_size)
            fonte_csv = Fonte(tabela, tamanho=tabela.stat().st_size)
        pasta = args.saida.expanduser().resolve()
        if pasta.exists() and (not pasta.is_dir() or any(pasta.iterdir())):
            raise ValueError(f"A pasta de saida ja contem arquivos: {pasta}. Use outra --saida para preservar os resultados.")
        relatorio.update({"fonte_gz": fonte_gz.local, "fonte_csv": fonte_csv.local})
        print("GZ selecionado:", fonte_gz.local, flush=True)
        print("CSV selecionado:", fonte_csv.local, flush=True)
        etapa = "carregar_representantes_csv"
        candidatos = carregar_candidatos(fonte_csv, fonte_gz.nome, args.max_candidatos)
        etapa = "carregar_modelo_cuda"
        torch, tokenizador, modelo, dispositivo, diagnostico = exigir_gpu(args.threads, args.cache)
        relatorio.update(diagnostico)
        pasta.mkdir(parents=True, exist_ok=True)
        pasta_saida = pasta
        etapa = "recuperar_sequencias"
        print(f"Buscando ate {args.max_representantes} representantes entre {len(candidatos)} candidatos.", flush=True)
        amostra, descartes, estatisticas = preparar_amostra(fonte_gz, candidatos,
                                                          args.max_representantes, args.max_residuos)
        relatorio.update(estatisticas)
        relatorio.update({"quantidade_amostra": len(amostra),
                          "amostra_completa": len(amostra) == args.max_representantes})
        colunas = ["id", "grupo", "arquivo_origem", "descricao", "tamanho", "sha256_sequencia",
                   "stops_finais_removidos", "sequencia"]
        salvar_csv(pasta / "amostra.csv", amostra, colunas)
        salvar_csv(pasta / "descartes.csv", descartes, ["id", "motivo", "tamanho"])
        with (pasta / "amostra.fasta").open("w", encoding="utf-8") as saida:
            for item in amostra:
                saida.write(f'>{item["descricao"]}\n{item["sequencia"]}\n')
        etapa = "gerar_embeddings_cuda"
        matriz, desempenho = gerar_embeddings(torch, tokenizador, modelo, dispositivo, amostra)
        import numpy as np
        np.save(pasta / "embeddings.npy", matriz, allow_pickle=False)
        relatorio.update(desempenho)
        relatorio.update({"ok": True, "formato_embeddings": list(matriz.shape), "pasta_saida": str(pasta),
                          "ordem_embeddings": "Mesma ordem das linhas de amostra.csv e registros de amostra.fasta."})
        if not relatorio["amostra_completa"]:
            print(f"Aviso: recuperados {len(amostra)} representantes, abaixo do limite solicitado.", flush=True)
    except Exception as erro:
        relatorio.update({"etapa_erro": etapa, "erro": f"{type(erro).__name__}: {erro}"})
    texto = json.dumps(relatorio, ensure_ascii=False, indent=2)
    if pasta_saida is not None:
        (pasta_saida / "relatorio.json").write_text(texto, encoding="utf-8")
    print(texto)
    return 0 if relatorio["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
