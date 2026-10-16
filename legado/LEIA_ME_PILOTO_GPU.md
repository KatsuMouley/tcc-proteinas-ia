# Primeiro piloto com proteinas reais na GTX 1650

Pre-requisito: o teste `testar_esm_gpu.py` ja terminou com `ok: true`,
`dispositivo: cuda:0` e NVIDIA GeForce GTX 1650. Use o ambiente existente
em `C:\ai_tcc`. Este pacote nao instala nada.

## 1. Coloque o script no projeto

Extraia este ZIP diretamente em `C:\ai_tcc`. Confira que o arquivo
`C:\ai_tcc\piloto_esm_gpu.py` ficou ao lado de `.venv` e de `cache`.

## 2. Localize um par de arquivos

No PowerShell:

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe .\piloto_esm_gpu.py --listar
```

O script pesquisa `C:\ai_tcc\dados` e a pasta Downloads do Windows,
incluindo os arquivos `.gz` e `.csv` que estao dentro dos ZIPs baixados
do Drive. Le os nomes dos arquivos no ZIP; nao extrai toda a base.

Um par tem nomes como `gbpln94.fsa_aa.gz` e `gbpln94.fsa_aa.csv`.
Esse nome e apenas um exemplo; o script mostra o que realmente encontrar.
O CSV precisa ser um resultado do agrupamento, com as colunas
`Arquivo_Origem`, `Grupo_Similaridade` e `ID_da_Proteina`.
O menor .gz com CSV correspondente aparece como `Par 1`.

Se seus ZIPs estiverem em outra pasta, indique o caminho:

```powershell
.\.venv\Scripts\python.exe .\piloto_esm_gpu.py --listar --fontes "D:\pasta_com_os_zips"
```

Use a mesma opcao `--fontes` no comando da proxima etapa.
Nao e preciso mover ou apagar os downloads para executar este piloto.

## 3. Execute o piloto

Se a listagem encontrou `Par 1`, execute:

```powershell
.\.venv\Scripts\python.exe .\piloto_esm_gpu.py --par 1
```

Para outro par, troque somente o numero. A selecao dos pares fica ordenada
pelo tamanho do .gz; refaca a listagem se adicionar ou remover dados.

Se voce ja extraiu apenas um .gz e o CSV correspondente, pode indicar
os caminhos diretamente, sem usar a listagem:

```powershell
.\.venv\Scripts\python.exe .\piloto_esm_gpu.py --gz ".\dados\brutos\gbpln94.fsa_aa.gz" --csv ".\dados\clusters\gbpln94.fsa_aa.csv"
```

Novamente, os nomes deste comando sao exemplos. Substitua pelos seus.

## 4. O que o programa faz, da primeira a ultima etapa

1. Localiza o par .gz/CSV escolhido. Os arquivos de entrada sao abertos para leitura.
2. Confere `Arquivo_Origem` no CSV e coleta ate 1.000 grupos distintos.
   Remove somente o prefixo `Grupo_` para recuperar o ID do representante
   original do MMseqs2. Nao escolhe um membro arbitrario do grupo.
3. Confirma que CUDA funciona e carrega a mesma revisao do ESM-2 do cache
   `C:\ai_tcc\cache\huggingface`. Nao baixa outro modelo.
4. Le o FASTA do .gz em fluxo, inclusive quando ele esta dentro de um ZIP,
   e recupera ate 100 representantes utilizaveis. Mantem no maximo uma
   sequencia do FASTA em leitura, alem da pequena amostra e dos IDs candidatos.
5. Seleciona sequencias com ate 512 residuos. Descarta sequencias maiores,
   vazias, com caracteres nao suportados ou identicas a outra da amostra.
   Nao corta as proteinas longas. Converte letras para maiusculas e remove
   marcadores `*` no final, registrando a quantidade removida. `*` internos
   causam descarte. Aceita os aminoacidos padrao e B, X, Z, U e O.
6. Salva o pequeno CSV/FASTA da amostra e os motivos de descarte.
7. Executa o modelo na GPU, com lote 1, precisao float32 e sem gradientes.
   Faz a media dos vetores dos residuos, excluindo os tokens especiais.
8. Salva uma matriz float32 com 320 colunas e o relatorio de execucao.

A CPU continua fazendo descompressao, leitura, tokenizacao e gravacao.
PyTorch e as bibliotecas numericas ficam limitados a duas threads de CPU
neste processo. Isso nao e um limite absoluto de uso do processador ou do SSD.
O modelo precisa usar CUDA: se houver erro, o programa para e nao passa para CPU.

## 5. Confira o resultado

Arquivos em `C:\ai_tcc\dados\amostra\piloto_gpu_01`:

| Arquivo | Conteudo |
| --- | --- |
| `amostra.csv` | IDs, grupos, descricoes, sequencias, tamanhos e hashes. |
| `amostra.fasta` | Somente as sequencias da pequena amostra. |
| `descartes.csv` | Representantes avaliados e descartados, com o motivo. |
| `embeddings.npy` | Matriz NumPy float32 de N linhas e 320 colunas. |
| `relatorio.json` | Quantidade real, dispositivo, tempos, memoria, fontes e eventuais erros. |

A linha 0 de `embeddings.npy` corresponde a primeira linha de dados
de `amostra.csv`, e assim por diante. Um resultado completo para o limite
padrao deve informar `ok: true`, `dispositivo: cuda:0`,
`quantidade_amostra: 100`, `amostra_completa: true` e
`formato_embeddings: [100, 320]`.

Se menos de 100 representantes forem aceitos, o programa salva os que encontrou
e informa `amostra_completa: false`. Isso pode ocorrer por haver poucos grupos,
IDs ausentes ou sequencias descartadas. Confira os motivos antes de aumentar
a amostra. Esta selecao serve para testar o funcionamento; nao representa
uma amostragem aleatoria ou uma avaliacao de qualidade biologica.

O programa pode parar a leitura quando a amostra estiver pronta. Nesse caso,
`integridade_gz_e_membro_zip_validada: false` informa que ele nao conferiu ate
o fim todos os bytes/CRCs do .gz selecionado e de seu membro no ZIP.
Quando true, refere-se somente a esse membro, nao aos outros arquivos do ZIP.
O piloto nao substitui uma verificacao completa dos arquivos baixados.

Pico de memoria PyTorch mede a alocacao do PyTorch, nao toda a VRAM usada
pelo Windows e por outros programas. O tempo da inferencia exclui aquecimento;
o tempo de preparacao dos dados e informado separadamente.

## Se ocorrer um erro

- Nenhum par encontrado: confira as pastas mostradas, use `--fontes`, ou
  extraia somente um .gz e seu CSV e passe `--gz`/`--csv`.
- Arquivo corrompido/incompleto: o programa informa erro durante a leitura;
  confira o ZIP/.gz selecionado e preserve os originais.
- Modelo nao encontrado no cache: o script precisa estar em `C:\ai_tcc`.
  Um cache em outro lugar pode ser indicado com `--cache "CAMINHO"`.
- Pasta de saida ja contem arquivos: os resultados sao preservados.
  Para uma nova tentativa, use `--saida ".\dados\amostra\piloto_gpu_02"`.
- Falta de memoria CUDA: mantenha lote 1 e experimente um limite menor,
  por exemplo `--max-residuos 256`, em outra pasta de saida.
- Interromper: pressione Ctrl+C. Os arquivos de entrada sao somente leitura;
  uma execucao interrompida pode deixar resultados incompletos na pasta de saida.

## Proxima etapa cientifica

Este piloto extrai caracteristicas com um modelo pre-treinado. Nao ajusta os
pesos do ESM-2 e nao treina um classificador. A regra `Tipo_Nutricional`
nao e usada como rotulo biologico. Depois do piloto precisamos definir
o alvo de classificacao, obter rotulos de referencia e controlar similaridade
entre treino, validacao e teste antes de avaliar F1, precisao ou sensibilidade.

## Validacao do pacote

A preparacao em fluxo, o pareamento ZIP/.gz/CSV e os casos de erro foram
verificados com arquivos pequenos de teste. O computador desta sessao nao
possui CUDA nem PyTorch/Transformers; a inferencia deste piloto com dados reais
precisa ser confirmada pelo comando acima no seu PC. O teste sintetico anterior
ja confirmou CUDA e o modelo na sua GTX 1650.
