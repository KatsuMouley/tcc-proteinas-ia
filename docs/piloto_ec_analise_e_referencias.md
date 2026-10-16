# Piloto EC 2 × EC 3: análise do conjunto e referências sem GPU

Calculado em 14/10/2026 a partir de `piloto_rotulado.csv`, `particoes.csv`, `global_cluster.tsv` e índices NPY. Os SHA-256 dos 9 arquivos conferem com os relatórios da coleta e da preparação.

## Conjunto

| Indicador | Valor |
|---|---:|
| Proteínas | 1.000 (500 Transferases, 500 Hidrolases) |
| Release UniProt | 2026_03 |
| Organismos distintos | 254 |
| Grupos MMseqs2 (50% id, 80% cov) | 791 (668 singletons; maior grupo 14) |
| Grupos com as duas classes | 0 |
| Partições (proteínas / grupos) | treino 801 / 637; validação 92 / 72; teste 107 / 82 |
| Teste por classe | 59 Transferases, 48 Hidrolases |
| Mediana de comprimento | Transferase 338; Hidrolase 272 |
| EC parcial (ex.: 2.1.1.-) | 128 Transferases, 157 Hidrolases |

Principais subclasses: Transferases 2.1 (metil, 150), 2.7 (fósforo/quinases, 98), 2.3 (aciltransferases, 85); Hidrolases 3.1 (ésteres, 189), 3.6 (anidridos, 84), 3.5 (C–N não peptídicas, 79), 3.4 (peptidases, 78).

### Evidência das anotações

Só 177 das 1.000 anotações EC têm evidência experimental (ECO:0000269): 118 Transferases e 59 Hidrolases. A maioria vem de inferência por regra ou similaridade: ECO:0000255 em 644, ECO:0000250 em 83, ECO:0000305 em 64. Revisado no Swiss-Prot não significa comprovado em laboratório, e isso deve constar nas limitações.

## Referências sem GPU (mesmas partições do MLP)

As referências foram treinadas em treino + validação e avaliadas no teste fixo, sem ajuste de hiperparâmetros. A validação cruzada usa 5 dobras por grupo, com dobra = SHA256(42:grupo) mod 5.

| Referência | Teste: acurácia | Teste: acurácia balanceada | Validação cruzada: acurácia balanceada (média ± dp) |
|---|---:|---:|---:|
| Classe majoritária do treino (Hidrolase) | 44,9% | 50,0% | 50,0% |
| Só comprimento (limiar do treino) | 57,9% | 55,8% | 62,7% ± 6,6 |
| Composição de 20 aminoácidos + logística | 62,6% | 63,2% | 59,1% ± 2,1 |
| Composição + log(comprimento) + logística | 69,2% | 68,5% | 63,1% ± 3,9 |
| Dipeptídeos (400) + logística | 65,4% | 64,4% | 58,1% ± 5,1 |
| Vizinho mais próximo por 3-mers | 65,4% | 65,3% | 70,4% ± 3,5 |
| **MLP sobre embeddings ESM-2** | [a preencher] | [a preencher] | [a preencher] |

Leitura: atributos simples de sequência chegam no máximo a cerca de 70%. Se o MLP com ESM-2 ficar claramente acima disso, o ganho vem da representação aprendida pelo modelo de linguagem de proteínas.

## Controles do script de treino

O script foi testado com embeddings sintéticos. Com sinal artificial, chegou a 92% de acurácia balanceada. Com ruído puro, ficou em 49,2% ± 2,5 na validação cruzada, o esperado sem vazamento entre treino e teste. Partições adulteradas e embeddings de formato errado bloqueiam a execução.
