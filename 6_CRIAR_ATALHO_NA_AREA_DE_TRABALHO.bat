@echo off
chcp 65001 >nul
title Criar o atalho do pup_cortes
cd /d "%~dp0"

rem O pup_cortes.exe nao vai para o GitHub: e gerado aqui a partir do app_arquivos\pup_cortes.cs
if not exist "pup_cortes.exe" (
    echo Gerando o pup_cortes.exe...
    call "app_arquivos\criar_exe.bat"
    cd /d "%~dp0"
)
if not exist "pup_cortes.exe" (
    echo Nao achei o pup_cortes.exe nesta pasta.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pasta = (Get-Location).Path;" ^
  "$nome = 'pup_cortes.lnk';" ^
  "$destino = Join-Path ([Environment]::GetFolderPath('Desktop')) $nome;" ^
  "$atalho = (New-Object -ComObject WScript.Shell).CreateShortcut($destino);" ^
  "$atalho.TargetPath = Join-Path $pasta 'pup_cortes.exe';" ^
  "$atalho.WorkingDirectory = $pasta;" ^
  "$atalho.IconLocation = (Join-Path $pasta 'pup_cortes.exe') + ',0';" ^
  "$atalho.Description = 'Fazer cortes de videos para TikTok, Reels e Kwai';" ^
  "$atalho.Save()"
if errorlevel 1 (
    echo.
    echo Nao consegui criar o atalho. Tire um print desta janela.
    pause
    exit /b 1
)

echo ============================================================
echo   PRONTO! O atalho "pup_cortes" esta na area de trabalho.
echo   E so clicar duas vezes nele para abrir o app.
echo ============================================================
echo.
pause
