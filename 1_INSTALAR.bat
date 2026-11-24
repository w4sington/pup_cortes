@echo off
chcp 65001 >nul
title Instalador - Cortes Automaticos
cd /d "%~dp0"

echo ============================================================
echo   INSTALANDO O GERADOR DE CORTES AUTOMATICOS
echo ============================================================
echo.

rem ---- Procura o Python (de preferencia 3.12) ----
set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY (
    py -3.11 --version >nul 2>&1 && set "PY=py -3.11"
)
if not defined PY (
    py -3 --version >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo Python nao encontrado. Instalando o Python 3.12...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    echo.
    echo ------------------------------------------------------------
    echo  Python instalado. FECHE esta janela e abra o
    echo  1_INSTALAR.bat de novo para continuar.
    echo ------------------------------------------------------------
    pause
    exit /b 0
)
echo Python encontrado: %PY%
echo.

echo [1/4] Criando o ambiente do programa...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" goto erro
set "VPY=.venv\Scripts\python.exe"

echo.
echo [2/4] Instalando os componentes (pode demorar alguns minutos)...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto erro

echo.
echo [3/4] Instalando o suporte a placa de video NVIDIA para o Whisper...
"%VPY%" -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
if errorlevel 1 echo    Nao deu, mas tudo bem: o Whisper vai usar o processador.

echo.
echo [4/4] Verificando o FFmpeg...
where ffmpeg >nul 2>&1
if errorlevel 1 (
    if exist "ffmpeg\bin\ffmpeg.exe" (
        echo    FFmpeg encontrado na pasta do programa.
    ) else (
        echo    Instalando o FFmpeg...
        winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    )
) else (
    echo    FFmpeg ja esta instalado.
)

if not exist "entrada" mkdir entrada
if not exist "saida" mkdir saida
if not exist "configuracoes.ini" copy /y "configuracoes.exemplo.ini" "configuracoes.ini" >nul

echo.
echo ============================================================
echo   PRONTO! Instalacao concluida.
echo   Agora coloque os videos na pasta "entrada" e abra o
echo   2_GERAR_CORTES.bat  (ou arraste o video em cima dele).
echo ============================================================
pause
exit /b 0

:erro
echo.
echo ============================================================
echo   Deu erro na instalacao. Tire um print desta janela
echo   e mande para o Claude que ele te ajuda.
echo ============================================================
pause
exit /b 1
