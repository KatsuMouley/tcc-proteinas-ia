# Mapa dos arquivos

## Entradas e ambiente do PC

| Pasta existente | Responsabilidade | Tratamento ao aplicar o pacote |
|---|---|---|
| `.venv/` | Python e bibliotecas instaladas | Mantida |
| `cache/huggingface/` | Pesos e tokenizador ESM-2 | Mantida |
| `arquivos .gz/` | Proteínas FASTA comprimidas, inclusive em ZIP | Mantida |
| `arquivos csv/` | CSV históricos produzidos pelo colega | Mantida |
| `dados/` | Embeddings, bases, auditorias, partições e modelos anteriores | Resultados mantidos; o atualizador utiliza o bloqueio da fila |

Esses conteúdos permanecem no seu computador; o ZIP distribui o código e a documentação. Não é um backup das sequências ou dos resultados.

## Código principal

| Arquivo ou pasta | Função |
|---|---|
| `iniciar_sistema.cmd` | Abre o dashboard |
| `iniciar_fluxo_completo.cmd` | Abre o sistema e cria um experimento completo de até 1.000 candidatos |
| `piloto_esm_gpu.py` | Leitura das fontes, seleção, CSV, tokenização e embeddings; também executa o piloto individual |
| `etapas/processar_base_gpu.py` | Gera embeddings dos representantes, em lotes com checkpoints |
| `etapas/validar_base_embeddings.py` | Audita os lotes sem GPU |
| `etapas/preparar_base_ia.py` | Diagnostica MMseqs2, consolida, agrupa globalmente e separa partições |
| `etapas/treinar_classificador_gpu.py` | Treina, avalia e faz previsões com o MLP |
| `sistema_tcc/__main__.py` | Inicializa serviço, controla instância única e opções da CLI |
| `sistema_tcc/core.py` | Configuração, fila SQLite, eventos, catálogo e executor |
| `sistema_tcc/execucoes.py` | Inventário das fontes e registro dos experimentos |
| `sistema_tcc/fluxo.py` | Executa as dez fases de um experimento |
| `sistema_tcc/inferencia.py` | Carrega ESM-2 e o classificador para a consulta local |
| `sistema_tcc/web.py` | API HTTP e entrega do dashboard |
| `sistema_tcc/static/` | HTML, CSS, JavaScript e ícone do dashboard |
| `sistema_tcc/config.json` | Pastas, limites, semente, threads e WSL |
| `sistema_tcc/*inicio_automatico.ps1` | Atalho opcional de início com Windows e sua remoção |

O piloto foi mantido na raiz por compatibilidade com o gerador. As etapas foram preservadas integralmente, incluindo a aceitação de até 12 threads no agrupamento e o temporário WSL em `/var/tmp`.

## Ferramentas e referências

| Local | Conteúdo |
|---|---|
| `ferramentas/ambiente/testar_esm_gpu.py` | Teste sintético CUDA/ESM-2, com cache localizado na raiz do projeto |
| `ferramentas/ambiente/diagnostico_windows.ps1` | Hardware e espaço livre; relatório em `dados/diagnosticos/` |
| `ferramentas/ambiente/exportar_dependencias.py` | Exporta as dependências reais da `.venv` usada para executá-lo |
| `docs/historico/` | Manuais e scripts anteriores, com identificação de versão |
| `testes/` | Testes do sistema; não treinam uma IA real |
| `manifesto_projeto.json` | Versão do pacote, integridade dos arquivos e origem dos códigos recebidos |

Scripts antigos em `docs/historico` têm extensão adicional `.txt` para não se tornarem comandos de execução por engano. As cópias preservam os bytes recebidos. Os manuais históricos continuam descrevendo seu contexto original; o README principal desta versão é o ponto de entrada atual.

## Saídas de cada experimento

| Subpasta de `dados/execucoes_tcc/IDENTIFICADOR/` | Conteúdo |
|---|---|
| `execucao.json` | Seleção de fontes, limite, parâmetros e hashes do código |
| `codigo/` | Cópia dos scripts científicos usados naquela execução |
| `banco.sqlite3` | Candidatos, fases, grupos e vínculos dos representantes |
| `entrada/` | FASTA dos candidatos e relatório de seleção |
| `mmseqs_inicial/` | Agrupamento da entrada e seu TSV |
| `fontes/` | GZ/CSV próprios do experimento |
| `embeddings/` | Lotes de vetores e controle do gerador |
| `auditorias/` | Auditoria técnica |
| `base/` | FASTA, índice CSV e matriz NPY consolidados |
| `grupos/` | Agrupamento global associado à base |
| `particoes/` | Índices de treino, validação e teste |
| `modelo/` | Checkpoint MLP, métricas, histórico e previsões de teste |
| `logs/` | Logs por fase |
| `relatorio_fluxo.json` | Confirmação e resumo final |

## O que muda no projeto ao atualizar

O atualizador escreve somente os caminhos de código/documentação declarados no pacote e arquiva nomes conhecidos de arquivos antigos na raiz. Arquivos desconhecidos e subpastas não declaradas continuam onde estavam.

O código anterior e os arquivos arquivados ficam em `historico/atualizacoes/atualizacao_DATA/arquivos/`. `plano.json` registra os hashes anteriores e novos, além dos arquivos criados. A configuração já existente em `sistema_tcc/config.json` é preservada.
