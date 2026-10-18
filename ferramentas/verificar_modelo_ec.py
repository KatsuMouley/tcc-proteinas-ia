"""Confere a consulta EC do painel contra o treino de 14/10.

Roda a inferencia do sistema (ESM-2 + MLP EC) em uma Transferase e uma Hidrolase
do teste fixo e compara o escore com predicoes_teste.csv do treino.
Uso: .venv\\Scripts\\python.exe ferramentas\\verificar_modelo_ec.py
"""
from argparse import Namespace
from pathlib import Path
import csv, sys

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "etapas"))
sys.path.insert(0, str(RAIZ))
from sistema_tcc.inferencia import Servico, MODELO, CACHE, MODELO_EC

PILOTO = RAIZ / "dados/piloto_ec2_ec3/swissprot_20261014T021908726567Z_46400a/piloto_rotulado.csv"
PRED = MODELO_EC.parent / "predicoes_teste.csv"

def ler(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))

seqs = {l["uid"]: l["sequencia"].strip().upper() for l in ler(PILOTO)}
pred = ler(PRED)
escolhidas = [next(l for l in pred if l["rotulo"] == c and l["correto"] == "True" and int(l["tamanho"]) <= 400)
              for c in ("Transferase", "Hidrolase")]
s = Servico(Namespace(modelo=MODELO, cache=CACHE, threads=2))
assert s.ec, "Modelo EC nao foi carregado (confira dados/modelos/classificador_ec2_ec3)."
ok = True
for l in escolhidas:
    r = s.prever(seqs[l["uid"]])["ec"]
    obtido, esperado = r["escores_softmax_nao_calibrados"]["Transferase"], float(l["escore_transferase"])
    bate = abs(obtido - esperado) < 1e-3 and r["classe"] == l["predicao"]
    ok &= bate
    print(f"{l['id_original']} (EC {l['ec']}, real {l['rotulo']}): painel -> {r['predicao']} "
          f"| escore Transferase {obtido:.6f} vs treino {esperado:.6f} -> {'OK' if bate else 'DIFERENTE'}")
    print("  sequencia para colar no painel:\n  " + seqs[l["uid"]])
print("\nRESULTADO:", "OK - a consulta reproduz o treino." if ok else "DIVERGENCIA - me envie esta saida.")
sys.exit(0 if ok else 1)
