// pup_cortes.exe - a porta de entrada do app pup_cortes.
//
// O app em si é o app_cortes.pyw (Python). Este .exe só o abre com o Python
// que o 1_INSTALAR.bat criou (.venv), sem janela preta, e mostra uma mensagem
// clara se faltar alguma coisa. Arrastar um vídeo em cima do .exe abre o app
// já com esse vídeo escolhido.
//
// Para gerar de novo depois de mudar este arquivo: app_arquivos\criar_exe.bat
// (usa o compilador C# que já vem no Windows, não precisa instalar nada).
// O ícone (icone.ico) é a logo do site nextlevelpc.com.br; o antigo, da
// tesoura, ficou em app_arquivos\icone_tesoura.

using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;

static class PupCortes
{
    const string Titulo = "pup_cortes";

    [STAThread]
    static void Main(string[] args)
    {
        string pasta = AcharPasta();
        if (pasta == null)
        {
            Avisar("Não encontrei a pasta do programa de cortes.\n\n" +
                   "Deixe o pup_cortes.exe dentro da pasta CortesAutomaticos " +
                   "(junto do cortes.py) e use o atalho da área de trabalho.");
            return;
        }

        string pythonw = Path.Combine(pasta, ".venv", "Scripts", "pythonw.exe");
        if (!File.Exists(pythonw))
        {
            Avisar("O programa ainda não foi instalado neste computador.\n\n" +
                   "Peça para um adulto abrir o 1_INSTALAR.bat (só na primeira vez).");
            return;
        }

        string argumentos = Aspas(Path.Combine(pasta, "app_cortes.pyw")) +
                            string.Concat(args.Select(a => " " + Aspas(a)));
        var inicio = new ProcessStartInfo(pythonw, argumentos);
        inicio.WorkingDirectory = pasta;
        inicio.UseShellExecute = false;
        try
        {
            Process.Start(inicio);
        }
        catch (Exception e)
        {
            Avisar("Não consegui abrir o app:\n" + e.Message);
        }
    }

    // A pasta do próprio .exe; se ele foi copiado para outro lugar (área de
    // trabalho, por exemplo), procura a pasta padrão em Documentos.
    static string AcharPasta()
    {
        string[] candidatas =
        {
            AppDomain.CurrentDomain.BaseDirectory,
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "CortesAutomaticos"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Documents", "CortesAutomaticos"),
        };
        return candidatas.FirstOrDefault(p => File.Exists(Path.Combine(p, "app_cortes.pyw")));
    }

    static string Aspas(string texto)
    {
        return "\"" + texto.TrimEnd('\\') + "\"";
    }

    static void Avisar(string texto)
    {
        MessageBox.Show(texto, Titulo, MessageBoxButtons.OK, MessageBoxIcon.Information);
    }
}
