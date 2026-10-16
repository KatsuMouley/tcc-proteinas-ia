# Verificação da entrega — 2026-10-13

## Concluído neste pacote

- 28 testes do sistema passaram na cópia organizada do projeto.
- 11 testes do atualizador passaram em diretórios temporários.
- Sintaxe dos 18 arquivos Python executáveis aprovada.
- Sintaxe JavaScript do dashboard aprovada com `node --check`.
- Ajuda das CLIs do controlador, atualizador, quatro etapas, piloto, teste GPU e exportador de ambiente aprovada.
- Scripts científicos e originais históricos comparados por SHA-256; as alterações de caminho nas ferramentas e a retirada da busca de arquivos externos nos testes estão identificadas no manifesto.

Os testes de atualização incluem simulação sem escrita, preservação de dados/configuração/arquivos desconhecidos, repetição sem mudanças, detecção de pacote alterado, bloqueio de caminhos fora do código, falha de cópia com restauração, restauração manual, edição posterior, instância ativa, links e pacote extraído dentro do destino.

Os 28 testes do projeto usam apenas os scripts distribuídos em `etapas/` e o piloto da raiz. Não procuram arquivos na pasta de uploads deste ambiente.

## Limite da validação

Leitura GZ/ZIP, rótulos, produção de lotes, auditoria, consolidação, partições e banco são exercitados com código real e dados temporários. MMseqs2, ESM-2 e treinamento são substituídos explicitamente nos testes. Os dados simulados não são distribuídos como resultados científicos reais.

Não foi executado CUDA/GTX 1650, WSL ou o atualizador sob Windows nesta entrega. A verificação local do bloqueio usa o sistema operacional deste ambiente. Também não foi feita uma nova inspeção visual do dashboard no navegador.

## Conferência no seu PC

1. Aplique o pacote com o serviço encerrado e confira `ok: true`.
2. Abra `iniciar_sistema.cmd` e confira os resultados anteriores.
3. Abra `iniciar_fluxo_completo.cmd` uma vez para o teste inicial de até 1.000 candidatos.
4. Acompanhe a execução nova até `relatorio_fluxo.json` e confira suas métricas próprias.
5. Confira uma proteína pelo banco e use sua sequência na consulta do modelo.

Se o recorte não tiver as duas classes em todas as partições, o erro é informado. Use mais candidatos ou outras fontes para o experimento seguinte.
