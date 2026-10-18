# Arquivos históricos

Os arquivos desta pasta preservam as versões recebidas durante a preparação do projeto. O ponto de entrada atual é o `README.md` na raiz.

| Conjunto | Contexto |
|---|---|
| `README_CPU_original.md`, `requirements*original.txt`, `setup_cpu_original.cmd.txt`, `verificar_ambiente_CPU_original.py.txt`, `testar_esm_CPU_original.py.txt` | Preparação inicial em CPU; anterior ao ambiente CUDA que foi confirmado |
| `setup_gpu_original.cmd.txt`, `LEIA_ME_GPU_original.md`, `testar_esm_GPU_original.py.txt` | Migração e teste GPU anteriores |
| `LEIA_ME_PILOTO_GPU_original.md` | Piloto anterior com pares GZ/CSV |
| `COMECE_AQUI_v1_original.md`, `iniciar_sistema_v1_original.cmd.txt` | Primeira versão do painel, anterior ao fluxo completo automático |
| `COMECE_AQUI_v2_antes_organizacao.md` | Guia da versão 2 antes desta organização |
| `manifesto_ambiente_original.json`, `diagnostico_windows_original.ps1.txt` | Preparação e diagnóstico anteriores |
| `agrupar_gz_ncbi_colega.py.txt`, `baixar_gz_colega.py.txt` | Extrator original do colega, com seus caminhos e ambiente antigos |

As duas listas de dependências completas recebidas são idênticas e ainda registram Torch CPU. Não use essas listas para sobrescrever sua `.venv` GPU. O extrator do colega tem caminhos de Drive e usuário próprios; o novo controlador executa seu procedimento de seleção/agrupamento local.

As extensões adicionais `.txt` preservam os scripts para leitura, sem integrá-los como comandos ao fluxo atual. Nenhum deles é chamado automaticamente.

Os arquivos que existiam no seu PC e forem substituídos ou arquivados pelo atualizador ficam em outro lugar: `historico/atualizacoes/`, na raiz do projeto, com seus hashes e plano de restauração. Esta pasta `docs/historico/` reúne as referências recebidas para montar o pacote.
