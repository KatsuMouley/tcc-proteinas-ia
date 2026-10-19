# Operação do sistema

> **Registro de 13–14/10/2026.** Este documento descreve o sistema antes da validação de 18–19/10. O estado atual (consulta EC, GPU/CPU, Configurações, Fase 1 pelo painel, instalação) está no [README](../README.md) e na seção 3.2 do Dossiê Técnico.


## Abrir e acompanhar

`iniciar_sistema.cmd` abre o dashboard. A base anterior de um milhão aparece com seus relatórios importados; isso não significa que foi processada novamente. O catálogo confere arquivos, formato, referências dos relatórios e alterações de tamanho/data sem repetir a auditoria inteira a cada atualização da tela.

Para apenas acompanhar com a fila pausada:

```powershell
.\.venv\Scripts\python.exe -m sistema_tcc --abrir --somente-painel
```

Para diagnosticar o catálogo sem rodar etapas:

```powershell
.\.venv\Scripts\python.exe -m sistema_tcc --diagnosticar
```

## Iniciar um experimento

Use `iniciar_fluxo_completo.cmd` ou o formulário **Novo experimento completo**. Comece com o recorte de 1.000 candidatos para conferir o funcionamento no Windows/WSL. Depois selecione um limite maior no painel, conforme o experimento planejado.

O limite é aplicado antes do agrupamento inicial. Representantes determinam a quantidade de embeddings. O sistema não baixa a coleção NCBI e não modifica os dados originais de entrada.

MMseqs2 usa 4 threads por padrão. No painel, a configuração pode ser ajustada antes de criar uma execução. No i5-10400F de 12 threads lógicas, o histórico confirmou uso de 8 para o agrupamento; o tempo disponível para tarefas do dia a dia depende da carga atual do PC. PyTorch mantém 2 threads CPU no fluxo e utiliza a GPU nas etapas correspondentes.

## Logs e métricas

**Tarefas e logs** permite selecionar a tarefa de fluxo completo. O navegador busca atualizações a cada 2 segundos; isso é atualização periódica do estado, não garantia de latência zero. A janela mostra até 500 linhas, e os arquivos completos continuam no disco.

As dez fases aparecem com seu estado. Mensagens de geração de vetores e épocas refletem a execução dos subprocessos. O gráfico de validação pode avançar com as épocas emitidas. Métricas finais do teste dependem da conclusão e conferência do relatório de treino.

Logs de cada fase ficam em `dados/execucoes_tcc/IDENTIFICADOR/logs/`. O agrupamento global também informa o caminho de seu `mmseqs.log` detalhado.

## Pausa, retomada e falhas

- **Pausar fila**: aguarda a fase em andamento e interrompe antes da seguinte.
- **Retomar execução**: reutiliza a mesma execução após conferir seus arquivos e confirmações.
- **Encerrar sistema**: espera a fase atual, conserva os arquivos e encerra o servidor.
- Encerramento inesperado: o painel exige conciliar o estado e verificar processos registrados antes de retomar.

O gerador de embeddings tem checkpoints próprios. A pausa do controlador ainda não ocorre a cada lote: durante essa fase, ela espera o recorte do gerador terminar. O fluxo não restaura o estado do otimizador no meio de um treino. Uma saída final existente sem aprovação é preservada e pode bloquear a retomada para evitar sobrescrita silenciosa.

Uma falha pausa a fila. O sistema não repete indefinidamente o mesmo comando. Se faltar uma classe ou dados suficientes para as partições, crie uma execução com mais candidatos; não ajuste a semente em função do desempenho do teste.

## Banco e consultas

Em **Banco**, selecione a execução e pesquise o acesso NCBI ou UID. A resposta é limitada a até 50 registros. **Usar sequência** preenche a consulta do modelo.

Todos os candidatos únicos selecionados ficam no banco. Apenas representantes usados na base recebem índice do embedding, UID da base, grupo global e partição. Isso explica linhas do banco sem essas referências.

Para prever, a execução precisa ter um modelo concluído. A inferência carrega o ESM-2 do cache e o checkpoint do MLP na GPU. Durante uma tarefa pesada, a consulta fica aguardando na fila. Escores softmax não devem ser apresentados como confiança clínica ou qualidade nutricional.

## Início com Windows

É opcional e não precisa ser configurado para o teste inicial:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sistema_tcc\instalar_inicio_automatico.ps1
```

O atalho abre o serviço no próximo login. Ele não cria um novo experimento a cada reinício. Para remover, execute `sistema_tcc/remover_inicio_automatico.ps1` da mesma forma.

## Atualizações do código

Extraia os pacotes de atualização fora de `C:\ai_tcc` e use o atualizador incluído. Ele faz backup de arquivos substituídos, preserva a configuração existente e arquiva nomes conhecidos de arquivos antigos da raiz. Não reorganiza os grandes conjuntos de dados.

Encerre o dashboard antes de atualizar. Arquivos novos no disco não alteram o código que uma instância antiga já carregou. O atualizador verifica processos Python do projeto no Windows e usa o mesmo bloqueio da fila.

## Testes do projeto

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -m unittest discover -s .\testes -p "test*.py" -v
```

Leitura, rótulos, geração dos lotes, auditoria, consolidação, partições e SQLite são exercitados em dados temporários. MMseqs2, ESM-2 e o treino são substituídos explicitamente. Nenhum resultado de teste simulado é distribuído como resultado científico real. A execução CUDA/WSL precisa ser conferida no seu computador.

O serviço fica restrito ao computador local, com ações protegidas pela sessão. O pacote não cria túnel público nem publica seu banco.
