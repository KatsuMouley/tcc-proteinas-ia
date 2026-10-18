$ErrorActionPreference = 'Stop'
$projetoTcc = Split-Path -Parent $PSScriptRoot
$pythonTcc = Join-Path $projetoTcc '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonTcc)) { throw 'Python do projeto não encontrado.' }
$inicioTcc = [Environment]::GetFolderPath('Startup')
$atalhoTcc = Join-Path $inicioTcc 'TCC-Proteinas-Sistema.lnk'
$shellTcc = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $atalhoTcc) {
    $anteriorTcc = $shellTcc.CreateShortcut($atalhoTcc)
    if ($anteriorTcc.TargetPath -ne $pythonTcc) { throw 'Há outro atalho com esse nome. Ele foi preservado.' }
}
$linkTcc = $shellTcc.CreateShortcut($atalhoTcc)
$linkTcc.TargetPath = $pythonTcc
$linkTcc.Arguments = '-m sistema_tcc'
$linkTcc.WorkingDirectory = $projetoTcc
$linkTcc.Description = 'Sistema local do TCC de proteínas'
$linkTcc.Save()
Write-Host 'Configurado: o sistema abrirá em segundo plano no próximo login do Windows.'
Write-Host 'Dashboard: http://127.0.0.1:8765'
Write-Host 'Este comando não inicia outra instância agora.'
