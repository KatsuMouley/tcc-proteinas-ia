# Piloto EC 2 x EC 3 — etapa 1: preparar os IDs

Status: seletor implementado. Execucao na base real do PC pendente. Nenhum rotulo EC foi obtido por este pacote.

## Instalar os tres arquivos adicionais

Copie `etapas/preparar_sondagem_ec.py`, `testes/test_sondagem_ec.py` e este documento para as mesmas subpastas em `C:\ai_tcc`. Este pacote acrescenta arquivos independentes; nao substitui os scripts anteriores nem a configuracao do sistema.

## Testar

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -B -m unittest discover -s .\testes -p "test_sondagem_ec.py" -v
```

Os testes usam bases sinteticas em pastas temporarias. Nao usam rede, GPU, modelo ou dados reais.

## Preparar a amostra

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -B .\etapas\preparar_sondagem_ec.py --quantidade 500 --semente 42
```

O comando percorre `indice.csv` e `particoes.csv`, confere seus hashes com os relatorios existentes e faz uma amostragem por reservatorio apenas entre as linhas de treino e validacao. A semente torna a selecao reproduzivel para as mesmas entradas e versao Python. A selecao e uniforme por sequencia, nao por grupo nem por classe EC. Grupos podem aparecer mais de uma vez.

Cada registro conserva indice global do vetor, UID, ID original com versao, grupo global, particao, comprimento, hash da sequencia e arquivo de origem. A regra Completa/Incompleta nao participa da selecao. Nenhum registro da particao teste e exportado.

O programa usa apenas a biblioteca padrao do Python. Nao carrega `embeddings.npy`, nao le FASTA, nao consulta UniProt/NCBI, nao usa CUDA e nao treina. A leitura completa dos CSVs evita escolher apenas os primeiros registros; o tempo no PC ainda deve ser observado. O progresso aparece a cada 100 mil linhas.

## Saidas

Cada execucao cria uma pasta nova em `dados/piloto_ec2_ec3/sondagem_ids_DATA_UUID/`, contendo:

- `candidatos.csv`: registros selecionados com os vinculos aos vetores e particoes originais.
- `ids_ncbi.txt`: IDs originais unicos, um por linha, mantendo a versao.
- `relatorio_preparacao.json`: metodo, contagens, hashes das entradas e caminho dos arquivos exportados.

As entradas cientificas sao abertas apenas para leitura. Se algum CSV nao corresponder ao relatorio ou se os UIDs estiverem desalinhados, o programa interrompe antes de criar a pasta de saida. Pastas de amostras anteriores sao preservadas. As particoes originais nao sao refeitas.

## Limites e proxima etapa

Esta e uma amostra para medir viabilidade de anotacao, nao um conjunto rotulado pronto para treino. Cobertura Swiss-Prot, EC 2/EC 3, quantidade de grupos por classe e suficiencia para o piloto permanecem a confirmar. Uma amostra pequena sem correspondencias nao prova ausencia de anotacoes no milhao.

O proximo passo, separado, sera consultar anotacoes revisadas usando esses IDs e conferir a identidade das sequencias antes de aceitar os rotulos. Nao remover a versao de um ID nem aceitar mapeamento ambiguo como anotacao confirmada sem verificacao.

A base atual ja foi limitada a 1-512 residuos. Este pacote nao permite contar quantas EC 2/EC 3 existiam entre os 414.614 descartes historicos por comprimento. Esses totais permanecem desconhecidos e nao sao registrados como zero.

Para continuidade, compartilhar o JSON final e `candidatos.csv` desta execucao. Os vetores e o milhao original permanecem no PC.
