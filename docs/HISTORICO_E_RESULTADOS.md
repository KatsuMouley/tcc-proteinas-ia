> **Registro de 13–14/10/2026.** Este documento descreve o sistema antes da validação de 18–19/10. O estado atual (consulta EC, GPU/CPU, Configurações, Fase 1 pelo painel, instalação) está no [README](../README.md) e na seção 3.2 do Dossiê Técnico.

---
tags: [tcc, proteinas, resultados]
---

# Histórico do experimento anterior

Este registro resume as saídas recebidas durante o desenvolvimento. Os dados, modelos e relatórios desse experimento continuam no seu PC. Este pacote não executou novamente o processamento de um milhão de proteínas.

## O que já foi concluído

1. Preparação de Python Windows e teste ESM-2 em CPU.
2. Migração para PyTorch com CUDA e confirmação da GTX 1650.
3. Piloto real de 100 representantes, com embeddings `100 × 320`, float32 e valores finitos.
4. Conferência dos rótulos pela regra literal: no piloto, 58 `Completa` e 42 `Incompleta`, sem divergências.
5. Ampliação em lotes até um milhão de embeddings de sequências únicas elegíveis.
6. Auditoria técnica completa, consolidação, agrupamento global e partições por grupo.
7. Treinamento do MLP e teste de previsões.
8. API e dashboard locais; depois, controlador para executar experiências novas automaticamente.
9. Organização do código neste pacote, com documentação atual e arquivos históricos identificados.

## Base de um milhão

| Indicador | Resultado recebido |
|---|---:|
| Embeddings | 1.000.000 |
| Dimensão | 320 |
| Precisão | float32 |
| Lotes | 16.565 |
| Classe `Completa` | 762.119 |
| Classe `Incompleta` | 237.881 |
| Representantes repetidos registrados | 166.915 |
| Descartes: mais de 512 resíduos | 414.614 |
| Descartes: caracteres não suportados | 232 |
| Erros da auditoria técnica | 0 |

A coleta original tinha 3.428 pares de fontes GZ/CSV encontrados; 1.482 foram concluídos até o fim com integridade e 1.946 permaneceram pendentes quando o limite de um milhão foi atingido. Assim, `base_completa: false` era compatível com a conclusão do recorte solicitado.

O recorte era o primeiro milhão de sequências únicas elegíveis na ordem de processamento. Não era uma amostra aleatória de toda a coleção NCBI. A exclusão acima de 512 resíduos também restringiu a população representada.

## Agrupamento e partições

O MMseqs2 global retornou 560.678 grupos, com 10.419 proteínas no maior grupo. O relatório recebido registrou 60,292 segundos para esse agrupamento, com 8 threads. Linclust usou identidade mínima 0,5 e cobertura mínima 0,8, com os demais parâmetros registrados no relatório.

| Partição | Proteínas | `Completa` | `Incompleta` | Grupos |
|---|---:|---:|---:|---:|
| Treino | 803.167 | 612.377 | 190.790 | 448.747 |
| Validação | 98.165 | 74.208 | 23.957 | 55.894 |
| Teste | 98.668 | 75.534 | 23.134 | 56.037 |

A semente foi 42 e foram verificados zero grupos compartilhados. Como Linclust é heurístico, essa conferência não demonstra ausência de toda homologia entre partições.

## Treino anterior

O classificador usou embeddings ESM-2 fixos e MLP `320 → 64 → 2`. O histórico registrado do experimento anterior descreveu 10 épocas, 20.674 parâmetros e aproximadamente 302,655 segundos para o treino e seu procedimento associado.

| Referência / modelo | Acurácia no teste | Acurácia balanceada |
|---|---:|---:|
| Classe majoritária `Completa` | 76,55% | 50,00% |
| MLP sobre embeddings | 89,85% | 89,34% |

F1 macro registrado: aproximadamente 0,8675. A matriz de confusão usa linhas reais e colunas previstas:

| Classe real | Prevista `Incompleta` | Prevista `Completa` |
|---|---:|---:|
| `Incompleta` | 20.447 | 2.687 |
| `Completa` | 7.324 | 68.210 |

Foram 10.011 erros. A regra direta reproduz os rótulos por construção; os resultados do MLP medem sua aproximação dessa regra.

## Consultas verificadas

Para `ACDEFGHIKLMNPQRSTVWY`, a regra direta retornou `Completa`, mas o MLP retornou `Incompleta`, com escore de `Completa` perto de 0,013709. Esse caso incorreto deve permanecer documentado.

Para a proteína real `p000000000`, com 185 resíduos, uma nova inferência reproduziu a previsão registrada `Incompleta`. Os escores de `Completa` ficaram próximos de 0,3508533, com diferença pequena de ponto flutuante. Uma consulta reprodutível confirma a ligação de inferência com o modelo, sem demonstrar acerto em todas as sequências.

## Diferença do fluxo automático novo

No histórico, o colega agrupou por arquivo e enviou CSVs. Nós começamos dos GZ/CSV e geramos embeddings de representantes. No controlador atual, um experimento novo seleciona candidatos dos GZ, agrupa o recorte inteiro com MMseqs2 e gera seu próprio CSV antes dos embeddings.

Os resultados novos têm pasta, banco, código congelado e modelo próprios. As quantidades e métricas acima pertencem ao experimento anterior, não são resultados prometidos para um recorte novo de 1.000 candidatos.

## Como apresentar no TCC

O framework demonstra organização e rastreabilidade de dados proteicos, embeddings de um modelo pré-treinado, treinamento supervisionado e consulta local. A regra de rótulos é explícita. A demonstração não constitui uma avaliação de qualidade nutricional real e não inclui AlphaFold no fluxo executado.

Relate fonte e seleção, filtros, rótulos, modelo/revisão, parâmetros MMseqs2, partições, referências, métricas e limitações. Conserve os relatórios originais como evidência dos resultados.
