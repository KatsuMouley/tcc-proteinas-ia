# Instala o que o fluxo novo precisa fora do Python: WSL + Ubuntu + MMseqs2.
# So e necessario para AGRUPAR (Fase 1) e rodar FLUXOS NOVOS / experimento EC7.
# A consulta de proteinas no painel NAO precisa disto.
#
# Uso: duplo clique em instalar_wsl_mmseqs.cmd (raiz do projeto). Pode rodar varias vezes:
# cada etapa ja concluida e pulada.
param([string]$Distro = "")

$ErrorActionPreference = "Continue"
$env:WSL_UTF8 = "1"
$raiz = Split-Path $PSScriptRoot -Parent

function Titulo($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }
function Limpo($s) { ($s -join "`n") -replace "`0", "" }
function EhAdmin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Distribuicao: parametro > Configuracoes do painel (config_local.json) > Ubuntu
if (-not $Distro) {
    $Distro = "Ubuntu"
    $cfg = Join-Path $raiz "config_local.json"
    if (Test-Path $cfg) {
        try { $v = (Get-Content $cfg -Raw | ConvertFrom-Json).wsl; if ($v) { $Distro = $v } } catch {}
    }
}

Titulo "1/3 WSL"
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-Host "O WSL nao existe neste Windows. Precisa do Windows 10 (2004+) ou 11."
    exit 1
}
$lista = (Limpo (wsl.exe -l -q 2>$null)).Split("`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
Write-Host ("Distribuicoes encontradas: " + ($(if ($lista) { $lista -join ", " } else { "nenhuma" })))

if ($lista -notcontains $Distro) {
    $outra = $lista | Where-Object { $_ -like "Ubuntu*" } | Select-Object -First 1
    if ($outra) {
        Write-Host "Nao achei '$Distro', mas achei '$outra'. Usando '$outra'."
        Write-Host "IMPORTANTE: no painel, em Configuracoes > 'Distribuicao WSL', escreva: $outra" -ForegroundColor Yellow
        $Distro = $outra
    } else {
        Titulo "Instalando o Ubuntu no WSL"
        if (-not (EhAdmin)) {
            Write-Host "Precisa de administrador. Vai abrir uma janela pedindo permissao..."
            Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Distro Ubuntu"
            exit 0
        }
        wsl.exe --install -d Ubuntu
        Write-Host ""
        Write-Host "PROXIMOS PASSOS (uma vez so):" -ForegroundColor Yellow
        Write-Host " 1. Se o Windows pedir, REINICIE o computador."
        Write-Host " 2. Abra 'Ubuntu' pelo menu Iniciar e crie um usuario e uma senha (qualquer um)."
        Write-Host " 3. Feche o Ubuntu e rode instalar_wsl_mmseqs.cmd de novo (em janela NORMAL, nao administrador)."
        exit 0
    }
}

Titulo "2/3 MMseqs2 no $Distro"
Write-Host "Acordando o WSL (a primeira vez pode levar ate 1 minuto)..."
$v = Limpo (wsl.exe -d $Distro --exec mmseqs version 2>&1)
if ($LASTEXITCODE -eq 0 -and $v -match "^\S+") {
    Write-Host "MMseqs2 ja instalado: $($v.Trim())" -ForegroundColor Green
} else {
    Write-Host "Instalando o pacote mmseqs2 do Ubuntu (como root; nao pede senha)..."
    wsl.exe -d $Distro -u root --exec bash -c "apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q mmseqs2"
    $v = Limpo (wsl.exe -d $Distro --exec mmseqs version 2>&1)
}

Titulo "3/3 Conferencia"
if ($LASTEXITCODE -eq 0 -and $v -match "^\S+") {
    $versao = ($v.Trim().Split("`n") | Select-Object -Last 1).Trim()
    Write-Host "OK: $Distro com MMseqs2 $versao" -ForegroundColor Green
    if ($versao -notlike "18-*") {
        Write-Host "Obs.: os resultados do TCC usaram MMseqs2 18-8cc5c. Outra versao funciona, mas o agrupamento de um fluxo NOVO pode sair um pouco diferente. A consulta nao e afetada." -ForegroundColor Yellow
    }
    Write-Host "Agora abra o painel > Configuracoes > Diagnostico e confira a linha 'WSL + MMseqs2'."
    exit 0
}
Write-Host "O MMseqs2 nao respondeu. Mensagem do WSL:" -ForegroundColor Red
Write-Host $v
if ($v -match "systemd") {
    Write-Host ""
    Write-Host "Erro conhecido do systemd no WSL. Para resolver (desligar o systemd so do Ubuntu, reversivel):" -ForegroundColor Yellow
    Write-Host "  wsl -d $Distro -u root --exec sed -i 's/systemd=true/systemd=false/' /etc/wsl.conf"
    Write-Host "  wsl --shutdown"
    Write-Host "e rode este instalador de novo."
} else {
    Write-Host "Tente: wsl --shutdown  e rode de novo. Se persistir, envie esta mensagem ao grupo."
}
exit 1
