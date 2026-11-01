@echo off
setlocal EnableExtensions
title Instalador do sistema TCC - Proteinas IA
set "REPO=https://github.com/KatsuMouley/tcc-proteinas-ia.git"
set "ZIP=https://github.com/KatsuMouley/tcc-proteinas-ia/archive/refs/heads/main.zip"
set "PASTA=C:\ai_tcc"

echo ============================================================
echo  Instalador - IA aplicada a Bioinformatica (TCC)
echo  1. Baixa o projeto do GitHub   2. Instala o sistema
echo  3. Escolhe onde salvar os arquivos   4. Escolhe MMseqs2
echo ============================================================
echo.
echo Pasta de instalacao. Pressione Enter para usar %PASTA%
set "ENTRADA="
set /p "ENTRADA=> "
if not "%ENTRADA%"=="" set "PASTA=%ENTRADA%"
echo Pasta: %PASTA%
echo.

rem ---------- 1. baixar o projeto ----------
where git >nul 2>&1
if errorlevel 1 goto sem_git

if exist "%PASTA%\.git" (
    echo Projeto ja existe nesta pasta. Atualizando com git pull ...
    git -C "%PASTA%" pull --ff-only
    if errorlevel 1 echo AVISO: nao foi possivel atualizar. Seguindo com a versao que ja esta na pasta.
    goto instalar
)
if exist "%PASTA%\instalar.cmd" (
    echo A pasta ja tem o projeto ^(sem git^). Seguindo com ele.
    goto instalar
)
echo Clonando o repositorio ...
git clone "%REPO%" "%PASTA%"
if errorlevel 1 goto falhou_clone
goto instalar

:sem_git
echo O Git nao foi encontrado neste computador.
echo   1 = instalar o Git agora com o winget ^(depois feche e abra este instalador de novo^)
echo   2 = baixar o projeto em ZIP, sem Git ^(a Fase 1 do Filipe nao sera clonada^)
choice /c 12 /n /m "Escolha 1 ou 2: "
if errorlevel 2 goto via_zip
where winget >nul 2>&1
if errorlevel 1 (
    echo O winget nao esta disponivel. Instale o Git em https://git-scm.com/download/win
    echo ou escolha a opcao 2 na proxima vez.
    pause
    exit /b 1
)
winget install --id Git.Git -e --source winget
echo.
echo Git instalado. Feche esta janela e abra o instalador novamente.
pause
exit /b 0

:via_zip
echo Baixando o projeto em ZIP ...
set "TMPZ=%TEMP%\tcc_main.zip"
set "TMPD=%TEMP%\tcc_zip"
if exist "%TMPD%" rmdir /s /q "%TMPD%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest '%ZIP%' -OutFile '%TMPZ%'; Expand-Archive -Force '%TMPZ%' '%TMPD%'; New-Item -ItemType Directory -Force '%PASTA%' | Out-Null; Copy-Item -Recurse -Force (Join-Path '%TMPD%' '*\*') '%PASTA%'"
if errorlevel 1 goto falhou_clone
if not exist "%PASTA%\instalar.cmd" goto falhou_clone
goto instalar

:falhou_clone
echo.
echo ERRO ao baixar o projeto. Verifique a internet e se a pasta de destino esta vazia.
echo Se o repositorio for privado, entre no GitHub com o Git antes de rodar de novo.
pause
exit /b 1

rem ---------- 2. instalar o sistema (pergunta onde salvar: PC ou nuvem) ----------
:instalar
cd /d "%PASTA%" || goto falhou_clone
call instalar.cmd
if errorlevel 1 (
    echo.
    echo A instalacao do sistema falhou. Veja as mensagens acima e envie ao grupo.
    pause
    exit /b 1
)

rem ---------- 3. MMseqs2: nativo ou WSL ----------
cd /d "%PASTA%"
echo.
echo ============================================================
echo  Agrupamento de proteinas ^(MMseqs2^): como deseja rodar?
echo   [1] Nativo do Windows ^(recomendado: sem Linux, sem administrador^)
echo   [2] WSL / Ubuntu ^(precisa de administrador; pode pedir reinicio^)
echo   [3] Instalar os dois
echo   [4] Pular por enquanto
echo ============================================================
choice /c 1234 /n /m "Escolha 1 a 4: "
if errorlevel 4 goto pronto
if errorlevel 3 goto ambos
if errorlevel 2 goto so_wsl
call ferramentas\instalar_mmseqs_nativo.cmd
goto pronto
:ambos
call ferramentas\instalar_mmseqs_nativo.cmd
cd /d "%PASTA%"
:so_wsl
call instalar_wsl_mmseqs.cmd
cd /d "%PASTA%"

:pronto
echo.
echo ============================================================
echo  Tudo pronto. Para abrir o sistema depois, use iniciar_sistema.cmd
echo  na pasta %PASTA%
echo ============================================================
choice /m "Abrir o sistema agora"
if errorlevel 2 goto fim
if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" -m sistema_tcc --abrir
:fim
pause
exit /b 0
