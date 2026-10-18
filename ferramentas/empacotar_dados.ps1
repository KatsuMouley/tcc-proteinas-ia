# Gera o pacote de dados para o Google Drive (rodar no PC do Katsu).
# Contem o necessario para a Visao geral do milhao e a consulta EC: base consolidada,
# agrupamento, particoes, relatorios, modelos, piloto EC e o ESM-2 em cache.
# Uso: powershell -ExecutionPolicy Bypass -File ferramentas\empacotar_dados.ps1
param([string]$Saida = "E:\ai_tcc_arquivo\pacote_dados_tcc.zip")
$raiz = "C:\ai_tcc"
$itens = @(
  "dados\base_ia\base_1m",
  "dados\base_ia\agrupamento_global_1m\global_cluster.tsv",
  "dados\base_ia\agrupamento_global_1m\relatorio_agrupamento.json",
  "dados\base_ia\agrupamento_global_1m\execucao.json",
  "dados\base_ia\agrupamento_global_1m\mmseqs.log",
  "dados\base_ia\particoes_1m",
  "dados\embeddings\base_ncbi_gpu\fontes.json",
  "dados\embeddings\base_ncbi_gpu\relatorio_execucao.json",
  "dados\validacao",
  "dados\modelos",
  "dados\piloto_ec2_ec3",
  "cache\huggingface"
)
foreach ($i in $itens) { if (-not (Test-Path (Join-Path $raiz $i))) { Write-Error "Faltando: $i"; exit 1 } }
New-Item -ItemType Directory -Force -Path (Split-Path $Saida) | Out-Null
Write-Host "Compactando (alguns minutos)..."
tar -a -c -f $Saida -C $raiz --exclude "respostas_api" @itens
if ($LASTEXITCODE -ne 0) { Write-Error "tar falhou"; exit 1 }
$h = Get-FileHash $Saida -Algorithm SHA256
$mb = [math]::Round((Get-Item $Saida).Length / 1MB)
"Pacote: $Saida ($mb MB)`nSHA256: $($h.Hash)" | Tee-Object -FilePath ($Saida + ".sha256.txt")
Write-Host "Suba o .zip e o .sha256.txt para o Drive do grupo."
