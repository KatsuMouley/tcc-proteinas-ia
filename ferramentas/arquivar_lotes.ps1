# Compacta os 16.565 lotes de embeddings do milhao para o HD e libera ~2 GB no SSD.
# Os lotes ja estao consolidados em dados\base_ia\base_1m\embeddings.npy; ficam so como prova de origem.
# Uso: powershell -ExecutionPolicy Bypass -File ferramentas\arquivar_lotes.ps1
param([string]$Saida = "E:\ai_tcc_arquivo\lotes_embeddings_milhao.zip")
$pasta = "C:\ai_tcc\dados\embeddings\base_ncbi_gpu"
$n = (Get-ChildItem "$pasta\lotes" -Recurse -File).Count
Write-Host "Arquivos nos lotes: $n. Compactando para $Saida (pode levar 10 a 20 minutos)..."
tar -a -c -f $Saida -C $pasta lotes controle.sqlite3
if ($LASTEXITCODE -ne 0) { Write-Error "tar falhou; nada foi apagado."; exit 1 }
$noZip = (tar -t -f $Saida | Where-Object { $_ -like "lotes/*" -and $_ -notlike "*/" }).Count
if ($noZip -ne $n) { Write-Error "Conferencia falhou ($noZip de $n); nada foi apagado."; exit 1 }
Write-Host "Conferido: $noZip arquivos no zip. Apagando a pasta lotes do SSD..."
Remove-Item "$pasta\lotes" -Recurse -Force
Remove-Item "$pasta\controle.sqlite3" -Force
Write-Host "Pronto. Zip guardado em $Saida"
