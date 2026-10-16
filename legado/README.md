# Proteínas · TCC — projeto organizado

Sistema local para selecionar proteínas dos GZ, agrupar com MMseqs2, gerar embeddings ESM-2 na GPU, preparar partições, treinar um MLP e consultar resultados no dashboard. SQLite registra a fila, os experimentos e os vínculos das proteínas.

## Começar

Para abrir o sistema e seus resultados:

```powershell
cd C:\ai_tcc
.\iniciar_sistema.cmd
```

Para criar e iniciar um experimento completo com até 1.000 candidatos:

```powershell
cd C:\ai_tcc
.\iniciar_fluxo_completo.cmd
```

**Abertura do painel e criação de experimento são comandos diferentes.** O primeiro permite acompanhar, consultar e iniciar pelo painel. O segundo já cria um novo fluxo e executa suas fases automaticamente.

Dashboard: [http://127.0.0.1:8765](http://127.0.0.1:8765). Em **Pipeline automático**, escolha todas as fontes ou um GZ específico, o limite e **Iniciar fluxo completo**. Consulte a execução correspondente no seletor do topo.

## Onde está cada parte

| Local | Função |
|---|---|
| `sistema_tcc/` | Dashboard, API local, fila e execução das fases |
| `etapas/` | Embeddings, auditoria, consolidação, agrupamento, partições e treino |
| `piloto_esm_gpu.py` | Biblioteca compartilhada de leitura e embeddings, além do piloto individual |
| `ferramentas/ambiente/` | Diagnóstico Windows, teste GPU e exportação das dependências instaladas |
| `docs/` | Arquitetura, operação, dependências, mapa e histórico do TCC |
| `testes/` | Testes do controlador e integração com componentes de IA/MMseqs2 simulados |
| `dados/` | Resultados anteriores, fila, bancos, experimentos e novos modelos |
| `cache/` | Modelo ESM-2 já baixado |
| `arquivos .gz/`, `arquivos csv/` | Fontes locais originais, inclusive ZIPs |
| `historico/atualizacoes/` | Backups produzidos ao aplicar este pacote |

O piloto permanece na raiz porque `processar_base_gpu.py` o importa dali. Os arquivos antigos de preparação ficam em `docs/historico/`; o guia dessa pasta explica quais ainda descrevem o ambiente CPU.

## Ambiente existente

Use a `.venv` já preparada com CUDA, o cache ESM-2 e Ubuntu WSL com MMseqs2. O controlador e dashboard usam a biblioteca padrão do Python; as etapas científicas usam NumPy, PyTorch e Transformers. Leia [docs/DEPENDENCIAS.md](docs/DEPENDENCIAS.md) antes de alterar o ambiente.

## Ler no Obsidian

- [COMECE_AQUI_SISTEMA.md](COMECE_AQUI_SISTEMA.md): comandos do dia a dia.
- [docs/ARQUITETURA.md](docs/ARQUITETURA.md): desenho e explicação de cada fase.
- [docs/MAPA_ARQUIVOS.md](docs/MAPA_ARQUIVOS.md): responsabilidades e destinos.
- [docs/OPERACAO.md](docs/OPERACAO.md): logs, pausa, retomada e problemas comuns.
- [docs/HISTORICO_E_RESULTADOS.md](docs/HISTORICO_E_RESULTADOS.md): o experimento anterior e os limites dos resultados.

## Significado das previsões

`Completa` significa que a sequência contém literalmente todas as letras de `HILKMFTWV`. A classificação é uma regra de composição; ela não mede digestibilidade, qualidade nutricional ou função biológica. MMseqs2 fornece grupos por semelhança; ESM-2 fornece vetores; o MLP aprende a aproximar os rótulos da regra. ESM-2 permanece fixo, sem novo treinamento.

Os resultados novos ficam em pastas próprias, separados da base anterior de um milhão. Cada execução é finita; não há repetição automática de treinamento depois de concluída.
