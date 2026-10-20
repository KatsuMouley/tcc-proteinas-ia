"""Experimento EC7 (separado do painel): coleta -> agrupamento -> embeddings + treino -> resumo.

Uso (na raiz C:\\ai_tcc, com a .venv):
    python experimentos\\ec7\\rodar_ec7.py tudo        # as 3 etapas em sequencia
    python experimentos\\ec7\\rodar_ec7.py coletar     # 1. baixa do Swiss-Prot (EC 1 a 7)
    python experimentos\\ec7\\rodar_ec7.py preparar    # 2. MMseqs2 + particoes por grupo
    python experimentos\\ec7\\rodar_ec7.py treinar     # 3. ESM-2 + MLP 320->64->7 + validacao cruzada
    python experimentos\\ec7\\rodar_ec7.py resumo      # mostra o resultado do ultimo treino

Cada etapa usa a pasta mais recente CONCLUIDA da etapa anterior. Nada aqui altera o painel,
o modelo EC 2 x EC 3 ou os scripts de etapas/. Saidas: dados/experimento_ec7/.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PROJETO = AQUI.parents[1]
sys.path.insert(0, str(AQUI))
sys.path.insert(1, str(PROJETO / "etapas"))
sys.path.insert(2, str(PROJETO))
import ec7_comum  # noqa: E402


def ajustes():
    """WSL, threads e dispositivo das Configuracoes do painel (config.json + config_local.json)."""
    try:
        from sistema_tcc.core import Config
        v = Config.carregar(PROJETO).valores
        return {"wsl": v.get("wsl", "Ubuntu"), "threads_mmseqs": int(v.get("threads_mmseqs", 4)),
                "threads_pytorch": int(v.get("threads_pytorch", 2)), "dispositivo": v.get("dispositivo", "auto")}
    except Exception:
        return {"wsl": "Ubuntu", "threads_mmseqs": 4, "threads_pytorch": 2, "dispositivo": "auto"}


def ler(p):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def ultima(padrao, relatorio, base=None):
    base = base or ec7_comum.SAIDA
    for pasta in sorted(base.glob(padrao), reverse=True):
        if ler(pasta / relatorio).get("ok") is True:
            return pasta
    return None


def coletar():
    import coletar_ec7
    print("== 1/3 Coleta Swiss-Prot EC 1 a 7 (ate 500 por classe; precisa de internet) ==", flush=True)
    return coletar_ec7.main(["--projeto", str(PROJETO)])


def preparar():
    import preparar_ec7
    coleta = ultima("swissprot_*", "relatorio_coleta.json")
    if not coleta:
        print("Nenhuma coleta concluida. Rode primeiro: coletar")
        return 1
    a = ajustes()
    args = ["--coleta", str(coleta), "--threads", str(a["threads_mmseqs"])]
    if os.name == "nt":
        args += ["--wsl", a["wsl"]]
    print(f"== 2/3 Agrupamento MMseqs2 + particoes: {coleta.name} ==", flush=True)
    return preparar_ec7.main(args)


def treinar(extra=()):
    import treinar_ec7
    coleta = ultima("swissprot_*", "relatorio_coleta.json")
    prep = coleta and ultima("preparacao_ec_*", "relatorio_preparacao_ec.json", coleta)
    if not prep:
        print("Nenhuma preparacao concluida. Rode primeiro: preparar")
        return 1
    a = ajustes()
    os.environ.setdefault("TCC_DISPOSITIVO", a["dispositivo"])
    args = ["--coleta", str(coleta), "--preparacao", str(prep), "--threads", str(a["threads_pytorch"]), *extra]
    if a["dispositivo"] == "cpu" and "--cpu" not in args:
        args.append("--cpu")
    print(f"== 3/3 Embeddings ESM-2 + MLP 7 classes: {prep.name} ==", flush=True)
    return treinar_ec7.main(args)


def resumo():
    coleta = ultima("swissprot_*", "relatorio_coleta.json")
    prep = coleta and ultima("preparacao_ec_*", "relatorio_preparacao_ec.json", coleta)
    treino = prep and ultima("treino_ec_*", "relatorio_treino_ec.json", prep)
    if not treino:
        print("Ainda nao ha treino EC7 concluido.")
        return 1
    r = ler(treino / "relatorio_treino_ec.json")
    t, cv = r["particao_fixa"]["teste_mlp"], r["validacao_cruzada_5_dobras_por_grupo"]
    pct = lambda v: f"{100 * v:.1f}%"
    print(f"Pasta: {treino}")
    print(f"Proteinas: {r['proteinas']}  ·  por classe: {r['rotulos']}")
    print(f"Acaso (7 classes): {pct(r['acaso'])}")
    print(f"Teste fixo (n={t['n']}): acuracia {pct(t['acuracia'])}, acuracia balanceada {pct(t['acuracia_balanceada'])}, F1 macro {t['f1_macro']:.3f}")
    print(f"Validacao cruzada 5 dobras: acuracia balanceada {pct(cv['acuracia_balanceada_media'])} ± {100 * cv['acuracia_balanceada_dp']:.1f}")
    print("Sensibilidade por classe (teste):")
    for c, v in t["sensibilidade_por_classe"].items():
        print(f"  {c:<15} {pct(v)}")
    print("Matriz de confusao (linhas = real, colunas = previsto):")
    print("  " + " ".join(f"{c[:5]:>6}" for c in r["classes"]))
    for c, linha in zip(r["classes"], t["matriz_confusao_linhas_reais_colunas_previstas"]):
        print(f"  {c[:5]:<5}" + "".join(f"{v:>7}" for v in linha))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    acao = argv[0] if argv else "tudo"
    if acao == "coletar":
        return coletar()
    if acao == "preparar":
        return preparar()
    if acao == "treinar":
        return treinar(argv[1:])
    if acao == "resumo":
        return resumo()
    if acao == "tudo":
        for etapa in (coletar, preparar, treinar):
            codigo = etapa()
            if codigo:
                print(f"Parado em {etapa.__name__} (codigo {codigo}). Corrija e rode a partir dessa etapa.")
                return codigo
        return resumo()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
