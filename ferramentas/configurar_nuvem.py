"""Pergunta onde salvar os arquivos e o que mandar para a nuvem (chamado pelo instalar.cmd).

Grava em config_local.json (fora do git): pasta_nuvem, salvar_fontes, copiar_resultados.
Pode ser rodado de novo a qualquer hora; tambem da para ajustar na tela Configuracoes.
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from sistema_tcc import pastas  # noqa: E402

ARQ = RAIZ / "config_local.json"


def perguntar(texto, padrao=""):
    try:
        r = input(texto).strip()
    except EOFError:
        return padrao
    return r or padrao


def sim(texto, padrao=True):
    r = perguntar(texto + (" [S/n] " if padrao else " [s/N] ")).lower()
    return padrao if not r else r.startswith(("s", "y"))


def main():
    atual = {}
    if ARQ.is_file():
        try:
            atual = json.loads(ARQ.read_text(encoding="utf-8-sig"))
        except ValueError:
            atual = {}
    print("\n=== Onde salvar os arquivos ===")
    print(f"Por padrao tudo fica neste PC, em {RAIZ}.")
    print("Se quiser guardar na nuvem, use uma pasta do Google Drive para computador, OneDrive ou Dropbox")
    print("(o app deles sincroniza). A fila, os logs e os modelos continuam neste PC.\n")
    achadas = pastas.detectar()
    print("  0) So neste PC (padrao)")
    for i, p in enumerate(achadas, 1):
        print(f"  {i}) {p}")
    print(f"  {len(achadas) + 1}) Digitar outro caminho")
    esc = perguntar("Escolha: ", "0")
    destino = ""
    if esc.isdigit() and 1 <= int(esc) <= len(achadas):
        destino = achadas[int(esc) - 1]
    elif esc == str(len(achadas) + 1):
        destino = perguntar("Caminho completo da pasta (ex.: G:\\Meu Drive\\TCC): ")
    if not destino:
        atual.pop("pasta_nuvem", None); atual["salvar_fontes"] = False; atual["copiar_resultados"] = False
        print("Ok: tudo fica neste PC.")
    else:
        try:
            destino = pastas.validar_pasta(destino)
        except ValueError as e:
            print(f"Nao foi possivel usar essa pasta: {e}\nNada foi alterado; rode este passo de novo quando quiser.")
            return 0
        print(f"\nPasta escolhida: {destino}\nO que enviar para ela?")
        atual["pasta_nuvem"] = destino
        atual["salvar_fontes"] = sim("  Baixar e guardar os .gz / CSVs do NCBI nela (arquivos grandes)?", False)
        atual["copiar_resultados"] = sim("  Copiar execucoes e treinos EC7 para ela quando terminarem?", True)
    ARQ.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Salvo em config_local.json. Para mudar depois: tela Configuracoes do sistema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
