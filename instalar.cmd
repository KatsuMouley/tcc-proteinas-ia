@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Instalador do sistema TCC - proteinas (ESM-2 + MLP)
echo  Traz o proprio Python 3.13: nao depende do Python do PC.
echo ============================================================
if /i not "%~dp0"=="C:\ai_tcc\" (
    echo AVISO: esta pasta e %~dp0
    echo Os relatorios da base do milhao registram C:\ai_tcc. Instale em C:\ai_tcc
    echo para a Visao geral e a consulta funcionarem com o pacote de dados.
    choice /m "Continuar mesmo assim"
    if errorlevel 2 exit /b 1
)

rem Rede lenta ou antivirus da faculdade: mais tempo por download, um download por vez, copia em vez de link
set "UV_HTTP_TIMEOUT=300"
set "UV_CONCURRENT_DOWNLOADS=1"
set "UV_LINK_MODE=copy"

rem 1. uv: baixa um executavel pequeno para dentro do projeto (sem instalar nada no Windows)
set "UV=%~dp0ferramentas\uv\uv.exe"
if not exist "%UV%" (
    echo Baixando o gerenciador uv ...
    if not exist "ferramentas\uv" mkdir "ferramentas\uv"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile 'ferramentas\uv\uv.zip'; Expand-Archive -Force 'ferramentas\uv\uv.zip' 'ferramentas\uv'; Remove-Item 'ferramentas\uv\uv.zip'"
)
if not exist "%UV%" (
    echo ERRO: nao foi possivel baixar o uv. Verifique a internet/antivirus e rode de novo.
    goto falhou
)

rem 2. ambiente .venv com Python 3.13 (se existir com outra versao, guarda como .venv_antigo)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,13) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo O .venv existente usa outro Python. Guardando como .venv_antigo e criando um novo ...
        ren ".venv" ".venv_antigo_%RANDOM%"
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo Criando o .venv com Python 3.13 ^(baixado pelo uv, so na primeira vez^) ...
    "%UV%" venv .venv --python 3.13 --managed-python
    if errorlevel 1 goto falhou
)
set "VPY=%~dp0.venv\Scripts\python.exe"

rem 3. dependencias
call :uvpip -r requirements.txt
if errorlevel 1 goto falhou
nvidia-smi >nul 2>&1
if errorlevel 1 goto cpu
echo Placa NVIDIA encontrada: instalando PyTorch com CUDA 12.6. Download grande, aguarde.
call :uvpip "torch==2.9.1+cu126" --index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 goto falhou
goto fase1
:cpu
echo Sem placa NVIDIA: instalando PyTorch para CPU. O sistema funciona no processador.
call :uvpip "torch==2.9.1" --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto falhou
:fase1
if not exist "fase1_extrator\genomic-data-extractor\agrupar_gz_ncbi.py" (
    echo Clonando a Fase 1 do Filipe para baixar e agrupar .gz do NCBI...
    git clone https://github.com/filipecamargoprado/genomic-data-extractor.git fase1_extrator\genomic-data-extractor
    if errorlevel 1 echo AVISO: nao foi possivel clonar a Fase 1. Veja o README.
)

rem 4. onde salvar os arquivos (PC ou nuvem sincronizada)
"%VPY%" ferramentas\configurar_nuvem.py

rem 5. ESM-2 e verificacao
"%VPY%" ferramentas\baixar_esm2.py
if errorlevel 1 goto falhou
"%VPY%" -c "import torch, transformers, numpy, sys; print('Python', sys.version.split()[0], '| torch', torch.__version__, '| GPU:', torch.cuda.is_available())"
if errorlevel 1 goto falhou
echo.
echo ============================================================
echo  Instalacao concluida.
echo  1. Para o MMseqs2/Ubuntu (agrupamento): instalar_wsl_mmseqs.cmd
echo  2. Opcional: extraia o pacote de dados do Drive em C:\ai_tcc
echo     ^(sem ele a consulta funciona com os modelos do repositorio^).
echo  3. Abra iniciar_sistema.cmd e confira a tela Configuracoes.
echo ============================================================
pause
exit /b 0
:falhou
echo.
echo ERRO na instalacao. Copie as mensagens acima e envie ao grupo.
pause
exit /b 1

rem Instala com ate 3 tentativas (o que ja baixou fica no cache e nao baixa de novo)
:uvpip
set "N=0"
:uvpip_tenta
"%UV%" pip install --python "%VPY%" %*
if not errorlevel 1 exit /b 0
set /a N+=1
if %N% lss 3 (
    echo Falha ao baixar ou extrair. Nova tentativa %N%/3 em 5 segundos ...
    timeout /t 5 >nul
    goto uvpip_tenta
)
exit /b 1
