# Experimento EC7 — classificador das 7 classes enzimáticas

**Separado do painel.** O sistema principal continua com o modelo EC 2 × EC 3
(`dados/modelos/classificador_ec2_ec3`). Nada nesta pasta altera o painel, esse modelo
ou os scripts de `etapas/`. Os resultados ficam em `dados/experimento_ec7/` (fora do git).

## Objetivo

Testar se a mesma receita do piloto EC 2 × EC 3 (ESM-2 → MLP 320 → 64 → N) funciona com as
7 classes EC. Se o resultado for bom, ele entra no TCC como resultado extra; se não for, vira trabalho futuro.

| EC | Classe | EC | Classe |
|---|---|---|---|
| 1 | Oxidorredutase | 5 | Isomerase |
| 2 | Transferase | 6 | Ligase |
| 3 | Hidrolase | 7 | Translocase |
| 4 | Liase | | |

## Como rodar

Dois cliques em `experimentos\ec7\rodar_ec7.cmd` roda tudo. Também dá para rodar uma etapa por vez:

```
experimentos\ec7\rodar_ec7.cmd coletar    1. Swiss-Prot, até 500 enzimas revisadas por classe (internet)
experimentos\ec7\rodar_ec7.cmd preparar   2. MMseqs2 (50% id., 80% cob.) + partições por grupo (WSL)
experimentos\ec7\rodar_ec7.cmd treinar    3. Embeddings ESM-2 + MLP + validação cruzada de 5 dobras
experimentos\ec7\rodar_ec7.cmd resumo     Mostra o resultado do último treino
```

WSL, threads e GPU/CPU vêm da tela **Configurações** do painel. Cada etapa usa a pasta
concluída mais recente da etapa anterior. Se uma etapa falhar, a pasta fica preservada com
o relatório do erro, e basta rodar de novo a partir dessa etapa.

## Protocolo (igual ao piloto EC 2 × EC 3)

- Swiss-Prot revisado, até 512 resíduos, uma única classe EC por proteína, sequências duplicadas
  removidas e seleção determinística (SHA-256 com semente 42).
- Agrupamento MMseqs2 e grupo inteiro numa só partição: 80% treino, 10% validação e 10% teste.
- MLP 320 → 64 → 7, Adam (lr 0,001, weight decay 0,0001), lote 64, até 200 épocas, paciência 20,
  pesos por classe e escolha da época pela acurácia balanceada na validação.
- Validação cruzada de 5 dobras por grupo. O teste não é usado para escolher nada.

## Como ler o resultado

- **Acaso com 7 classes = 14,3%** (contra 50% no binário). Compare a acurácia balanceada com isso,
  não com os 86% do modelo EC 2 × EC 3.
- Use principalmente a **validação cruzada** (média ± desvio). O teste fixo tem cerca de 10% da coleta.
- Algumas classes (sobretudo EC 7) podem ficar abaixo de 500 proteínas por causa do limite de
  512 resíduos. O relatório da coleta mostra quantas entraram por classe; os pesos por classe
  compensam o desbalanceamento no treino.

## Arquivos

| Arquivo | Origem |
|---|---|
| `coletar_ec7.py` | cópia generalizada de `etapas/baixar_piloto_swissprot_ec.py` |
| `preparar_ec7.py` | cópia generalizada de `etapas/preparar_piloto_ec.py` |
| `treinar_ec7.py` | cópia generalizada de `etapas/piloto_ec_embeddings_treino.py` |
| `ec7_comum.py` | as 7 classes; aplicadas só no processo deste experimento |
| `rodar_ec7.py` / `.cmd` | orquestra as etapas e mostra o resumo |
