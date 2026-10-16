# Dependências e ambiente

Esta entrega atualiza o código. Reutilize a `.venv`, o driver NVIDIA, o cache ESM-2 e Ubuntu WSL/MMseqs2 que já funcionaram no seu PC. Não é necessário reinstalar pacotes para abrir o controlador e o dashboard.

## O que cada parte usa

| Parte | Dependências |
|---|---|
| Dashboard, HTTP, fila e SQLite | Biblioteca padrão do Python |
| Leitura e preparação | Biblioteca padrão e NumPy |
| Embeddings e consulta | PyTorch com CUDA, Transformers, tokenizador/pesos ESM-2 |
| Treino MLP | NumPy e PyTorch com CUDA |
| Agrupamento | MMseqs2 no Ubuntu WSL, separado da `.venv` Windows |

O histórico de execução recebido confirmou PyTorch `2.9.1+cu126`, CUDA compilada `12.6` e GTX 1650 de 4 GiB. Isso descreve o ambiente que passou no teste; a lista efetivamente instalada precisa ser exportada do seu computador.

Os arquivos `requirements_instaladas_CPU_original.txt` e `requirements_antes_GPU_original.txt` recebidos ainda contêm `torch==2.7.1+cpu` e são idênticos. Eles ficam em `docs/historico/` e não são a receita de reinstalação do ambiente GPU atual. O antigo `requirements_CPU_original.txt` também pertence à preparação inicial.

## Registrar o ambiente atual

Com os scripts de instalação encerrados, execute:

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe .\ferramentas\ambiente\exportar_dependencias.py
```

O comando grava `requirements.instaladas.txt` e `ambiente.json` em uma pasta nova de `dados/diagnosticos/`. Ele usa `pip freeze` do mesmo Python, registra versões por metadados e não instala bibliotecas nem importa Torch para usar a GPU.

## Testar a GPU novamente, se necessário

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe .\ferramentas\ambiente\testar_esm_gpu.py
```

O teste reutiliza `cache/huggingface/` da raiz. Download é bloqueado por padrão. A opção explícita `--permitir-download` permite recuperar componentes ausentes; ela não é usada pelo fluxo automático.

## Diagnosticar MMseqs2

```powershell
.\.venv\Scripts\python.exe .\etapas\preparar_base_ia.py diagnosticar
```

O diagnóstico deve encontrar MMseqs2 no Ubuntu. WSL não fica dentro da `.venv`. Os scripts usam `/var/tmp` para os temporários do agrupamento. O tamanho virtual mostrado pelo disco WSL não equivale ao espaço físico livre do SSD Windows.

## Hardware e disco

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ferramentas\ambiente\diagnostico_windows.ps1
```

O relatório fica em `dados/diagnosticos/diagnostico_maquina.json`. É uma verificação do estado atual do PC, sem instalar software. A opção de política de execução vale para esse processo PowerShell.

## Exportar para colegas

Este ZIP serve para compartilhar o código e os guias. Para executar em outro computador, o colega precisa preparar um ambiente compatível, ter acesso às fontes escolhidas, ao ESM-2 e ao MMseqs2. A `.venv` de um PC não é um pacote portátil. Os dados e checkpoints já produzidos precisam ser enviados separadamente caso façam parte do teste deles.
