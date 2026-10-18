# Sistema local de proteínas — primeira versão funcional

Este pacote adiciona dashboard, fila persistente, preparação automática e consulta do classificador ao projeto que está em `C:\ai_tcc`.

Usa o Python da sua `.venv`, os scripts existentes, o cache do ESM-2 e o MLP que você já treinou. O dashboard e o controlador usam apenas a biblioteca padrão do Python. A inferência utiliza as dependências que já estão no projeto. Não há instalação de pacotes, cadastro em nuvem ou transferência de dados neste instalador.

## Começar em três passos

1. Extraia **o conteúdo** de `Sistema_Local_Proteinas_TCC_v1.zip` diretamente em `C:\ai_tcc`. A pasta `sistema_tcc` deve ficar ao lado de `etapas` e `.venv`, sem uma pasta intermediária.
2. No PowerShell, execute:

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -m sistema_tcc --abrir
```

3. O navegador abrirá [http://127.0.0.1:8765](http://127.0.0.1:8765). A alternativa é dar dois cliques em `iniciar_sistema.cmd`.

A janela do PowerShell mantém o serviço funcionando. Fechar a aba do navegador não interrompe a fila. Para terminar o serviço, use **Encerrar sistema**, no rodapé do painel, ou `Ctrl+C` no terminal. Uma tarefa já ativa termina normalmente antes de o processo encerrar.

Se preferir conferir os relatórios sem iniciar tarefas:

```powershell
.\.venv\Scripts\python.exe -m sistema_tcc --somente-painel --abrir
```

Esse comando salva a fila como pausada e o agendamento como manual. Depois, os botões **Ativar automático** e **Retomar fila** restauram o processamento.

## O que deve aparecer com a sua base atual

O painel lê os arquivos no seu computador. A expectativa, pelos registros anteriores, é reconhecer:

| Etapa | Saída existente |
|---|---|
| Embeddings | `dados/embeddings/base_ncbi_gpu/relatorio_execucao.json` |
| Auditoria | `dados/validacao/base_ncbi_gpu/auditoria_*/relatorio.json` |
| Consolidação | `dados/base_ia/base_1m/relatorio_consolidacao.json` |
| Agrupamento global | `dados/base_ia/agrupamento_global_1m/relatorio_agrupamento.json` |
| Partições | `dados/base_ia/particoes_1m/relatorio_particoes.json` |
| Treinamento | `dados/modelos/classificador_regra_aa_esm2/relatorio_treino.json` |

Devem aparecer seus números reais: um milhão de vetores de 320 valores, 560.678 grupos, partições e métricas do classificador. Esses números não foram colocados como resultados fixos no código do dashboard: dependem dos relatórios presentes e compatíveis.

Com as seis etapas completas, o sistema fica aguardando consultas e novas solicitações. Não gera novamente o milhão de vetores e não realiza outro treino. “Recorte concluído” se refere ao objetivo configurado; não afirma que toda a coleção NCBI foi percorrida.

## As quatro telas

### Visão geral

- Quantidade de vetores, grupos e espaço físico livre.
- Distribuição `Completa`/`Incompleta`.
- Treino, validação e teste por grupos.
- Comparação do MLP com a classe majoritária e a regra direta.
- Histórico de acurácia balanceada da validação.

As métricas antigas são resultados do experimento salvo. O painel não mede continuamente uso de CPU, RAM ou VRAM. “Modelo carregado na GPU” descreve a inferência desta instância; a GPU registrada no relatório de treino descreve a execução anterior.

### Pipeline automático

O agendamento fica ativado na primeira abertura normal e verifica as pendências a cada 15 segundos. Segue esta ordem:

1. Gerar ou retomar embeddings até o limite **total** configurado.
2. Auditar os lotes com o gerador desta fila encerrado.
3. Consolidar as sequências, o índice e a matriz.
4. Agrupar globalmente com MMseqs2.
5. Criar partições por grupos.

O treinamento é uma ação explícita na etapa 6, disponível quando toda a preparação está pronta e não há uma saída de treino já concluída. Essa escolha conserva a separação entre preparar dados e realizar experimentos. Teste não orienta automaticamente outros treinos.

O executor agenda uma etapa de cada vez. Dependências, relatórios e saídas são conferidos antes e depois da execução. Um erro fica registrado e interrompe a progressão; uma nova tentativa é solicitada pelo botão da etapa depois de corrigir o problema.

**Desativar automático** impede novas decisões do agendador. Tarefas já enfileiradas ainda podem executar. **Pausar fila** impede que a próxima tarefa comece; a tarefa ativa termina normalmente. **Cancelar**, no histórico, vale apenas para solicitações pendentes.

Perfis iniciais: 2 threads CPU para PyTorch e 4 para MMseqs2. O painel permite escolher 8 quando o computador estiver dedicado ao processamento. A escolha vale para novas solicitações, preservando os argumentos já registrados de uma tarefa enfileirada. O agrupamento existente é reutilizado independentemente de ter sido executado anteriormente com 8 threads.

### Consultar proteína

1. Cole entre 1 e 512 letras de aminoácidos, sem cabeçalho FASTA ou espaços internos.
2. Clique em **Comparar regra e IA**.
3. A consulta entra na fila e aguarda a tarefa ativa, se houver.
4. O executor carrega ESM-2 e MLP do cache local, com CUDA obrigatória.
5. O painel mostra a regra, aminoácidos presentes/ausentes, previsão do MLP e escores não calibrados.

O modelo é reutilizado entre consultas consecutivas. Antes de iniciar outro script científico, esta instância libera sua cópia do modelo da GPU. Todas as tarefas da fila, incluindo previsões, são serializadas.

O exemplo `ACDEFGHIKLMNPQRSTVWY` contém os nove aminoácidos da regra. No teste anterior, o MLP classificou essa sequência como `Incompleta`, divergindo da regra. Essa divergência deve permanecer visível: os escores não são probabilidades de acerto validadas.

Sequências de consultas pendentes ficam temporariamente no SQLite local para atender a solicitação. Depois da conclusão ou falha, o campo da sequência é removido da tarefa; o resultado permanece. Não há envio a serviços externos.

### Tarefas e logs

Cada solicitação tem ID, origem, estado, comando executado, progresso e resultado. Etapas históricas importadas são identificadas como **Importado**; não recebem início de execução inventado.

Logs novos são capturados da saída real dos scripts, com atualização do navegador a cada 2 segundos. O log detalhado do MMseqs2, quando indicado pelo wrapper, pode ser selecionado separadamente. Logs antigos aparecem somente se os arquivos `treino.log` ou `mmseqs.log` ainda existirem.

O navegador lê blocos de até 64 KiB e mantém até 500 linhas. Os arquivos completos continuam no disco. Ao abrir uma tarefa, o painel mostra o trecho mais recente e acompanha as novas linhas.

## Arquivos adicionados e dados de controle

| Local | Finalidade |
|---|---|
| `sistema_tcc/` | Código do controlador, API, interface e configuração |
| `iniciar_sistema.cmd` | Inicialização com o Python existente |
| `testes/test_sistema_tcc.py` | Testes isolados do controlador |
| `dados/sistema_tcc/controle.sqlite3` | Fila, estado dos controles, eventos e referências às saídas |
| `dados/sistema_tcc/logs/` | Logs novos de tarefas |
| `dados/sistema_tcc/servidor.log` | Saída do serviço quando iniciado em segundo plano |

Os três últimos são criados no seu computador. O SQLite do controlador é separado de `dados/embeddings/base_ncbi_gpu/controle.sqlite3`, que continua pertencendo ao gerador de embeddings. O ZIP não inclui os dados de um milhão de proteínas, o cache, a `.venv` ou cópias dos scripts científicos existentes.

## Configuração e novas versões

`sistema_tcc/config.json` configura objetivo, semente, pastas, intervalo, WSL e reserva de disco. A configuração inicial aponta para a base de um milhão existente, usa Ubuntu para MMseqs2 no Windows e preserva a reserva de 10 GiB dos scripts.

A primeira versão automatiza a preparação de **uma versão configurada**. Não baixa automaticamente novos arquivos NCBI, não extrai novos pares de CSV/GZ e não cria novas versões sozinha ao detectar mudanças nas fontes.

Para outro recorte, preserve os resultados atuais, encerre o serviço e forneça outra configuração com novas pastas de saída para embeddings, auditorias, base, grupos, partições, modelo e controlador. O argumento `--config` seleciona esse arquivo. Todos os caminhos precisam ficar dentro do projeto, e entradas/saídas não podem se sobrepor. O novo treinamento continua sendo solicitado explicitamente no painel.

Não altere o inventário de fontes dentro de uma saída de embeddings existente. O gerador mantém sua conferência de assinatura e rejeita uma retomada quando fontes ou critérios mudam. O limite refere-se ao total desejado nessa saída, incluindo lotes anteriores.

## Retomada e conciliação

- A fila sobrevive ao reinício do serviço.
- Se uma tarefa estava executando durante um encerramento inesperado, fica em **Conciliação necessária**. A fila permanece pausada.
- O botão **Conciliar** verifica se o processo registrado já terminou e se há saída concluída. Agrupamentos incompletos também exigem verificar processos MMseqs2.
- Depois da conciliação, retome a fila. Se a etapa ficou incompleta, uma nova tentativa precisa ser solicitada.
- Embeddings retomam lotes confirmados usando o controle original do gerador.
- Auditoria, consolidação, agrupamento e treino conservam os limites de retomada dos wrappers existentes. O controlador não acrescenta retomada de otimizador do MLP nem de temporários do MMseqs2.
- Pastas finais existentes sem saída aprovada são bloqueadas. O controlador não as apaga para tentar de novo.

Use o controlador como executor dos scripts desta versão. Processos iniciados manualmente em outro terminal não participam da mesma fila; encerre-os antes de iniciar a preparação automática ou a inferência pelo painel.

## Iniciar automaticamente com o Windows — opcional

Depois de conferir que o dashboard abriu e reconheceu seus arquivos, execute uma vez:

```powershell
cd C:\ai_tcc
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sistema_tcc\instalar_inicio_automatico.ps1
```

Cria um atalho **do seu usuário** na pasta de inicialização do Windows. No próximo login, usa `pythonw.exe` da mesma `.venv` para iniciar em segundo plano. Não precisa de administrador e não inicia uma segunda instância agora. A política `Bypass` vale apenas para esse processo de instalação; não muda a política permanente do Windows.

Abra [http://127.0.0.1:8765](http://127.0.0.1:8765) para consultar o sistema. O atalho funciona enquanto o seu usuário está conectado; não é um serviço de sistema que inicia antes do login.

Para remover o início automático:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sistema_tcc\remover_inicio_automatico.ps1
```

Remover o atalho não encerra a instância atual. Use **Encerrar sistema** no painel para finalizar essa instância. Configurações de automático/pausa são persistidas; se deixou a fila pausada, ela continua pausada na próxima abertura.

## Diagnóstico e verificações

Para listar as etapas reconhecidas sem executar os scripts:

```powershell
.\.venv\Scripts\python.exe -m sistema_tcc --diagnosticar
```

O diagnóstico lê relatórios e registra referências no SQLite separado do controlador. Não usa GPU ou inicia preparação. Se o sistema já estiver aberto, veja o estado no painel em vez de tentar abrir outra instância.

Para executar os testes incluídos:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\testes -p test_sistema_tcc.py -v
```

Os testes usam diretórios temporários, bases pequenas e um substituto explícito da inferência. Verificam persistência, serialização, deduplicação, propagação de dependências inválidas, bloqueio de sobrescrita, execução de subprocessos, falhas sem repetição automática, cursores de log e proteção das ações HTTP. O contrato dos comandos é conferido com os parsers dos scripts científicos existentes.

**Validação desta entrega:** 22 testes do controlador e da API aprovados em Linux; sintaxe e referências da interface verificadas. A consulta real com seus pesos/cache na GTX 1650 e o atalho de inicialização dependem do teste no seu Windows. Não houve novo treino ou geração real de embeddings na produção deste pacote. Não foi feita inspeção visual da interface em um navegador nesta entrega.

### Importação não substitui auditoria científica

Para reaproveitar resultados sem repetir horas de leitura, o controlador confere tipo do relatório, protocolo, contagens, referências SHA-256 entre os relatórios, presença dos arquivos e cabeçalho/tamanho das matrizes. Depois da primeira importação, alterações de tamanho ou data dos artefatos registrados bloqueiam a etapa e suas dependências.

Ele não recalcula o SHA-256 de todos os arquivos grandes a cada atualização do painel, nem prova que os arquivos nunca foram modificados antes da primeira importação. Auditorias e hashes completos continuam sendo responsabilidade dos scripts científicos nos momentos apropriados. Execute a auditoria original se houver dúvida sobre a integridade anterior dos dados.

## Limites do experimento e do serviço

`Completa`/`Incompleta` é a presença literal de `HILKMFTWV`. A regra direta permanece como referência e a IA é um classificador experimental dessa regra, sem avaliação de digestibilidade, qualidade nutricional ou função biológica.

O serviço escuta somente em `127.0.0.1`, sem abrir porta para a internet. As ações exigem o token da sessão local e uma origem permitida; a API não aceita comandos de shell. Arquivos científicos não são servidos como uma pasta pública.

Esta entrega não cria túnel público nem acesso remoto. Compartilhamento externo será uma integração própria, com controle de acesso e ajuste das origens aceitas.
