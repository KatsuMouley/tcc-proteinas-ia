$ErrorActionPreference = 'Stop'
$TccProject = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$TccResults = Join-Path $TccProject 'dados\diagnosticos'
New-Item -ItemType Directory -Path $TccResults -Force | Out-Null

$TccOs = Get-CimInstance Win32_OperatingSystem
$TccCpu = @(Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors)
$TccGpu = @(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion)
$TccDisks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
    [ordered]@{
        unidade = $_.DeviceID
        tamanho_gib = [Math]::Round($_.Size / 1GB, 2)
        livre_gib = [Math]::Round($_.FreeSpace / 1GB, 2)
    }
})
$TccNvidiaOutput = @()
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $TccNvidiaOutput = @(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>&1 | ForEach-Object { "$($_)" })
}
$TccPythonVersions = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $TccPythonVersions = @(py --list 2>&1 | ForEach-Object { "$($_)" })
}
$TccReport = [ordered]@{
    data_utc = [DateTime]::UtcNow.ToString('o')
    sistema = $TccOs.Caption
    arquitetura = $TccOs.OSArchitecture
    ram_total_gib = [Math]::Round(($TccOs.TotalVisibleMemorySize * 1KB) / 1GB, 2)
    ram_livre_gib = [Math]::Round(($TccOs.FreePhysicalMemory * 1KB) / 1GB, 2)
    processadores = $TccCpu
    placas_video = $TccGpu
    nvidia_smi = $TccNvidiaOutput
    python_instalados = $TccPythonVersions
    discos = $TccDisks
}
$TccJson = $TccReport | ConvertTo-Json -Depth 6
$TccJson | Set-Content -LiteralPath (Join-Path $TccResults 'diagnostico_maquina.json') -Encoding UTF8
Write-Output $TccJson
