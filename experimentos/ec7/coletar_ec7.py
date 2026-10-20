"""EXPERIMENTO EC7: baixa e audita enzimas revisadas do Swiss-Prot das classes EC 1 a 7.

Copia generalizada de etapas/baixar_piloto_swissprot_ec.py (o original nao e alterado).
Saida: dados/experimento_ec7/swissprot_.../  Sem gerar vetores ou treinar.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import uuid

import sys as _sys
_AQUI = Path(__file__).resolve().parent
_sys.path.insert(0, str(_AQUI))
_sys.path.insert(1, str(_AQUI.parents[1] / "etapas"))
import ec7_comum  # noqa: E402  (aplica os rotulos das 7 classes ao cliente UniProt)
try:
    import consultar_sondagem_ec as api
except ImportError as e:
    raise SystemExit("Falta etapas/consultar_sondagem_ec.py da consulta EC ja instalada. "
                     "Mantenha os dois scripts na mesma pasta etapas/.") from e

REVISAO = 1
ALFABETO = frozenset("ACDEFGHIKLMNPQRSTVWYBXZUO")
CLASSES = ec7_comum.CODIGOS
CONSULTAS = {c: f"(reviewed:true) AND (ec:{c}.-.-.-)" for c in CLASSES}


def exigir(condicao, mensagem):
    if not condicao:
        raise ValueError(mensagem)


def parametros_validos(por_classe, candidatos_por_classe, semente):
    exigir(type(por_classe) is int and 1 <= por_classe <= 2000,
           "--por-classe deve ser um inteiro entre 1 e 2000.")
    exigir(type(candidatos_por_classe) is int and por_classe <= candidatos_por_classe <= 5000,
           "--candidatos-por-classe deve estar entre --por-classe e 5000.")
    exigir(type(semente) is int, "A semente deve ser inteira.")
    exigir(getattr(api, "REVISAO_CLIENTE", 0) >= 2,
           "Atualize consultar_sondagem_ec.py para a revisao 2 antes desta coleta.")


def ajustar_tamanho(url, quantidade):
    api.url_segura(url)
    p = urlsplit(url)
    params = dict(parse_qsl(p.query))
    params.update(format="json", size=str(min(500, quantidade)))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(params), ""))


def buscar_classe(cliente, classe, limite, progresso=print):
    params = {"query": CONSULTAS[classe], "format": "json", "size": min(500, limite),
              "sort": "accession asc"}
    endereco = api.API + "/uniprotkb/search?" + urlencode(params)
    linhas, visitados, acessions = [], set(), set()
    total, anterior = None, ""
    while endereco:
        exigir(endereco not in visitados, "URL repetida na paginacao Swiss-Prot.")
        visitados.add(endereco)
        dados, headers = cliente.pedir(endereco)
        exigir(isinstance(dados.get("results"), list), "Pagina sem lista results; coleta incompleta.")
        valor = headers.get("x-total-results", "")
        exigir(isinstance(valor, str) and valor.isdigit(),
               "Header x-total-results ausente ou invalido; nao concluir cobertura zero.")
        observado = int(valor)
        exigir(total in (None, observado), "O total de resultados mudou durante a coleta.")
        total = observado
        resultados = dados["results"]
        exigir(len(resultados) <= min(500, limite - len(linhas)),
               "A API excedeu o tamanho de pagina solicitado.")
        for entrada in resultados:
            exigir(isinstance(entrada, dict), "Entrada Swiss-Prot com formato invalido.")
            acc = entrada.get("primaryAccession", "")
            exigir(isinstance(acc, str) and re.fullmatch(r"[A-Z0-9]{6,10}", acc),
                   "Entrada sem primaryAccession valida.")
            exigir(acc not in acessions and acc > anterior,
                   "Accessions repetidas ou fora da ordem solicitada; paginacao inconsistente.")
            acessions.add(acc)
            anterior = acc
            linhas.append(entrada)
        meta = {"classe_consultada": classe, "query": CONSULTAS[classe], "ordem": "accession asc",
                "total_reportado_api": total, "candidatos_baixados": len(linhas),
                "limite_candidatos": limite, "consulta_esgotada": len(linhas) == total,
                "paginas": len(visitados)}
        exigir(len(linhas) <= total, "A pagina excedeu o total declarado da consulta.")
        progresso(f"Swiss-Prot EC {classe}: {len(linhas)}/{min(limite, total)} candidatos baixados.")
        if len(linhas) == min(limite, total):
            return linhas, meta
        exigir(resultados, "Pagina vazia antes do total esperado; coleta incompleta.")
        proxima = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("link", ""))
        exigir(proxima is not None, "A API encerrou as paginas antes do total esperado; coleta incompleta.")
        endereco = ajustar_tamanho(urljoin(endereco, proxima.group(1)), limite - len(linhas))
    raise ValueError("Consulta terminou sem contabilizacao final.")


def preparar_registro(entrada, consultas):
    acc = entrada["primaryAccession"]
    exigir(entrada.get("entryType") in (api.REVISADO, api.NAO_REVISADO),
           f"Tipo de entrada desconhecido em {acc}.")
    seq = entrada.get("sequence", {}).get("value")
    exigir(isinstance(seq, str), f"Sequencia ausente em {acc}; resposta incompleta.")
    seq = seq.upper()
    exigir(entrada["sequence"].get("length") == len(seq), f"Comprimento inconsistente em {acc}.")
    ecs, evidencias = api.extrair_ecs(entrada)
    interpretaveis = bool(ecs) and all(api.EC_VALIDO.fullmatch(ec) for ec in ecs)
    classes = {ec.split(".")[0] for ec in ecs if api.EC_VALIDO.fullmatch(ec)}
    classe = next(iter(classes)) if interpretaveis and len(classes) == 1 and classes <= set(CLASSES) else ""
    motivos = []
    if entrada["entryType"] != api.REVISADO:
        motivos.append("entrada_nao_revisada")
    if not ecs:
        motivos.append("sem_ec_explicito")
    elif not interpretaveis:
        motivos.append("ec_nao_interpretavel")
    elif len(classes) > 1:
        motivos.append("ec_multiclasse")
    elif not classe:
        motivos.append("ec_fora_do_alvo")
    if not seq:
        motivos.append("sequencia_vazia")
    if len(seq) > 512:
        motivos.append("mais_de_512_residuos")
    if not set(seq) <= ALFABETO:
        motivos.append("caracteres_nao_suportados")
    nome = entrada.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value", "")
    return {"id_original": acc, "classe_ec": classe, "rotulo_ec": api.ROTULOS.get(classe, ""),
            "ecs_uniprot": "|".join(ecs), "classes_ec_anotadas": "|".join(sorted(classes)),
            "ec_parcial": any(not all(v.isdigit() for v in ec.split(".")) for ec in ecs),
            "revisado": entrada["entryType"] == api.REVISADO,
            "tamanho": len(seq), "sha256_sequencia": hashlib.sha256(seq.encode("utf-8")).hexdigest(),
            "sequencia": seq, "nome_proteina": nome,
            "organismo": entrada.get("organism", {}).get("scientificName", ""),
            "taxon_id": entrada.get("organism", {}).get("taxonId", ""),
            "consultas_ec_origem": "|".join(sorted(consultas)),
            "fonte": f"https://www.uniprot.org/uniprotkb/{acc}/entry",
            "evidencias_ec_json": json.dumps(evidencias, ensure_ascii=False),
            "motivos": motivos, "status_coleta": "pendente", "accession_representante": acc,
            "accessions_mesma_sequencia": acc}


def auditar_e_selecionar(por_consulta, por_classe, semente):
    # A mesma accession pode aparecer em mais de uma consulta EC.
    entradas, origens = {}, defaultdict(set)
    for classe in CLASSES:
        for entrada in por_consulta[classe]:
            acc = entrada["primaryAccession"]
            assinatura = json.dumps(entrada, sort_keys=True, ensure_ascii=False)
            exigir(acc not in entradas or entradas[acc][1] == assinatura,
                   f"A accession {acc} mudou entre consultas; nao misturar respostas divergentes.")
            entradas[acc] = (entrada, assinatura)
            origens[acc].add(classe)
    auditados = [preparar_registro(entradas[acc][0], origens[acc]) for acc in sorted(entradas)]
    por_hash = defaultdict(list)
    for x in auditados:
        por_hash[x["sha256_sequencia"]].append(x)
    for grupo in por_hash.values():
        # Anotacoes conflitantes para sequencias identicas sao excluidas antes da amostra.
        classes = {c for x in grupo if x["revisado"] for c in x["classes_ec_anotadas"].split("|") if c}
        if len(classes) > 1:
            for x in grupo:
                x["motivos"].append("classes_conflitantes_na_mesma_sequencia")
        elegiveis = [x for x in grupo if not x["motivos"]]
        if elegiveis:
            representante = min(elegiveis, key=lambda x: x["id_original"])
            accessions = "|".join(sorted(x["id_original"] for x in elegiveis))
            for x in elegiveis:
                x["accession_representante"] = representante["id_original"]
                x["accessions_mesma_sequencia"] = accessions
                if x is not representante:
                    x["motivos"].append("sequencia_duplicada")
    elegiveis = [x for x in auditados if not x["motivos"]]
    escolhidos = set()
    for classe in CLASSES:
        candidatos = [x for x in elegiveis if x["classe_ec"] == classe]
        candidatos.sort(key=lambda x: (hashlib.sha256(
            f"{semente}:{x['sha256_sequencia']}".encode()).hexdigest(), x["id_original"]))
        escolhidos.update(x["id_original"] for x in candidatos[:por_classe])
    selecionados = []
    for x in auditados:
        x["status_coleta"] = ("excluido" if x["motivos"] else
                              "selecionado" if x["id_original"] in escolhidos else "elegivel_fora_da_amostra")
        x["motivos_exclusao"] = "|".join(x.pop("motivos"))
        if x["status_coleta"] == "selecionado":
            selecionados.append(x)
    selecionados.sort(key=lambda x: x["sha256_sequencia"])
    linhas = [{"indice_global": i, "uid": f"ec{i:09d}", **x} for i, x in enumerate(selecionados)]
    return auditados, linhas


def comprimentos(linhas):
    valores = [x["tamanho"] for x in linhas]
    return {"quantidade": len(valores), "minimo": min(valores) if valores else None,
            "mediana": statistics.median(valores) if valores else None,
            "maximo": max(valores) if valores else None,
            "menos_de_30": sum(v < 30 for v in valores)}


def coletar(projeto, por_classe=500, candidatos_por_classe=2000, semente=42,
            timeout=30, progresso=print, cliente_factory=api.ClienteUniProt):
    parametros_validos(por_classe, candidatos_por_classe, semente)
    timeout = api.positivo(str(timeout))
    projeto = Path(projeto).resolve()
    exigir(projeto.is_dir(), "A pasta do projeto nao existe.")
    pai = projeto / "dados/experimento_ec7"
    exigir(pai.resolve().is_relative_to(projeto), "A saida redireciona para fora do projeto.")
    pai.mkdir(parents=True, exist_ok=True)
    saida = pai / (datetime.now(timezone.utc).strftime("swissprot_%Y%m%dT%H%M%S%fZ_") + uuid.uuid4().hex[:6])
    saida.mkdir()
    bruto = saida / "respostas_api"
    bruto.mkdir()
    rel = {"tipo": "coleta_swissprot_ec7", "schema": 1, "revisao_coletor": REVISAO,
           "ok": False, "status": "coleta_em_andamento", "iniciada_em_utc": api.agora(),
           "pasta_saida": str(saida), "meta_por_classe": por_classe,
           "limite_candidatos_por_consulta": candidatos_por_classe, "semente": semente,
           "consultas": CONSULTAS, "comprimento_permitido": [1, 512],
           "metodo_selecao": "Primeiros candidatos por accession asc de cada consulta, limitados pelo protocolo; "
                              "apos filtros e deduplicacao, menor SHA256(semente:hash_da_sequencia) por classe.",
           "amostra_aleatoria_de_todo_swissprot": False,
           "modelo_embeddings_planejado": api.MODELO, "revisao_embeddings_planejada": api.REVISAO,
           "embeddings_gerados": False, "gpu_utilizada": False, "agrupamento_global": "pendente",
           "particoes_por_grupos": "pendente", "teste_historico_consultado": False,
           "treinamento_realizado": False, "treinamento_liberado": False,
           "originais_alterados": False, "rotulos_selecionados": None,
           "exclusoes_comprimento": None,
           "limites": ["O piloto nao e uma amostra aleatoria de todo o Swiss-Prot nem do NCBI.",
               "Anotacao revisada pode conter evidencia por inferencia; nao equivale a ensaio experimental proprio.",
               "As contagens de descartes referem-se somente aos candidatos baixados nesta coleta.",
               "Experimento separado: classificador das 7 classes EC; nao substitui o modelo EC 2 x EC 3 do painel.",
               "EC 7 (translocases) e outras classes podem ficar abaixo da meta por classe; o treino usa pesos por classe.",
               "Agrupar e separar por grupos antes do treino; reservar o teste ate o protocolo estar fechado."]}
    api.salvar_json(saida / "relatorio_coleta.json", rel)
    try:
        cliente = cliente_factory(bruto, timeout=timeout, progresso=progresso)
        por_consulta, metas = {}, {}
        for classe in CLASSES:
            por_consulta[classe], metas[classe] = buscar_classe(cliente, classe, candidatos_por_classe, progresso)
        releases = sorted({m["headers"]["x-uniprot-release"] for m in cliente.metadados
                           if m["headers"].get("x-uniprot-release")})
        exigir(len(releases) <= 1, "O release UniProt mudou entre as paginas; repetir a coleta em nova pasta.")
        auditados, selecionados = auditar_e_selecionar(por_consulta, por_classe, semente)
        exigir(len({x["sha256_sequencia"] for x in selecionados}) == len(selecionados),
               "Sequencia duplicada na selecao final.")
        exigir(all(x["revisado"] and x["classe_ec"] in CLASSES
                   and 1 <= x["tamanho"] <= 512 and not x["motivos_exclusao"] for x in selecionados),
               "A selecao final violou os criterios.")
        colunas = list(auditados[0]) if auditados else ["id_original", "classe_ec", "rotulo_ec", "tamanho",
            "sha256_sequencia", "sequencia", "motivos_exclusao", "status_coleta"]
        api.salvar_csv(saida / "candidatos_auditados.csv", auditados, colunas)
        api.salvar_csv(saida / "piloto_rotulado.csv", selecionados, ["indice_global", "uid", *colunas])
        with (saida / "sequencias.fasta").open("w", encoding="utf-8", newline="\n") as f:
            for x in selecionados:
                f.write(f">{x['uid']}\n{x['sequencia']}\n")
        contagens = {api.ROTULOS[c]: sum(x["classe_ec"] == c for x in selecionados) for c in CLASSES}
        completa = all(n == por_classe for n in contagens.values())
        rel.update(ok=True, status="coleta_completa_preparacao_ia_pendente" if completa else
                   "coleta_concluida_amostra_menor_que_a_meta", finalizada_em_utc=api.agora(),
            amostra_completa=completa, total_selecionado=len(selecionados), rotulos_selecionados=contagens,
            fontes_por_consulta=metas, uniprot_releases=releases or ["[a confirmar: header ausente]"],
            candidatos_unicos_auditados=len(auditados),
            contagens_por_status=dict(Counter(x["status_coleta"] for x in auditados)),
            exclusoes_por_motivo=dict(Counter(m for x in auditados for m in x["motivos_exclusao"].split("|") if m)),
            motivos_exclusao_podem_sobrepor=True,
            exclusoes_comprimento={"escopo": "candidatos desta coleta, antes da selecao final",
                "candidatos_unicos_mais_512": sum(x["tamanho"] > 512 for x in auditados),
                "enzimas_revisadas_ec_exclusiva_mais_512": {
                    api.ROTULOS[c]: sum(x["revisado"] and x["classe_ec"] == c and x["tamanho"] > 512
                                        for x in auditados) for c in CLASSES},
                "enzimas_ec_nos_descartes_historicos_da_base_1m": None},
            comprimentos_por_classe={api.ROTULOS[c]: comprimentos([x for x in selecionados if x["classe_ec"] == c])
                                     for c in CLASSES},
            grupos_criados=False, particoes_criadas=False, respostas_http=cliente.metadados,
            sha256_coletor=api.sha(Path(__file__)), sha256_cliente_http=api.sha(Path(api.__file__)),
            hashes_saidas={n: api.sha(saida / n) for n in (
                "candidatos_auditados.csv", "piloto_rotulado.csv", "sequencias.fasta")})
        api.salvar_json(saida / "relatorio_coleta.json", rel)
        return rel
    except KeyboardInterrupt:
        rel.update(status="interrompida_coleta_inconclusiva", finalizada_em_utc=api.agora())
        api.salvar_json(saida / "relatorio_coleta.json", rel)
        raise
    except (OSError, ValueError, KeyError, TypeError, api.FalhaConsulta) as e:
        rel.update(status="falha_tecnica_coleta_inconclusiva", erro=str(e), finalizada_em_utc=api.agora())
        api.salvar_json(saida / "relatorio_coleta.json", rel)
        raise api.FalhaConsulta(f"{e}\nArquivos parciais preservados em: {saida}") from e


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--projeto", type=Path, default=_AQUI.parents[1])
    p.add_argument("--por-classe", type=int, default=500)
    p.add_argument("--candidatos-por-classe", type=int, default=3000)
    p.add_argument("--semente", type=int, default=42)
    p.add_argument("--timeout", type=api.positivo, default=30)
    args = p.parse_args(argv)
    try:
        r = coletar(args.projeto, args.por_classe, args.candidatos_por_classe, args.semente, args.timeout)
    except KeyboardInterrupt:
        print("Coleta interrompida; nenhum treinamento iniciado.")
        return 130
    except (OSError, ValueError, KeyError, TypeError, api.FalhaConsulta) as e:
        print(json.dumps({"ok": False, "erro": str(e), "rotulos_selecionados": None,
                          "treinamento_realizado": False}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({k: v for k, v in r.items() if k != "respostas_http"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
