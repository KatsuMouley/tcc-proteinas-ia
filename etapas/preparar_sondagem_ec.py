"""Seleciona IDs de treino/validacao para a futura sondagem EC 2 x EC 3."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import random
import re
import shutil
import sys
import tempfile
import uuid

MODELO = "facebook/esm2_t6_8M_UR50D"
REVISAO = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
COLUNAS = ("indice_global", "uid", "id_original", "grupo_global", "particao",
           "tamanho", "sha256_sequencia", "arquivo_origem")
CONJUNTOS = ("treino", "validacao", "teste")


def exigir(condicao, mensagem):
    if not condicao:
        raise ValueError(mensagem)


def sha_arquivo(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_json(path):
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def formato_id(identificador):
    if re.fullmatch(r"(?:NP|XP|YP|WP|AP|ZP)_\d+\.\d+", identificador):
        return "compativel_RefSeq_protein"
    if re.fullmatch(r"[A-Z]{3}\d+\.\d+", identificador):
        return "compativel_INSDC_protein_id"
    return "outro_formato_a_conferir"


def preparar(projeto, quantidade=500, semente=42, progresso=print):
    exigir(type(quantidade) is int and 1 <= quantidade <= 5000,
           "A quantidade deve ser um inteiro entre 1 e 5000.")
    projeto = Path(projeto).resolve()
    base = projeto / "dados/base_ia/base_1m"
    particoes = projeto / "dados/base_ia/particoes_1m"
    arquivos = {
        "indice.csv": base / "indice.csv",
        "particoes.csv": particoes / "particoes.csv",
        "relatorio_consolidacao.json": base / "relatorio_consolidacao.json",
        "relatorio_particoes.json": particoes / "relatorio_particoes.json",
    }
    for path in arquivos.values():
        exigir(path.is_file(), f"Arquivo necessario nao encontrado: {path}")
    marcas = {nome: (p.stat().st_size, p.stat().st_mtime_ns) for nome, p in arquivos.items()}
    r = ler_json(arquivos["relatorio_consolidacao.json"])
    s = ler_json(arquivos["relatorio_particoes.json"])
    exigir(r.get("ok") is True and r.get("tipo") == "base_ia_consolidada",
           "O relatorio de consolidacao nao esta aprovado.")
    total = r.get("proteinas")
    exigir(type(total) is int and total > 0, "Total de proteinas invalido.")
    exigir(r.get("modelo") == MODELO and r.get("revisao") == REVISAO
           and r.get("formato_embeddings") == [total, 320],
           "O modelo, revisao ou formato declarado dos embeddings diverge do experimento.")
    exigir(s.get("ok") is True and s.get("tipo") == "particoes_por_grupos_globais"
           and s.get("proteinas") == total and s.get("grupos_compartilhados_entre_particoes") == 0,
           "O relatorio de particoes nao corresponde a uma separacao aprovada por grupos.")
    exigir(Path(s["base_consolidada"]).resolve() == base,
           "As particoes registradas pertencem a outra base consolidada.")

    gerador = random.Random(semente)
    amostra = []
    contagens = Counter({nome: 0 for nome in CONJUNTOS})
    elegiveis = 0
    lidas = 0
    with arquivos["indice.csv"].open(encoding="utf-8-sig", newline="") as f, \
         arquivos["particoes.csv"].open(encoding="utf-8-sig", newline="") as g:
        indice = csv.DictReader(f, delimiter=";", strict=True)
        particao = csv.DictReader(g, delimiter=";", strict=True)
        exigir(set(COLUNAS) - {"grupo_global", "particao"} <= set(indice.fieldnames or ()),
               "Colunas obrigatorias ausentes em indice.csv.")
        exigir({"indice_global", "uid", "grupo_global", "particao"} <= set(particao.fieldnames or ()),
               "Colunas obrigatorias ausentes em particoes.csv.")
        for i, (a, b) in enumerate(zip_longest(indice, particao)):
            exigir(a is not None and b is not None and i < total,
                   "Os dois CSVs possuem tamanhos divergentes do relatorio.")
            esperado = f"p{i:09d}"
            exigir(int(a["indice_global"]) == int(b["indice_global"]) == i
                   and a["uid"] == b["uid"] == esperado,
                   f"Indice/UID fora de ordem ou sem correspondencia na linha {i}.")
            nome = b["particao"]
            exigir(nome in CONJUNTOS, f"Particao desconhecida na linha {i}: {nome}")
            contagens[nome] += 1
            lidas += 1
            if lidas % 100000 == 0:
                progresso(f"Selecao: {lidas}/{total} linhas; {elegiveis} elegiveis ate aqui.")
            if nome == "teste":
                continue
            exigir(a["id_original"] and a["id_original"] == a["id_original"].strip(),
                   f"ID original vazio ou com espacos externos na linha {i}.")
            tamanho = int(a["tamanho"])
            exigir(1 <= tamanho <= 512, f"Comprimento fora do recorte da base na linha {i}.")
            exigir(re.fullmatch(r"[a-f0-9]{64}", a["sha256_sequencia"]) is not None,
                   f"Hash de sequencia invalido na linha {i}.")
            exigir(re.fullmatch(r"p\d{9}", b["grupo_global"]) is not None,
                   f"Grupo global invalido na linha {i}.")
            linha = {chave: a[chave] for chave in COLUNAS
                     if chave not in ("grupo_global", "particao")}
            linha.update(grupo_global=b["grupo_global"], particao=nome)
            elegiveis += 1
            if len(amostra) < quantidade:
                amostra.append(linha)
            else:
                posicao = gerador.randrange(elegiveis)
                if posicao < quantidade:
                    amostra[posicao] = linha
    exigir(lidas == total and elegiveis > 0, "Total divergente ou nenhum registro de treino/validacao.")
    for nome in CONJUNTOS:
        exigir(contagens[nome] == s["particoes"][nome]["proteinas"],
               f"A contagem da particao {nome} diverge do relatorio.")

    progresso("Conferindo os hashes dos CSVs; os vetores nao serao carregados.")
    hashes = {nome: sha_arquivo(p) for nome, p in arquivos.items()}
    exigir(hashes["indice.csv"] == r["hashes_arquivos"]["indice.csv"],
           "indice.csv diverge do hash da consolidacao; nenhuma saida foi criada.")
    exigir(hashes["particoes.csv"] == s["hashes_arquivos"]["particoes.csv"],
           "particoes.csv diverge do hash registrado; nenhuma saida foi criada.")
    exigir(all((p.stat().st_size, p.stat().st_mtime_ns) == marcas[nome]
               for nome, p in arquivos.items()),
           "Um arquivo de entrada mudou durante a leitura; nenhuma saida foi criada.")
    amostra.sort(key=lambda linha: int(linha["indice_global"]))
    exigir(all(linha["particao"] in ("treino", "validacao") for linha in amostra),
           "A selecao incluiu teste; nenhuma saida foi criada.")
    ids = list(dict.fromkeys(linha["id_original"] for linha in amostra))

    pai = projeto / "dados/piloto_ec2_ec3"
    exigir(not pai.is_symlink() and pai.resolve().is_relative_to(projeto),
           "A pasta de saida nao pode redirecionar para fora do projeto.")
    pai.mkdir(parents=True, exist_ok=True)
    nome = datetime.now(timezone.utc).strftime("sondagem_ids_%Y%m%dT%H%M%S%fZ_") + uuid.uuid4().hex[:6]
    saida = pai / nome
    temporario = Path(tempfile.mkdtemp(prefix=".preparando_ids_", dir=pai))
    try:
        with (temporario / "candidatos.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUNAS, delimiter=";")
            w.writeheader()
            w.writerows(amostra)
        (temporario / "ids_ncbi.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
        relatorio = {
            "tipo": "preparacao_sondagem_ec2_ec3", "schema": 1, "ok": True,
            "status": "ids_selecionados_anotacoes_ec_pendentes",
            "quantidade_solicitada": quantidade, "selecionados": len(amostra),
            "ids_originais_unicos": len(ids), "amostra_completa": len(amostra) == quantidade,
            "semente": semente, "python": sys.version.split()[0],
            "metodo": "Reservatorio uniforme por sequencia em treino/validacao; nao estratificado por EC; grupos podem repetir.",
            "linhas_examinadas": lidas, "contagens_originais_conferidas": dict(contagens),
            "elegiveis_treino_validacao": elegiveis,
            "selecionados_por_particao": {n: sum(x["particao"] == n for x in amostra) for n in CONJUNTOS},
            "grupos_distintos_selecionados": len({x["grupo_global"] for x in amostra}),
            "formatos_ids": dict(Counter(formato_id(x) for x in ids)),
            "modelo_embeddings": MODELO, "revisao_embeddings": REVISAO,
            "hashes_entradas_conferidos": hashes,
            "sha256_candidatos_csv": sha_arquivo(temporario / "candidatos.csv"),
            "pasta_saida": str(saida), "arquivo_candidatos": str(saida / "candidatos.csv"),
            "arquivo_ids": str(saida / "ids_ncbi.txt"),
            "originais_alterados": False, "embeddings_lidos": False,
            "gpu_utilizada": False, "consulta_uniprot_realizada": False,
            "predicoes_teste_lidas": False, "treinamento_realizado": False,
            "resultados_ec2_ec3": None, "enzimas_ec_descartadas_mais_512": None,
            "limite": "A base ja foi filtrada em 1-512 residuos. Esta etapa nao mede EC nos descartes historicos nem rotula proteinas.",
        }
        (temporario / "relatorio_preparacao.json").write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.rename(saida)
    except BaseException:
        shutil.rmtree(temporario, ignore_errors=True)
        raise
    return relatorio


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--projeto", type=Path, default=Path.cwd(), help="Raiz do projeto existente.")
    p.add_argument("--quantidade", type=int, default=500, help="IDs candidatos solicitados, de 1 a 5000.")
    p.add_argument("--semente", type=int, default=42)
    args = p.parse_args(argv)
    try:
        r = preparar(args.projeto, args.quantidade, args.semente)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(json.dumps({"ok": False, "erro": str(e), "originais_alterados": False}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
