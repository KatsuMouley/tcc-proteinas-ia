"""Fase 1 (Filipe Camargo Prado) integrada ao painel.

Usa as funcoes ORIGINAIS de fase1_extrator/genomic-data-extractor sem alterar os arquivos dele:
  baixar_gz.baixar_arquivo_individual  -> download de cada .fsa_aa.gz do FTP do NCBI
  agrupar_gz_ncbi.descompactar_gz / rodar_mmseqs / salvar_resultados_no_csv / registrar_sucesso
Os scripts dele apontam para o Google Drive e o PC dele; aqui so redirecionamos essas pastas
para dentro do projeto:
  .gz    -> "arquivos .gz/"     (o fluxo novo do painel le daqui)
  CSVs   -> "arquivos csv/"     (Arquivo_Origem;Grupo_Similaridade;ID_da_Proteina;Tipo_Nutricional)
  logs, historico e temporarios -> dados/fase1/
Uso: python -m sistema_tcc.fase1 listar --divisao bct
     python -m sistema_tcc.fase1 baixar --divisao bct --quantidade 2
     python -m sistema_tcc.fase1 agrupar
"""
from argparse import ArgumentParser
from ftplib import FTP
from pathlib import Path
from unittest import mock
import gzip
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

RAIZ = Path(__file__).resolve().parents[1]
REPO = RAIZ / "fase1_extrator/genomic-data-extractor"
DIR_GZ = RAIZ / "arquivos .gz"
DIR_CSV = RAIZ / "arquivos csv"
PASTA = RAIZ / "dados/fase1"
TEMP = PASTA / "temp"
HISTORICO = PASTA / "historico_arquivos_processados.txt"
LOG_EXECUCAO = PASTA / "ultima_execucao.log"
FTP_HOST, FTP_DIR = "ftp.ncbi.nlm.nih.gov", "/ncbi-asn1/protein_fasta/"
DIVISOES = {"bct": "Bactérias", "pln": "Plantas e fungos", "inv": "Invertebrados", "vrt": "Outros vertebrados",
            "mam": "Mamíferos", "pri": "Primatas", "rod": "Roedores", "vrl": "Vírus", "phg": "Bacteriófagos",
            "env": "Amostras ambientais", "syn": "Sintéticas", "pat": "Patentes", "gss": "GSS (genômicas)"}
MAX_ARQUIVOS = 20


def _carregar(arquivo, **pastas):
    exigir((REPO / arquivo).is_file(), f"Fase 1 nao encontrada: {REPO / arquivo}. Clone o repositorio do Filipe em fase1_extrator/.")
    spec = importlib.util.spec_from_file_location(Path(arquivo).stem + "_filipe", REPO / arquivo)
    mod = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True  # nao criar __pycache__ dentro da pasta do Filipe
    with mock.patch("os.makedirs"):  # o import dele cria pastas no Google Drive dele; aqui nao
        spec.loader.exec_module(mod)
    for nome, valor in pastas.items():
        setattr(mod, nome, str(valor))
    return mod


def exigir(cond, msg):
    if not cond:
        raise ValueError(msg)


def _ordem(nome):
    m = re.match(r"gb([a-z]+)(\d+)\.fsa_aa\.gz$", nome)
    return (m.group(1), int(m.group(2))) if m else (nome, 0)


def listar(divisao):
    exigir(divisao in DIVISOES, "Divisao desconhecida.")
    ftp = FTP(FTP_HOST, timeout=60)
    try:
        ftp.login()
        ftp.cwd(FTP_DIR)
        nomes = [n for n in ftp.nlst() if n.startswith("gb" + divisao) and n.endswith(".fsa_aa.gz")]
    finally:
        try:
            ftp.quit()
        except Exception:
            pass
    return sorted(nomes, key=_ordem)


def _gzip_integro(path):
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1 << 22):
                pass
        return True
    except Exception:
        return False


def baixar(divisao, quantidade, reserva_gib=10):
    exigir(type(quantidade) is int and 1 <= quantidade <= MAX_ARQUIVOS, f"Quantidade: 1 a {MAX_ARQUIVOS} arquivos.")
    DIR_GZ.mkdir(parents=True, exist_ok=True)
    livre = shutil.disk_usage(RAIZ).free / 1024**3
    exigir(livre - 0.2 * quantidade > reserva_gib, f"Pouco espaco: {livre:.1f} GiB livres, reserva {reserva_gib} GiB.")
    mod = _carregar("baixar_gz.py", PASTA_DESTINO=DIR_GZ)
    print(f"Listando {DIVISOES[divisao]} (gb{divisao}) no FTP do NCBI...", flush=True)
    todos = listar(divisao)
    novos = [n for n in todos if not (DIR_GZ / n).exists()][:quantidade]
    print(f"{len(todos)} arquivo(s) no NCBI; {len(novos)} novo(s) para baixar.", flush=True)
    for i, nome in enumerate(novos, 1):
        mod.baixar_arquivo_individual(nome, i, len(novos))  # funcao original do Filipe
        destino = DIR_GZ / nome
        if destino.exists() and not _gzip_integro(destino):
            print(f"Arquivo incompleto ou corrompido, removido: {nome}", flush=True)
            destino.unlink()
        elif destino.exists():
            print(f"Conferido (gzip integro): {nome} · {destino.stat().st_size / 1048576:.1f} MiB", flush=True)
    print("FASE1_FIM: download concluido.", flush=True)


def _wsl_cmd(distro):
    """Os comandos do Filipe chamam 'wsl' (distribuicao padrao). Este atalho fixa a distro configurada."""
    exigir(re.fullmatch(r"[A-Za-z0-9._-]{1,100}", distro or ""), "Nome de distribuicao WSL invalido.")
    PASTA.mkdir(parents=True, exist_ok=True)
    atalho = PASTA / "wsl_tcc.cmd"
    atalho.write_text(f'@wsl.exe --distribution {distro} --exec %*\r\n', encoding="ascii")
    return str(atalho)


class _SubprocessVisivel:
    """Igual ao subprocess, mas registra comando e erro quando algo falha (o original usa DEVNULL)."""
    CalledProcessError = subprocess.CalledProcessError
    DEVNULL = subprocess.DEVNULL

    def run(self, cmd, check=False, stdout=None, stderr=None, **kw):
        r = subprocess.run(cmd, capture_output=True, **kw)
        if r.returncode != 0:
            err = (r.stderr or b"").decode("utf-8", "replace").replace("\x00", "").strip().splitlines()
            out = (r.stdout or b"").decode("utf-8", "replace").replace("\x00", "").strip().splitlines()
            print("Comando falhou (codigo %s): %s" % (r.returncode, " ".join(map(str, cmd[1:]))), flush=True)
            for linha in (err or out)[-15:]:
                print("   " + linha, flush=True)
            if check:
                raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)
        return r


def pendentes():
    feitos = set(HISTORICO.read_text(encoding="utf-8").split()) if HISTORICO.is_file() else set()
    return sorted([p.name for p in DIR_GZ.glob("*.gz") if p.name not in feitos], key=_ordem) if DIR_GZ.is_dir() else []


def agrupar(distro="Ubuntu"):
    exigir(str(RAIZ).lower().startswith("c:") or os.name != "nt", "O agrupamento da Fase 1 exige o projeto no disco C:.")
    for p in (DIR_CSV, TEMP):
        p.mkdir(parents=True, exist_ok=True)
    mod = _carregar("agrupar_gz_ncbi.py", DIR_GZ=DIR_GZ, DIR_CSV_DRIVE=DIR_CSV, DIR_TEMP_LOCAL=TEMP,
                    ARQUIVO_LOG=HISTORICO, ARQUIVO_LOG_SISTEMA=PASTA / "log_fase1.txt", g_drive=PASTA)
    if os.name == "nt":
        mod.EXECUTAVEL_LINUX = _wsl_cmd(distro)
    mod.subprocess = _SubprocessVisivel()  # mostra no log o erro que o script original descarta
    mod.setup_logging(str(PASTA / "log_fase1.txt"))
    fila = pendentes()
    print(f"{len(fila)} arquivo(s) .gz para agrupar com MMseqs2 (50% identidade, 80% cobertura).", flush=True)
    for i, arquivo in enumerate(fila, 1):
        print(f"[{i}/{len(fila)}] {arquivo}", flush=True)
        fasta = TEMP / (arquivo.split(".")[0] + ".fas")
        try:
            if mod.descompactar_gz(str(DIR_GZ / arquivo), str(fasta)) and mod.rodar_mmseqs(str(fasta), str(TEMP)):
                mod.salvar_resultados_no_csv(str(TEMP), arquivo, str(fasta))
                mod.registrar_sucesso(arquivo)
                print(f"OK: {arquivo} -> arquivos csv/{arquivo.replace('.gz', '')}.csv", flush=True)
            else:
                print(f"FALHOU: {arquivo} (veja dados/fase1/log_fase1.txt)", flush=True)
        finally:
            for item in TEMP.iterdir():
                shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
    print("FASE1_FIM: agrupamento concluido.", flush=True)


class Gerenciador:
    """Roda uma acao da Fase 1 por vez, em segundo plano, com log em dados/fase1/ultima_execucao.log."""

    def __init__(self, config):
        self.c = config
        self.proc = None
        self.acao = None
        self.trava = threading.Lock()

    def rodando(self):
        return self.proc is not None and self.proc.poll() is None

    def iniciar(self, obj):
        with self.trava:
            exigir(not self.rodando(), "Ja ha uma acao da Fase 1 em andamento.")
            acao = obj.get("acao")
            cmd = [sys.executable, "-u", "-m", "sistema_tcc.fase1"]
            if acao == "baixar":
                exigir(set(obj) == {"acao", "divisao", "quantidade"}, "Informe divisao e quantidade.")
                exigir(obj["divisao"] in DIVISOES, "Divisao desconhecida.")
                exigir(type(obj["quantidade"]) is int and 1 <= obj["quantidade"] <= MAX_ARQUIVOS, f"Quantidade: 1 a {MAX_ARQUIVOS}.")
                cmd += ["baixar", "--divisao", obj["divisao"], "--quantidade", str(obj["quantidade"]),
                        "--reserva", str(self.c.valores.get("reserva_gib", 10))]
            elif acao == "agrupar":
                exigir(set(obj) == {"acao"}, "Agrupar nao recebe parametros.")
                exigir(pendentes(), "Nenhum .gz pendente de agrupamento.")
                cmd += ["agrupar", "--wsl", self.c.valores.get("wsl", "Ubuntu")]
            else:
                raise ValueError("Acao desconhecida: use baixar ou agrupar.")
            PASTA.mkdir(parents=True, exist_ok=True)
            log = LOG_EXECUCAO.open("w", encoding="utf-8")
            log.write(time.strftime("%d/%m/%Y %H:%M:%S") + " · " + " ".join(cmd[3:]) + "\n")
            log.flush()
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            self.proc = subprocess.Popen(cmd, cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT, env=env,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.acao = acao
            return {"ok": True, "acao": acao}

    def estado(self):
        feitos = set(HISTORICO.read_text(encoding="utf-8").split()) if HISTORICO.is_file() else set()
        arquivos = [{"nome": p.name, "mib": round(p.stat().st_size / 1048576, 1), "agrupado": p.name in feitos,
                     "csv": (DIR_CSV / p.name.replace(".gz", ".csv")).is_file()}
                    for p in sorted(DIR_GZ.glob("*.gz"), key=lambda p: _ordem(p.name))] if DIR_GZ.is_dir() else []
        linhas = LOG_EXECUCAO.read_text(encoding="utf-8", errors="replace").splitlines()[-40:] if LOG_EXECUCAO.is_file() else []
        return {"ok": True, "rodando": self.rodando(), "acao": self.acao,
                "codigo_saida": None if self.proc is None or self.rodando() else self.proc.returncode,
                "divisoes": DIVISOES, "max_arquivos": MAX_ARQUIVOS, "arquivos": arquivos,
                "fase1_presente": (REPO / "agrupar_gz_ncbi.py").is_file(), "log": linhas}


def main():
    ap = ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="acao", required=True)
    s = sub.add_parser("listar"); s.add_argument("--divisao", required=True)
    s = sub.add_parser("baixar"); s.add_argument("--divisao", required=True); s.add_argument("--quantidade", type=int, default=1)
    s.add_argument("--reserva", type=float, default=10)
    s = sub.add_parser("agrupar"); s.add_argument("--wsl", default="Ubuntu")
    a = ap.parse_args()
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if a.acao == "listar":
            nomes = listar(a.divisao)
            print(f"{len(nomes)} arquivo(s):", ", ".join(nomes[:20]), "..." if len(nomes) > 20 else "")
        elif a.acao == "baixar":
            baixar(a.divisao, a.quantidade, a.reserva)
        else:
            agrupar(a.wsl)
    except Exception as e:
        print(f"ERRO: {type(e).__name__}: {e}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
