@echo off
rem Gera de novo o pup_cortes.exe a partir do pup_cortes.cs.
rem Usa o compilador C# que ja vem no Windows (.NET Framework 4).
cd /d "%~dp0"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo Nao achei o compilador C# do Windows.
    pause
    exit /b 1
)
"%CSC%" /nologo /codepage:65001 /target:winexe /optimize+ /win32icon:icone.ico /out:..\pup_cortes.exe /r:System.Windows.Forms.dll pup_cortes.cs
if errorlevel 1 (
    echo.
    echo Deu erro ao gerar o .exe
    pause
    exit /b 1
)
echo Pronto: pup_cortes.exe gerado na pasta do programa.
