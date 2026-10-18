from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit

from . import configuracoes
from .fase1 import Gerenciador
from .core import ETAPAS, exigir


def unico(pares):
    resultado = {}
    for chave, valor in pares:
        exigir(chave not in resultado, "JSON contém campo duplicado.")
        resultado[chave] = valor
    return resultado


def sem_constantes(_):
    raise ValueError("JSON não aceita NaN ou Infinity.")


def pagina_log(executor, ident, cursor=0, extra=False):
    t = executor.store.tarefa(ident)
    exigir(t is not None, "Tarefa não encontrada.")
    texto = ""
    chave = "log_extra" if extra else "log"
    if not t.get(chave):
        return {"ok": True, "texto": "", "cursor": 0, "fim": True,
            "mensagem": "Este resultado foi importado de um relatório; não há log histórico disponível." if t["origem"] == "importado" else "O log será criado quando a tarefa começar."}
    path = Path(t[chave]).resolve()
    exigir(path.is_relative_to(executor.c.raiz), "Log fora do projeto.")
    if not path.is_file() and t["etapa"] == "agrupar" and extra:
        path = executor.c.caminhos["grupos"] / "mmseqs.log"  # O wrapper renomeia a pasta ao concluir.
    if not path.is_file():
        return {"ok": True, "texto": "", "cursor": 0, "fim": True, "mensagem": "Arquivo de log ainda indisponível."}
    tamanho = path.stat().st_size
    if cursor < 0 or cursor > tamanho:
        cursor = max(0, tamanho - 65536)
    with path.open("rb") as f:
        f.seek(cursor)
        bloco = f.read(65536)
        pos = f.tell()
    texto = bloco.decode("utf-8", errors="replace")
    return {"ok": True, "texto": texto, "cursor": pos, "fim": pos >= tamanho,
        "bytes_total": tamanho, "mensagem": None}


def servidor(executor, porta=8765):
    token = secrets.token_urlsafe(32)
    fase1 = Gerenciador(executor.c)
    assets = Path(__file__).parent / "static"
    rotas = {"/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        "/favicon.svg": ("favicon.svg", "image/svg+xml")}

    class Handler(BaseHTTPRequestHandler):
        server_version = "SistemaProteinasTCC/1"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_):
            pass

        def permitido(self, escrita=False):
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            exigir(self.headers.get("Host") in hosts, "Host não permitido. Abra o endereço local indicado.")
            origem = self.headers.get("Origin")
            exigir(not origem or origem in {"http://" + h for h in hosts}, "Origem não permitida.")
            exigir(self.headers.get("Sec-Fetch-Site") != "cross-site", "Solicitação de outra origem não permitida.")
            if escrita:
                exigir(secrets.compare_digest(self.headers.get("X-TCC-Token", ""), token), "Sessão expirada. Atualize o painel.")

        def resposta(self, status, obj, content_type="application/json; charset=utf-8", arquivo=None):
            corpo = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            if arquivo:
                self.send_header("Content-Disposition", 'attachment; filename="' + arquivo + '"')
            self.end_headers()
            self.wfile.write(corpo)

        def corpo(self):
            exigir(not self.headers.get("Transfer-Encoding") and not self.headers.get("Content-Encoding"), "Envie JSON sem compressão.")
            exigir(self.headers.get_content_type() == "application/json", "Use Content-Type: application/json.")
            n = int(self.headers.get("Content-Length", "0"))
            exigir(0 < n <= 16384, "Corpo JSON deve ter até 16 KiB.")
            bruto = self.rfile.read(n)
            exigir(len(bruto) == n, "Corpo incompleto.")
            obj = json.loads(bruto.decode("utf-8"), object_pairs_hook=unico, parse_constant=sem_constantes)
            exigir(isinstance(obj, dict), "Envie um objeto JSON.")
            return obj

        def do_GET(self):
            try:
                self.permitido()
                uri = urlsplit(self.path)
                if uri.path in rotas:
                    nome, mime = rotas[uri.path]
                    self.resposta(200, (assets / nome).read_bytes(), mime)
                elif uri.path == "/api/estado":
                    qs = parse_qs(uri.query)
                    estado = executor.estado(qs.get("execucao", [None])[0])
                    estado["token"] = token
                    self.resposta(200, estado)
                elif uri.path == "/api/fontes":
                    fontes = executor.execucoes.inventario(forcar=parse_qs(uri.query).get("forcar", ["0"])[0] == "1")
                    self.resposta(200, {"ok": True, "fontes": [{"id": x["id"], "nome": x["nome"],
                        "bytes_gz": x["bytes_gz"], "membro": x["membro"], "arquivo": x["arquivo"]} for x in fontes]})
                elif uri.path == "/api/proteinas":
                    qs = parse_qs(uri.query)
                    ident = qs.get("execucao", [""])[0]
                    self.resposta(200, {"ok": True, "proteinas": executor.execucoes.proteinas(ident, qs.get("busca", [""])[0])})
                elif uri.path.startswith("/api/logs/"):
                    ident = int(uri.path.rsplit("/", 1)[1])
                    qs = parse_qs(uri.query)
                    self.resposta(200, pagina_log(executor, ident, int(qs.get("cursor", ["0"])[0]), qs.get("extra", ["0"])[0] == "1"))
                elif uri.path.startswith("/api/relatorios/"):
                    etapa = uri.path.rsplit("/", 1)[1]
                    exigir(etapa in ETAPAS, "Etapa desconhecida.")
                    executor.catalogo.refresh(True)
                    qs = parse_qs(uri.query)
                    cat, _ = executor.catalogo_execucao(qs.get("execucao", ["original"])[0])
                    cat.refresh(True)
                    r = cat.relatorios.get(etapa)
                    exigir(r is not None, "Relatório indisponível.")
                    self.resposta(200, r, arquivo="relatorio_" + etapa + ".json")
                elif uri.path == "/api/configuracoes":
                    self.resposta(200, configuracoes.ler(executor.c))
                elif uri.path == "/api/fase1":
                    self.resposta(200, fase1.estado())
                elif uri.path == "/api/diagnostico":
                    self.resposta(200, configuracoes.diagnosticar(executor.c))
                elif uri.path == "/api/saude":
                    self.resposta(200, {"ok": True, "fila_ativa": bool(executor.thread and executor.thread.is_alive()),
                        "gpu_carregada": executor.servico is not None, "versao": "2.0.0", "projeto": str(executor.c.raiz)})
                else:
                    self.resposta(404, {"ok": False, "erro": "Rota não encontrada."})
            except (ValueError, TypeError, UnicodeError) as e:
                self.resposta(400, {"ok": False, "erro": str(e)})
            except OSError:
                self.resposta(500, {"ok": False, "erro": "Arquivo indisponível. Confira o projeto."})
            except Exception as e:
                executor.store.evento("API: " + type(e).__name__ + ": " + str(e))
                self.resposta(500, {"ok": False, "erro": "Falha interna. Consulte servidor.log."})

        def do_POST(self):
            try:
                self.permitido(escrita=True)
            except ValueError as e:
                self.resposta(403, {"ok": False, "erro": str(e)})
                return
            try:
                uri = urlsplit(self.path)
                obj = self.corpo()
                if uri.path == "/api/controle":
                    exigir(obj and set(obj) <= {"automatico", "pausado", "threads_mmseqs"}, "Controle desconhecido.")
                    executor.controles(**obj)
                    self.resposta(200, {"ok": True})
                elif uri.path == "/api/etapas":
                    exigir(set(obj) == {"etapa"} and isinstance(obj["etapa"], str), "Informe somente etapa.")
                    r = executor.agendar(obj["etapa"], repetir=True)
                    self.resposta(200 if r.get("reutilizado") else 202, {"ok": True, **r})
                elif uri.path == "/api/prever":
                    exigir("sequencia" in obj and set(obj) <= {"sequencia", "execucao"}, "Informe sequencia e, opcionalmente, execucao.")
                    tarefa = executor.prever(obj["sequencia"], obj.get("execucao", "original"))
                    self.resposta(202, {"ok": True, "tarefa_id": tarefa["id"]})
                elif uri.path == "/api/execucoes":
                    exigir(set(obj) == {"limite", "fonte"}, "Informe limite e fonte.")
                    self.resposta(202, executor.iniciar_fluxo(obj["limite"], obj["fonte"]))
                elif uri.path == "/api/retomar-fluxo":
                    exigir(set(obj) == {"execucao"}, "Informe execucao.")
                    r = executor.retomar_fluxo(obj["execucao"])
                    executor.controles(pausado=False)
                    self.resposta(202, r)
                elif uri.path == "/api/cancelar":
                    exigir(set(obj) == {"id"} and type(obj["id"]) is int, "Informe o ID da tarefa.")
                    executor.cancelar(obj["id"])
                    self.resposta(200, {"ok": True})
                elif uri.path == "/api/recuperar":
                    exigir(set(obj) == {"id"} and type(obj["id"]) is int, "Informe o ID da tarefa.")
                    executor.recuperar(obj["id"])
                    self.resposta(200, {"ok": True})
                elif uri.path == "/api/configuracoes":
                    self.resposta(200, configuracoes.salvar(executor.c, obj))
                elif uri.path == "/api/fase1":
                    self.resposta(202, fase1.iniciar(obj))
                elif uri.path == "/api/encerrar":
                    exigir(not obj, "Encerrar não recebe parâmetros.")
                    executor.parar.set()
                    executor.acordar.set()
                    self.resposta(202, {"ok": True, "mensagem": "Sistema encerrando; a tarefa ativa terminará normalmente."})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self.resposta(404, {"ok": False, "erro": "Rota não encontrada."})
            except (ValueError, TypeError, KeyError, UnicodeError) as e:
                self.resposta(400, {"ok": False, "erro": str(e)})
            except TimeoutError:
                self.resposta(408, {"ok": False, "erro": "Tempo esgotado ao receber a solicitação."})
            except Exception as e:
                executor.store.evento("API: " + type(e).__name__ + ": " + str(e))
                self.resposta(500, {"ok": False, "erro": "Falha interna. Confira os logs."})

    class LocalServer(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            # O navegador fechou a conexão (troca de tela, F5): não é falha do sistema.
            import sys
            if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
                return
            super().handle_error(request, client_address)

    return LocalServer(("127.0.0.1", porta), Handler)
