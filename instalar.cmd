@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Instalador do sistema TCC - proteinas (ESM-2 + MLP)
echo ============================================================
if /i not "%~dp0"=="C:\ai_tcc\" (
    echo AVISO: esta pasta e %~dp0
    echo Os relatorios da base do milhao registram C:\ai_tcc. Instale em C:\ai_tcc
    echo para a Visao geral e a consulta funcionarem com o pacote de dados.
    choice /m "Continuar mesmo assim"
    if errorlevel 2 exit /b 1
)
set "PY="
py -3.13 --version >nul 2>&1 && set "PY=py -3.13"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (
    echo ERRO: Python nao encontrado. Instale o Python 3.13 em python.org
    echo e marque "Add python.exe to PATH". Depois rode este instalador de novo.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo Criando o ambiente .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto falhou
)
set "VPY=%~dp0.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto falhou
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto falhou
nvidia-smi >nul 2>&1
if errorlevel 1 goto cpu
echo Placa NVIDIA encontrada: instalando PyTorch com CUDA 12.6. Download grande, aguarde.
"%VPY%" -m pip install "torch==2.9.1+cu126" --index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 goto falhou
goto esm
:cpu
echo Sem placa NVIDIA: instalando PyTorch para CPU. O sistema funciona no processador.
"%VPY%" -m pip install "torch==2.9.1" --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto falhou
:esm
"%VPY%" ferramentas\baixar_esm2.py
if errorlevel 1 goto falhou
echo.
echo ============================================================
echo  Instalacao concluida.
echo  1. Extraia o pacote de dados do Drive dentro de C:\ai_tcc (veja o README).
echo  2. Abra iniciar_sistema.cmd e confira a tela Configuracoes.
echo ============================================================
pause
exit /b 0
:falhou
echo.
echo ERRO na instalacao. Copie as mensagens acima e envie ao grupo.
pause
exit /b 1
