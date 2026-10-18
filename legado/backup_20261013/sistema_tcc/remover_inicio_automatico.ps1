$ErrorActionPreference = 'Stop'
$projetoTcc = Split-Path -Parent $PSScriptRoot
$pythonTcc = Join-Path $projetoTcc '.venv\Scripts\pythonw.exe'
$atalhoTcc = Join-Path ([Environment]::GetFolderPath('Startup')) 'TCC-Proteinas-Sistema.lnk'
if (Test-Path -LiteralPath $atalhoTcc) {
    $shellTcc = New-Object -ComObject WScript.Shell
    $linkTcc = $shellTcc.CreateShortcut($atalhoTcc)
    if ($linkTcc.TargetPath -ne $pythonTcc) { throw 'O atalho pertence a outro projeto. Ele foi preservado.' }
    Remove-Item -LiteralPath $atalhoTcc
}
Write-Host 'Início automático removido. A instância que já estiver aberta continua funcionando.'
