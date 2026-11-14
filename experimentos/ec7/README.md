# Modelo EC 1 a EC 7 — classificador das sete classes enzimáticas

**Este é o modelo principal do TCC** desde a versão 3.4 (31/10/2026). Ele está integrado ao assistente guiado (caminho "Treinar o modelo EC 1 a EC 7"), à consulta (resultado em destaque), ao mapa e à matriz 7 × 7 de Explorar e analisar e à aba Pipeline automático do painel avançado. O modelo treinado fica em `dados/modelos/classificador_ec7` (no Git). Treinos novos ficam em `dados/experimento_ec7/` (fora do Git).

O EC 2 × EC 3 (transferase × hidrolase, `dados/modelos/classificador_ec2_ec3`) foi o piloto que validou o método e continua no sistema como **modelo complementar**.

| EC | Classe | EC | Classe |
|---|---|---|---|
| 1 | Oxidorredutase | 5 | Isomerase |
| 2 | Transferase | 6 | Ligase |
| 3 | Hidrolase | 7 | Translocase |
| 4 | Liase | | |

## Resultado registrado no TCC

| Medida | Valor |
|---|---|
| Acurácia balanceada no teste fixo | **75,4%** (F1 macro 0,755; 343 enzimas de 175 grupos) |
| Validação cruzada, 5 dobras por grupo | 71,3% ± 3,0 (dobras de 66,5% a 73,9%) |
| Acaso | 14,3% |
| Dados | 3.500 enzimas do Swiss-Prot (500 por classe), 1.968 grupos; treino 2.823 / validação 334 / teste 343 |
| Tempo (embeddings + seis treinos, GTX 1650) | cerca de 22 min |

Sensibilidade por classe no teste: EC 7 90,0% · EC 6 83,8% · EC 5 74,5% · EC 1 71,7% · EC 2 71,4% · EC 4 70,7% · EC 3 66,0%.

## Como rodar

**Pela interface (recomendado):** no assistente guiado, escolha "Treinar o modelo EC 1 a EC 7" e siga as telas Dados → Agrupar → Treinar → Resultados. No painel avançado, use Pipeline automático → modelo EC 1 a EC 7 (coletar, preparar, treinar, continuar ou fazer tudo).

**Pela linha de comando:** dois cliques em `experimentos\ec7\rodar_ec7.cmd` rodam tudo. Também dá para rodar uma etapa por vez:

```
experimentos\ec7\rodar_ec7.cmd coletar    1. Swiss-Prot, até 500 enzimas revisadas por classe (internet)
experimentos\ec7\rodar_ec7.cmd preparar   2. MMseqs2 (50% id., 80% cob.) + partições por grupo
experimentos\ec7\rodar_ec7.cmd treinar    3. Embeddings ESM-2 + MLP + validação cruzada de 5 dobras
experimentos\ec7\rodar_ec7.cmd continuar  2 e 3, reaproveitando a última coleta
experimentos\ec7\rodar_ec7.cmd resumo     Mostra o resultado do último treino
```

O modo do MMseqs2 (nativo ou WSL), as threads e GPU/CPU vêm da tela **Configurações**. Cada etapa usa a pasta concluída mais recente da etapa anterior. Se uma etapa falhar, a pasta fica preservada com o relatório do erro: basta rodar de novo a partir dessa etapa. Se o UniProt responder erro (HTTP 500), a coleta para com segurança e preserva os arquivos parciais. O treino do EC 1 a EC 7 não roda junto com outra tarefa, para não disputar a placa de vídeo.

## Protocolo (o mesmo do piloto EC 2 × EC 3)

- Swiss-Prot revisado (release 2026_03), com EC explícito, uma única classe EC de primeiro nível e até 512 resíduos. Sequências repetidas são removidas por SHA-256. A seleção é determinística, pelos menores valores de SHA-256("42:" + hash da sequência).
- Agrupamento com MMseqs2 `easy-linclust` (50% de identidade, 80% de cobertura). Cada grupo inteiro vai para uma só partição: cerca de 80% treino, 10% validação e 10% teste.
- MLP 320 → 64 → 7 (20.999 parâmetros), Adam (lr 0,001, weight decay 0,0001), lote 64, até 200 épocas, parada após 20 épocas sem melhora, entropia cruzada com pesos por classe e escolha da época pela acurácia balanceada na validação.
- Validação cruzada de 5 dobras por grupo. O teste não é usado para escolher nada.

## Como ler o resultado

- Compare a acurácia balanceada com o **acaso de 14,3%**, não com os 86% do modelo EC 2 × EC 3: o número de classes muda a dificuldade.
- Com 343 proteínas no teste, a validação cruzada (média ± desvio) é a estimativa mais estável.
- O modelo sempre escolhe uma das sete classes, mesmo para proteínas que não são enzimas, e os escores não são calibrados. Use o resultado para **triagem**, não para atribuir função de forma definitiva.

## Arquivos

| Arquivo | Origem |
|---|---|
| `coletar_ec7.py` | versão generalizada de `etapas/baixar_piloto_swissprot_ec.py` |
| `preparar_ec7.py` | versão generalizada de `etapas/preparar_piloto_ec.py` |
| `treinar_ec7.py` | versão generalizada de `etapas/piloto_ec_embeddings_treino.py` |
| `ec7_comum.py` | as sete classes |
| `rodar_ec7.py` / `.cmd` | orquestra as etapas e mostra o resumo |
