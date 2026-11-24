@echo off
chcp 65001 >nul
title Atualizar o pup_cortes
cd /d "%~dp0"

echo ============================================================
echo   ATUALIZANDO O PUP_CORTES (pelo GitHub)
echo ============================================================
echo.
echo  Feche o pup_cortes antes de continuar (os cortes que estiverem
echo  rodando terminam normalmente). Suas configuracoes, videos e
echo  cortes prontos nao sao mexidos.
echo.
pause

where git >nul 2>&1
if errorlevel 1 (
    echo O Git nao esta instalado. Instalando...
    winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
    echo.
    echo Git instalado. FECHE esta janela e abra o 7_ATUALIZAR.bat de novo.
    pause
    exit /b 0
)

if not exist ".git" (
    echo Esta pasta nao foi baixada com o Git (veio em .zip^), entao nao da
    echo para atualizar sozinho. Baixe a versao nova em:
    echo     https://github.com/w4sington/pup_cortes
    echo e copie para ela o seu configuracoes.ini e as pastas entrada e saida.
    pause
    exit /b 1
)

for /f %%h in ('git rev-parse HEAD') do set "ANTES=%%h"

echo [1/3] Baixando a versao nova...
git pull --ff-only
if errorlevel 1 (
    echo.
    echo ============================================================
    echo   Nao deu para atualizar: algum arquivo do programa foi
    echo   mudado nesta pasta. Tire um print desta janela.
    echo ============================================================
    pause
    exit /b 1
)

for /f %%h in ('git rev-parse HEAD') do set "DEPOIS=%%h"
if "%ANTES%"=="%DEPOIS%" (
    echo.
    echo Voce ja esta com a versao mais nova. Nada para fazer.
    pause
    exit /b 0
)

echo.
echo [2/3] Conferindo os componentes...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
) else (
    echo    Falta o ambiente do programa: rode o 1_INSTALAR.bat
)

echo.
echo [3/3] Conferindo o pup_cortes.exe...
git diff --quiet %ANTES% %DEPOIS% -- app_arquivos/pup_cortes.cs app_arquivos/icone.ico
if errorlevel 1 (
    if exist "pup_cortes.exe" del /q "pup_cortes.exe"
    call "app_arquivos\criar_exe.bat"
    cd /d "%~dp0"
) else (
    echo    Nao mudou.
)

echo.
echo ============================================================
echo   PRONTO! Novidades desta atualizacao:
echo ============================================================
git log --no-merges --format="  - %%s" %ANTES%..%DEPOIS%
echo.
pause
