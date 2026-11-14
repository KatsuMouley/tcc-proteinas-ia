# Sistema TCC — IA aplicada à classificação de proteínas

Trabalho de Conclusão de Curso do **Bacharelado em Engenharia de Software** da **Universidade Positivo** (Curitiba, 2026) — *Inteligência Artificial Aplicada à Genética e Bioinformática*.

Esta é a **terceira versão** da pipeline do TCC. As duas primeiras (coleta via FTP do NCBI e agrupamento com MMseqs2) estão em [`genomic-data-extractor`](https://github.com/filipecamargoprado/genomic-data-extractor) e são usadas aqui sem alterações. Este repositório transforma essa base em um sistema local de IA: agrupa proteínas parecidas com o MMseqs2, representa cada uma por um vetor de 320 números gerado pelo modelo de linguagem de proteínas **ESM-2** (congelado) e treina classificadores **MLP**. Tudo roda no próprio computador, com um assistente guiado e um painel técnico no navegador.

## Resultados

| Modelo | Papel | Acurácia balanceada no teste | Validação cruzada (5 dobras por grupo) | Referência |
|---|---|---|---|---|
| **EC 1 a EC 7** | **principal** | **75,4%** (n = 343, F1 macro 0,755) | 71,3% ± 3,0 | acaso: 14,3% |
| EC 2 × EC 3 (transferase × hidrolase) | complementar | 83,0% (n = 107) | 86,0% ± 3,9 | melhor referência sem ESM-2: 70,4% |
| Completa × Incompleta (regra dos nove aminoácidos) | prova de conceito em escala | 89,3% (base histórica, n = 98.668) · 87,7% (fluxo de dez fases, n = 34.615) | — | só comprimento: 74,9% |

- O modelo principal foi treinado com **3.500 enzimas revisadas do Swiss-Prot** (500 por classe EC).
- Treino, validação e teste são divididos **por grupo de similaridade** do MMseqs2 (50% de identidade, 80% de cobertura), com sorteio determinístico por SHA-256 (semente 42). Assim, nenhum grupo aparece em dois conjuntos.
- A prova de conceito tem rótulo calculado da própria sequência: ela valida a engenharia em um milhão de proteínas, **não** é um resultado biológico.
- O sistema serve para **triagem**, não para atribuir função de forma definitiva. Os escores não são calibrados, e o modelo sempre escolhe uma classe, mesmo para proteínas que não são enzimas.

## Instalação (Windows 10/11)

**Caminho recomendado:** baixe e rode [`instalador/Instalar_TCC.cmd`](instalador/Instalar_TCC.cmd) em uma janela normal (não "como administrador"). Ele:

1. pergunta a pasta (padrão **`C:\ai_tcc`**) e faz o `git clone` (ou `git pull`, se o projeto já existir);
2. roda o `instalar.cmd`, que baixa o **uv**, cria um `.venv` com **Python 3.13 próprio** (não depende do Python do PC), instala as dependências, escolhe o **PyTorch com CUDA 12.6** se houver placa NVIDIA ou **para CPU** nos demais casos, clona a coleta da segunda versão em `fase1_extrator\` e baixa o ESM-2 (~30 MB);
3. pergunta onde salvar os arquivos grandes: só neste PC ou em uma pasta sincronizada (Google Drive, OneDrive ou Dropbox);
4. pergunta como instalar o MMseqs2: **nativo do Windows** (recomendado, sem Linux e sem administrador), **WSL/Ubuntu** (pede administrador), os dois ou nenhum;
5. oferece abrir o sistema.

Já clonou o repositório? Rode `instalar.cmd` e depois `ferramentas\instalar_mmseqs_nativo.cmd` (ou `instalar_wsl_mmseqs.cmd`, para usar o WSL).

Guia completo, com verificação e problemas comuns: [`docs/INSTALACAO.md`](docs/INSTALACAO.md).

| Para… | Precisa de |
|---|---|
| Consultar proteínas | Instalação básica. Os três modelos já vêm no Git (`dados\modelos\`). GPU NVIDIA **opcional** |
| Treinar o EC 1 a EC 7, rodar um fluxo novo ou agrupar arquivos do NCBI | + MMseqs2 (nativo ou WSL), internet e ~10 GiB livres |
| Ver o mapa e as estatísticas da base de um milhão | + pacote de dados opcional (~1,7 GB, pasta do grupo) |

## Usar

Abra **`iniciar_sistema.cmd`**. A janela preta é o servidor: deixe-a aberta e não clique dentro dela (se clicar, aperte Esc).

- **http://127.0.0.1:8765/** — **assistente guiado**, a página inicial. Linear e educativo, ele apresenta o problema e os três modelos e oferece três caminhos: treinar o EC 1 a EC 7, ver os resultados ou consultar uma proteína. Também mostra as dez fases do sistema e traz fontes para aprender mais.
- **http://127.0.0.1:8765/avancado** — **painel técnico**, com sete abas:
  - *Visão geral*: métricas e partições;
  - *Pipeline automático*: coleta da segunda versão, modelo EC 1 a EC 7, novo experimento e fila;
  - *Consultar proteína*: o EC 1 a EC 7 em destaque e os demais modelos em "Ver outros modelos";
  - *Tarefas e logs*;
  - *Banco de proteínas*;
  - *Explorar e analisar*: mapa PCA, boxplot com Mann-Whitney, histogramas, correlação e matriz 7 × 7;
  - *Configurações*: GPU/CPU, threads, modo do MMseqs2, pasta de nuvem e diagnóstico.

**Novo experimento completo** executa dez fases: extrair → MMseqs2 na entrada → rotular → embeddings ESM-2 → auditar → consolidar → MMseqs2 global → separar por grupo → treinar e avaliar → registrar em SQLite. **Use o limite de 1.000 proteínas** para testes; o fluxo de um milhão levou cerca de 2 h 23 min e ocupa mais de 20 GB.

Também é possível rodar o modelo EC 1 a EC 7 pela linha de comando: veja [`experimentos/ec7/README.md`](experimentos/ec7/README.md).

## Reprodutibilidade

- ESM-2 `facebook/esm2_t6_8M_UR50D`, revisão `c731040fcd8d73dceaa04b0a8e6329b345b0f5df`, float32.
- MMseqs2 `easy-linclust`: `--min-seq-id 0.5 -c 0.8 --cov-mode 0 --cluster-mode 1 --alignment-mode 3 --kmer-per-seq 80 -e 0.001`. O TCC usou a versão **18-8cc5c**.
- Partição: `SHA-256("42:" + representante)` → treino (< 0,8), validação (< 0,9) e teste.
- Cada execução guarda um manifesto com fontes, semente e o SHA-256 do código copiado para a sua pasta. Ao iniciar ou retomar o fluxo, o sistema confere esses hashes.
- Versões fixadas: Python 3.13, PyTorch 2.9.1, Transformers 4.57.6, NumPy 2.2.6.
- Testes: `.venv\Scripts\python.exe -m unittest discover -s testes` (com o sistema fechado).

## Limitações conhecidas

- O sistema foi desenvolvido e testado só no Windows; Linux, macOS e contêineres ficam como trabalho futuro.
- Enzimas com mais de 512 resíduos ou com mais de uma classe EC ficaram de fora do treino.
- Os testes dos modelos enzimáticos são pequenos (343 e 107 proteínas).

## Pastas

| Pasta | Conteúdo |
|---|---|
| `sistema_tcc\` | servidor local, assistente guiado e painel (`static\`), fila de tarefas, fluxo de dez fases, consulta |
| `etapas\` | scripts de cada fase (embeddings, auditoria, base, agrupamento, treino, piloto EC 2 × EC 3) |
| `experimentos\ec7\` | coleta, agrupamento e treino do modelo EC 1 a EC 7 |
| `ferramentas\` | instalação (MMseqs2 nativo, WSL, ESM-2), diagnóstico, empacotamento de dados |
| `instalador\` | `Instalar_TCC.cmd` e `construir_exe.cmd` (gera um `.exe` com o IExpress) |
| `testes\` | testes automáticos |
| `docs\` | instalação e registros técnicos (os arquivos de 16 a 19/10 descrevem a versão daquela data) |
| `legado\` | versões antigas, só para histórico |
| `dados\modelos\` | os três modelos treinados, **no Git** |
| `dados\` (resto), `cache\`, `.venv\`, `fase1_extrator\`, `arquivos .gz\`, `arquivos csv\` | **fora do Git** |

## Autores

Caio Tsutiya Marcidele · Filipe Camargo Prado · Guilherme Fernando Nascimento · Lohanna Bieti Vieira · Vitor Luiz Mougenot · Yuri Congeca Terato Ramos

**Orientador:** Prof. Aryel Marlus Repula de Oliveira — Universidade Positivo, Curitiba, 2026.
