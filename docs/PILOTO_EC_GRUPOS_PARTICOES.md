# Piloto EC 2 × EC 3 — agrupamento e partições

Projeto: Inteligência Artificial Aplicada à Genética e Bioinformática

## 1. Estado confirmado

A coleta Swiss-Prot terminou no PC com `ok: true` e os 25 testes aprovados.

| Resultado da coleta | Quantidade |
| --- | ---: |
| Registros baixados nas duas consultas | 4.000 |
| Candidatos únicos auditados | 3.951 |
| Transferases selecionadas | 500 |
| Hidrolases selecionadas | 500 |
| Candidatos acima de 512 resíduos | 868 |
| EC 2 exclusiva e revisada acima de 512 | 371 |
| EC 3 exclusiva e revisada acima de 512 | 384 |
| Selecionadas com menos de 30 resíduos | 0 |

Os motivos de exclusão se sobrepõem; as duas contagens por EC exclusiva não
englobam todo candidato acima de 512. Estas contagens pertencem ao piloto,
não aos descartes históricos do milhão. O release recebido foi `2026_03`.

As Transferases selecionadas têm comprimentos de 45 a 512, mediana 338;
as Hidrolases, de 70 a 512, mediana 272. Esses dados devem constar na análise
de limitações do recorte. A seleção limitada por accession não representa
uma amostra aleatória de todo o Swiss-Prot.

**Implementado neste pacote:** conferência de integridade, execução de
MMseqs2, validação do TSV e separação por grupos. Os 14 testes locais usam
dados e processo MMseqs2 simulados. A execução real do novo agrupamento e
suas contagens permanecem **[a confirmar]**.

**Planejado para depois:** embeddings deste piloto e treinamento EC.
O milhão, os 560.678 grupos históricos e o MLP preliminar não são refeitos.

## 2. Instalação

Copie estes três arquivos novos do ZIP para `C:\ai_tcc`, mesclando as pastas:

| Arquivo | Finalidade |
| --- | --- |
| `etapas\preparar_piloto_ec.py` | Conferir, agrupar e separar o piloto |
| `testes\test_preparacao_piloto_ec.py` | Testes locais com processo simulado |
| `docs\PILOTO_EC_GRUPOS_PARTICOES.md` | Este guia |

O programa reutiliza `etapas\consultar_sondagem_ec.py` e o backend de execução
de `etapas\preparar_base_ia.py`, que já estão no PC. O ambiente existente com
NumPy e o MMseqs2 instalado no Ubuntu/WSL são usados nesta etapa.

## 3. Executar os testes

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -B -m unittest discover -s .\testes -p "test_preparacao_piloto_ec.py" -v
```

Esperado: **14 testes, OK**. São verificados hashes, rótulos EC, correspondência
CSV/FASTA, cobertura do TSV, preservação das entradas, grupos inteiros nas
partições e índices NumPy. Os testes não executam o MMseqs2 real.

## 4. Preparar o piloto no PC

```powershell
cd C:\ai_tcc
$Coleta = ".\dados\piloto_ec2_ec3\swissprot_20261014T021908726567Z_46400a"
.\.venv\Scripts\python.exe -B .\etapas\preparar_piloto_ec.py --coleta $Coleta --esperado 1000 --wsl Ubuntu --threads 8 --semente 42
```

Este comando usa CPU para o MMseqs2. Os embeddings na GPU serão outra etapa.
Uma pasta `preparacao_ec_DATA_HORA_IDENTIFICADOR` é criada dentro da coleta.
O log do MMseqs2 fica nessa pasta e seu caminho aparece no terminal.

## 5. O que o comando faz

1. Confere o relatório e os hashes dos arquivos da coleta. Verifica as 1.000
   linhas, UIDs, rótulos, ECs explícitos, revisão, comprimentos e hashes das
   sequências. Confere também quantidade e ordem no FASTA.
2. Executa `easy-linclust` nas 1.000 sequências com os parâmetros já usados
   no experimento anterior. O temporário privado do WSL fica em `/var/tmp`.
3. Confere se o TSV contém cada UID exatamente uma vez e se toda representante
   pertence ao próprio grupo. UIDs de outra base, faltantes ou repetidos bloqueiam.
4. Atribui um destino a cada grupo inteiro, por hash da semente e UID da
   representante. Não propaga o rótulo da representante aos membros.
5. Salva as partições e os índices correspondentes às linhas originais do
   `piloto_rotulado.csv`. Mantém esses vínculos para a futura matriz de embeddings.

| Parâmetro MMseqs2 | Valor |
| --- | --- |
| Identidade mínima | 0,5 |
| Cobertura mínima | 0,8 |
| `--cov-mode` | 0 |
| `--cluster-mode` | 1 |
| `--alignment-mode` | 3 |
| `--kmer-per-seq` | 80 |
| `--split-memory-limit` | 8G |
| E-value | 0,001 |
| Threads CPU | 8 no comando apresentado |

A separação usa os primeiros oito bytes de `SHA256(semente:UID_representante)`,
divididos por `2**64`: abaixo de 0,8 → treino; de 0,8 a menos de 0,9 → validação;
o restante → teste. As proporções 80/10/10 são aproximadas e os grupos não são
divididos para forçar equilíbrio de classes.

A semente 42 está fixada antes do treino. O programa não busca outra semente
em função das contagens. Se uma partição ficar vazia ou faltar uma classe
em treino/validação, a preparação é preservada como inconclusiva para revisão
do protocolo. Não se escolhem novos parâmetros olhando desempenho de teste.

## 6. Saídas e critérios de conclusão

| Saída | Uso |
| --- | --- |
| `global_cluster.tsv` | Representante e membros de cada grupo deste piloto |
| `particoes.csv` | UID, índice, grupo, partição e rótulo próprio da proteína |
| `treino_indices.npy` | Índices de treino, int64, começando em zero |
| `validacao_indices.npy` | Índices de validação no mesmo CSV |
| `teste_indices.npy` | Índices reservados para avaliação futura |
| `grupos_por_linha.npy` | Índice da representante para cada linha do CSV |
| `relatorio_preparacao_ec.json` | Grupos, partições, classes, hashes, parâmetros e estado |
| `execucao_mmseqs.json`, `mmseqs.log` | Comando efetivo, ambiente e log |

O relatório deverá registrar `ok: true` e
`grupos_compartilhados_entre_particoes: 0`. O teste é criado e reservado;
nenhuma predição ou métrica de teste é calculada.

Linclust é heurístico. Zero grupos compartilhados confirma a separação dos
grupos encontrados, sem provar ausência de toda homologia entre as partições.
Esses parâmetros e essa limitação devem ser apresentados no TCC.

O script preserva os dados de entrada e cria outra pasta em cada execução.
Na falha, conserva o relatório e o log disponíveis, com `ok: false`.
`treinamento_liberado` permanece falso, pois ainda faltam os embeddings.

## 7. O que enviar de volta

Cole o JSON final do terminal. Vamos conferir quantidade de grupos, maior
grupo, singletons, partições e distribuição de classes antes de preparar
a geração dos embeddings do piloto na GPU.
