from argparse import ArgumentParser
from pathlib import Path
import sys
import threading
import webbrowser
import json
import os
from urllib.request import urlopen

from .core import Catalogo, Config, Executor, Store, instancia_unica
from .web import servidor


def main():
    parser = ArgumentParser(description="Dashboard e automação local do TCC de proteínas.")
    parser.add_argument("--projeto", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--porta", type=int, default=8765)
    parser.add_argument("--abrir", action="store_true", help="Abre o dashboard no navegador.")
    parser.add_argument("--somente-painel", action="store_true", help="Pausa a fila e desativa o agendamento automático.")
    parser.add_argument("--diagnosticar", action="store_true", help="Lista relatórios e pendências sem executar tarefas.")
    parser.add_argument("--novo-fluxo", action="store_true", help="Inicia automaticamente uma execução nova dos GZ até o treino e banco.")
    parser.add_argument("--limite", type=int, default=1000, help="Máximo de candidatos da execução nova; de 100 a 1.000.000.")
    args = parser.parse_args()
    if not 0 <= args.porta <= 65535:
        parser.error("Porta inválida.")
    try:
        c = Config.carregar(args.projeto, args.config)
        os.environ["TCC_DISPOSITIVO"] = c.valores["dispositivo"]  # herdado pelos scripts das etapas
        # pythonw.exe não oferece stdout/stderr; conservar o diagnóstico em arquivo.
        c.caminhos["sistema"].mkdir(parents=True, exist_ok=True)
        if sys.stdout is None or sys.stderr is None:
            log = (c.caminhos["sistema"] / "servidor.log").open("a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = log
        with instancia_unica(c.caminhos["sistema"]):
            store = Store(c.caminhos["sistema"])
            catalogo = Catalogo(c, store)
            executor = Executor(c, store, catalogo)
            if args.diagnosticar:
                estados = catalogo.refresh(True)
                for e, r in estados.items():
                    print(e + ": " + r["estado"] + " · " + r["motivo"])
                return 0
            if args.somente_painel:
                executor.controles(automatico=False, pausado=True)
            # Reservar a porta antes de iniciar qualquer tarefa.
            server = servidor(executor, args.porta)
            try:
                if args.novo_fluxo:
                    r = executor.iniciar_fluxo(args.limite)
                    print("Nova execução completa: " + r["execucao"], flush=True)
                executor.start()
                url = f"http://127.0.0.1:{server.server_port}"
                print("Sistema local pronto: " + url, flush=True)
                print("Novo fluxo completo: GZ -> MMseqs2 -> embeddings -> auditoria -> partições -> treino -> banco.", flush=True)
                print("Ctrl+C encerra após a tarefa ativa terminar. Para impedir a próxima tarefa, pause a fila.", flush=True)
                store.evento("Sistema iniciado em " + url)
                if args.abrir:
                    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
                try:
                    server.serve_forever(poll_interval=0.5)
                except KeyboardInterrupt:
                    print("Encerrando. Aguardando a tarefa ativa terminar e preservar os arquivos...", flush=True)
                finally:
                    executor.encerrar()
            finally:
                server.server_close()
        return 0
    except Exception as e:
        if args.abrir and isinstance(e, RuntimeError) and "já está aberto" in str(e):
            url = f"http://127.0.0.1:{args.porta}"
            try:
                with urlopen(url + "/api/saude", timeout=3) as resposta:
                    estado = json.load(resposta)
                if estado.get("versao") == "2.0.0" and Path(estado.get("projeto", "")).resolve() == args.projeto.resolve():
                    if args.novo_fluxo:
                        from urllib.request import Request
                        with urlopen(url+"/api/estado", timeout=5) as resposta:
                            sessao = json.load(resposta)
                        req = Request(url+"/api/execucoes", data=json.dumps({"limite": args.limite, "fonte": "todas"}).encode(),
                            headers={"Content-Type": "application/json", "X-TCC-Token": sessao["token"]}, method="POST")
                        with urlopen(req, timeout=30) as resposta:
                            criada = json.load(resposta)
                        print("Fluxo completo enfileirado: " + criada["execucao"])
                    webbrowser.open(url)
                    print("O sistema já está aberto: " + url)
                    return 0
            except Exception:
                pass
        print(type(e).__name__ + ": " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
