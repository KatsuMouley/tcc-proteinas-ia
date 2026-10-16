@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_GPU_TCC=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_GPU_TCC%" (
    echo ERRO: .venv nao encontrada. Coloque os arquivos dentro de C:\ai_tcc.
    exit /b 1
)
if not exist "%~dp0testar_esm_gpu.py" (
    echo ERRO: testar_esm_gpu.py precisa estar na mesma pasta deste instalador.
    exit /b 1
)

echo Instalando PyTorch com CUDA 12.6 no ambiente existente.
echo Execute este instalador quando os outros scripts deste ambiente terminarem.
echo O modelo ESM-2 existente sera reutilizado pelo teste.
echo.

if not exist "%~dp0requirements_antes_gpu.txt" (
    "%PYTHON_GPU_TCC%" -m pip freeze > "%~dp0requirements_antes_gpu.txt"
    if errorlevel 1 exit /b 1
)

"%PYTHON_GPU_TCC%" -m pip install --upgrade "torch==2.9.1+cu126" --index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 (
    echo ERRO: a instalacao falhou. Copie a mensagem anterior para diagnostico.
    exit /b 1
)

"%PYTHON_GPU_TCC%" -m pip check
if errorlevel 1 (
    echo ERRO: existem dependencias incompativeis. Copie a saida de pip check.
    exit /b 1
)

"%PYTHON_GPU_TCC%" "%~dp0testar_esm_gpu.py"
if errorlevel 1 (
    echo O teste GPU nao passou. Veja o JSON acima; nao houve treinamento.
    exit /b 1
)

echo.
echo GPU confirmada para inferencia sintetica do ESM-2.
echo Os outros scripts precisam configurar CUDA para usar a GPU tambem.
exit /b 0
