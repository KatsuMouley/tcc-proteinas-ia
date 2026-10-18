# Sistema TCC — IA aplicada à classificação de proteínas

TCC de Engenharia de Computação (Universidade Positivo) — *Inteligência Artificial Aplicada à Genética e Bioinformática*.

O sistema lê proteínas do NCBI, agrupa sequências parecidas (MMseqs2), transforma cada proteína em um vetor de 320 números com o modelo de linguagem de proteínas **ESM-2** e treina classificadores **MLP**. Tudo roda localmente, com um painel no navegador.

**Resultado principal:** separar enzimas **Transferase (EC 2)** de **Hidrolase (EC 3)** — 86,0% ± 3,9 de acurácia balanceada (validação cruzada por grupo) e 83,0% no teste fixo, contra no máximo 70,4% das referências simples. Prova de conceito: regra dos nove aminoácidos (HILKMFTWV) em 1 milhão de proteínas do NCBI, 89,3%.

## O que você precisa

| Para… | Precisa de |
|---|---|
| Abrir o painel e ver os resultados do milhão | Windows 10/11, Python 3.13, pacote de dados do Drive |
| Consultar uma proteína (EC 2 × EC 3) | o item acima; GPU NVIDIA **opcional** (sem ela roda no processador) |
| Baixar e agrupar .gz do NCBI (Fase 1 do Filipe) | Git, internet (FTP do NCBI); o agrupamento também precisa de WSL + MMseqs2 |
| Rodar um fluxo novo com .gz do NCBI | o item acima + WSL (Ubuntu) com MMseqs2 + ~10 GB livres |

## Instalação em outro computador

1. **Clone em `C:\ai_tcc`** (os relatórios da base do milhão registram esse caminho):
   ```powershell
   git clone https://github.com/KatsuMouley/tcc-proteinas-ia.git C:\ai_tcc
   ```
2. **Rode `instalar.cmd`** (duplo clique). Ele cria o `.venv`, instala as bibliotecas, escolhe o PyTorch certo (GPU NVIDIA ou CPU), prepara o ESM-2 (~30 MB) e clona a Fase 1 do Filipe em `fase1_extrator\`. Leva de 5 a 15 minutos.
3. **Baixe o pacote de dados** (`pacote_dados_tcc.zip`, ~1,7 GB) da pasta do grupo no Google Drive e extraia **dentro de `C:\ai_tcc`**, mantendo as pastas (`dados\…` e `cache\…`):
   ```powershell
   tar -xf "$env:USERPROFILE\Downloads\pacote_dados_tcc.zip" -C C:\ai_tcc
   ```
4. **Abra `iniciar_sistema.cmd`**. O painel abre em http://127.0.0.1:8765.
5. Vá em **Configurações**: escolha o processamento (Automático, GPU ou CPU) e veja o **Diagnóstico do ambiente**. Se mudar algo, reinicie o sistema (Ctrl+C na janela preta e abra o `iniciar_sistema.cmd` de novo).

> Não clique dentro da janela preta: o Windows entra em modo "Selecionar" e pausa o sistema. Se acontecer, aperte Esc.

## Usar

- **Visão geral:** resultados do milhão (vetores, grupos, acurácia, partições).
- **Consultar proteína:** cole uma sequência (1 a 512 aminoácidos). Resposta: **Transferase (EC 2)** ou **Hidrolase (EC 3)** com a confiança, e a regra dos nove aminoácidos como prova de conceito.
- **Pipeline automático → Fontes do NCBI:** escolha a divisão (bactérias, plantas…) e quantos arquivos baixar; depois, se quiser, "Agrupar por arquivo" gera os CSVs da Fase 1 em `arquivos csv\`. Usa os scripts originais do Filipe, sem alterá-los.
- **Pipeline automático → Novo experimento completo:** fluxo novo com .gz do NCBI (10 etapas: leitura → MMseqs2 → rótulos → ESM-2 → auditoria → consolidação → agrupamento global → partições → treino → banco). **Use limite 1.000**; o padrão de 1 milhão ocupa mais de 20 GB.
- **Tarefas e logs:** acompanhe cada etapa ao vivo.

## Fluxo novo (opcional): WSL + MMseqs2

1. No PowerShell como administrador: `wsl --install -d Ubuntu` e reinicie.
2. No Ubuntu: `sudo apt update && sudo apt install -y mmseqs2`.
3. Baixe os `.gz` pelo painel (Fontes do NCBI) ou coloque `.gz`/`.zip` em `C:\ai_tcc\arquivos .gz\`.
4. Confira em **Configurações → Diagnóstico** a linha "WSL + MMseqs2".

## Pastas

| Pasta | Conteúdo |
|---|---|
| `sistema_tcc\` | painel (servidor local + interface), fila de tarefas, fluxo de 10 etapas, consulta |
| `etapas\` | scripts de cada etapa (embeddings, auditoria, base, agrupamento, treino, piloto EC) |
| `ferramentas\` | instalação, diagnóstico, conferência do modelo EC, empacotamento |
| `testes\` | testes automáticos (`.venv\Scripts\python.exe -m unittest discover -s testes`) |
| `docs\` | documentação técnica e resultados |
| `legado\` | versões antigas, só para histórico |
| `dados\` | bases, modelos e execuções (**fora do git**; vem no pacote do Drive) |
| `fase1_extrator\` | Fase 1 do Filipe (**fora do git**; o `instalar.cmd` clona): https://github.com/filipecamargoprado/genomic-data-extractor |
| `arquivos .gz\`, `arquivos csv\` | fontes do NCBI e CSVs da Fase 1 (**fora do git**) |

## Problemas comuns

| Sintoma | Solução |
|---|---|
| "Sistema desconectado" | Confira se a janela preta está aberta e fora do modo "Selecionar" (Esc). Espere 1 minuto e F5. |
| Etapa 2 (MMseqs2) falha por tempo | Abra o Ubuntu uma vez antes ou rode `wsl -d Ubuntu --exec mmseqs version`. |
| "GPU (CUDA) escolhida… indisponível" | Em Configurações, escolha Automático ou CPU e reinicie. |
| Consulta falha com "Modelo indisponível" | Falta o pacote de dados, ou o projeto não está em `C:\ai_tcc`. Veja o Diagnóstico. |

## Documentação

- Dossiê técnico do TCC (pipeline, matemática, justificativas): link na pasta do grupo.
- `docs\COMECE_AQUI_SISTEMA.md` (operação do painel), `docs\ARQUITETURA.md`, `docs\piloto_ec_analise_e_referencias.md`.

Grupo: Caio, Filipe, Guilherme, Lohanna, Vitor (Katsu) e Yuri · Orientador: Prof. Aryel.
