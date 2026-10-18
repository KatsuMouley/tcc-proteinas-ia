# Sistema de proteínas — versão 2: execução completa automática

Esta atualização inicia um experimento novo desde os GZ até o treinamento e o banco. A base anterior de um milhão permanece separada.

## Atualizar e iniciar agora

1. No dashboard antigo, clique em **Encerrar sistema**, no rodapé. Aguarde o terminal encerrar; a tarefa ativa termina normalmente.
2. Extraia o conteúdo do ZIP atualizado diretamente em `C:\ai_tcc`, substituindo `sistema_tcc` e os arquivos de inicialização. Preserve `dados`, `cache`, `.venv`, `etapas` e seus GZ/CSV.
3. Execute no PowerShell:

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -m sistema_tcc --abrir --novo-fluxo --limite 1000
```

Ou dê dois cliques em `iniciar_fluxo_completo.cmd`.

**Esse comando já cria e inicia um fluxo completo.** Não precisa clicar em cada etapa. A opção `--novo-fluxo` cria outro experimento a cada invocação; para apenas abrir o dashboard, use `iniciar_sistema.cmd` ou o comando sem essa opção.

Dashboard: [http://127.0.0.1:8765](http://127.0.0.1:8765).

Atualizar os arquivos no disco não substitui o servidor antigo ainda em execução. Encerre a versão antiga antes de iniciar a nova.

## Iniciar pelo painel

Em **Pipeline automático → Novo experimento completo**, escolha todas as fontes ou um GZ específico, incluindo membros de ZIP. Escolha o limite e clique em **Iniciar fluxo completo**. As etapas, inclusive treino, avançam automaticamente.

O seletor no topo alterna entre a base original e as execuções novas. Gráficos, banco e consultas do modelo acompanham a execução selecionada.

O primeiro teste começa com até **1.000 candidatos únicos elegíveis**, antes do agrupamento. MMseqs2 seleciona representantes: por exemplo, 1.000 candidatos podem produzir 650 representantes e 650 embeddings. Se a fonte terminar antes do limite, usa o que foi recuperado, desde que haja dados suficientes para as próximas etapas. Depois, o painel permite 10.000, 100.000 ou 1.000.000 candidatos.

## Fases automáticas

| Fase | Operação | Recurso |
|---|---|---|
| Entrada | Leitura de FASTA nos GZ/ZIP, normalização, filtro 1–512 resíduos e deduplicação por SHA-256 | CPU/disco |
| MMseqs2 inicial | Linclust no recorte escolhido; representante/membro em TSV | CPU/Ubuntu WSL |
| Rótulos | GZ/CSV com grupos reais e regra HILKMFTWV por sequência | CPU |
| Embeddings | Gerador existente sobre os representantes | GTX 1650/ESM-2 |
| Auditoria | Lotes, hashes, índices, sequências e rótulos | CPU |
| Consolidação | FASTA, índice e matriz NPY | CPU/disco |
| Grupos globais | Agrupamento dos representantes para as partições | CPU/WSL |
| Partições | Grupos inteiros em treino, validação e teste; semente 42 | CPU |
| Treino | MLP 320→64→2; seleção pela validação e avaliação no teste | GTX 1650 |
| Banco | Modelo, métricas e vínculos proteína/grupo/embedding/partição | SQLite |

**ESM-2 permanece pré-treinado e fixo. O novo treinamento ajusta o MLP**, por até 10 épocas, com os controles do script existente. Não treina ESM-2 do zero.

O MMseqs2 inicial agrupa o recorte escolhido como um conjunto. Isso difere do histórico do colega, que agrupou por arquivo. Versão, comando e parâmetros são registrados. Mantém identidade 0,5, cobertura 0,8, cov-mode 0 e Linclust heurístico.

O fluxo usa os GZ locais já existentes. Não baixa dados NCBI e não depende dos CSV antigos: gera seu próprio CSV após MMseqs2.

## Banco e arquivos

Cada execução fica em `dados/execucoes_tcc/exp_DATA_IDENTIFICADOR/`.

| Local | Conteúdo |
|---|---|
| `execucao.json` | Fontes, objetivo, parâmetros e hashes de código |
| `codigo/` | Cópias dos scripts científicos desta execução |
| `banco.sqlite3` | Candidatos, fases, grupos, referências, partições e experimento |
| `entrada/` | FASTA do recorte e relatório |
| `mmseqs_inicial/` | TSV inicial e relatório |
| `fontes/` | GZ/CSV produzidos para o gerador |
| `embeddings/` | Lotes e controle original do gerador |
| `auditorias/`, `base/`, `grupos/`, `particoes/` | Saídas de preparação |
| `modelo/` | Novo MLP, histórico, métricas e predições do teste |
| `logs/` | Logs por fase |
| `relatorio_fluxo.json` | Resultado final |

A fila permanece em `dados/sistema_tcc/controle.sqlite3`, separada dos bancos científicos.

A tabela `proteinas` guarda **todos os candidatos únicos selecionados**, inclusive membros não escolhidos como representantes: acesso NCBI original, UID interno, origem, sequência, SHA-256, comprimento, rótulo e grupo inicial. Só representantes recebem índice de embedding, UID da base, grupo global e partição. NPY guarda os vetores; SQLite guarda suas referências, sem duplicar a matriz.

UIDs internos evitam colisões de identificadores no FASTA. Na base consolidada, `id_original` referencia o UID de entrada; o acesso original NCBI permanece no banco.

Em **Banco de proteínas**, busque um ID ou veja até 50 registros. **Usar sequência** preenche a consulta. O novo modelo fica disponível após seu treino e conferências; a previsão aguarda a fila quando há tarefa pesada.

## Logs, pausa e retomada

O navegador atualiza estado e logs a cada 2 segundos. Pipeline mostra as dez fases. Tarefas/logs mostram fase, vetores confirmados e épocas. O gráfico pode apresentar validação emitida durante o treino; métricas finais do teste aparecem quando o relatório é concluído.

Escolha **Tarefas e logs → Fluxo completo**. A janela guarda até 500 linhas; os logs completos ficam no disco. O wrapper do agrupamento global também informa seu `mmseqs.log` detalhado.

**Pausar fila** deixa a fase atual terminar e interrompe antes da próxima. **Retomar execução** confere hashes e continua das fases confirmadas. Durante embeddings, a pausa entre fases aguarda o recorte do gerador encerrar; ainda não é pausa cooperativa a cada lote. O gerador conserva sua retomada de lotes se houver encerramento inesperado.

**Encerrar sistema** encerra após a fase ativa, preservando saídas. Ao reiniciar, estados sem encerramento conhecido exigem conciliação. PIDs dos subprocessos registrados são conferidos antes de retomar.

Falhas não entram em repetição infinita. Corrija a mensagem e retome. Para amostra insuficiente ou classe ausente, crie um recorte maior; a semente não é alterada automaticamente pelo resultado do teste. Uma pasta final existente sem aprovação é preservada: crie outra execução se necessário.

Cada execução é finita. O sistema não cria outro treino automaticamente ao concluir o atual.

## Requisitos e uso do PC

Usa a `.venv`, PyTorch/CUDA, cache ESM-2 e Ubuntu WSL/MMseqs2 existentes. Não instala pacotes. `etapas` e `piloto_esm_gpu.py` precisam estar no projeto; os scripts são copiados para manter o registro da execução.

PyTorch usa 2 threads CPU e GPU. MMseqs2 começa com 4; escolha 8 antes de iniciar um experimento se dedicar o computador. Reserva de 10 GiB, conferida entre fases e pelos scripts.

O início opcional com Windows continua disponível:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sistema_tcc\instalar_inicio_automatico.ps1
```

Ele abre o serviço no próximo login, sem criar um treino novo em cada reinício. Para remover, use `sistema_tcc/remover_inicio_automatico.ps1` da mesma forma. A política vale para aquele processo, sem mudança permanente no Windows.

## Verificação desta atualização

Os testes antigos do controlador foram mantidos. Os novos verificam seleção individual, ZIP/GZ, limites, código/fontes alterados, fluxo completo, redução para representantes, vínculo no banco e pausa/retomada.

Leitura, rótulos, produção dos lotes, auditoria, consolidação, partições e banco usam código real em dados temporários. **MMseqs2, ESM-2 e treino são substituídos explicitamente nos testes locais.** Seus resultados simulados não são distribuídos como dados da aplicação. A execução real desses três componentes com WSL/GTX 1650 precisa ser conferida no seu PC. Não foi feita inspeção visual em navegador nesta entrega.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\testes -p "test*.py" -v
```

Serviço local em `127.0.0.1`, ações protegidas pela sessão e sem aceitar comandos arbitrários. Não cria túnel público.

## Limites científicos

`Completa`/`Incompleta` significa presença literal de HILKMFTWV, sem avaliar digestibilidade, qualidade nutricional ou função biológica. A regra direta é a referência e o MLP tenta aproximá-la. Softmax não foi calibrado.

O recorte depende da ordem e elegibilidade das fontes; embeddings são dos representantes. Não é amostra aleatória de todo NCBI. Grupos distintos de Linclust não provam ausência de toda homologia. Esses limites precisam constar no TCC.
