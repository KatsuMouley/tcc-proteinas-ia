"""Definicoes do experimento EC7 (separado do painel).

Ao ser importado, aplica os rotulos das 7 classes ao modulo consultar_sondagem_ec
SOMENTE no processo deste experimento. O arquivo original nao e alterado.
"""
from pathlib import Path
import sys

AQUI = Path(__file__).resolve().parent
PROJETO = AQUI.parents[1]
if str(PROJETO / "etapas") not in sys.path:
    sys.path.insert(0, str(PROJETO / "etapas"))

ROTULOS = {"1": "Oxidorredutase", "2": "Transferase", "3": "Hidrolase", "4": "Liase",
           "5": "Isomerase", "6": "Ligase", "7": "Translocase"}
CODIGOS = tuple(ROTULOS)
SAIDA = PROJETO / "dados/experimento_ec7"

import consultar_sondagem_ec as _api  # noqa: E402

_api.ROTULOS = dict(ROTULOS)
