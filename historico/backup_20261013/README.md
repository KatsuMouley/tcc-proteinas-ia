# Ambiente local para a IA de proteínas do TCC

Este pacote prepara o ambiente do primeiro experimento. Ainda não inclui treinamento com proteínas reais, rótulos, banco populado ou dashboard. O teste do ESM usa uma sequência artificial, identificada como teste técnico.

## Escolha das ferramentas

| Ferramenta | Uso |
|---|---|
| Windows de 64 bits e Python 3.13 | Ambiente selecionado para o computador do projeto. Python 3.12 e 3.11 de 64 bits também são aceitos pelo instalador. |
| `venv` | Bibliotecas isoladas na pasta deste projeto. |
| PyTorch 2.7.1 CPU | Executar o modelo pré-treinado, mantendo seus pesos fixos. |
| Transformers 4.57.6 | Carregar o ESM-2 e o tokenizer. |
| ESM-2 `facebook/esm2_t6_8M_UR50D` | Extrair embeddings de 320 dimensões. Modelo com 8 milhões de parâmetros. |
| NumPy, pandas e Biopython | Vetores, tabelas e leitura dos FASTAs. |
| scikit-learn e joblib | Treinar, avaliar e salvar o classificador pequeno. |
| Matplotlib | Figuras de avaliação. |
| SQLite (`sqlite3`) | Banco local, já disponível no Python. |

As dependências diretas estão fixadas em `requirements.txt` e no instalador. O instalador registra todas as versões efetivamente resolvidas em `requirements.instaladas.txt`. Esse arquivo será a referência da reprodução do ambiente. Os testes abaixo precisam passar no computador de destino antes de considerar a configuração validada.

O modelo é público e roda localmente. O primeiro download requer acesso à internet; este fluxo não chama a API da OpenAI. O MMseqs2 pode continuar no Linux já utilizado pelo colega: importaremos seus CSVs, recuperaremos sequências dos representantes e combinaremos com os rótulos. O controle adicional de similaridade da amostra experimental também precisa de execução do MMseqs2, no ambiente Linux disponível, antes da avaliação.

## Espaço e memória

**Recomendação operacional: reservar 20 GB livres em SSD para esta primeira versão com uma amostra pequena.** É uma margem de trabalho, não uma exigência oficial do ESM. Não inclui copiar todo o acervo bruto, nem o CSV consolidado de dezenas de gigabytes.

| Item | Estimativa para planejamento |
|---|---|
| Python e ambiente com bibliotecas CPU | Reservar aproximadamente 2–4 GB; o consumo real varia com as dependências e arquivos temporários. |
| Pesos ESM-2 em safetensors | Aproximadamente 31,4 MB, além de arquivos pequenos de configuração e tokenizer. |
| Amostra e arquivos de preparação | Dimensionar pelos lotes escolhidos; trabalhar primeiro com uma amostra limitada. |
| Embeddings | 1.000 vetores de 320 números float32 representam aproximadamente 1,28 MB de valores, mais IDs e metadados. |
| Margem restante | Resultados, cache, temporários e ajustes durante o experimento. |

Uma máquina com 8 GB de RAM pode ser viável para um piloto pequeno em CPU, lote 1 e sequências curtas; isso precisa ser medido. 16 GB de RAM é uma recomendação mais confortável, não uma garantia de velocidade. GPU é opcional nesta etapa. Não podemos estimar o tempo de execução sem medir o piloto no hardware real.

Use uma pasta local, por exemplo `E:\TCC-IA`, fora da pasta sincronizada do Drive. Isso evita sincronizar ambiente e cache a cada mudança. O Windows e o Python ainda podem usar temporários no disco do sistema; mantenha espaço livre também nele. Compartilhe o código e os resultados relevantes com o grupo; cada integrante cria o próprio ambiente.

## Instalação em etapas

1. Extraia todo este pacote em uma pasta local, por exemplo `E:\TCC-IA`.
2. Abra o PowerShell nessa pasta.
3. Verifique os Python instalados:

```powershell
py --list
```

Se houver Python 3.13 de 64 bits, podemos utilizar essa instalação. O instalador escolhe explicitamente 3.13, 3.12 ou 3.11, nessa ordem; o Python padrão do Windows pode continuar em 3.14. Se não houver uma versão compatível, instale-a pelo [site oficial do Python](https://www.python.org/downloads/windows/). Habilite o launcher `py` quando o instalador oferecer essa opção. A recomendação é usar um ambiente dedicado; não alterar o Python dos scripts históricos do colega.

4. Instale o ambiente CPU:

```powershell
.\setup_cpu.cmd
```

O instalador cria o ambiente, instala as bibliotecas, verifica as dependências e executa operações técnicas mínimas. Ele interrompe ao encontrar falha. Não apaga dados nem altera configurações do Windows. Se falhar, guarde a mensagem de erro antes de tentar outras versões de pacotes.

5. Confira o modelo com o teste curto:

```powershell
.\.venv\Scripts\python.exe .\testar_esm.py
```

A primeira execução baixa os arquivos do modelo para `cache\huggingface` dentro do projeto. O teste exige um embedding finito com dimensão 320. O relatório deve conter `"ok": true`. Não mede qualidade biológica ou desempenho de classificação.

6. Confira novamente sem baixar nada:

```powershell
.\.venv\Scripts\python.exe .\testar_esm.py --offline
```

7. Gere um diagnóstico do hardware quando precisar avaliar aceleração ou memória:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\diagnostico_windows.ps1
```

O parâmetro de política vale apenas para esse processo; o script não modifica a política permanente. Ele lê RAM, processador, nomes de placas, driver e espaço em disco. Não coleta senhas ou credenciais. O relatório fica em `resultados\diagnostico_maquina.json`.

## Uso cotidiano

Não é necessário ativar o ambiente no terminal. Execute os scripts com o Python dele:

```powershell
.\.venv\Scripts\python.exe .\verificar_ambiente.py
```

No VS Code, selecione como interpretador o arquivo `.venv\Scripts\python.exe` desta pasta. O editor é opcional.

O diagnóstico de CUDA retornará `False` na instalação CPU, mesmo que exista uma GPU NVIDIA na máquina. O relatório do hardware ajuda a escolher outra distribuição do PyTorch depois, se necessário. Este pacote não instala drivers, CUDA Toolkit ou uma versão GPU sem identificar placa e driver.

## Onde ficam os arquivos

| Pasta ou arquivo | Conteúdo |
|---|---|
| `dados\brutos` | Cópias limitadas dos arquivos de entrada; preservar os originais. |
| `dados\amostra` | Sequências selecionadas, inclusive representantes. |
| `dados\rotulos` | Categorias de referência e procedência. |
| `dados\embeddings` | Vetores gerados para as sequências da amostra. |
| `modelos` | Classificador e configuração do experimento. |
| `resultados` | Diagnósticos, métricas e figuras. |
| `cache\huggingface` | Arquivos do ESM baixados. |
| `requirements.instaladas.txt` | Versões efetivamente instaladas. |

## Próxima etapa depois de validar o ambiente

Importar um CSV real de agrupamento e seu FASTA bruto correspondente, recuperar representantes, associar rótulos de referência e preparar uma divisão de treino, validação e teste com controle de similaridade entre arquivos. Então gerar embeddings e treinar a regressão logística. O banco completo e o dashboard não bloqueiam a validação inicial do ambiente.

## Validação deste pacote

Foram conferidas a sintaxe dos scripts Python, a geração de relatórios de erro e o conteúdo do ZIP. Na revisão para Python 3.13, também foi conferida a disponibilidade de pacotes compilados para Windows de 64 bits nos índices oficiais de PyTorch, NumPy, scikit-learn, Biopython e Matplotlib, e a compatibilidade declarada do pandas 2.2.3 com Python 3.13. Nesta sessão não há Windows/PowerShell nem PyTorch e Transformers instalados para executar a instalação ou a inferência. Portanto, os testes reais de instalação e do modelo precisam ser executados na máquina de destino. Os testes sintéticos deste pacote não são resultados do TCC.

## Fontes oficiais consultadas

- [ESM: modelos e extração de embeddings](https://github.com/facebookresearch/esm/blob/main/README.md).
- [Arquivo de pesos ESM-2 pequeno](https://huggingface.co/facebook/esm2_t6_8M_UR50D/blob/main/model.safetensors).
- [Transformers: instalação e cache](https://huggingface.co/docs/transformers/en/installation).
- [Transformers 4.57.6: metadados da versão](https://pypi.org/project/transformers/4.57.6/).
- [PyTorch: instalação local](https://pytorch.org/get-started/locally/) e [versões anteriores](https://pytorch.org/get-started/previous-versions/).
- [Python: ambientes virtuais](https://docs.python.org/3/library/venv.html).
- [PyTorch CPU: índice oficial de pacotes](https://download.pytorch.org/whl/cpu/torch/).
- [pandas 2.2.3: compatibilidade com Python 3.13](https://pandas.pydata.org/pandas-docs/stable/whatsnew/v2.2.3.html).
