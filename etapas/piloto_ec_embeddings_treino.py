"""Piloto EC 2 (Transferase) x EC 3 (Hidrolase): embeddings ESM-2 e treino do MLP.

1. Confere a coleta Swiss-Prot e as particoes por grupo ja preparadas.
2. Gera os embeddings com o MESMO metodo do milhao (piloto_esm_gpu.py da raiz:
   facebook/esm2_t6_8M_UR50D, revisao fixa, cache local, media dos residuos, float32).
3. Treina o MLP 320 -> 64 -> 2 com hiperparametros fixos (sem busca):
   a) particao fixa treino/validacao/teste;
   b) validacao cruzada de 5 dobras por grupo MMseqs2 (dobra = SHA256(semente:grupo) mod 5).
O teste nao e usado para escolher nada. Tudo e gravado numa pasta nova.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJETO = Path(__file__).resolve().parents[1]
CLASSES = ["Hidrolase", "Transferase"]  # indice 0 = EC 3, indice 1 = EC 2
FAIXAS = [(1, 199), (200, 299), (300, 399), (400, 512)]


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_csv(caminho: Path) -> list[dict]:
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def hash_int(texto: str) -> int:
    return int(hashlib.sha256(texto.encode()).hexdigest()[:16], 16)


# ---------------------------------------------------------------- dados
def carregar(coleta: Path, prep: Path):
    rot = ler_csv(coleta / "piloto_rotulado.csv")
    par = ler_csv(prep / "particoes.csv")
    if len(rot) != len(par):
        raise ValueError("piloto_rotulado.csv e particoes.csv tem tamanhos diferentes.")
    linhas = []
    for i, (r, p) in enumerate(zip(rot, par)):
        if int(r["indice_global"]) != i or r["uid"] != p["uid"] or r["rotulo_ec"] != p["rotulo_ec"]:
            raise ValueError(f"Linha {i}: UID, ordem ou rotulo divergem entre os CSVs.")
        seq = r["sequencia"].strip().upper()
        if hashlib.sha256(seq.encode()).hexdigest() != r["sha256_sequencia"] or len(seq) != int(r["tamanho"]):
            raise ValueError(f"Linha {i}: sequencia nao confere com hash/tamanho.")
        if r["rotulo_ec"] not in CLASSES or r["revisado"] != "True":
            raise ValueError(f"Linha {i}: rotulo fora do alvo ou entrada nao revisada.")
        linhas.append({"uid": r["uid"], "id_original": r["id_original"], "sequencia": seq,
                       "tamanho": len(seq), "rotulo": r["rotulo_ec"], "ec": r["ecs_uniprot"],
                       "grupo": p["grupo_global"], "particao": p["particao"]})
    for nome in ("treino", "validacao", "teste"):
        idx = set(np.load(prep / f"{nome}_indices.npy").tolist())
        if idx != {i for i, l in enumerate(linhas) if l["particao"] == nome}:
            raise ValueError(f"{nome}_indices.npy nao confere com particoes.csv.")
    grupos_part = {}
    for l in linhas:
        if grupos_part.setdefault(l["grupo"], l["particao"]) != l["particao"]:
            raise ValueError("Um grupo aparece em mais de uma particao.")
    return linhas


# ---------------------------------------------------------------- metricas
def metricas(y, p):
    y = np.asarray(y); p = np.asarray(p)
    cm = np.zeros((2, 2), dtype=int)
    for a, b in zip(y, p):
        cm[a, b] += 1
    sens = np.divide(cm.diagonal(), cm.sum(1), out=np.zeros(2), where=cm.sum(1) > 0)
    prec = np.divide(cm.diagonal(), cm.sum(0), out=np.zeros(2), where=cm.sum(0) > 0)
    f1 = np.divide(2 * prec * sens, prec + sens, out=np.zeros(2), where=(prec + sens) > 0)
    return {"n": int(len(y)), "acuracia": float((y == p).mean()) if len(y) else None,
            "acuracia_balanceada": float(sens.mean()), "f1_macro": float(f1.mean()),
            "ordem_classes": CLASSES, "matriz_confusao_linhas_reais_colunas_previstas": cm.tolist(),
            "sensibilidade_por_classe": dict(zip(CLASSES, map(float, sens)))}


# ---------------------------------------------------------------- MLP
def treinar_mlp(torch, X, y, i_tr, i_va, semente, disp, epocas, paciencia, lote=64):
    torch.manual_seed(semente); np.random.seed(semente)
    media = X[i_tr].mean(0); dp = np.maximum(X[i_tr].std(0), 1e-6)
    Z = ((X - media) / dp).astype(np.float32)
    cont = np.bincount(y[i_tr], minlength=2)
    if (cont == 0).any() or len(set(y[i_va])) < 2:
        raise ValueError("Treino ou validacao sem as duas classes.")
    pesos = torch.tensor(len(i_tr) / (2 * cont), dtype=torch.float32, device=disp)
    modelo = torch.nn.Sequential(torch.nn.Linear(X.shape[1], 64), torch.nn.ReLU(),
                                 torch.nn.Linear(64, 2)).to(disp)
    opt = torch.optim.Adam(modelo.parameters(), lr=1e-3, weight_decay=1e-4)
    perda = torch.nn.CrossEntropyLoss(weight=pesos)
    Xt = torch.tensor(Z, device=disp); yt = torch.tensor(y, device=disp)
    ger = torch.Generator().manual_seed(semente)
    melhor, estado, sem_melhora, hist = -1.0, None, 0, []
    for ep in range(1, epocas + 1):
        modelo.train()
        ordem = torch.tensor(i_tr)[torch.randperm(len(i_tr), generator=ger)]
        soma = 0.0
        for k in range(0, len(ordem), lote):
            b = ordem[k:k + lote].to(disp)
            opt.zero_grad()
            l = perda(modelo(Xt[b]), yt[b]); l.backward(); opt.step()
            soma += l.item() * len(b)
        modelo.eval()
        with torch.no_grad():
            pv = modelo(Xt[torch.tensor(i_va, device=disp)]).argmax(1).cpu().numpy()
        ba = metricas(y[i_va], pv)["acuracia_balanceada"]
        hist.append({"epoca": ep, "perda_treino": soma / len(i_tr), "acuracia_balanceada_validacao": ba})
        if ba > melhor:
            melhor, sem_melhora = ba, 0
            estado = {k: v.detach().clone() for k, v in modelo.state_dict().items()}
            hist[-1]["melhor"] = True
        else:
            sem_melhora += 1
            if sem_melhora >= paciencia:
                break
    modelo.load_state_dict(estado); modelo.eval()

    def prever(idx):
        with torch.no_grad():
            s = torch.softmax(modelo(Xt[torch.tensor(idx, device=disp)]), 1).cpu().numpy()
        return s.argmax(1), s[:, 1]
    return modelo, prever, {"media": media, "dp": dp}, hist, melhor


# ---------------------------------------------------------------- principal
def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coleta", type=Path, required=True, help="Pasta swissprot_... da coleta")
    ap.add_argument("--preparacao", type=Path, required=True, help="Pasta preparacao_ec_... com as particoes")
    ap.add_argument("--cache", type=Path, default=PROJETO / "cache" / "huggingface")
    ap.add_argument("--embeddings-existentes", type=Path, default=None,
                    help="Reutiliza um embeddings.npy ja gerado por este script (pula a GPU no ESM-2)")
    ap.add_argument("--semente", type=int, default=42)
    ap.add_argument("--epocas", type=int, default=200)
    ap.add_argument("--paciencia", type=int, default=20)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--cpu", action="store_true", help="Treina o MLP na CPU (apenas para testes)")
    a = ap.parse_args(argv)
    inicio = time.perf_counter()

    linhas = carregar(a.coleta, a.preparacao)
    y = np.array([CLASSES.index(l["rotulo"]) for l in linhas])
    agora = datetime.now(timezone.utc)
    saida = a.preparacao / f"treino_ec_{agora.strftime('%Y%m%dT%H%M%SZ')}_{hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:6]}"
    saida.mkdir(parents=False, exist_ok=False)
    rel = {"tipo": "piloto_ec2_ec3_embeddings_e_mlp", "ok": False, "iniciado_utc": agora.isoformat(),
           "pasta_saida": str(saida), "proteinas": len(linhas),
           "rotulos": {c: int((y == i).sum()) for i, c in enumerate(CLASSES)},
           "hashes_entradas": {n: sha256_arquivo(p) for n, p in {
               "piloto_rotulado.csv": a.coleta / "piloto_rotulado.csv",
               "particoes.csv": a.preparacao / "particoes.csv",
               "treino_indices.npy": a.preparacao / "treino_indices.npy",
               "validacao_indices.npy": a.preparacao / "validacao_indices.npy",
               "teste_indices.npy": a.preparacao / "teste_indices.npy"}.items()},
           "sha256_script": sha256_arquivo(Path(__file__)), "semente": a.semente,
           "hiperparametros_fixos": {"arquitetura": [320, 64, 2], "otimizador": "Adam", "lr": 1e-3,
                                     "weight_decay": 1e-4, "lote": 64, "epocas_max": a.epocas,
                                     "paciencia": a.paciencia, "selecao": "maior acuracia balanceada na validacao",
                                     "normalizacao_e_pesos": "calculados somente no treino de cada rodada"},
           "teste_usado_para_ajuste": False}
    try:
        import torch
        torch.set_num_threads(a.threads)
        # ---- embeddings
        if a.embeddings_existentes:
            X = np.load(a.embeddings_existentes)
            rel["embeddings"] = {"origem": str(a.embeddings_existentes), "sha256": sha256_arquivo(a.embeddings_existentes)}
        else:
            sys.path.insert(0, str(PROJETO))
            import piloto_esm_gpu as piloto
            print("Gerando embeddings ESM-2 com piloto_esm_gpu.py (mesmo metodo do milhao)...", flush=True)
            carregado = piloto.exigir_gpu(a.threads, a.cache)
            X, desempenho = piloto.gerar_embeddings(*carregado[:4], linhas)
            rel["embeddings"] = {"modelo": piloto.MODELO, "revisao": piloto.REVISAO,
                                 "diagnostico_gpu": carregado[4], "desempenho": desempenho,
                                 "sha256_piloto_esm_gpu": sha256_arquivo(PROJETO / "piloto_esm_gpu.py")}
        X = np.asarray(X, dtype=np.float32)
        if X.shape != (len(linhas), 320) or not np.isfinite(X).all():
            raise ValueError(f"Embeddings invalidos: formato {X.shape}.")
        np.save(saida / "embeddings.npy", X)
        rel["embeddings"].update({"formato": list(X.shape), "precisao": "float32",
                                  "sha256_salvo": sha256_arquivo(saida / "embeddings.npy")})

        disp = torch.device("cpu" if a.cpu or not torch.cuda.is_available() else "cuda:0")
        rel["dispositivo_mlp"] = str(disp); rel["pytorch"] = torch.__version__

        # ---- a) particao fixa
        idx = {n: np.array([i for i, l in enumerate(linhas) if l["particao"] == n]) for n in ("treino", "validacao", "teste")}
        print(f"Treino fixo: {len(idx['treino'])} / {len(idx['validacao'])} / {len(idx['teste'])}", flush=True)
        modelo, prever, norm, hist, melhor_va = treinar_mlp(torch, X, y, idx["treino"], idx["validacao"],
                                                            a.semente, disp, a.epocas, a.paciencia)
        p_te, s_te = prever(idx["teste"])
        maj = int(np.bincount(y[idx["treino"]]).argmax())
        y_te = y[idx["teste"]]
        tam_te = np.array([linhas[i]["tamanho"] for i in idx["teste"]])
        por_faixa = {}
        for lo, hi in FAIXAS:
            m = (tam_te >= lo) & (tam_te <= hi)
            if m.any():
                por_faixa[f"{lo}-{hi}"] = metricas(y_te[m], p_te[m])
        rel["particao_fixa"] = {
            "epocas_executadas": len(hist), "melhor_epoca": max(h["epoca"] for h in hist if h.get("melhor")),
            "validacao_acuracia_balanceada": melhor_va,
            "teste_mlp": metricas(y_te, p_te),
            "teste_classe_majoritaria_do_treino": metricas(y_te, np.full(len(y_te), maj)),
            "teste_mlp_por_faixa_comprimento": por_faixa}
        torch.save({"estado": modelo.state_dict(), "media": torch.from_numpy(norm["media"]),
                    "dp": torch.from_numpy(norm["dp"]), "classes": CLASSES, "arquitetura": [320, 64, 2]},
                   saida / "modelo_ec.pt")
        with open(saida / "historico_particao_fixa.json", "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=1)
        with open(saida / "predicoes_teste.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["indice", "uid", "id_original", "ec", "tamanho", "grupo", "rotulo", "predicao", "escore_transferase", "correto"])
            for i, p, s in zip(idx["teste"], p_te, s_te):
                l = linhas[i]
                w.writerow([i, l["uid"], l["id_original"], l["ec"], l["tamanho"], l["grupo"], l["rotulo"],
                            CLASSES[p], f"{s:.6f}", CLASSES[p] == l["rotulo"]])

        # ---- b) validacao cruzada 5 dobras por grupo
        dobra = np.array([hash_int(f"{a.semente}:{l['grupo']}") % 5 for l in linhas])
        interna = np.array([hash_int(f"{a.semente}:validacao_interna:{l['grupo']}") % 10 == 0 for l in linhas])
        cv = []
        for k in range(5):
            te = np.where(dobra == k)[0]
            va = np.where((dobra != k) & interna)[0]
            tr = np.where((dobra != k) & ~interna)[0]
            _, prev_k, _, hist_k, _ = treinar_mlp(torch, X, y, tr, va, a.semente + k, disp, a.epocas, a.paciencia)
            m = metricas(y[te], prev_k(te)[0])
            m.update({"dobra": k, "treino": int(len(tr)), "validacao_interna": int(len(va)), "epocas": len(hist_k)})
            cv.append(m)
            print(f"Dobra {k + 1}/5: acuracia balanceada {m['acuracia_balanceada']:.4f}", flush=True)
        ba = np.array([m["acuracia_balanceada"] for m in cv]); ac = np.array([m["acuracia"] for m in cv])
        f1 = np.array([m["f1_macro"] for m in cv])
        rel["validacao_cruzada_5_dobras_por_grupo"] = {
            "regra_dobras": "SHA256(semente:grupo_global) mod 5; validacao interna = SHA256(semente:validacao_interna:grupo) mod 10 == 0",
            "observacao": "Todas as 1.000 proteinas participam; nenhuma escolha de hiperparametro foi feita com estas dobras.",
            "acuracia_media": float(ac.mean()), "acuracia_dp": float(ac.std(ddof=1)),
            "acuracia_balanceada_media": float(ba.mean()), "acuracia_balanceada_dp": float(ba.std(ddof=1)),
            "f1_macro_media": float(f1.mean()), "f1_macro_dp": float(f1.std(ddof=1)), "dobras": cv}
        rel.update({"ok": True, "segundos": round(time.perf_counter() - inicio, 1),
                    "limites": ["Piloto de 1.000 enzimas revisadas do Swiss-Prot (recorte por accession, nao aleatorio).",
                                "Teste fixo pequeno (cerca de 100 proteinas); usar tambem a validacao cruzada.",
                                "Linclust a 50% nao elimina homologia remota entre treino e teste.",
                                "ESM-2 foi pre-treinado em UniRef50, que pode conter estas proteinas."]})
    except Exception as e:  # registra a falha sem inventar resultados
        rel["erro"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        with open(saida / "relatorio_treino_ec.json", "w", encoding="utf-8") as f:
            json.dump(rel, f, ensure_ascii=False, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    resumo = {"ok": rel["ok"], "pasta_saida": rel["pasta_saida"],
              "teste_fixo_mlp": {k: rel["particao_fixa"]["teste_mlp"][k] for k in ("n", "acuracia", "acuracia_balanceada", "f1_macro", "matriz_confusao_linhas_reais_colunas_previstas")},
              "cv5": {k: v for k, v in rel["validacao_cruzada_5_dobras_por_grupo"].items() if k != "dobras" and k != "regra_dobras" and k != "observacao"},
              "segundos": rel["segundos"]}
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
