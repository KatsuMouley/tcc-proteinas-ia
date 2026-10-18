@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1

where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher nao encontrado. Instale uma versao compativel conforme o README.
    goto falha
)

if exist ".venv\Scripts\python.exe" goto validar

for %%V in (3.13 3.12 3.11) do (
    py -%%V -c "import sys; assert sys.maxsize > 2**32" >nul 2>&1
    if not errorlevel 1 (
        echo Criando ambiente com Python %%V de 64 bits.
        py -%%V -m venv .venv
        if errorlevel 1 goto falha
        goto validar
    )
)
echo Instale Python 3.13, 3.12 ou 3.11 de 64 bits.
goto falha

:validar
set "TCC_PY=%~dp0.venv\Scripts\python.exe"
"%TCC_PY%" -c "import sys; assert sys.version_info[:2] in ((3,11),(3,12),(3,13)) and sys.maxsize > 2**32, 'O ambiente precisa de Python 3.11, 3.12 ou 3.13 de 64 bits'"
if errorlevel 1 goto falha

"%TCC_PY%" -m pip install --no-cache-dir --upgrade pip
if errorlevel 1 goto falha
"%TCC_PY%" -m pip install --no-cache-dir --only-binary=:all: "torch==2.7.1" --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto falha
"%TCC_PY%" -m pip install --no-cache-dir --only-binary=:all: -r requirements.txt --index-url https://pypi.org/simple
if errorlevel 1 goto falha
"%TCC_PY%" -m pip check
if errorlevel 1 goto falha
"%TCC_PY%" verificar_ambiente.py
if errorlevel 1 goto falha
"%TCC_PY%" -m pip freeze > requirements.instaladas.txt
if errorlevel 1 goto falha

echo.
echo Ambiente CPU preparado. O modelo ainda sera baixado pelo teste separado.
echo Execute: .venv\Scripts\python.exe testar_esm.py
echo Nao foi realizado treinamento com dados biologicos.
popd
exit /b 0

:falha
echo.
echo Preparacao interrompida. Confira o erro acima antes de continuar.
popd
exit /b 1
