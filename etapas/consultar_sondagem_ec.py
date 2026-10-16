"""Mede cobertura de EC 2/3 no UniProt para uma sondagem de treino/validacao.

Usa somente a biblioteca padrao. Nao abre embeddings, modelos ou o teste.
Cada execucao cria outra pasta; uma falha de rede nao significa ausencia de EC.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

API = "https://rest.uniprot.org"
MODELO = "facebook/esm2_t6_8M_UR50D"
REVISAO = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
COLUNAS = ("indice_global", "uid", "id_original", "grupo_global", "particao",
           "tamanho", "sha256_sequencia", "arquivo_origem")
REVISADO = "UniProtKB reviewed (Swiss-Prot)"
NAO_REVISADO = "UniProtKB unreviewed (TrEMBL)"
EC_VALIDO = re.compile(r"[1-7](?:\.(?:\d+|-|n\d*)){3}")
ROTULOS = {"2": "Transferase", "3": "Hidrolase"}
REVISAO_CLIENTE = 2


class FalhaConsulta(RuntimeError):
    """A cobertura nao pode ser concluida por uma falha tecnica."""


def exigir(condicao, mensagem):
    if not condicao:
        raise ValueError(mensagem)


def agora():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def salvar_json(path, dados):
    temporario = path.with_suffix(path.suffix + ".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(path)


def namespace(identificador):
    if re.fullmatch(r"[A-Z]{3}\d+\.\d+", identificador):
        return "EMBL-GenBank-DDBJ_CDS"
    if re.fullmatch(r"(?:NP|XP|YP|WP|AP|ZP)_\d+\.\d+", identificador):
        return "RefSeq_Protein"
    raise ValueError(f"Formato de ID nao suportado nesta sondagem: {identificador}")


def sem_versao(identificador):
    return re.sub(r"\.\d+$", "", identificador)


def carregar_sondagem(pasta):
    pasta = Path(pasta).resolve()
    caminhos = {n: pasta / n for n in (
        "candidatos.csv", "ids_ncbi.txt", "relatorio_preparacao.json")}
    for path in caminhos.values():
        exigir(path.is_file(), f"Arquivo necessario nao encontrado: {path}")
    marcas = {n: sha(p) for n, p in caminhos.items()}
    r = json.loads(caminhos["relatorio_preparacao.json"].read_text(encoding="utf-8-sig"))
    exigir(r.get("ok") is True and r.get("schema") == 1
           and r.get("tipo") == "preparacao_sondagem_ec2_ec3",
           "O relatorio nao e uma preparacao aprovada da sondagem EC 2/3.")
    exigir(r.get("modelo_embeddings") == MODELO and r.get("revisao_embeddings") == REVISAO,
           "Modelo ou revisao dos embeddings incompativeis.")
    exigir(r.get("sha256_candidatos_csv") == marcas["candidatos.csv"],
           "candidatos.csv diverge do hash da preparacao; consulta bloqueada.")
    with caminhos["candidatos.csv"].open(encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f, delimiter=";", strict=True)
        exigir(set(COLUNAS) <= set(leitor.fieldnames or ()), "Colunas obrigatorias ausentes.")
        linhas = [{c: x[c] for c in COLUNAS} for x in leitor]
    exigir(1 <= len(linhas) <= 5000 and len(linhas) == r.get("selecionados"),
           "Quantidade divergente ou fora do limite de 1 a 5000 candidatos.")
    uids, grupos, ids = set(), {}, {}
    for x in linhas:
        i = int(x["indice_global"])
        exigir(i >= 0 and x["uid"] == f"p{i:09d}" and x["uid"] not in uids,
               "UID/indice invalido ou repetido na sondagem.")
        uids.add(x["uid"])
        exigir(x["particao"] in ("treino", "validacao"),
               "A sondagem contem teste ou particao desconhecida; consulta bloqueada.")
        exigir(re.fullmatch(r"p\d{9}", x["grupo_global"]) is not None,
               "Grupo global invalido.")
        exigir(grupos.setdefault(x["grupo_global"], x["particao"]) == x["particao"],
               "Um grupo aparece em particoes diferentes; consulta bloqueada.")
        exigir(1 <= int(x["tamanho"]) <= 512
               and re.fullmatch(r"[a-f0-9]{64}", x["sha256_sequencia"]) is not None,
               "Comprimento ou hash de sequencia invalido.")
        namespace(x["id_original"])
        assinatura = (x["tamanho"], x["sha256_sequencia"])
        exigir(ids.setdefault(x["id_original"], assinatura) == assinatura,
               "O mesmo ID original tem sequencias divergentes na amostra.")
    exigir(caminhos["ids_ncbi.txt"].read_text(encoding="utf-8-sig").splitlines() == list(ids),
           "ids_ncbi.txt nao corresponde aos IDs e a ordem de candidatos.csv.")
    contagens = {p: sum(x["particao"] == p for x in linhas)
                for p in ("treino", "validacao", "teste")}
    exigir(contagens == r.get("selecionados_por_particao")
           and len(ids) == r.get("ids_originais_unicos")
           and len(grupos) == r.get("grupos_distintos_selecionados"),
           "As contagens da sondagem divergem do relatorio de preparacao.")
    exigir(all(sha(p) == marcas[n] for n, p in caminhos.items()),
           "Uma entrada mudou durante a leitura.")
    return linhas, r, marcas


def url_segura(url):
    p = urlsplit(url)
    exigir(p.scheme == "https" and p.hostname == "rest.uniprot.org"
           and p.port in (None, 443) and not p.username and not p.password,
           "A API retornou um endereco fora de https://rest.uniprot.org; consulta bloqueada.")
    return url


class RedirecionamentoSeguro(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url_segura(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ClienteUniProt:
    def __init__(self, pasta, timeout=30, espera_maxima=600, intervalo=3, progresso=print):
        exigir(all(math.isfinite(v) and v > 0 for v in (timeout, espera_maxima, intervalo)),
               "Timeout, espera maxima e intervalo devem ser positivos e finitos.")
        self.pasta = pasta
        self.timeout, self.espera_maxima, self.intervalo = timeout, espera_maxima, intervalo
        self.progresso = progresso
        self.opener = build_opener(RedirecionamentoSeguro())
        self.numero = 0
        self.metadados = []
        self.sugestoes = []
        self.resumos_jobs = []

    def pedir(self, url, formulario=None):
        url_segura(url)
        dados = urlencode(formulario).encode("utf-8") if formulario is not None else None
        req = Request(url, data=dados, headers={"Accept": "application/json",
            "User-Agent": "TCC-Proteinas-Sondagem-EC/1.0"})
        # POST nao e repetido automaticamente: evita enviar o mesmo job duas vezes.
        tentativas = 1 if formulario is not None else 3
        for tentativa in range(tentativas):
            try:
                with self.opener.open(req, timeout=self.timeout) as resposta:
                    url_segura(resposta.geturl())
                    bruto = resposta.read()
                    corpo = json.loads(bruto.decode("utf-8-sig"))
                    if not isinstance(corpo, dict) or "messages" in corpo:
                        raise FalhaConsulta("A API retornou JSON sem o formato esperado ou uma mensagem de erro.")
                    headers = {k.lower(): v for k, v in resposta.headers.items()
                               if k.lower() in ("date", "link", "x-total-results",
                                                "x-uniprot-release", "x-uniprot-release-date")}
                    envelope = {"url_solicitada": url, "url_final": resposta.geturl(),
                        "metodo": req.get_method(), "consultado_em_utc": agora(),
                        "headers": headers, "sha256_corpo_http": hashlib.sha256(bruto).hexdigest(),
                        "dados": corpo}
                    self.numero += 1
                    # O corpo HTTP exato e o JSON legivel sao guardados para auditoria.
                    nome = f"resposta_{self.numero:04d}"
                    (self.pasta / (nome + ".body.json")).write_bytes(bruto)
                    salvar_json(self.pasta / (nome + ".json"), envelope)
                    self.metadados.append({k: v for k, v in envelope.items() if k != "dados"})
                    return corpo, headers
            except HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or tentativa + 1 == tentativas:
                    raise FalhaConsulta(f"UniProt respondeu HTTP {e.code}. Cobertura EC nao concluida.") from e
                valor = e.headers.get("Retry-After", "") if e.headers else ""
                espera = min(30, max(1, int(valor))) if valor.isdigit() else 2 ** (tentativa + 1)
            except (URLError, TimeoutError, http.client.HTTPException, json.JSONDecodeError,
                    UnicodeDecodeError) as e:
                if tentativa + 1 == tentativas:
                    raise FalhaConsulta(f"Falha de conexao, timeout de {self.timeout:g}s ou resposta invalida do UniProt. "
                                        "Cobertura EC nao concluida; confira a internet e tente novamente.") from e
                espera = 2 ** (tentativa + 1)
            self.progresso(f"Consulta GET interrompida; nova tentativa em {espera}s.")
            time.sleep(espera)

    def mapear(self, origem, ids, modo):
        self.progresso(f"UniProt: {len(ids)} IDs; {origem}; {modo}.")
        resposta, _ = self.pedir(API + "/idmapping/run", {
            "from": origem, "to": "UniProtKB", "ids": ",".join(ids)})
        job = resposta.get("jobId", "")
        exigir(isinstance(job, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job),
               "A API nao retornou um jobId valido.")
        salvar_json(self.pasta / f"job_{job}.json", {"job_id": job, "from": origem,
            "to": "UniProtKB", "modo": modo, "ids": ids, "criado_em_utc": agora()})
        inicio = time.monotonic()
        falhos, sugestoes, obsoletos = [], [], set()

        def auxiliares(payload):
            for campo in ("failedIds", "suggestedIds"):
                exigir(isinstance(payload.get(campo, []), list), f"Lista {campo} invalida na resposta.")
            falhos.extend(payload.get("failedIds", []))
            sugestoes.extend(payload.get("suggestedIds", []))
            if payload.get("obsoleteCount") is not None:
                n = payload["obsoleteCount"]
                exigir(type(n) is int and n >= 0, "obsoleteCount invalido.")
                obsoletos.add(n)
                exigir(len(obsoletos) == 1, "obsoleteCount mudou durante a consulta.")

        def registrar_resumo(mapeados, nao_mapeados, sugeridos, pares):
            self.resumos_jobs.append({"job_id": job, "namespace": origem, "modo": modo,
                "ids_enviados": len(ids), "ids_mapeados_uniprotkb": len(mapeados),
                "ids_failedIds": len(nao_mapeados), "ids_com_sugestao_uniparc": len(sugeridos),
                "ids_contabilizados": len(mapeados | nao_mapeados | sugeridos),
                "pares_sugestoes_uniparc": pares,
                "obsoleteCount": next(iter(obsoletos)) if obsoletos else None})

        while True:
            status, _ = self.pedir(API + "/idmapping/status/" + job)
            estado = status.get("jobStatus")
            if estado in ("RUNNING", "NEW", "PENDING"):
                if time.monotonic() - inicio >= self.espera_maxima:
                    raise FalhaConsulta(f"Job {job} nao terminou em {self.espera_maxima:g}s. "
                                        "Respostas preservadas; cobertura EC nao concluida.")
                self.progresso(f"Job {job}: {estado}; aguardando {self.intervalo:g}s.")
                time.sleep(self.intervalo)
                continue
            if estado not in (None, "FINISHED"):
                raise FalhaConsulta(f"Job {job} terminou com estado {estado!r}; cobertura EC nao concluida.")
            exigir(estado == "FINISHED" or any(c in status for c in ("results", "failedIds", "suggestedIds")),
                   "Resposta de status incompleta; nao sera interpretada como cobertura zero.")
            auxiliares(status)
            break
        # Um job pode terminar sem criar paginas quando todos os IDs falham.
        # Apenas a lista explicita completa permite concluir zero mapeamentos.
        if not status.get("results") and not sugestoes and set(falhos) == set(ids):
            registrar_resumo(set(), set(falhos), set(), 0)
            return []
        detalhe, _ = self.pedir(API + "/idmapping/details/" + job)
        endereco = url_segura(detalhe.get("redirectURL", ""))
        p = urlsplit(endereco)
        params = dict(parse_qsl(p.query))
        params.update(format="json", size="500")
        params.pop("fields", None)  # Precisamos da anotacao e da sequencia completas.
        endereco = urlunsplit((p.scheme, p.netloc, p.path, urlencode(params), ""))
        visitados, resultados, total = set(), [], None
        while endereco:
            exigir(endereco not in visitados, "A paginacao repetiu uma URL; consulta incompleta.")
            visitados.add(endereco)
            pagina, headers = self.pedir(endereco)
            exigir(isinstance(pagina.get("results", []), list)
                   and any(c in pagina for c in ("results", "failedIds", "suggestedIds")),
                   "Pagina sem lista results; nao sera interpretada como cobertura zero.")
            resultados.extend(pagina.get("results", []))
            auxiliares(pagina)
            if "x-total-results" in headers:
                numero = int(headers["x-total-results"])
                exigir(total in (None, numero), "Total de resultados mudou durante a paginacao.")
                total = numero
            proxima = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("link", ""))
            endereco = url_segura(urljoin(endereco, proxima.group(1))) if proxima else None
        exigir(total is None or total == len(resultados),
               "Quantidade recebida diverge do total da API; cobertura incompleta.")

        def resolver(identificador):
            exigir(isinstance(identificador, str), "ID retornado pela API nao e texto.")
            if identificador in ids:
                return [identificador]
            # Alguns servicos devolvem a accession sem versao. A sequencia ainda
            # sera conferida por tamanho E SHA-256; nunca se aceita apenas o ID.
            aliases = [i for i in ids if sem_versao(i) == identificador
                       or (i == sem_versao(i) and i == sem_versao(identificador))]
            exigir(aliases, f"A API devolveu um ID nao solicitado: {identificador}")
            return aliases

        registros, mapeados, entradas = [], set(), {}
        for resultado in resultados:
            exigir(isinstance(resultado, dict) and "from" in resultado and "to" in resultado,
                   "Par de mapeamento invalido na resposta da API.")
            de, entrada = resultado["from"], resultado["to"]
            if isinstance(entrada, str):
                exigir(re.fullmatch(r"[A-Z0-9]+(?:-\d+)?", entrada) is not None,
                       "Accession UniProt invalida.")
                if entrada not in entradas:
                    entradas[entrada], _ = self.pedir(API + "/uniprotkb/" + entrada + ".json")
                entrada = entradas[entrada]
            exigir(isinstance(entrada, dict), "A API nao retornou uma entrada UniProtKB.")
            for consultado in resolver(de):
                mapeados.add(consultado)
                registros.append({"id_consultado": consultado, "id_retornado": de,
                    "namespace": origem, "modo": modo, "job_id": job, "entrada": entrada})
        nao_mapeados = {i for f in falhos for i in resolver(f)}
        # suggestedIds aponta para UniParc: contabilizar e preservar, nunca
        # transformar UPI em entrada Swiss-Prot ou em rotulo de funcao.
        pares_sugeridos = {}
        for s in sugestoes:
            exigir(isinstance(s, dict) and "from" in s and "to" in s,
                   "Sugestao sem o par from/to; cobertura incompleta.")
            upi = s["to"]
            exigir(isinstance(upi, str) and re.fullmatch(r"UPI[0-9A-F]{10,16}", upi),
                   "suggestedIds retornou destino diferente de um identificador UniParc UPI valido.")
            for consultado in resolver(s["from"]):
                pares_sugeridos.setdefault((consultado, upi), {
                    "id_consultado": consultado, "id_retornado": s["from"],
                    "namespace": origem, "modo": modo, "job_id": job, "uniparc_id": upi})
        sugeridos = {m["id_consultado"] for m in pares_sugeridos.values()}
        exigir(not (mapeados & nao_mapeados), "Um ID foi informado como mapeado e nao mapeado pela API.")
        restantes = set(ids) - (mapeados | nao_mapeados | sugeridos)
        exigir(not restantes,
               "A API nao explicou todos os IDs enviados; cobertura incompleta, nunca cobertura zero. "
               f"Solicitados={len(ids)}, mapeados={len(mapeados)}, failedIds={len(nao_mapeados)}, "
               f"suggestedIds={len(sugeridos)}, restantes={len(restantes)}; exemplos={sorted(restantes)[:5]}.")
        self.sugestoes.extend(pares_sugeridos.values())
        registrar_resumo(mapeados, nao_mapeados, sugeridos, len(pares_sugeridos))
        return registros


def extrair_ecs(entrada):
    evidencias = []

    def visitar(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "ecNumbers":
                    exigir(isinstance(v, list), "Campo ecNumbers com formato desconhecido.")
                    for ec in v:
                        exigir(isinstance(ec, dict) and isinstance(ec.get("value"), str),
                               "Anotacao EC com formato desconhecido.")
                        evidencias.append({"ec": ec["value"], "campo": "proteinDescription",
                                           "evidencias": ec.get("evidences", [])})
                else:
                    visitar(v)
        elif isinstance(obj, list):
            for x in obj:
                visitar(x)

    visitar(entrada.get("proteinDescription", {}))
    for comentario in entrada.get("comments", []):
        if comentario.get("commentType") == "CATALYTIC ACTIVITY":
            reacao = comentario.get("reaction", {})
            if reacao.get("ecNumber"):
                exigir(isinstance(reacao["ecNumber"], str), "ecNumber de reacao invalido.")
                evidencias.append({"ec": reacao["ecNumber"], "campo": "CATALYTIC ACTIVITY",
                                   "evidencias": reacao.get("evidences", [])})
    return sorted({x["ec"].strip() for x in evidencias}), evidencias


def avaliar(linhas, mapeamentos, sugestoes=()):
    por_id, sugeridos_por_id = defaultdict(list), defaultdict(set)
    for x in mapeamentos:
        por_id[x["id_original"]].append(x)
    for s in sugestoes:
        sugeridos_por_id[s["id_original"]].add(s["uniparc_id"])
    decisoes, pares = [], []
    for x in linhas:
        revisados, exatos = [], []
        vistos = {}
        for m in por_id[x["id_original"]]:
            e = m["entrada"]
            exigir(e.get("entryType") in (REVISADO, NAO_REVISADO), "Tipo de entrada UniProtKB desconhecido.")
            acc = e.get("primaryAccession", "")
            exigir(isinstance(acc, str) and re.fullmatch(r"[A-Z0-9]+(?:-\d+)?", acc),
                   "Entrada sem primaryAccession valida.")
            seq = e.get("sequence", {}).get("value", "")
            exigir(isinstance(seq, str) and re.fullmatch(r"[A-Za-z]+", seq),
                   "Entrada UniProt sem sequencia proteica valida.")
            seq = seq.upper()
            exigir(e["sequence"].get("length") == len(seq), "Comprimento UniProt inconsistente.")
            h = hashlib.sha256(seq.encode("ascii")).hexdigest()
            exato = len(seq) == int(x["tamanho"]) and h == x["sha256_sequencia"]
            rev = e["entryType"] == REVISADO  # 'unreviewed' tambem contem 'reviewed'.
            ecs, evidencia = extrair_ecs(e)
            pares.append({**x, **{k: m[k] for k in (
                "id_consultado", "id_retornado", "namespace", "modo", "job_id")},
                "uniprot_accession": acc, "revisado": rev, "tamanho_uniprot": len(seq),
                "sha256_uniprot": h, "sequencia_exata": exato, "ecs": "|".join(ecs),
                "evidencias_ec_json": json.dumps(evidencia, ensure_ascii=False),
                "organismo": e.get("organism", {}).get("scientificName", "")})
            if rev:
                assinatura = (h, tuple(ecs))
                exigir(vistos.setdefault(acc, assinatura) == assinatura,
                       "A mesma accession UniProt retornou sequencia ou anotacao divergente.")
                if acc not in revisados:
                    revisados.append(acc)
                    if exato:
                        exatos.append((acc, ecs))
        ecs = sorted({ec for _, numeros in exatos for ec in numeros})
        classes = {ec.split(".")[0] for ec in ecs if EC_VALIDO.fullmatch(ec)}
        classe = ""
        if not por_id[x["id_original"]]:
            status = "sugestao_uniparc_sem_rotulo" if sugeridos_por_id[x["id_original"]] else "sem_mapeamento"
        elif not revisados:
            status = "apenas_nao_revisado"
        elif not exatos:
            status = "sequencia_divergente"
        elif not ecs:
            status = "revisado_exato_sem_ec"
        elif any(not EC_VALIDO.fullmatch(ec) for ec in ecs):
            status = "ec_nao_interpretavel"
        elif len(classes) > 1:
            status = "multiclasse_ec_excluida"
        elif classes <= {"2", "3"}:
            classe = next(iter(classes))
            status = "rotulo_confirmado"
        else:
            status = "ec_fora_do_alvo"
        decisoes.append({**x, "status_ec": status, "classe_ec": classe,
            "rotulo_ec": ROTULOS.get(classe, ""), "ecs_uniprot": "|".join(ecs),
            "uniprot_accessions": "|".join(sorted(a for a, _ in exatos)),
            "ec_parcial": any(not all(v.isdigit() for v in ec.split(".")) for ec in ecs),
            "mapeado_uniprot": bool(por_id[x["id_original"]]),
            "tem_revisado": bool(revisados), "tem_revisado_exato": bool(exatos),
            "tem_sugestao_uniparc": bool(sugeridos_por_id[x["id_original"]]),
            "uniparc_sugeridos": "|".join(sorted(sugeridos_por_id[x["id_original"]]))})
    return decisoes, pares


def salvar_csv(path, linhas, colunas):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";")
        w.writeheader()
        w.writerows(linhas)


def consultar(pasta, timeout=30, espera_maxima=600, progresso=print, cliente_factory=ClienteUniProt):
    pasta = Path(pasta).resolve()
    linhas, _, marcas = carregar_sondagem(pasta)
    saida = pasta / (datetime.now(timezone.utc).strftime("consulta_uniprot_%Y%m%dT%H%M%S%fZ_")
                     + uuid.uuid4().hex[:6])
    saida.mkdir()
    bruto = saida / "respostas_api"
    bruto.mkdir()
    r = {"tipo": "sondagem_ec2_ec3_uniprot", "schema": 1, "revisao_cliente": REVISAO_CLIENTE, "ok": False,
         "status": "consulta_em_andamento", "iniciada_em_utc": agora(),
         "pasta_sondagem": str(pasta), "pasta_saida": str(saida),
         "candidatos": len(linhas), "hashes_entradas": marcas,
         "criterio": "EC explicito de entrada revisada Swiss-Prot; sequencia de mesmo tamanho e SHA-256. "
                     "Uma unica classe EC, 2 ou 3; EC parcial com classe conhecida e admitido. "
                     "Multiclasse e anotacoes nao revisadas sao excluidas. Nenhum rotulo por grupo ou palavra-chave.",
         "modelo_embeddings": MODELO, "revisao_embeddings": REVISAO,
         "originais_alterados": False, "embeddings_lidos": False, "gpu_utilizada": False,
         "conjunto_teste_consultado": False, "treinamento_realizado": False,
         "resultados_ec2_ec3": None, "enzimas_ec_descartadas_mais_512": None,
         "limites": ["Amostra de treino/validacao do recorte inicial do NCBI, ja limitado a 1-512 residuos.",
                     "Esta sondagem nao mede EC dos descartes historicos nem representa todo o NCBI.",
                     "Revisao no Swiss-Prot nao implica comprovacao experimental de cada anotacao.",
                     "Nao foram avaliados classificadores ou decidido desempenho no conjunto de teste."]}
    salvar_json(saida / "relatorio_consulta.json", r)
    try:
        cliente = cliente_factory(bruto, timeout=timeout, espera_maxima=espera_maxima, progresso=progresso)
        entradas = defaultdict(list)
        for identificador in dict.fromkeys(x["id_original"] for x in linhas):
            entradas[namespace(identificador)].append(identificador)
        mapeamentos = []
        for origem, ids in entradas.items():
            direto = cliente.mapear(origem, ids, "id_com_versao")
            for m in direto:
                mapeamentos.append({**m, "id_original": m["id_consultado"]})
            faltantes = set(ids) - {m["id_consultado"] for m in direto}
            bases = list(dict.fromkeys(sem_versao(i) for i in ids if i in faltantes))
            if bases:
                progresso(f"Sem mapeamento com versao: {len(faltantes)} IDs. Consultando accessions sem versao; "
                          "o hash da sequencia continua obrigatorio.")
                for m in cliente.mapear(origem, bases, "accession_sem_versao"):
                    for identificador in ids:
                        if identificador in faltantes and sem_versao(identificador) == m["id_consultado"]:
                            mapeamentos.append({**m, "id_original": identificador})
        releases = sorted({m["headers"]["x-uniprot-release"] for m in cliente.metadados
                           if m["headers"].get("x-uniprot-release")})
        exigir(len(releases) <= 1, "A versao do UniProt mudou durante a consulta; execute novamente em outra pasta.")
        sugestoes = []
        for s in cliente.sugestoes:
            for x in linhas:
                if namespace(x["id_original"]) == s["namespace"] and (
                    x["id_original"] == s["id_consultado"] if s["modo"] == "id_com_versao"
                    else sem_versao(x["id_original"]) == s["id_consultado"]):
                    sugestoes.append({**x, **s, "rotulo_ec_atribuido_pela_sugestao": False})
        decisoes, pares = avaliar(linhas, mapeamentos, sugestoes)
        exigir(all(sha(pasta / n) == h for n, h in marcas.items()), "Uma entrada mudou durante a consulta.")
        confirmados = [x for x in decisoes if x["status_ec"] == "rotulo_confirmado"]
        dcols = list(decisoes[0])
        salvar_csv(saida / "decisoes_candidatos.csv", decisoes, dcols)
        salvar_csv(saida / "rotulos_ec_confirmados.csv", confirmados, dcols)
        pcols = list(pares[0]) if pares else list(COLUNAS) + ["id_consultado", "id_retornado",
            "namespace", "modo", "job_id", "uniprot_accession", "revisado", "tamanho_uniprot",
            "sha256_uniprot", "sequencia_exata", "ecs", "evidencias_ec_json", "organismo"]
        salvar_csv(saida / "mapeamentos_uniprot.csv", pares, pcols)
        scols = list(COLUNAS) + ["id_consultado", "id_retornado", "namespace", "modo",
            "job_id", "uniparc_id", "rotulo_ec_atribuido_pela_sugestao"]
        salvar_csv(saida / "sugestoes_uniparc.csv", sugestoes, scols)
        cobertura = {campo: sum(x[campo] for x in decisoes) for campo in (
            "mapeado_uniprot", "tem_revisado", "tem_revisado_exato", "tem_sugestao_uniparc")}
        cobertura["rotulo_ec2_ou_ec3_confirmado"] = len(confirmados)
        r.update(ok=True, status="cobertura_medida_treino_ec_pendente", finalizada_em_utc=agora(),
            uniprot_releases=releases or ["[a confirmar: header ausente]"],
            respostas_http=cliente.metadados, resumos_jobs=cliente.resumos_jobs, criterios_verificados=True,
            contagens_por_status=dict(Counter(x["status_ec"] for x in decisoes)),
            cobertura_contagens=cobertura,
            cobertura_percentual={k: round(100 * v / len(linhas), 4) for k, v in cobertura.items()},
            resultados_ec2_ec3={ROTULOS[c]: sum(x["classe_ec"] == c for x in confirmados) for c in ROTULOS},
            por_particao={nome: {"candidatos": sum(x["particao"] == nome for x in linhas),
                "Transferase": sum(x["particao"] == nome and x["classe_ec"] == "2" for x in confirmados),
                "Hidrolase": sum(x["particao"] == nome and x["classe_ec"] == "3" for x in confirmados)}
                for nome in ("treino", "validacao", "teste")},
            grupos_com_rotulo=len({x["grupo_global"] for x in confirmados}),
            rotulos_com_ec_parcial=sum(x["ec_parcial"] for x in confirmados),
            sha256_script=sha(Path(__file__)),
            hashes_saidas={n: sha(saida / n) for n in (
                "decisoes_candidatos.csv", "rotulos_ec_confirmados.csv", "mapeamentos_uniprot.csv",
                "sugestoes_uniparc.csv")})
        salvar_json(saida / "relatorio_consulta.json", r)
        return r
    except KeyboardInterrupt:
        r.update(status="interrompida_cobertura_nao_concluida", finalizada_em_utc=agora())
        salvar_json(saida / "relatorio_consulta.json", r)
        raise
    except (OSError, ValueError, KeyError, TypeError, FalhaConsulta) as e:
        r.update(status="falha_tecnica_cobertura_nao_concluida", erro=str(e), finalizada_em_utc=agora())
        salvar_json(saida / "relatorio_consulta.json", r)
        raise FalhaConsulta(f"{e}\nArquivos parciais preservados em: {saida}. "
                            "Nao interpretar esta falha como ausencia de anotacoes.") from e


def positivo(valor):
    numero = float(valor)
    if not math.isfinite(numero) or numero <= 0:
        raise argparse.ArgumentTypeError("Use um numero positivo e finito.")
    return numero


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sondagem", required=True, type=Path, help="Pasta criada por preparar_sondagem_ec.py.")
    p.add_argument("--timeout", type=positivo, default=30, help="Timeout de cada requisicao HTTP em segundos.")
    p.add_argument("--espera-maxima", type=positivo, default=600, help="Limite de espera de cada job no UniProt.")
    args = p.parse_args(argv)
    try:
        r = consultar(args.sondagem, args.timeout, args.espera_maxima)
    except KeyboardInterrupt:
        print("Consulta interrompida. Cobertura EC nao concluida; nenhuma etapa de treino foi iniciada.")
        return 130
    except (OSError, ValueError, KeyError, TypeError, FalhaConsulta) as e:
        print(json.dumps({"ok": False, "erro": str(e), "resultados_ec2_ec3": None,
                          "treinamento_realizado": False}, ensure_ascii=False, indent=2))
        return 1
    # O relatorio completo inclui a proveniencia HTTP; o terminal mostra o resumo.
    print(json.dumps({k: v for k, v in r.items() if k != "respostas_http"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
