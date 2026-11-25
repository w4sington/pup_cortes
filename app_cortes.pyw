# -*- coding: utf-8 -*-
"""
PUP_CORTES - o jeito facil de usar o Cortes Automaticos

Uma janela so, sem tela preta, para qualquer pessoa usar (ate uma crianca):
  1. escolher o video   2. apertar "Fazer cortes"   3. assistir os cortes prontos

Visual no estilo do Windows 7 (botoes com degrade, caixas de grupo, barra de
comandos e barra de status), com as cores do site da Next Level PC.

Abre pelo pup_cortes.exe (ou .venv\\Scripts\\pythonw.exe app_cortes.pyw).
Por baixo roda o mesmo cortes.py dos .bat, sem janela, e acompanha o
andamento pelo status.json - entao tambem mostra um corte que foi iniciado
pelo 2_GERAR_CORTES.bat.

Integracao com o site (opcional, fica fora do repositorio): com os arquivos
redes.py e whatsapp_cortes.py na pasta, aparecem as abas Postagens (Reels e
TikTok programados) e Contas, e os avisos pelo WhatsApp. Sem eles, o app mostra
so os cortes.
"""

import datetime
import hashlib
import io
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import controle  # noqa: E402
import cortes  # noqa: E402
import formatar  # noqa: E402

try:  # integracao com o site (opcional, fica fora do repositorio)
    import redes  # noqa: E402
    import whatsapp_cortes as zap  # noqa: E402
except ImportError:
    redes = zap = None
SITE = redes is not None  # mostra as abas Postagens e Contas

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except Exception:  # sem Pillow o app funciona, so sem as miniaturas
    Image = None

NOME = "pup_cortes"
SCRIPT = cortes.BASE / "cortes.py"   # o teste troca por um cortes de mentira
ARQ_ERROS = cortes.BASE / "logs" / "app_erros.log"
PASTA_MINIATURAS = cortes.BASE / "logs" / "miniaturas"
ICONE_ICO = cortes.BASE / "app_arquivos" / "icone.ico"
ARQ_ULTIMA_POSTAGEM = cortes.BASE / "logs" / "ultima_postagem.json"  # contas e horario da ultima vez
QTDS = [3, 5, 8, 10]
TELAS_CORTES = ("inicio", "trabalhando", "pronto", "erro")  # o que fica atras da aba "Cortes"
INTERVALOS = [("1 hora", 3600), ("2 horas", 7200), ("3 horas", 10800), ("6 horas", 21600),
              ("12 horas", 43200), ("1 dia", 86400), ("2 dias", 172800)]
COR_REDE = {"instagram": "#C13584", "tiktok": "#111111", "youtube": "#CC0000"}

# Cores do site (nextlevelpc.com.br) + cinzas do Windows 7
AZUL, AZUL_ESCURO, CIANO, MARINHO = "#2563EB", "#1D4ED8", "#00D4FF", "#0F172A"
TEXTO, APAGADO, CINZA_TOPO = "#1E293B", "#64748B", "#94A3B8"
BRANCO, FACE, LINHA, BORDA = "#FFFFFF", "#F0F0F0", "#DFDFDF", "#ADADAD"
SELECAO, SELECAO_BORDA = "#E5F3FF", "#99D1FF"      # item com o mouse em cima (Explorer)
VERDE, VERMELHO = "#15803D", "#C42B1C"

# Degrades dos botoes do Windows 7: (topo, meio de cima, meio de baixo, base, borda, letra)
ESTILO_BOTAO = {
    "normal":    ("#F2F2F2", "#EBEBEB", "#DDDDDD", "#CFCFCF", "#707070", TEXTO),
    "em_cima":   ("#EAF6FD", "#D9F0FC", "#BEE6FD", "#A7D9F5", "#3C7FB1", TEXTO),
    "apertado":  ("#E5F4FC", "#C4E5F6", "#98D1EF", "#68B3DB", "#2C628B", TEXTO),
    "desligado": ("#F4F4F4", "#F4F4F4", "#F4F4F4", "#F4F4F4", "#ADB2B5", "#838383"),
}
ESTILO_PRINCIPAL = {  # o botao da acao principal, no azul do site
    "normal":    ("#6A9EF7", "#5A92F5", "#2F6DEC", "#2563EB", "#1E3A8A", "#FFFFFF"),
    "em_cima":   ("#80ADF8", "#6FA2F7", "#4580EF", "#3573EC", "#1E3A8A", "#FFFFFF"),
    "apertado":  ("#2563EB", "#2259DD", "#1D4ED8", "#1A45C2", "#172F6E", "#FFFFFF"),
    "desligado": ESTILO_BOTAO["desligado"],
}

FRASES = {
    "ia": ["Ligando a inteligência artificial...", "Preparando tudo..."],
    "conferindo": ["Conferindo se está tudo pronto..."],
    "transcrevendo": ["Ouvindo tudo o que foi falado...", "Anotando cada palavra...",
                      "Prestando atenção no vídeo..."],
    "escolhendo": ["Procurando as melhores partes...", "A IA está assistindo e dando notas...",
                   "Escolhendo os melhores momentos..."],
    "gerando": ["Deixando o vídeo em pé para o celular...", "Colocando as legendas...",
                "Seguindo o rosto de quem está falando...", "Fazendo as capas..."],
}
ETAPAS = ["Ouvir", "Escolher", "Montar"]
# Gameplay (jogo quase sem fala): a IA assiste as imagens em vez de ouvir (gameplay.py)
FRASES_GAMEPLAY = dict(FRASES, **{
    "transcrevendo": ["Assistindo a gameplay...", "Medindo a ação e o som de cada segundo...",
                      "A IA está olhando cada cena e dando notas..."],
    "escolhendo": ["Escolhendo os melhores momentos...", "Escrevendo os ganchos...",
                   "Procurando gráficos bonitos e ação..."],
    "gerando": ["Deixando o jogo em tela cheia, em pé...", "Colocando o gancho no começo...",
                "Fazendo as capas..."],
})
ETAPAS_GAMEPLAY = ["Assistir", "Escolher", "Montar"]
TIPOS = [("fala", "Com fala (podcast, entrevista, live falada)"),
         ("gameplay", "Gameplay (jogo, quase sem fala)")]

ESCALA = 1.0  # tela com zoom (125%, 150%...): calculada quando a janela abre


def px(n):
    return int(round(n * ESCALA))


def fonte(tam=10, peso="normal"):  # Segoe UI: a letra do Windows desde o Vista
    return ({"normal": "Segoe UI", "semi": "Segoe UI Semibold"}[peso], tam)


def registrar_erro(texto):
    try:
        ARQ_ERROS.parent.mkdir(exist_ok=True)
        with open(ARQ_ERROS, "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%d/%m/%Y %H:%M:%S')}]\n{texto}\n")
    except Exception:
        pass


AUMID = "NextLevelPC.pup_cortes"  # a "identidade" do app no Windows (barra de tarefas)


def identidade_windows():
    """O app roda no pythonw.exe, entao o Windows o agruparia como "Python"
    (com a logo do Python na barra de tarefas). Com uma identidade propria,
    a barra mostra o icone da janela: a logo da loja. Precisa vir antes de
    abrir a janela."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
    except Exception:
        pass


def preparar_fixar(raiz):
    """Para "Fixar na barra de tarefas" abrir o pup_cortes.exe (com a logo)
    e nao o Python sozinho: grava na janela o comando, o nome e o icone de
    reabrir (propriedades System.AppUserModel.* do Windows)."""
    exe = cortes.BASE / "pup_cortes.exe"
    if os.name != "nt" or not exe.exists():
        return
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                        ("d4", ctypes.c_ubyte * 8)]

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        class PROPVARIANT(ctypes.Structure):  # so o pedaco usado aqui: texto (VT_LPWSTR)
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                        ("r3", ctypes.c_ushort), ("valor", ctypes.c_void_p), ("resto", ctypes.c_void_p)]

        def guid(texto):
            g = GUID()
            ctypes.oledll.ole32.CLSIDFromString(texto, ctypes.byref(g))
            return g

        hwnd = ctypes.windll.user32.GetParent(raiz.winfo_id())  # a moldura da janela, nao o miolo do Tk
        loja = ctypes.c_void_p()
        ctypes.oledll.shell32.SHGetPropertyStoreForWindow(
            wintypes.HWND(hwnd), ctypes.byref(guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")), ctypes.byref(loja))
        tabela = ctypes.cast(loja, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        gravar_valor = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                          ctypes.POINTER(PROPVARIANT))(tabela[6])   # IPropertyStore::SetValue
        confirmar = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(tabela[7])   # ::Commit
        soltar = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(tabela[2])      # ::Release
        grupo_props = guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
        textos = []  # o texto precisa existir ate o Commit
        try:
            for pid, texto in ((5, AUMID),            # System.AppUserModel.ID
                               (2, f'"{exe}"'),       # RelaunchCommand
                               (4, NOME),             # RelaunchDisplayNameResource
                               (3, f"{exe},0")):      # RelaunchIconResource (o icone dentro do .exe)
                buf = ctypes.create_unicode_buffer(texto)
                textos.append(buf)
                valor = PROPVARIANT(vt=31, valor=ctypes.cast(buf, ctypes.c_void_p).value)
                gravar_valor(loja, ctypes.byref(PROPERTYKEY(grupo_props, pid)), ctypes.byref(valor))
            confirmar(loja)
        finally:
            soltar(loja)
    except Exception:
        registrar_erro(traceback.format_exc())


def abrir(caminho):
    """Abre um arquivo ou pasta com o programa padrao do Windows."""
    try:
        os.startfile(str(caminho))
    except Exception as e:
        messagebox.showinfo(NOME, f"Não consegui abrir:\n{caminho}\n\n{e}")


# ----------------------------------------------------------------------------
# Andamento
# ----------------------------------------------------------------------------

def progresso(st):
    """(agora, teto) em %: onde o corte esta, e ate onde a barra pode andar
    sozinha enquanto a etapa nao avanca - assim ela nunca parece travada."""
    etapa = st.get("etapa")
    if etapa == "transcrevendo":
        pct = st.get("pct") or 0
        return 5 + 0.45 * pct, 5 + 0.45 * min(100, pct + 5)
    if etapa == "escolhendo":
        partes, parte = st.get("partes") or 0, st.get("parte") or 0
        if not partes:
            return 50, 52
        return 50 + 15 * max(0, parte - 1) / partes, 50 + 15 * parte / partes
    if etapa == "gerando":
        total, corte = st.get("cortes_total") or 0, st.get("corte") or 0
        if not total:
            return 65, 66
        return 65 + 35 * max(0, corte - 1) / total, 65 + 35 * corte / total
    return 2, 5


def tipo_salvo(cfg):
    return "gameplay" if cfg["geral"].get("tipo_video", "fala").strip().lower() == "gameplay" else "fala"


def numero_da_etapa(st):
    return {"transcrevendo": 1, "escolhendo": 2, "gerando": 3}.get(st.get("etapa"), 0)


# ----------------------------------------------------------------------------
# Miniaturas (rodam fora da tela, em segundo plano)
# ----------------------------------------------------------------------------

def quadro_do_video(caminho, segundo, largura=480):
    """Uma imagem do video tirada pelo FFmpeg (guardada em logs/miniaturas)."""
    if Image is None or not cortes.FFMPEG:
        return None
    try:
        caminho = Path(caminho)
        info = caminho.stat()
        chave = hashlib.sha1(f"{caminho}|{info.st_mtime}|{info.st_size}|{segundo:.1f}|{largura}"
                             .encode("utf-8")).hexdigest()[:20]
        destino = PASTA_MINIATURAS / f"{chave}.jpg"
        if not destino.exists():
            PASTA_MINIATURAS.mkdir(parents=True, exist_ok=True)
            subprocess.run([cortes.FFMPEG, "-v", "error", "-y", "-ss", f"{segundo:.2f}", "-i", str(caminho),
                            "-frames:v", "1", "-vf", f"scale={largura}:-2", "-q:v", "4", str(destino)],
                           capture_output=True, timeout=120, creationflags=controle.sem_janela())
        if destino.exists():
            with Image.open(destino) as img:
                return img.convert("RGB")
    except Exception:
        pass
    return None


def imagem_do_corte(item):
    """A capa do corte; se ele nao tiver capa, um quadro do proprio corte."""
    if Image is None:
        return None
    if item.get("capa"):
        try:
            with Image.open(item["capa"]) as img:
                return img.convert("RGB")
        except Exception:
            pass
    return quadro_do_video(item["arquivo"], 1.5, 360)


def encaixar(img, w, h):
    """Corta e redimensiona para preencher w x h."""
    iw, ih = img.size
    esc = max(w / iw, h / ih)
    img = img.resize((max(1, round(iw * esc)), max(1, round(ih * esc))), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def redondo(img, tam, fundo=(255, 255, 255)):
    """Recorta a imagem num circulo (com borda lisa), sobre o fundo branco da tela."""
    img = encaixar(img.convert("RGB"), tam, tam)
    mascara = Image.new("L", (tam * 4, tam * 4), 0)
    ImageDraw.Draw(mascara).ellipse((0, 0, tam * 4 - 1, tam * 4 - 1), fill=255)
    saida = Image.new("RGB", (tam, tam), fundo)
    saida.paste(img, (0, 0), mascara.resize((tam, tam), Image.LANCZOS))
    return saida


def avatar(conta, tam):
    """Foto da conta (guardada em logs/miniaturas). Sem foto: circulo na cor
    da rede com a inicial do nome."""
    if Image is None:
        return None
    url = conta.get("foto") or ""
    if url:
        try:
            destino = PASTA_MINIATURAS / f"conta_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:20]}.jpg"
            if not destino.exists():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    dados = r.read()
                PASTA_MINIATURAS.mkdir(parents=True, exist_ok=True)
                Image.open(io.BytesIO(dados)).convert("RGB").save(destino, quality=90)
            with Image.open(destino) as img:
                return redondo(img, tam)
        except Exception:
            pass
    cor = COR_REDE.get(conta.get("rede"), AZUL)
    img = Image.new("RGB", (tam * 4, tam * 4), cor)
    letra = (redes.nome_conta(conta).lstrip("@")[:1] or "?").upper()
    try:
        f = ImageFont.truetype("arialbd.ttf", tam * 2)
    except Exception:
        f = ImageFont.load_default()
    ImageDraw.Draw(img).text((tam * 2, tam * 2), letra, fill="#FFFFFF", font=f, anchor="mm")
    return redondo(img, tam)


def carregar_json(arq, padrao):
    try:
        return json.loads(Path(arq).read_text(encoding="utf-8"))
    except Exception:
        return padrao


def gravar_json(arq, dados):
    try:
        Path(arq).parent.mkdir(exist_ok=True)
        Path(arq).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Pecas da tela (estilo Windows 7)
# ----------------------------------------------------------------------------

def misturar(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def degrade(cv, x1, y1, x2, y2, cores):
    """Pinta um degrade vertical linha por linha. `cores`: (topo, meio de cima,
    meio de baixo, base) - o "brilho" de vidro do Windows 7 vem do salto no meio."""
    topo, meio1, meio2, base = cores
    altura = max(1, y2 - y1)
    meio = y1 + altura // 2
    for y in range(y1, y2):
        if y < meio:
            cor = misturar(topo, meio1, (y - y1) / max(1, meio - y1 - 1))
        else:
            cor = misturar(meio2, base, (y - meio) / max(1, y2 - meio - 1))
        cv.create_line(x1, y, x2, y, fill=cor)


def borda_cortada(cv, x1, y1, x2, y2, cor):
    """Borda de 1 px com os cantos "cortados", como nos botoes do Windows."""
    cv.create_line(x1 + 1, y1, x2 - 1, y1, fill=cor)
    cv.create_line(x1 + 1, y2 - 1, x2 - 1, y2 - 1, fill=cor)
    cv.create_line(x1, y1 + 1, x1, y2 - 1, fill=cor)
    cv.create_line(x2 - 1, y1 + 1, x2 - 1, y2 - 1, fill=cor)


# Icones dos botoes: letras das fontes de icones que ja vem no Windows 10/11
# (Segoe Fluent Icons no 11, Segoe MDL2 Assets no 10). Sem a fonte, o botao fica so com o texto.
ICONES = {
    "ajustes": "\uE713",    # engrenagem
    "voltar": "\uE72B",     # seta para a esquerda
    "pasta": "\uE838",      # pasta aberta
    "procurar": "\uE8B7",   # pasta
    "assistir": "\uE768",   # play
    "copiar": "\uE8C8",
    "baixar": "\uE896",
    "parar": "\uE71A",
    "atualizar": "\uE72C",
    "agendar": "\uE787",    # calendario
    "detalhes": "\uE8A5",   # documento
    "cortar": "\uE8C6",     # tesoura
    "cancelar": "\uE711",   # X
    "salvar": "\uE74E",
    "apagar": "\uE74D",     # lixeira
    "novo": "\uE710",       # +
    "ok": "\uE73E",         # visto
    "ligar": "\uE71B",      # corrente (ligar ao site)
    "desligar": "\uE7E8",   # botao de desligar
    "testar": "\uE9D9",     # diagnostico
    "carregar": "\uE945",   # raio
    "contas": "\uE77B",     # pessoa
    "abrir": "\uE8A7",      # abrir em outra janela
    "enviar": "\uE724",     # aviao de papel
    "editar": "\uE70F",     # lapis
}

# Icone de cada botao pelo texto dele (assim nao precisa passar icone= em todo lugar).
# Textos que mudam (ex.: "Agendar 3 cortes") acham o icone pela primeira palavra.
ICONE_DO_TEXTO = {
    "Ajustes...": "ajustes", "Fazer cortes": "cortar", "Procurar...": "procurar",
    "Ver os cortes": "assistir", "Baixar": "baixar", "Parar": "parar", "Voltar": "voltar",
    "Abrir a pasta": "pasta", "Programar todos...": "agendar", "Fazer outro vídeo": "novo",
    "Assistir": "assistir", "Copiar": "copiar", "Programar postagem": "agendar",
    "Ver detalhes": "detalhes", "Tentar de novo": "atualizar", "Ligar ao site...": "ligar",
    "Cancelar": "cancelar", "Ligar": "ligar", "Abrir de novo": "abrir", "Salvar": "salvar",
    "Apagar nicho": "apagar", "Pôr na lista": "novo", "Tirar da lista": "apagar",
    "Atualizar": "atualizar", "Novo nicho...": "novo", "Abrir o painel...": "abrir",
    "Mudar nicho...": "editar", "Conectar": "ligar", "Desconectar": "desligar",
    "Conectar de novo": "ligar", "Nova postagem...": "novo", "Postar agora": "enviar",
    "Mudar...": "editar", "Continuar": "ok", "Agendar": "agendar", "Conectar contas...": "contas",
    "Atualizar o baixador": "atualizar", "Carregar": "carregar", "Descarregar": "desligar",
    "Testar": "testar",
}


def icone_do_texto(texto):
    return ICONE_DO_TEXTO.get(texto) or ICONE_DO_TEXTO.get((texto or "").split(" ")[0])
_FONTE_ICONES = []  # [nome da fonte ou None], descoberta na primeira vez


def fonte_icones():
    if not _FONTE_ICONES:
        try:
            from tkinter import font as tkfont
            familias = set(tkfont.families())
        except Exception:  # janela ainda nao existe: tenta de novo na proxima
            return None
        _FONTE_ICONES.append(next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in familias), None))
    return _FONTE_ICONES[0]


_FONTES_MEDIDAS = {}


def medir(letra, texto):
    """Largura em pixels de `texto` na fonte (familia, tamanho)."""
    if letra not in _FONTES_MEDIDAS:
        from tkinter import font as tkfont
        _FONTES_MEDIDAS[letra] = tkfont.Font(family=letra[0], size=letra[1])
    return _FONTES_MEDIDAS[letra].measure(texto)


class Botao(tk.Canvas):
    """Botao do Windows 7: cinza com degrade, azulado com o mouse em cima.
    `principal=True` e o botao da acao principal, no azul do site.
    `icone` = chave do ICONES (aparece antes do texto; o botao cresce para caber).
    Sem `icone`, usa o do ICONE_DO_TEXTO; `icone=False` deixa sem."""

    def __init__(self, pai, texto, comando, largura=110, altura=30, tam=10, principal=False, icone=None):
        if icone is None:
            icone = icone_do_texto(texto)
        self.icone = ICONES.get(icone) if icone and fonte_icones() else None
        if self.icone:
            largura += tam * 2 + 2
        super().__init__(pai, width=px(largura), height=px(altura), bg=pai["bg"],
                         highlightthickness=0, cursor="hand2")
        self.texto, self.comando, self.tam = texto, comando, tam
        self.estilos = ESTILO_PRINCIPAL if principal else ESTILO_BOTAO
        self.ligado, self.em_cima, self.apertado = True, False, False
        self.bind("<Enter>", lambda e: self._estado(em_cima=True))
        self.bind("<Leave>", lambda e: self._estado(em_cima=False, apertado=False))
        self.bind("<ButtonPress-1>", lambda e: self._estado(apertado=True))
        self.bind("<ButtonRelease-1>", self._clique)
        self.desenhar()

    def _estado(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.desenhar()

    def _clique(self, e):
        estava = self.apertado
        self._estado(apertado=False)
        if (estava and self.ligado and 0 <= e.x <= self.winfo_width()
                and 0 <= e.y <= self.winfo_height()):
            self.comando()

    def ativar(self, ligado=True):
        self.ligado = ligado
        self.config(cursor="hand2" if ligado else "arrow")
        self.desenhar()

    def mudar(self, texto):
        self.texto = texto
        self.desenhar()

    def desenhar(self):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        if not self.ligado:
            estado = "desligado"
        elif self.apertado:
            estado = "apertado"
        elif self.em_cima:
            estado = "em_cima"
        else:
            estado = "normal"
        *cores, borda, letra = self.estilos[estado]
        degrade(self, 1, 1, w - 1, h - 1, cores)
        if estado != "desligado":  # filete claro por dentro, o "vidro"
            self.create_line(2, 1, w - 2, 1, fill=misturar(cores[0], "#FFFFFF", 0.6))
        borda_cortada(self, 0, 0, w, h, borda)
        letra_texto = fonte(self.tam, "semi" if self.estilos is ESTILO_PRINCIPAL else "normal")
        if not self.icone:
            self.create_text(w / 2, h / 2, text=self.texto, fill=letra, font=letra_texto)
            return
        # icone + espaco + texto, o conjunto centralizado no botao
        f_ic = (fonte_icones(), self.tam)
        larg_ic = medir(f_ic, self.icone)
        larg_tx = medir(letra_texto, self.texto) if self.texto else 0
        espaco = px(7) if self.texto else 0
        x = (w - (larg_ic + espaco + larg_tx)) / 2
        self.create_text(x, h / 2 + 1, text=self.icone, fill=letra, font=f_ic, anchor="w")
        if self.texto:
            self.create_text(x + larg_ic + espaco, h / 2, text=self.texto, fill=letra, font=letra_texto, anchor="w")


class EscolhaQtd(tk.Frame):
    """Quantos cortes: botoes de opcao (radio) do Windows."""

    def __init__(self, pai, opcoes, valor):
        super().__init__(pai, bg=pai["bg"])
        self.var = tk.IntVar(value=valor)
        self.botoes = {}
        for op in opcoes:
            b = ttk.Radiobutton(self, text=str(op), value=op, variable=self.var, style="Branco.TRadiobutton")
            b.pack(side="left", padx=(0, px(14)))
            self.botoes[op] = b

    @property
    def valor(self):
        return self.var.get()

    def mudar(self, valor, avisar=False):
        self.var.set(valor)


class Barra(tk.Canvas):
    """Barra de progresso do Windows 7, no azul do site."""

    def __init__(self, pai, largura=520, altura=22):
        super().__init__(pai, width=px(largura), height=px(altura), bg=pai["bg"], highlightthickness=0)
        self.valor = 0.0
        self.desenhar()

    def mudar(self, valor):
        self.valor = max(0.0, min(100.0, valor))
        self.desenhar()

    def desenhar(self):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        degrade(self, 1, 1, w - 1, h - 1, ("#F3F3F3", "#EAEAEA", "#DEDEDE", "#E8E8E8"))
        cheio = int((w - 2) * self.valor / 100)
        if cheio > 0:
            degrade(self, 1, 1, 1 + cheio, h - 1, ("#9CC1FB", "#6A9EF7", "#2563EB", "#3B79F0"))
        borda_cortada(self, 0, 0, w, h, "#BCBCBC")


class Passos(tk.Frame):
    """Ouvir > Escolher > Montar, como a lista de etapas de um assistente."""

    def __init__(self, pai):
        super().__init__(pai, bg=pai["bg"])
        self.rotulos = []
        for i, nome in enumerate(ETAPAS):
            if i:
                tk.Label(self, text="›", bg=pai["bg"], fg=BORDA, font=fonte(14)).pack(side="left", padx=px(10))
            r = tk.Label(self, bg=pai["bg"], font=fonte(11))
            r.pack(side="left")
            self.rotulos.append(r)
        self.atual = -1
        self.mudar(0)

    def rotular(self, nomes):
        """Troca os nomes das etapas (gameplay: Assistir em vez de Ouvir)."""
        if list(nomes) != list(getattr(self, "nomes", ETAPAS)):
            self.nomes = list(nomes)
            atual, self.atual = self.atual, -1
            self.mudar(atual)

    def mudar(self, atual):
        if atual == self.atual:
            return
        self.atual = atual
        for i, (r, nome) in enumerate(zip(self.rotulos, getattr(self, "nomes", ETAPAS)), 1):
            if atual > i:
                r.config(text=f"✔ {nome}", fg=VERDE, font=fonte(11))
            elif atual == i:
                r.config(text=f"{i}. {nome}", fg=AZUL_ESCURO, font=fonte(11, "semi"))
            else:
                r.config(text=f"{i}. {nome}", fg=APAGADO, font=fonte(11))


class Rolagem(tk.Frame):
    """Area branca com borda e barra de rolagem (a roda do mouse e ligada pelo App)."""

    def __init__(self, pai):
        super().__init__(pai, bg=BRANCO, highlightthickness=1, highlightbackground=BORDA)
        self.cv = tk.Canvas(self, bg=BRANCO, highlightthickness=0)
        barra = ttk.Scrollbar(self, orient="vertical", command=self.cv.yview)
        self.dentro = tk.Frame(self.cv, bg=BRANCO)
        self.janela = self.cv.create_window((0, 0), window=self.dentro, anchor="nw")
        self.cv.configure(yscrollcommand=barra.set)
        self.cv.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.dentro.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self.janela, width=e.width))

    def rolar(self, delta):
        if self.dentro.winfo_height() > self.cv.winfo_height():
            self.cv.yview_scroll(int(-delta / 120) or (-1 if delta > 0 else 1), "units")

    def topo(self):
        self.cv.yview_moveto(0)


def rotulo(pai, texto="", tam=10, peso="normal", cor=TEXTO, **kw):
    return tk.Label(pai, text=texto, bg=pai["bg"], fg=cor, font=fonte(tam, peso), **kw)


def instrucao(pai, texto):
    """A "instrucao principal" dos dialogos do Windows 7: azul, maior, no topo."""
    r = tk.Label(pai, text=texto, bg=BRANCO, fg=AZUL_ESCURO, font=fonte(14), anchor="w", justify="left")
    r.pack(fill="x", padx=px(24), pady=(px(16), px(8)))
    return r


def grupo(pai, titulo, padx=24, mostrar=True):
    """Caixa de grupo do Windows (moldura fina com o titulo em cima). Devolve
    o miolo; a moldura e o `.master` dele (para esconder e mostrar)."""
    g = ttk.LabelFrame(pai, text=f" {titulo} ", style="Branco.TLabelframe", padding=px(12))
    if mostrar:
        g.pack(fill="x", padx=px(padx), pady=(0, px(12)))
    dentro = tk.Frame(g, bg=BRANCO)
    dentro.pack(fill="both", expand=True)
    return dentro


def link(pai, texto, comando, tam=9, cor=None):
    """Texto azul sublinhado que funciona como botao (como nos dialogos do Windows)."""
    r = tk.Label(pai, text=texto, bg=pai["bg"], fg=cor or AZUL, cursor="hand2",
                 font=("Segoe UI", tam, "underline"))
    r.bind("<Button-1>", lambda e: comando())
    return r


def limpar(quadro):
    for w in quadro.winfo_children():
        w.destroy()


class EscolhaHorario(tk.Frame):
    """Dia (Hoje, Amanha, qua 22/10...) + hora e minuto, com caixas do Windows."""

    def __init__(self, pai, ao_mudar=None):
        super().__init__(pai, bg=pai["bg"])
        hoje = datetime.date.today()
        self.datas = [hoje + datetime.timedelta(days=i) for i in range(120)]
        nomes = []
        for i, d in enumerate(self.datas):
            dia = f"{d:%d/%m}"
            nomes.append(f"Hoje ({dia})" if i == 0 else f"Amanhã ({dia})" if i == 1
                         else f"{redes.DIAS[d.weekday()]} {dia}")
        self.dia = ttk.Combobox(self, values=nomes, state="readonly", width=13, font=fonte(10))
        self.dia.pack(side="left")
        rotulo(self, " às ").pack(side="left")
        self.hora = ttk.Spinbox(self, from_=0, to=23, width=3, format="%02.0f", wrap=True, font=fonte(10))
        self.hora.pack(side="left")
        rotulo(self, ":").pack(side="left")
        self.minuto = ttk.Spinbox(self, from_=0, to=55, increment=5, width=3, format="%02.0f", wrap=True,
                                  font=fonte(10))
        self.minuto.pack(side="left")
        if ao_mudar:
            self.dia.bind("<<ComboboxSelected>>", lambda e: ao_mudar(), add="+")
            for w in (self.hora, self.minuto):
                w.configure(command=ao_mudar)
                w.bind("<KeyRelease>", lambda e: ao_mudar(), add="+")
        self.definir(self.sugestao())

    @staticmethod
    def sugestao():
        """Proximo horario bom de postar (12h, 18h ou 21h), com pelo menos 15 min de folga."""
        agora = datetime.datetime.now()
        for dias in (0, 1):
            d = agora.date() + datetime.timedelta(days=dias)
            for h in (12, 18, 21):
                t = datetime.datetime.combine(d, datetime.time(h, 0))
                if t >= agora + datetime.timedelta(minutes=15):
                    return t.timestamp()
        return (agora + datetime.timedelta(hours=1)).timestamp()

    def definir(self, epoch):
        t = datetime.datetime.fromtimestamp(epoch)
        self.dia.current(max(0, min(len(self.datas) - 1, (t.date() - self.datas[0]).days)))
        self.hora.set(f"{t.hour:02d}")
        self.minuto.set(f"{t.minute:02d}")

    def epoch(self):
        """O horario escolhido (epoch), ou None se a hora digitada nao vale."""
        try:
            h, m = int(self.hora.get()), int(self.minuto.get())
            if not (0 <= h <= 23 and 0 <= m <= 59) or self.dia.current() < 0:
                return None
            return datetime.datetime.combine(self.datas[self.dia.current()], datetime.time(h, m)).timestamp()
        except (ValueError, TypeError):
            return None

    def habilitar(self, ligado):
        self.dia.configure(state="readonly" if ligado else "disabled")
        for w in (self.hora, self.minuto):
            w.configure(state="normal" if ligado else "disabled")


def barra_de_comandos(pai):
    """A faixa cinza com os botoes, embaixo dos dialogos do Windows 7."""
    faixa = tk.Frame(pai, bg=FACE)
    faixa.pack(side="bottom", fill="x")
    tk.Frame(faixa, bg=LINHA, height=1).pack(side="top", fill="x")
    dentro = tk.Frame(faixa, bg=FACE)
    dentro.pack(fill="x", padx=px(16), pady=px(11))
    return dentro


def miniatura(pai, w, h):
    """Quadro com borda fina para uma miniatura (antes de a imagem carregar,
    fica so o fundo cinza claro)."""
    return tk.Label(pai, bg="#F3F3F3", highlightthickness=1, highlightbackground=BORDA, bd=0)


def destacar_ao_passar(quadro, ao_clicar):
    """Item que acende em azul claro com o mouse em cima, como no Explorer."""
    todos = [quadro] + quadro.winfo_children()

    def pintar(cor, borda):
        quadro.config(highlightbackground=borda)
        for w in todos:
            if isinstance(w, tk.Label) and w.cget("image") == "" or w is quadro:
                w.config(bg=cor)

    quadro.config(highlightthickness=1, highlightbackground=BRANCO, cursor="hand2")
    for w in todos:
        w.bind("<Enter>", lambda e: pintar(SELECAO, SELECAO_BORDA), add="+")
        w.bind("<Leave>", lambda e: pintar(BRANCO, BRANCO), add="+")
        w.bind("<Button-1>", lambda e: ao_clicar(), add="+")


# ----------------------------------------------------------------------------
# Telas
# ----------------------------------------------------------------------------

class Tela(tk.Frame):
    def __init__(self, app):
        super().__init__(app.meio, bg=BRANCO)
        self.app = app
        self.imagens = []   # o Tk esquece imagem sem referencia

    def mostrar(self, **kw):
        pass

    def ao_sair(self):
        """Chamado quando outra tela toma o lugar desta."""
        pass

    def foto(self, img):
        foto = ImageTk.PhotoImage(img)
        self.imagens.append(foto)
        return foto

    def vazio(self, w, h):
        """Imagem em branco do tamanho certo, para guardar o lugar da miniatura
        (sem imagem, o Label mede em letras, nao em pixels)."""
        foto = tk.PhotoImage(width=w, height=h)
        self.imagens.append(foto)
        return foto


class TelaInicio(Tela):
    def __init__(self, app):
        super().__init__(app)
        self.video = None
        self.info = None

        comandos = barra_de_comandos(self)
        Botao(comandos, "Ajustes", app.abrir_ajustes, largura=90, icone="ajustes").pack(side="left")
        self.fazer = Botao(comandos, "Fazer cortes", self.fazer_cortes, largura=170, altura=36, tam=11,
                           principal=True)
        self.fazer.pack(side="right")

        instrucao(self, "Escolha um vídeo (ou cole o link) e clique em Fazer cortes")

        # --- video -----------------------------------------------------------------------
        caixa = grupo(self, "Vídeo")
        self.previa = tk.Canvas(caixa, width=px(256), height=px(144), bg="#F3F3F3", cursor="hand2",
                                highlightthickness=1, highlightbackground=BORDA)
        self.previa.pack(side="left")
        self.previa.bind("<Button-1>", lambda e: self.escolher())
        lado = tk.Frame(caixa, bg=BRANCO)
        lado.pack(side="left", fill="both", expand=True, padx=(px(18), 0))
        self.nome = rotulo(lado, "Nenhum vídeo escolhido", 12, "semi", wraplength=px(500), justify="left")
        self.nome.pack(anchor="w")
        self.detalhe = rotulo(lado, "Clique em Procurar para escolher o vídeo.", 10, cor=APAGADO,
                              wraplength=px(500), justify="left")
        self.detalhe.pack(anchor="w", pady=(px(2), px(12)))
        botoes = tk.Frame(lado, bg=BRANCO)
        botoes.pack(anchor="w")
        Botao(botoes, "Procurar...", self.escolher, largura=110).pack(side="left")
        self.ver = Botao(botoes, "Ver os cortes", self.ver_cortes, largura=120)

        # --- ou baixar pelo link (yt-dlp) ---------------------------------------------------
        rotulo(lado, "Ou cole o link do vídeo (YouTube, Instagram, TikTok, Kwai, Twitch...):", 9,
               cor=APAGADO).pack(anchor="w", pady=(px(14), px(3)))
        linha_link = tk.Frame(lado, bg=BRANCO)
        linha_link.pack(anchor="w")
        self.link = ttk.Entry(linha_link, font=fonte(10), width=44)
        self.link.pack(side="left", ipady=px(2))
        self.link.bind("<Return>", lambda e: self.baixar())
        self.link.bind("<Button-3>", self.menu_colar)
        self.botao_baixar = Botao(linha_link, "Baixar", self.baixar, largura=90)
        self.botao_baixar.pack(side="left", padx=(px(8), 0))
        self.download = tk.Frame(lado, bg=BRANCO)  # aparece só enquanto baixa
        self.barra_download = Barra(self.download, largura=300, altura=14)
        self.barra_download.pack(side="left")
        self.texto_download = rotulo(self.download, "", 9, cor=APAGADO)
        self.texto_download.pack(side="left", padx=(px(8), 0))
        link(self.download, "Cancelar", self.cancelar_download).pack(side="left", padx=(px(10), 0))
        self.parar_download = None

        # --- tipo de video: fala (ouve) ou gameplay (a IA assiste as imagens) --------------
        tipo_caixa = grupo(self, "Tipo de vídeo")
        linha_tipo = tk.Frame(tipo_caixa, bg=BRANCO)
        linha_tipo.pack(anchor="w")
        self.tipo = tk.StringVar(value=tipo_salvo(app.cfg))
        for valor, texto in TIPOS:
            ttk.Radiobutton(linha_tipo, text=texto, value=valor, variable=self.tipo, style="Branco.TRadiobutton",
                            command=self.mudou_tipo).pack(side="left", padx=(0, px(18)))
        self.linha_jogo = tk.Frame(tipo_caixa, bg=BRANCO)  # aparece so no modo gameplay
        rotulo(self.linha_jogo, "Nome do jogo (ajuda a IA a escrever os ganchos):", 9,
               cor=APAGADO).pack(side="left")
        self.jogo = ttk.Entry(self.linha_jogo, font=fonte(10), width=22)
        self.jogo.insert(0, app.cfg["gameplay"].get("jogo", ""))
        self.jogo.pack(side="left", padx=(px(8), 0), ipady=px(1))
        self.jogo.bind("<FocusOut>", lambda e: self.salvar_jogo())
        self.jogo.bind("<Return>", lambda e: self.salvar_jogo())
        self.dica_tipo = rotulo(tipo_caixa, "", 9, cor=APAGADO, wraplength=px(760), justify="left")
        self.mostrar_tipo()

        # --- opcoes ------------------------------------------------------------------------
        opcoes = grupo(self, "Opções")
        rotulo(opcoes, "Quantos cortes:").pack(side="left", padx=(0, px(14)))
        padrao = int(app.cfg["geral"]["quantidade_cortes"] or 5)
        self.qtd = EscolhaQtd(opcoes, sorted(set(QTDS + [padrao])), padrao)
        self.qtd.pack(side="left")

        # --- meus cortes / como funciona ---------------------------------------------------
        self.recentes_moldura = ttk.LabelFrame(self, text=" Meus cortes ", style="Branco.TLabelframe",
                                               padding=px(10))
        self.recentes_moldura.pack(fill="x", padx=px(24))
        self.recentes = tk.Frame(self.recentes_moldura, bg=BRANCO)
        self.recentes.pack(fill="x")

    # ------------------------------------------------------------------------------
    def mostrar(self, video=None, **kw):
        self.imagens.clear()
        if video:
            self.usar_video(Path(video))
        else:
            self.video, self.info = None, None
            self.nome.config(text="Nenhum vídeo escolhido")
            self.detalhe.config(text="Clique em Procurar ou cole o link do vídeo.")
            self.desenhar_previa(None)
            self.atualizar_botoes()
        self.montar_recentes()
        self.app.atualizar_status()

    def desenhar_previa(self, img):
        cv = self.previa
        cv.delete("all")
        w, h = int(cv["width"]), int(cv["height"])
        if img is not None:
            cv.create_image(0, 0, anchor="nw", image=self.foto(encaixar(img, w, h)))
            return
        cv.create_text(w / 2, h / 2, text="Nenhum vídeo", fill=APAGADO, font=fonte(10))

    def escolher(self):
        tipos = " ".join("*" + e for e in sorted(cortes.EXTENSOES))
        inicial = cortes.PASTA_ENTRADA if cortes.PASTA_ENTRADA.exists() else Path.home()
        caminho = filedialog.askopenfilename(parent=self.app.raiz, title="Escolha o vídeo para cortar",
                                             initialdir=str(inicial),
                                             filetypes=[("Vídeos", tipos), ("Todos os arquivos", "*.*")])
        if caminho:
            self.usar_video(Path(caminho))

    def usar_video(self, video):
        if not video.exists() or video.suffix.lower() not in cortes.EXTENSOES:
            messagebox.showinfo(NOME, f"Esse arquivo não é um vídeo que eu sei cortar:\n{video.name}")
            return
        self.video, self.info = video, None
        self.nome.config(text=video.name)
        self.detalhe.config(text="Lendo o vídeo...")
        self.desenhar_previa(None)
        self.atualizar_botoes()

        def ler():
            info = cortes.info_video(video)
            return info, quadro_do_video(video, min(30.0, info["dur"] / 3), 640)

        def pronto(resultado):
            if self.video != video:
                return
            if isinstance(resultado, Exception):
                self.video = None
                self.nome.config(text="Não consegui abrir esse vídeo")
                self.detalhe.config(text=formatar.texto_erro(resultado)[:300])
                self.atualizar_botoes()
                return
            self.info, img = resultado
            self.detalhe_video()
            self.desenhar_previa(img)
            self.atualizar_botoes()
        self.app.em_segundo_plano(ler, pronto)

    # --- baixar pelo link ----------------------------------------------------------------
    def menu_colar(self, e):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Colar", command=lambda: self.link.event_generate("<<Paste>>"))
        menu.tk_popup(e.x_root, e.y_root)

    def baixar(self):
        if self.parar_download is not None:
            return  # já está baixando
        url = controle.achar_link(self.link.get())
        if not url:  # campo vazio: tenta o link que a pessoa acabou de copiar
            try:
                url = controle.achar_link(self.app.raiz.clipboard_get())
            except tk.TclError:
                url = ""
            if url:
                self.link.delete(0, "end")
                self.link.insert(0, url)
        if not url:
            messagebox.showinfo(NOME, "Cole o link do vídeo no campo (ele começa com https://).\n\n"
                                      "No YouTube: clique em Compartilhar e depois em Copiar.",
                                parent=self.app.raiz)
            return
        parar = self.parar_download = threading.Event()
        self.botao_baixar.ativar(False)
        self.barra_download.mudar(0)
        self.texto_download.config(text="Procurando o vídeo...")
        self.download.pack(anchor="w", pady=(px(6), 0))
        altura = controle.qualidade_download(self.app.cfg)

        def progresso(etapa, pct, titulo):
            self.app.fila.put((self._andamento_download, (etapa, pct, titulo)))
        self.app.em_segundo_plano(
            lambda: controle.baixar_video(url, cortes.PASTA_ENTRADA, altura, progresso, parar),
            lambda resultado: self._fim_download(resultado, parar))

    def _andamento_download(self, dados):
        etapa, pct, titulo = dados
        if etapa == "video":
            valor, texto = pct * 0.85, f"Baixando o vídeo: {pct:.0f}%"
        elif etapa == "audio":
            valor, texto = 85 + pct * 0.13, f"Baixando o som: {pct:.0f}%"
        elif etapa == "juntando":
            valor, texto = 99, "Juntando vídeo e som..."
        else:
            valor, texto = 1, "Procurando o vídeo..."
        self.barra_download.mudar(valor)
        self.texto_download.config(text=texto)
        if titulo and self.video is None:
            self.nome.config(text=titulo)
            self.detalhe.config(text="Baixando...")

    def _fim_download(self, resultado, parar):
        if parar is not self.parar_download:
            return  # resposta de um download antigo
        self.parar_download = None
        self.botao_baixar.ativar(True)
        self.download.pack_forget()
        if isinstance(resultado, Exception):
            if self.video is None:
                self.nome.config(text="Nenhum vídeo escolhido")
                self.detalhe.config(text="Clique em Procurar ou cole o link do vídeo.")
            if isinstance(resultado, controle.DownloadCancelado):
                self.app.aviso_rapido("Download cancelado.")
            elif isinstance(resultado, cortes.ErroAmigavel):
                messagebox.showinfo(NOME, formatar.texto_erro(resultado), parent=self.app.raiz)
            else:
                messagebox.showinfo(NOME, f"Não consegui baixar o vídeo:\n{resultado}", parent=self.app.raiz)
            return
        self.link.delete(0, "end")
        self.usar_video(resultado)
        self.app.aviso_rapido("Vídeo baixado. Agora é só clicar em Fazer cortes.")

    def cancelar_download(self):
        if self.parar_download is not None:
            self.parar_download.set()
            self.texto_download.config(text="Cancelando...")

    def pasta_do_video(self):
        return cortes.PASTA_SAIDA / cortes.nome_seguro(self.video.stem, 60) if self.video else None

    # --- tipo de video ------------------------------------------------------------------
    def mostrar_tipo(self):
        if self.tipo.get() == "gameplay":
            self.linha_jogo.pack(anchor="w", pady=(px(8), 0))
            self.dica_tipo.config(text="A IA assiste o vídeo (gráficos, ação, coisas curiosas), escolhe os "
                                       "trechos e escreve um gancho. Sai em pé, tela cheia, só o jogo, sem "
                                       "marca d'água. Precisa de um modelo com visão (ex.: Qwen3.5).")
        else:
            self.linha_jogo.pack_forget()
            self.dica_tipo.config(text="A IA ouve o que é falado, escolhe os trechos e coloca legenda.")
        self.dica_tipo.pack(anchor="w", pady=(px(6), 0))

    def mudou_tipo(self):
        cortes.salvar_opcao("geral", "tipo_video", self.tipo.get())
        self.app.cfg["geral"]["tipo_video"] = self.tipo.get()
        self.mostrar_tipo()
        self.detalhe_video()
        self.atualizar_botoes()

    def salvar_jogo(self):
        jogo = self.jogo.get().strip()
        if jogo != self.app.cfg["gameplay"].get("jogo", "").strip():
            cortes.salvar_opcao("gameplay", "jogo", jogo)
            self.app.cfg["gameplay"]["jogo"] = jogo

    def detalhe_video(self):
        if not (self.video and self.info):
            return
        partes = [formatar.duracao(self.info["dur"]), f"{self.info['w']}x{self.info['h']}"]
        if not self.info["audio"]:
            partes.append("sem som (no modo Gameplay dá para cortar mesmo assim)" if self.tipo.get() == "gameplay"
                          else "SEM SOM: não dá para cortar (é preciso ouvir o que é falado)")
        self.detalhe.config(text="   •   ".join(partes))

    def atualizar_botoes(self):
        pode = bool(self.info and (self.info.get("audio") or self.tipo.get() == "gameplay"))
        self.fazer.ativar(bool(self.video) and pode)
        pasta = self.pasta_do_video()
        if pasta and (pasta / "POSTAGENS.txt").exists():
            self.fazer.mudar("Fazer de novo")
            self.ver.pack(side="left", padx=(px(8), 0))
        else:
            self.fazer.mudar("Fazer cortes")
            self.ver.pack_forget()

    def fazer_cortes(self):
        self.salvar_jogo()
        self.app.fazer_cortes(self.video, self.qtd.valor, self.tipo.get())

    def ver_cortes(self):
        self.app.ir("pronto", pasta=self.pasta_do_video())

    def montar_recentes(self):
        for w in self.recentes.winfo_children():
            w.destroy()
        pastas = controle.resultados_recentes(4)
        if not pastas:  # primeira vez: explica em 3 passos
            self.recentes_moldura.config(text=" Como funciona ")
            for n, texto in enumerate(["Clique em Procurar ou cole o link de um vídeo comprido (podcast, live, entrevista).",
                                       "Clique em Fazer cortes. A inteligência artificial escolhe as melhores partes.",
                                       "Assista os cortes prontos: eles saem em pé, com legenda e capa."], 1):
                rotulo(self.recentes, f"{n}.  {texto}", 10, cor=TEXTO).pack(anchor="w", pady=px(1))
            return
        self.recentes_moldura.config(text=" Meus cortes ")
        for pasta in pastas:
            self.item_recente(pasta)

    def item_recente(self, pasta):
        item = tk.Frame(self.recentes, bg=BRANCO)
        item.pack(side="left", padx=(0, px(6)))
        img_lbl = miniatura(item, px(45), px(80))
        img_lbl.config(image=self.vazio(px(45), px(80)))
        img_lbl.grid(row=0, column=0, rowspan=2, padx=px(6), pady=px(6))
        itens = controle.ler_resultado(pasta)
        nome = controle.nome_original(pasta)
        rotulo(item, nome if len(nome) <= 32 else nome[:30] + "…", 10, wraplength=px(150),
               justify="left").grid(row=0, column=1, sticky="sw", padx=(0, px(8)))
        quando = formatar.quando((pasta / "POSTAGENS.txt").stat().st_mtime)
        rotulo(item, f"{len(itens)} corte(s), {quando}", 9, cor=APAGADO).grid(
            row=1, column=1, sticky="nw", padx=(0, px(8)))
        destacar_ao_passar(item, lambda p=pasta: self.app.ir("pronto", pasta=p))
        if itens:
            self.app.em_segundo_plano(
                lambda: imagem_do_corte(itens[0]),
                lambda img: img and img_lbl.config(image=self.foto(encaixar(img, px(45), px(80)))))


class TelaTrabalhando(Tela):
    def __init__(self, app):
        super().__init__(app)
        comandos = barra_de_comandos(self)
        Botao(comandos, "Voltar", self.voltar, largura=90).pack(side="left", padx=(0, px(12)))
        self.dica = rotulo(comandos, "", 9, cor=APAGADO)
        self.dica.pack(side="left")
        self.parar = Botao(comandos, "Parar", self.pedir_parar, largura=100)
        self.parar.pack(side="right")

        self.titulo = instrucao(self, "Fazendo os cortes...")
        corpo = tk.Frame(self, bg=BRANCO)
        corpo.pack(fill="both", expand=True, padx=px(24))
        self.subtitulo = rotulo(corpo, "", 11, "semi", wraplength=px(800), justify="left")
        self.subtitulo.pack(anchor="w")
        linha = tk.Frame(corpo, bg=BRANCO)
        linha.pack(fill="x", pady=(px(12), 0))
        self.previa = tk.Label(linha, bg="#F3F3F3", highlightthickness=1, highlightbackground=BORDA)
        self.previa.pack(side="left", anchor="n")
        lado = tk.Frame(linha, bg=BRANCO)
        lado.pack(side="left", fill="both", expand=True, padx=(px(22), 0))
        self.passos = Passos(lado)
        self.passos.pack(anchor="w", pady=(px(4), px(14)))
        barra_linha = tk.Frame(lado, bg=BRANCO)
        barra_linha.pack(anchor="w")
        self.barra = Barra(barra_linha, largura=430)
        self.barra.pack(side="left")
        self.pct = rotulo(barra_linha, "0%", 11, "semi", AZUL_ESCURO, width=5, anchor="e")
        self.pct.pack(side="left")
        self.frase = rotulo(lado, "", 11)
        self.frase.pack(anchor="w", pady=(px(14), px(2)))
        self.info = rotulo(lado, "", 9, cor=APAGADO)
        self.info.pack(anchor="w")
        self.ativa = False

    def mostrar(self, video=None, preparando=False, **kw):
        """`preparando`: o app vai acordar a IA antes de comecar (cortes novos).
        Sem isso, so acompanha um corte que ja esta rodando."""
        self.video = Path(video) if video else None
        self.preparando = preparando
        self.inicio = time.time()
        self.valor, self.alvo, self.teto = 0.0, 0.0, 2.0
        self.frase_etapa, self.frase_quando, self.frase_ia = None, 0, None
        self.leitura = 0
        self.passos.mudar(0)
        self.tipo_corte = tipo_salvo(self.app.cfg)  # o status.json confirma depois
        self.passos.rotular(ETAPAS_GAMEPLAY if self.tipo_corte == "gameplay" else ETAPAS)
        self.barra.mudar(0)
        self.parar.ativar(True)
        self.previa.config(image=self.vazio(px(256), px(144)))
        self.subtitulo.config(text=self.video.name if self.video else "")
        aviso_zap = " e o aviso chega no WhatsApp" if zap and zap.avisos_ligados(self.app.cfg) else ""
        self.dica.config(text=f"Pode fechar esta janela: os cortes continuam sozinhos{aviso_zap}.")
        self.carregar_previa(self.video)
        self.ligar()

    def ligar(self):
        """Comeca (ou retoma, ao voltar da aba Postagens/Contas) o acompanhamento.
        A `geracao` impede dois relogios rodando juntos se a volta for rapida."""
        self.ativa = True
        self.geracao = getattr(self, "geracao", 0) + 1
        self.tique(self.geracao)

    def ao_sair(self):
        self.ativa = False

    def carregar_previa(self, video):
        if video and video.exists():
            self.app.em_segundo_plano(
                lambda: quadro_do_video(video, 30.0, 640),
                lambda img: img and self.previa.config(image=self.foto(encaixar(img, px(256), px(144)))))

    def mostrar_frase_ia(self, texto):
        self.frase_ia = texto

    def tique(self, geracao):
        if not self.ativa or geracao != self.geracao:
            return
        try:
            self._tique()
        finally:
            if self.ativa and geracao == self.geracao:
                self.after(100, lambda: self.tique(geracao))

    def _tique(self):
        agora = time.time()
        self.leitura += 1
        if self.preparando:
            etapa, st = "ia", {}
            self.teto = 4.5
        elif self.leitura % 4 == 1:  # le o status.json a cada ~0,4 s
            st = controle.ler_status()
            etapa = self.conferir(st)
            if etapa is None:
                return
        else:
            etapa, st = self.frase_etapa or "conferindo", None

        # barra: corre ate onde o corte esta e depois anda devagarinho ate o teto
        alvo = max(self.valor, self.alvo)
        if alvo > self.valor + 0.3:
            self.valor += (alvo - self.valor) * 0.18
        else:
            self.valor += (self.teto - self.valor) * 0.004
        self.barra.mudar(self.valor)
        self.pct.config(text=f"{int(self.valor)}%")

        if st is not None and st.get("tipo"):
            self.tipo_corte = st["tipo"]
            self.passos.rotular(ETAPAS_GAMEPLAY if self.tipo_corte == "gameplay" else ETAPAS)
        frases = FRASES_GAMEPLAY if getattr(self, "tipo_corte", "fala") == "gameplay" else FRASES
        if etapa != self.frase_etapa or agora - self.frase_quando > 5:
            opcoes = frases.get(etapa, frases["conferindo"])
            texto = self.frase_ia if (etapa == "ia" and self.frase_ia) else random.choice(opcoes)
            self.frase.config(text=texto)
            self.frase_etapa, self.frase_quando = etapa, agora
        if etapa == "ia" and self.frase_ia and self.frase.cget("text") != self.frase_ia:
            self.frase.config(text=self.frase_ia)

        if st is not None:
            partes = []
            if st.get("etapa") == "gerando" and st.get("cortes_total"):
                partes.append(f"Corte {st.get('corte') or 0} de {st['cortes_total']}")
            if (st.get("videos_total") or 1) > 1:
                partes.append(f"Vídeo {st.get('video_num')} de {st.get('videos_total')}")
            partes.append(f"Tempo: {formatar.duracao(agora - (st.get('inicio') or self.inicio))}")
            self.info.config(text="   •   ".join(partes))

    def conferir(self, st):
        """Le o status.json. Devolve a etapa atual, ou None se o corte acabou
        (e ja levou para a proxima tela)."""
        proc = self.app.proc
        if proc is not None and st.get("execucao") != proc.execucao:
            # O cortes.py acabou de abrir e ainda nao escreveu o status dele
            # (compara pela etiqueta: o numero do processo e o do lancador do .venv)
            if proc.poll() is None:
                return "conferindo"
            self.terminar({"estado": "sem_status", "codigo": proc.returncode})
            return None
        vivo = controle.pid_vivo(st.get("pid")) or (proc is not None and proc.poll() is None)
        if st.get("estado") != "rodando" or not vivo:
            self.terminar(st)
            return None

        if not self.video and st.get("video"):
            self.video = cortes.PASTA_ENTRADA / st["video"]
            self.subtitulo.config(text=st["video"])
            self.carregar_previa(self.video)
        agora_pct, teto = progresso(st)
        n, total = (st.get("video_num") or 1), (st.get("videos_total") or 1)
        self.alvo = ((n - 1) * 100 + agora_pct) / total
        self.teto = ((n - 1) * 100 + teto) / total
        self.passos.mudar(numero_da_etapa(st))
        return st.get("etapa") or "conferindo"

    def comecou(self):
        self.preparando = False
        self.alvo = 2

    def terminar(self, st):
        self.ativa = False
        self.app.proc = None
        estado = st.get("estado")
        res = st.get("resultados") or []
        prontos = [r for r in res if not r.get("erro") and r.get("pasta")]
        if estado in ("concluido", "erro") and prontos:
            pasta = cortes.PASTA_SAIDA / prontos[-1]["pasta"]
            falhas = len(res) - len(prontos)
            self.passos.mudar(4)
            self.barra.mudar(100)
            self.app.ir("pronto", pasta=pasta, comemorar=True,
                        aviso=f"{falhas} vídeo(s) deram erro." if falhas else None)
        elif estado == "cancelado":
            self.app.ir("inicio")
            self.app.aviso_rapido("Os cortes foram parados.")
        elif estado == "erro":
            erro = (res[-1].get("erro") if res else None) or st.get("erro") or "Erro desconhecido."
            self.app.ir("erro", texto=formatar.texto_erro(erro), video=self.video)
        else:
            cauda = controle.cauda_log()
            texto = "O programa de cortes fechou sem terminar."
            if cauda:
                texto += "\n\nÚltimas linhas:\n" + cauda
            self.app.ir("erro", texto=texto, video=self.video)

    def voltar(self):
        """Volta para o inicio sem parar nada: os cortes seguem por tras (como pelo .bat).
        Para ver o andamento de novo, e so clicar em Fazer cortes."""
        if self.preparando:  # ainda ligando a IA: o corte nem comecou, voltar agora faria comecar dois
            self.app.aviso_rapido("Espere a IA ligar (ou clique em Parar para desistir).")
            return
        self.app.voltar_ao_inicio("Os cortes continuam rodando. Clique em Fazer cortes para ver o andamento.")

    def pedir_parar(self):
        if not messagebox.askyesno(NOME, "Parar os cortes agora?\n\nOs cortes que já ficaram prontos não se perdem.",
                                   parent=self.app.raiz):
            return
        if self.preparando:
            self.app.desistir_de_comecar = True
            self.ativa = False
            self.app.ir("inicio")
            return
        st = controle.ler_status()
        proc = self.app.proc
        pid = proc.pid if (proc is not None and proc.poll() is None) else st.get("pid")
        self.ativa = False  # senao a tela veria o processo morto e acharia que deu erro
        self.parar.ativar(False)
        self.frase.config(text="Parando...")
        self.app.em_segundo_plano(lambda: controle.cancelar_corte(pid),
                                  lambda _: self.terminar({"estado": "cancelado"}))


class TelaPronta(Tela):
    def __init__(self, app):
        super().__init__(app)
        comandos = barra_de_comandos(self)
        Botao(comandos, "Voltar", app.voltar_ao_inicio, largura=90).pack(side="left", padx=(0, px(8)))
        Botao(comandos, "Abrir a pasta", self.abrir_pasta, largura=120).pack(side="left")
        if SITE:
            Botao(comandos, "Programar todos...", lambda: app.programar(self.itens), largura=150).pack(
                side="left", padx=(px(8), 0))
        Botao(comandos, "Fazer outro vídeo", lambda: app.ir("inicio"), largura=170, altura=36, tam=11,
              principal=True).pack(side="right")
        self.itens = []
        self.titulo = instrucao(self, "Os cortes estão prontos")
        self.subtitulo = rotulo(self, "", 10, cor=APAGADO, anchor="w")
        self.subtitulo.pack(fill="x", padx=px(24), pady=(0, px(10)))
        self.rolagem = Rolagem(self)
        self.rolagem.pack(fill="both", expand=True, padx=px(24), pady=(0, px(14)))
        self.rolagem.cv.bind("<Configure>", self._largura, add="+")
        self.cartoes, self.colunas = [], 0

    def mostrar(self, pasta=None, comemorar=False, aviso=None, **kw):
        self.pasta = Path(pasta)
        self.imagens.clear()
        for c in self.cartoes:
            c.destroy()
        self.cartoes, self.colunas = [], 0
        itens = controle.ler_resultado(self.pasta, self.app.cfg["video"]["credito"].strip())
        self.itens = itens
        self.titulo.config(text="Os cortes estão prontos!" if comemorar else "Cortes")
        self.subtitulo.config(text=f"{len(itens)} corte(s) de: {controle.nome_original(self.pasta)}")
        for item in itens:
            self.cartoes.append(self.cartao(item))
        if not itens:
            vazio = rotulo(self.rolagem.dentro, "Nenhum corte nesta pasta.", 10, cor=APAGADO)
            vazio.grid(row=0, column=0, padx=px(20), pady=px(30))
            self.cartoes.append(vazio)
        self._largura()
        self.rolagem.topo()
        if aviso:
            self.app.aviso_rapido(aviso)
        if comemorar:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

    def cartao(self, item):
        c = tk.Frame(self.rolagem.dentro, bg=BRANCO)
        w_img, h_img = px(160), px(284)
        img_lbl = miniatura(c, w_img, h_img)
        img_lbl.config(image=self.vazio(w_img, h_img), cursor="hand2")
        img_lbl.pack(padx=px(8), pady=(px(8), px(6)))
        img_lbl.bind("<Button-1>", lambda e: abrir(item["arquivo"]))
        titulo = item["titulo"] if len(item["titulo"]) <= 60 else item["titulo"][:58] + "…"
        rotulo(c, f"{item['numero']:02d}. {titulo}", 10, "semi", wraplength=w_img, justify="left",
               anchor="w").pack(fill="x", padx=px(8))
        if item.get("nota") is not None:
            rotulo(c, f"Nota da IA: {float(item['nota']):.0f}/10", 9, cor=APAGADO,
                   anchor="w").pack(fill="x", padx=px(8))
        linha = tk.Frame(c, bg=BRANCO)
        linha.pack(fill="x", padx=px(8), pady=(px(6), px(4)))
        Botao(linha, "Assistir", lambda: abrir(item["arquivo"]), largura=58, altura=26, tam=9).pack(side="left")
        Botao(linha, "Copiar", lambda: self.copiar(item), largura=54, altura=26, tam=9).pack(side="right")
        if SITE:
            Botao(c, "Programar postagem", lambda: self.app.programar([item]), largura=140, altura=26,
                  tam=9).pack(padx=px(8), pady=(0, px(10)))
        else:
            tk.Frame(c, bg=BRANCO, height=px(4)).pack()
        self.app.em_segundo_plano(lambda: imagem_do_corte(item),
                                  lambda img: img and img_lbl.config(image=self.foto(encaixar(img, w_img, h_img))))
        return c

    def _largura(self, e=None):
        largura = self.rolagem.cv.winfo_width()
        colunas = max(1, largura // px(184))
        if colunas == self.colunas or not self.cartoes:
            return
        self.colunas = colunas
        for i, c in enumerate(self.cartoes):
            c.grid(row=i // colunas, column=i % colunas, padx=px(4), pady=px(4), sticky="n")

    def copiar(self, item):
        texto = item.get("legenda") or item["titulo"]
        self.app.raiz.clipboard_clear()
        self.app.raiz.clipboard_append(texto)
        self.app.raiz.update()
        self.app.aviso_rapido("Legenda copiada. É só colar na hora de postar.")

    def abrir_pasta(self):
        abrir(self.pasta)


class TelaErro(Tela):
    def __init__(self, app):
        super().__init__(app)
        comandos = barra_de_comandos(self)
        Botao(comandos, "Voltar", app.voltar_ao_inicio, largura=90).pack(side="left", padx=(0, px(8)))
        Botao(comandos, "Ver detalhes", lambda: abrir(controle.ARQ_LOG), largura=110).pack(side="left")
        self.tentar = Botao(comandos, "Tentar de novo", self.tentar_de_novo, largura=130, principal=True)
        self.tentar.pack(side="right")

        corpo = tk.Frame(self, bg=BRANCO)
        corpo.pack(fill="both", expand=True, padx=px(24), pady=px(20))
        icone = tk.Canvas(corpo, width=px(36), height=px(36), bg=BRANCO, highlightthickness=0)
        icone.grid(row=0, column=0, sticky="n", padx=(0, px(14)))
        r = px(16)
        icone.create_oval(px(2), px(2), px(2) + 2 * r, px(2) + 2 * r, fill=VERMELHO, outline="#9E1F14")
        c, d = px(2) + r, px(6)
        icone.create_line(c - d, c - d, c + d, c + d, fill="#FFFFFF", width=px(3))
        icone.create_line(c - d, c + d, c + d, c - d, fill="#FFFFFF", width=px(3))
        self.titulo = tk.Label(corpo, text="", bg=BRANCO, fg=AZUL_ESCURO, font=fonte(14), anchor="w")
        self.titulo.grid(row=0, column=1, sticky="w")
        self.texto = tk.Label(corpo, text="", bg=BRANCO, fg=TEXTO, font=fonte(10), justify="left",
                              anchor="w", wraplength=px(760))
        self.texto.grid(row=1, column=1, sticky="w", pady=(px(10), px(14)))
        rotulo(corpo, "Se continuar dando erro, peça ajuda a um adulto.", 10, cor=APAGADO).grid(
            row=2, column=1, sticky="w")

    def mostrar(self, texto="", titulo="Não deu certo dessa vez", video=None, **kw):
        self.video = video
        self.titulo.config(text=titulo)
        self.texto.config(text=texto)
        self.tentar.ativar(bool(video))

    def tentar_de_novo(self):
        self.app.ir("inicio", video=self.video)


# ----------------------------------------------------------------------------
# Redes sociais: contas e postagens programadas (quem posta e o site; ver redes.py)
# ----------------------------------------------------------------------------

def texto_agendador(seg):
    """Uma linha sobre o agendador do site (o Cron que posta com o PC desligado)."""
    if seg is None:
        return "Agendador do site ainda não rodou (falta o Cron no cPanel)."
    if seg <= 900:
        return "Agendador do site funcionando: posta mesmo com o PC desligado."
    return f"Agendador do site parado há {formatar.duracao(seg)}: só posta com o app aberto."


def item_da_origem(origem):
    """O corte no PC a partir do caminho guardado na postagem (para a miniatura)."""
    mp4 = Path(origem or "")
    if not mp4.name or not mp4.exists():
        return None
    capa = mp4.with_name(mp4.stem + "_capa.jpg")
    return {"arquivo": mp4, "capa": capa if capa.exists() else None}


def aviso_site(pai, erro, app, depois):
    """Quadro de "nao deu para falar com o site", com o botao que resolve.
    `depois`: o que fazer ao ligar o PC ao site ou ao tentar de novo."""
    g = grupo(pai, "Ligação com o site")
    if isinstance(erro, redes.SemSenha):
        texto = ("Para conectar contas e programar postagens, este PC precisa estar ligado ao site da loja. "
                 "É a mesma senha dos avisos no WhatsApp, e só precisa fazer uma vez.")
    else:
        texto = str(erro)
    rotulo(g, texto, 10, wraplength=px(640), justify="left").pack(anchor="w")
    linha = tk.Frame(g, bg=BRANCO)
    linha.pack(anchor="w", pady=(px(10), 0))
    if isinstance(erro, (redes.SemSenha, redes.SenhaErrada)):
        Botao(linha, "Ligar ao site...", lambda: JanelaSenha(app, depois), largura=140, principal=True).pack(side="left")
    else:
        Botao(linha, "Tentar de novo", depois, largura=120).pack(side="left")


class Dialogo(tk.Toplevel):
    """Janela de dialogo do app: icone, sem redimensionar, centralizada na principal."""

    def __init__(self, app, titulo):
        super().__init__(app.raiz, bg=BRANCO)
        self.app = app
        self.imagens = []
        self.withdraw()
        self.title(f"{titulo} - {NOME}")
        self.resizable(False, False)
        self.transient(app.raiz)
        if ICONE_ICO.exists():
            self.iconbitmap(str(ICONE_ICO))

    def abrir(self):
        """Mostra a janela depois de montada, no meio da janela principal."""
        self.update_idletasks()
        r = self.app.raiz
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = r.winfo_rootx() + (r.winfo_width() - w) // 2
        y = r.winfo_rooty() + max(0, (r.winfo_height() - h) // 3)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        self.grab_set()
        self.focus_set()

    def foto(self, img):
        foto = ImageTk.PhotoImage(img)
        self.imagens.append(foto)
        return foto

    def vazio(self, w, h):
        foto = tk.PhotoImage(width=w, height=h)
        self.imagens.append(foto)
        return foto

    def existe(self):
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False


class JanelaSenha(Dialogo):
    """Liga este PC ao site: pede a senha do PC (a mesma do vigia do WhatsApp)."""

    def __init__(self, app, depois=None):
        super().__init__(app, "Ligar ao site")
        self.depois = depois
        comandos = barra_de_comandos(self)
        Botao(comandos, "Cancelar", self.destroy, largura=90).pack(side="right")
        self.ok = Botao(comandos, "Ligar", self.ligar, largura=90, principal=True)
        self.ok.pack(side="right", padx=(0, px(8)))
        instrucao(self, "Ligar este PC ao site da loja")
        g = grupo(self, "Senha do PC")
        for n, texto in enumerate(["Clique em Abrir o painel e entre com o seu login de administrador.",
                                   'No quadro "PC dos cortes", clique em Copiar.',
                                   "Cole a senha aqui embaixo (Ctrl+V) e clique em Ligar."], 1):
            rotulo(g, f"{n}.  {texto}").pack(anchor="w", pady=px(1))
        link(g, "Abrir o painel", lambda: webbrowser.open(redes.ADMIN_SENHA), 10).pack(anchor="w", pady=(px(6), px(8)))
        self.campo = ttk.Entry(g, font=fonte(10), width=50)
        self.campo.pack(anchor="w", ipady=px(2))
        self.campo.bind("<Return>", lambda e: self.ligar())
        self.msg = rotulo(g, "", 9, cor=VERMELHO, wraplength=px(440), justify="left")
        self.msg.pack(anchor="w", pady=(px(4), 0))
        self.abrir()
        self.campo.focus_set()

    def ligar(self):
        senha = self.campo.get().strip()
        if not senha:
            self.msg.config(text="Cole a senha primeiro.", fg=VERMELHO)
            return
        self.ok.ativar(False)
        self.msg.config(text="Conferindo com o site...", fg=APAGADO)

        def depois(res):
            if not self.existe():
                return
            self.ok.ativar(True)
            if isinstance(res, Exception):
                texto = ("Essa senha não confere. Copie de novo no painel e cole aqui."
                         if isinstance(res, redes.SenhaErrada) else str(res))
                self.msg.config(text=texto, fg=VERMELHO)
                return
            controle.salvar_senha(senha)
            self.app.recarregar_config()
            self.destroy()
            self.app.aviso_rapido("Pronto: este PC está ligado ao site.")
            if self.depois:
                self.depois()
        self.app.em_segundo_plano(lambda: redes.conferir_senha(self.app.cfg, senha), depois)


class JanelaConectar(Dialogo):
    """Abre o login da rede no navegador e espera o site avisar que deu certo.
    Com `nicho` ({id, nome}), a conta ja entra nesse nicho."""

    def __init__(self, app, rede, depois, nicho=None):
        self.rede, self.depois, self.nicho = rede, depois, nicho
        nome = redes.NOMES[rede]
        super().__init__(app, f"Conectar {nome}")
        self.url = self.state = None
        self.ativo, self.inicio, self.passo = True, time.time(), 0
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        comandos = barra_de_comandos(self)
        self.fechar_btn = Botao(comandos, "Cancelar", self.fechar, largura=90)
        self.fechar_btn.pack(side="right")
        self.reabrir = Botao(comandos, "Abrir de novo", self.abrir_navegador, largura=120)
        self.reabrir.pack(side="left")
        self.reabrir.ativar(False)
        instrucao(self, f"Conectar um {nome} no nicho {nicho['nome']}" if nicho else f"Conectar uma conta do {nome}")
        corpo = tk.Frame(self, bg=BRANCO)
        corpo.pack(fill="x", padx=px(24), pady=(0, px(18)))
        self.texto = rotulo(corpo, "Abrindo o navegador...", 10, wraplength=px(460), justify="left")
        self.texto.pack(anchor="w")
        self.barra = Barra(corpo, largura=460, altura=14)
        self.barra.pack(anchor="w", pady=(px(14), 0))
        lembrete = {
            "instagram": "Cada conta do Instagram precisa estar como testadora no app da Meta (Funções do app) e "
                         "ter aceitado o convite.",
            "tiktok": "Sem a aprovação do TikTok, o app dele aceita até 10 contas no Sandbox (Target users).",
            "youtube": "Enquanto o app do Google estiver em teste, o e-mail da conta precisa estar em Usuários de "
                       "teste (Google Cloud > Tela de permissão OAuth). Se o Google avisar que o app não foi "
                       "verificado, clique em Avançado e depois em Continuar.",
        }.get(rede, "")
        rotulo(corpo, lembrete, 9, cor=APAGADO, wraplength=px(460), justify="left").pack(anchor="w", pady=(px(10), 0))
        self.abrir()
        self.app.em_segundo_plano(lambda: redes.conectar(app.cfg, rede, nicho["id"] if nicho else None),
                                  self.comecou)
        self.animar()

    def animar(self):
        if not self.ativo or not self.existe():
            return
        self.passo = (self.passo + 1.5) % 100  # barra andando enquanto espera
        self.barra.mudar(self.passo)
        self.after(60, self.animar)

    def comecou(self, res):
        if not self.ativo or not self.existe():
            return
        if isinstance(res, Exception):
            self.falhou(str(res))
            return
        self.url, self.state = res
        self.abrir_navegador()
        quem = {"instagram": "na conta profissional do Instagram", "tiktok": "na conta do TikTok",
                "youtube": "na conta Google do canal do YouTube"}.get(self.rede, "na conta")
        if self.nicho:
            quem += f" do nicho {self.nicho['nome']}"
        self.texto.config(text=f"Termine no navegador: entre {quem} e clique em Permitir. Se ele já entrar "
                               "sozinho em outra conta, saia dela e entre na certa.\n\n"
                               "Esta janela fecha sozinha quando der certo.")
        self.reabrir.ativar(True)
        self.after(3000, self.olhar)

    def abrir_navegador(self):
        if self.url:
            webbrowser.open(self.url)

    def olhar(self):
        if not self.ativo or not self.existe():
            return
        if time.time() - self.inicio > 20 * 60:
            self.falhou("Demorou demais. Feche e clique em Conectar de novo.")
            return
        self.app.em_segundo_plano(lambda: redes.conexao(self.app.cfg, self.state), self.resposta)

    def resposta(self, res):
        if not self.ativo or not self.existe():
            return
        if isinstance(res, Exception) or res.get("estado") == "esperando":
            self.after(2500, self.olhar)  # ainda no navegador (ou a internet piscou): pergunta de novo
            return
        if res.get("estado") == "ok":
            self.ativo = False
            self.destroy()
            self.app.aviso_rapido(res.get("mensagem") or "Conta conectada!")
            self.depois()
            return
        self.falhou(res.get("mensagem") or "Não deu para conectar.")

    def falhou(self, texto):
        self.ativo = False
        self.barra.mudar(0)
        self.texto.config(text=texto, fg=VERMELHO)
        self.reabrir.ativar(False)
        self.fechar_btn.mudar("Fechar")

    def fechar(self):
        self.ativo = False
        self.destroy()


class JanelaNicho(Dialogo):
    """Cria ou muda um nicho: nome, cor e a grade de horarios em que ele posta."""

    def __init__(self, app, nicho=None, depois=None):
        self.nicho, self.depois = nicho, depois
        super().__init__(app, "Mudar nicho" if nicho else "Novo nicho")
        horarios = (nicho or {}).get("horarios") or {"horas": ["12:00", "18:00", "21:00"], "dias": list(range(7))}
        self.horas = list(horarios.get("horas") or [])
        usadas = {n["cor"] for n in getattr(app, "nichos", [])}
        livres = [c for c in redes.CORES_NICHO if c not in usadas]
        self.cor = (nicho or {}).get("cor") or (livres or redes.CORES_NICHO)[0]

        comandos = barra_de_comandos(self)
        Botao(comandos, "Cancelar", self.destroy, largura=90).pack(side="right")
        self.ok = Botao(comandos, "Salvar", self.salvar, largura=100, principal=True)
        self.ok.pack(side="right", padx=(0, px(8)))
        if nicho:
            Botao(comandos, "Apagar nicho", self.apagar, largura=120).pack(side="left")
        self.msg = rotulo(comandos, "", 9, cor=VERMELHO, wraplength=px(260), justify="left")
        self.msg.pack(side="left", padx=(px(10), 0))
        instrucao(self, "Mudar o nicho" if nicho else "Novo nicho")

        g = grupo(self, "Nome e cor")
        self.nome = ttk.Entry(g, font=fonte(10), width=36)
        self.nome.insert(0, (nicho or {}).get("nome", ""))
        self.nome.pack(anchor="w", ipady=px(2))
        rotulo(g, "Exemplo: Carros, Tecnologia, Podcast, Humor", 9, cor=APAGADO).pack(anchor="w")
        self.cores = tk.Canvas(g, width=px(len(redes.CORES_NICHO) * 34), height=px(34), bg=BRANCO,
                               highlightthickness=0, cursor="hand2")
        self.cores.pack(anchor="w", pady=(px(8), 0))
        self.cores.bind("<Button-1>", self.clicar_cor)
        self.desenhar_cores()

        g = grupo(self, "Horários em que este nicho posta")
        linha = tk.Frame(g, bg=BRANCO)
        linha.pack(fill="x")
        self.lista = tk.Listbox(linha, height=6, width=10, font=fonte(11), activestyle="none", bd=0,
                                highlightthickness=1, highlightbackground=BORDA, selectbackground=AZUL)
        self.lista.pack(side="left")
        lado = tk.Frame(linha, bg=BRANCO)
        lado.pack(side="left", fill="y", padx=(px(14), 0))
        nova = tk.Frame(lado, bg=BRANCO)
        nova.pack(anchor="w")
        self.hora = ttk.Spinbox(nova, from_=0, to=23, width=3, format="%02.0f", wrap=True, font=fonte(10))
        self.hora.set("19")
        self.hora.pack(side="left")
        rotulo(nova, ":").pack(side="left")
        self.minuto = ttk.Spinbox(nova, from_=0, to=55, increment=5, width=3, format="%02.0f", wrap=True,
                                  font=fonte(10))
        self.minuto.set("00")
        self.minuto.pack(side="left")
        Botao(nova, "Pôr na lista", self.por_hora, largura=100, altura=26, tam=9).pack(side="left", padx=(px(8), 0))
        Botao(lado, "Tirar da lista", self.tirar_hora, largura=110, altura=26, tam=9).pack(anchor="w", pady=(px(8), 0))
        rotulo(lado, "Dica: 12:00, 18:00 e 21:00 costumam dar\nmais visualização em Reels e TikTok.", 9,
               cor=APAGADO, justify="left").pack(anchor="w", pady=(px(10), 0))

        dias = tk.Frame(g, bg=BRANCO)
        dias.pack(anchor="w", pady=(px(10), 0))
        rotulo(dias, "Dias:").pack(side="left", padx=(0, px(8)))
        marcados = set(horarios.get("dias") or range(7))
        self.dias = []
        for i, nome in enumerate(redes.DIAS):
            var = tk.BooleanVar(value=i in marcados)
            ttk.Checkbutton(dias, text=nome, variable=var, style="Branco.TCheckbutton",
                            command=self.atualizar).pack(side="left", padx=(0, px(6)))
            self.dias.append(var)
        self.previsao = rotulo(g, "", 9, cor=APAGADO, wraplength=px(480), justify="left")
        self.previsao.pack(anchor="w", pady=(px(8), 0))
        self.encher_lista()
        self.abrir()
        self.nome.focus_set()

    def desenhar_cores(self):
        cv = self.cores
        cv.delete("all")
        for i, cor in enumerate(redes.CORES_NICHO):
            x, y, t = px(3 + i * 34), px(3), px(26)
            if cor == self.cor:
                cv.create_rectangle(x - px(2), y - px(2), x + t + px(2), y + t + px(2), outline=TEXTO, width=px(2))
            cv.create_rectangle(x, y, x + t, y + t, fill=cor, outline="#707070")

    def clicar_cor(self, e):
        i = int(e.x // px(34))
        if 0 <= i < len(redes.CORES_NICHO):
            self.cor = redes.CORES_NICHO[i]
            self.desenhar_cores()

    def grade(self):
        return {"horas": sorted(set(self.horas)), "dias": [i for i, v in enumerate(self.dias) if v.get()]}

    def encher_lista(self):
        self.horas = sorted(set(self.horas))
        self.lista.delete(0, "end")
        for h in self.horas:
            self.lista.insert("end", f"  {h}")
        self.atualizar()

    def por_hora(self):
        try:
            h, m = int(self.hora.get()), int(self.minuto.get())
        except ValueError:
            self.msg.config(text="Confira a hora digitada.")
            return
        if not (0 <= h <= 23 and 0 <= m <= 59):
            self.msg.config(text="Confira a hora digitada.")
            return
        self.msg.config(text="")
        self.horas.append(f"{h:02d}:{m:02d}")
        self.encher_lista()

    def tirar_hora(self):
        for i in reversed(self.lista.curselection()):
            del self.horas[i]
        self.encher_lista()

    def atualizar(self):
        g = self.grade()
        if not g["horas"]:
            self.previsao.config(text="Sem horários: ao programar, você escolhe o dia e a hora de cada vez.")
            return
        if not g["dias"]:
            self.previsao.config(text="Marque pelo menos um dia.")
            return
        proximos = redes.proximos_horarios(g, 3)
        self.previsao.config(text=f"Posta {redes.texto_horarios(g)}.\nPróximos: "
                                  + ", ".join(redes.data_hora(t) for t in proximos) + ".")

    def salvar(self):
        nome = self.nome.get().strip()
        if not nome:
            self.msg.config(text="Dê um nome para o nicho.")
            return
        g = self.grade()
        if g["horas"] and not g["dias"]:
            self.msg.config(text="Marque pelo menos um dia.")
            return
        self.ok.ativar(False)

        def depois(res):
            if not self.existe():
                return
            self.ok.ativar(True)
            if isinstance(res, Exception):
                self.msg.config(text=str(res))
                return
            self.destroy()
            self.app.aviso_rapido(f"Nicho {nome} salvo.")
            if self.depois:
                self.depois()
        self.app.em_segundo_plano(
            lambda: redes.salvar_nicho(self.app.cfg, (self.nicho or {}).get("id"), nome, self.cor, g), depois)

    def apagar(self):
        if not messagebox.askyesno(NOME, f"Apagar o nicho {self.nicho['nome']}?\n\nAs contas dele ficam sem nicho "
                                         "(não são desconectadas) e as postagens já programadas continuam.",
                                   parent=self):
            return

        def depois(res):
            if isinstance(res, Exception):
                if self.existe():
                    self.msg.config(text=str(res))
                return
            if self.existe():
                self.destroy()
            self.app.aviso_rapido("Nicho apagado.")
            if self.depois:
                self.depois()
        self.app.em_segundo_plano(lambda: redes.apagar_nicho(self.app.cfg, self.nicho["id"]), depois)


class TelaContas(Tela):
    """Gerenciador de contas: os nichos, as contas de cada um e os horarios em que postam."""

    def __init__(self, app):
        super().__init__(app)
        comandos = barra_de_comandos(self)
        Botao(comandos, "Atualizar", self.carregar, largura=100).pack(side="left")
        self.agendador = rotulo(comandos, "", 9, cor=APAGADO)
        self.agendador.pack(side="left", padx=px(14))
        Botao(comandos, "Novo nicho...", lambda: JanelaNicho(app, depois=self.carregar), largura=150, altura=36,
              tam=11, principal=True).pack(side="right")
        instrucao(self, "Contas e nichos")
        rotulo(self, "Cada nicho tem as contas dele e os horários em que posta. Ao programar um corte para o "
                     "nicho, ele cai no próximo horário livre, em todas as contas do nicho.", 9, cor=APAGADO,
               wraplength=px(900), justify="left").pack(anchor="w", padx=px(24), pady=(0, px(8)))
        self.rolagem = Rolagem(self)
        self.rolagem.config(highlightthickness=0)
        self.rolagem.pack(fill="both", expand=True, pady=(0, px(8)))
        self.corpo = self.rolagem.dentro
        self.pedido = 0

    def mostrar(self, **kw):
        self.carregar()

    def carregar(self):
        self.pedido += 1
        pedido = self.pedido
        if not self.corpo.winfo_children():
            rotulo(self.corpo, "Carregando as contas...", 10, cor=APAGADO).pack(anchor="w", padx=px(24))
        self.app.em_segundo_plano(lambda: redes.contas(self.app.cfg),
                                  lambda r: pedido == self.pedido and self.montar(r))

    def montar(self, r):
        topo = self.rolagem.cv.yview()[0]
        self.imagens.clear()
        limpar(self.corpo)
        if isinstance(r, Exception):
            self.agendador.config(text="")
            aviso_site(self.corpo, r, self.app, self.carregar)
            return
        self.r = r
        self.app.nichos = r.get("nichos") or []
        self.agendador.config(text=texto_agendador(r.get("agendador_seg")))
        faltam = [redes.NOMES[x] for x in redes.REDES if not r.get(f"{x}_pronto")]
        if faltam:
            g = grupo(self.corpo, "Falta configurar no site")
            rotulo(g, f"Falta colar no site as chaves do app do {' e do '.join(faltam)} (só uma vez). O passo a "
                      "passo está no painel da loja: /admin-bot, aba Ajuda.", 10, wraplength=px(640),
                   justify="left").pack(anchor="w")
            Botao(g, "Abrir o painel...", lambda: webbrowser.open(redes.ADMIN_REDES), largura=140).pack(
                anchor="w", pady=(px(10), 0))
        ids = {n["id"] for n in self.app.nichos}
        for n in self.app.nichos:
            self.grupo_nicho(n, [c for c in r["contas"] if c.get("nicho") == n["id"]])
        soltas = [c for c in r["contas"] if c.get("nicho") not in ids]
        if soltas or not self.app.nichos:
            self.grupo_nicho(None, soltas)
        self.after(60, lambda: self.rolagem.cv.yview_moveto(topo))  # depois de a lista nova ganhar tamanho

    def grupo_nicho(self, n, contas):
        g = grupo(self.corpo, n["nome"] if n else "Sem nicho")
        topo = tk.Frame(g, bg=BRANCO)
        topo.pack(fill="x", pady=(0, px(8)))
        if n:
            tk.Label(topo, text="■", bg=BRANCO, fg=n["cor"], font=fonte(14)).pack(side="left", padx=(0, px(6)))
            rotulo(topo, "Posta " + redes.texto_horarios(n["horarios"]), 10, "semi").pack(side="left")
            Botao(topo, "Mudar nicho...", lambda: JanelaNicho(self.app, n, self.carregar), largura=120, altura=26,
                  tam=9).pack(side="right")
        else:
            texto = ("Contas que ainda não estão em nenhum nicho. Use \"Nicho\" ao lado da conta para mudar."
                     if self.app.nichos else
                     "Crie um nicho (botão Novo nicho, aqui embaixo) e coloque as contas nele.")
            rotulo(topo, texto, 9, cor=APAGADO).pack(side="left")
        for c in contas:
            self.linha_conta(g, c)
        if not contas:
            rotulo(g, "Nenhuma conta neste nicho ainda.", 9, cor=APAGADO).pack(anchor="w", pady=(0, px(6)))
        rodape = tk.Frame(g, bg=BRANCO)
        rodape.pack(fill="x", pady=(px(4), 0))
        for rede in redes.REDES:
            if self.r.get(f"{rede}_pronto"):
                Botao(rodape, f"Conectar {redes.NOMES[rede]}...",
                      lambda rd=rede: JanelaConectar(self.app, rd, self.carregar, n),
                      largura=160, altura=28, tam=9).pack(side="left", padx=(0, px(8)))

    def linha_conta(self, pai, c):
        linha = tk.Frame(pai, bg=BRANCO)
        linha.pack(fill="x", pady=(0, px(10)))
        tam = px(44)
        img = tk.Label(linha, bg=BRANCO, image=self.vazio(tam, tam), bd=0)
        img.pack(side="left", anchor="n")
        lado = tk.Frame(linha, bg=BRANCO)
        lado.pack(side="right", anchor="n")
        textos = tk.Frame(linha, bg=BRANCO)
        textos.pack(side="left", fill="x", expand=True, padx=(px(12), 0))
        cab = tk.Frame(textos, bg=BRANCO)
        cab.pack(anchor="w")
        rotulo(cab, redes.nome_conta(c), 11, "semi").pack(side="left")
        tk.Label(cab, text=f" {redes.NOMES[c['rede']]} ", bg=COR_REDE.get(c["rede"], AZUL), fg=BRANCO,
                 font=fonte(8, "semi")).pack(side="left", padx=(px(8), 0))
        if c.get("problema"):
            rotulo(textos, "⚠ " + c["problema"], 9, cor=VERMELHO).pack(anchor="w")
        else:
            extra = c["nome"] if c.get("usuario") and c.get("nome") and c["nome"] != c["usuario"] else ""
            rotulo(textos, "   •   ".join(x for x in (extra, "Conectada ✔") if x), 9, cor=VERDE).pack(anchor="w")
        if c["rede"] == "tiktok":
            var = tk.StringVar(value=c.get("modo") or "rascunho")
            opcoes = [("rascunho", "Rascunho: eu termino de postar no celular")]
            if self.r.get("tiktok_direto") or c.get("modo") == "direto":
                opcoes.append(("direto", "Postar direto (precisa da aprovação do TikTok)"))
            for valor, texto in opcoes:
                ttk.Radiobutton(textos, text=texto, value=valor, variable=var, style="Branco.TRadiobutton",
                                command=lambda v=var: self.mudar_modo(c, v)).pack(anchor="w", pady=(px(2), 0))

        nichos = self.app.nichos
        caixa = tk.Frame(lado, bg=BRANCO)
        caixa.pack(anchor="e")
        rotulo(caixa, "Nicho:", 9).pack(side="left", padx=(0, px(4)))
        escolha = ttk.Combobox(caixa, state="readonly", width=16, font=fonte(9),
                               values=["(sem nicho)"] + [n["nome"] for n in nichos])
        atual = next((i for i, n in enumerate(nichos) if n["id"] == c.get("nicho")), None)
        escolha.current(0 if atual is None else atual + 1)
        escolha.bind("<<ComboboxSelected>>",
                     lambda e: self.mover(c, None if escolha.current() == 0 else nichos[escolha.current() - 1]))
        escolha.pack(side="left")
        botoes = tk.Frame(lado, bg=BRANCO)
        botoes.pack(anchor="e", pady=(px(6), 0))
        Botao(botoes, "Desconectar", lambda: self.desconectar(c), largura=100, altura=26, tam=9).pack(side="right")
        if c.get("problema"):
            nicho = next((n for n in nichos if n["id"] == c.get("nicho")), None)
            Botao(botoes, "Conectar de novo", lambda: JanelaConectar(self.app, c["rede"], self.carregar, nicho),
                  largura=120, altura=26, tam=9, principal=True).pack(side="right", padx=(0, px(6)))
        self.app.em_segundo_plano(lambda: avatar(c, tam), lambda im: im and img.config(image=self.foto(im)))

    def mover(self, conta, nicho):
        def depois(res):
            if isinstance(res, Exception):
                messagebox.showinfo(NOME, str(res), parent=self.app.raiz)
            else:
                self.app.aviso_rapido(f"{redes.nome_conta(conta)} agora está "
                                      + (f"no nicho {nicho['nome']}." if nicho else "sem nicho."))
            self.carregar()
        self.app.em_segundo_plano(lambda: redes.nicho_da_conta(self.app.cfg, conta["id"], nicho and nicho["id"]),
                                  depois)

    def mudar_modo(self, conta, var):
        antes, modo = conta.get("modo") or "rascunho", var.get()
        if modo == antes:
            return
        if modo == "direto" and not messagebox.askyesno(
                NOME, "Postar direto no TikTok?\n\nAté o TikTok aprovar o seu app, o vídeo sai como \"Só eu\" e "
                      "a conta precisa estar privada. Depois da aprovação, sai para todo mundo.\n\n"
                      "Mudar mesmo assim?", parent=self.app.raiz):
            var.set(antes)
            return

        def depois(res):
            if isinstance(res, Exception):
                var.set(antes)
                messagebox.showinfo(NOME, str(res), parent=self.app.raiz)
                return
            conta["modo"] = modo
            self.app.aviso_rapido("TikTok " + redes.nome_conta(conta) + ": "
                                  + ("postar direto." if modo == "direto" else "rascunho."))
        self.app.em_segundo_plano(lambda: redes.mudar_modo(self.app.cfg, conta["id"], modo), depois)

    def desconectar(self, conta):
        if not messagebox.askyesno(NOME, f"Desconectar {redes.NOMES[conta['rede']]} {redes.nome_conta(conta)}?\n\n"
                                         "As postagens dela que ainda não saíram serão canceladas.",
                                   parent=self.app.raiz):
            return

        def depois(res):
            if isinstance(res, Exception):
                messagebox.showinfo(NOME, str(res), parent=self.app.raiz)
            else:
                self.app.aviso_rapido("Conta desconectada.")
            self.carregar()
        self.app.em_segundo_plano(lambda: redes.desconectar(self.app.cfg, conta["id"]), depois)


class TelaPostagens(Tela):
    """O que vai sair (e o que ja saiu) no Instagram e no TikTok."""

    def __init__(self, app):
        super().__init__(app)
        comandos = barra_de_comandos(self)
        Botao(comandos, "Atualizar", self.recarregar, largura=100).pack(side="left")
        self.agendador = rotulo(comandos, "", 9, cor=APAGADO)
        self.agendador.pack(side="left", padx=px(14))
        Botao(comandos, "Nova postagem...", lambda: JanelaEscolher(app), largura=160, altura=36, tam=11,
              principal=True).pack(side="right")
        instrucao(self, "Postagens programadas")
        topo = tk.Frame(self, bg=BRANCO)
        topo.pack(fill="x", padx=px(24), pady=(0, px(10)))
        self.subtitulo = rotulo(topo, "", 10, cor=APAGADO, anchor="w")
        self.subtitulo.pack(side="left")
        self.filtro = ttk.Combobox(topo, state="readonly", width=22, font=fonte(10), values=["Todos os nichos"])
        self.filtro.current(0)
        self.filtro.bind("<<ComboboxSelected>>", lambda e: self.remontar())
        self.filtro.pack(side="right")
        rotulo(topo, "Mostrar:").pack(side="right", padx=(0, px(8)))
        self.rolagem = Rolagem(self)
        self.rolagem.pack(fill="both", expand=True, padx=px(24), pady=(0, px(14)))
        self.lista = self.rolagem.dentro
        self.ativa, self.pedido, self.assinatura, self.geracao = False, 0, None, 0
        self.ultimo, self.nichos, self.nicho_da_conta = None, [], {}

    def mostrar(self, **kw):
        self.ativa = True
        self.recarregar()
        self.geracao += 1
        self.after(20000, lambda g=self.geracao: self.tique(g))

    def ao_sair(self):
        self.ativa = False

    def tique(self, geracao):
        """Atualiza sozinha a cada 20 s enquanto estiver na tela."""
        if not self.ativa or geracao != self.geracao:
            return
        self.carregar()
        self.after(20000, lambda: self.tique(geracao))

    def recarregar(self):
        self.assinatura = None
        self.carregar()

    def carregar(self):
        self.pedido += 1
        pedido = self.pedido
        if not self.lista.winfo_children():
            rotulo(self.lista, "Carregando...", 10, cor=APAGADO).pack(anchor="w", padx=px(16), pady=px(16))
        def buscar():
            postagens = redes.postagens(self.app.cfg)
            try:
                contas = redes.contas(self.app.cfg)  # para saber de que nicho e cada conta
            except redes.ErroRede:
                contas = None
            return postagens, contas
        self.app.em_segundo_plano(buscar, lambda r: pedido == self.pedido and self.montar(r))

    def remontar(self):
        self.assinatura = None
        if self.ultimo is not None:
            self.montar(self.ultimo)

    def nichos_do_post(self, p):
        """Ids dos nichos das contas da postagem (None = conta sem nicho)."""
        return {self.nicho_da_conta.get(d["conta"]) for d in p["destinos"]}

    def montar(self, r):
        if not isinstance(r, Exception):
            self.ultimo = r
            r, contas = r
            if contas is not None:
                self.nichos = list(contas.get("nichos") or [])
                self.app.nichos = self.nichos
                ids = {n["id"] for n in self.nichos}
                self.nicho_da_conta = {c["id"]: (c.get("nicho") if c.get("nicho") in ids else None)
                                       for c in contas["contas"]}
                escolhido = self.filtro.get()
                valores = ["Todos os nichos"] + [n["nome"] for n in self.nichos] + ["Sem nicho"]
                self.filtro.configure(values=valores)
                self.filtro.current(valores.index(escolhido) if escolhido in valores else 0)
        if isinstance(r, Exception):
            self.assinatura = None
            self.imagens.clear()
            limpar(self.lista)
            self.subtitulo.config(text="")
            self.agendador.config(text="")
            aviso_site(self.lista, r, self.app, self.recarregar)
            return
        prox, ant = r["proximas"], r["anteriores"]
        self.app.postagens_pendentes = len(prox)
        self.agendador.config(text=texto_agendador(r.get("agendador_seg")))
        i = self.filtro.current()
        if 0 < i <= len(self.nichos):
            alvo = self.nichos[i - 1]["id"]
            prox = [p for p in prox if alvo in self.nichos_do_post(p)]
            ant = [p for p in ant if alvo in self.nichos_do_post(p)]
        elif i == len(self.nichos) + 1:
            prox = [p for p in prox if None in self.nichos_do_post(p)]
            ant = [p for p in ant if None in self.nichos_do_post(p)]
        # Nada mudou desde a ultima olhada: nao redesenha (senao a lista pisca a cada 20 s)
        assinatura = json.dumps([prox, ant, i], sort_keys=True) + str(int(time.time() // 60))
        if assinatura == self.assinatura:
            return
        self.assinatura = assinatura
        topo = self.rolagem.cv.yview()[0]
        self.imagens.clear()
        limpar(self.lista)
        self.subtitulo.config(text=f"{len(prox)} para sair   •   {len(ant)} nos últimos 30 dias" if prox or ant else "")
        if not prox and not ant:
            texto = ("Nenhuma postagem deste nicho." if i else
                     "Nenhuma postagem ainda.\n\nNos cortes prontos, clique em Programar postagem, "
                     "ou aqui embaixo em Nova postagem.")
            rotulo(self.lista, texto, 10, cor=APAGADO, justify="left").pack(anchor="w", padx=px(16), pady=px(20))
            return
        grupo_atual = None
        for p in prox:  # "Vão sair", separado por dia
            dia = datetime.date.fromtimestamp(p["quando"])
            falta = (dia - datetime.date.today()).days
            grupo_dia = dia if falta >= 0 else "atrasadas"
            if grupo_dia != grupo_atual:
                grupo_atual = grupo_dia
                if falta < 0:
                    self.cabecalho("Atrasadas (o site ainda vai postar)")
                else:
                    nome = {0: "Hoje", 1: "Amanhã"}.get(falta, "")
                    self.cabecalho(f"{nome}   {redes.DIAS[dia.weekday()]} {dia:%d/%m}".strip())
            self.linha(p, True)
        if ant:
            self.cabecalho("Já saíram (últimos 30 dias)")
            for p in ant:
                self.linha(p, False)
        tk.Frame(self.lista, bg=BRANCO, height=px(12)).pack()
        self.after(60, lambda: self.rolagem.cv.yview_moveto(topo))  # depois de a lista nova ganhar tamanho

    def cabecalho(self, texto):
        rotulo(self.lista, texto, 10, "semi", AZUL_ESCURO).pack(anchor="w", padx=px(12), pady=(px(12), px(2)))
        tk.Frame(self.lista, bg=LINHA, height=1).pack(fill="x", padx=px(12))

    def linha(self, p, futura):
        q = tk.Frame(self.lista, bg=BRANCO)
        q.pack(fill="x", padx=px(12), pady=(px(10), 0))
        w, h = px(45), px(80)
        img = miniatura(q, w, h)
        img.config(image=self.vazio(w, h))
        img.pack(side="left", anchor="n")
        botoes = tk.Frame(q, bg=BRANCO)
        botoes.pack(side="right", anchor="n", padx=(px(10), 0))
        meio = tk.Frame(q, bg=BRANCO)
        meio.pack(side="left", fill="x", expand=True, padx=(px(12), 0))

        quando = redes.data_hora(p["quando"])
        falta = p["quando"] - time.time()
        if futura and falta > 0:
            quando = datetime.datetime.fromtimestamp(p["quando"]).strftime("%H:%M") + f"   ({redes.daqui_a(falta)})"
        cab = tk.Frame(meio, bg=BRANCO)
        cab.pack(anchor="w")
        rotulo(cab, quando, 11, "semi", AZUL_ESCURO if futura else TEXTO).pack(side="left")
        for n in self.nichos:  # etiqueta colorida com o nicho
            if n["id"] in self.nichos_do_post(p):
                tk.Label(cab, text=f" {n['nome']} ", bg=n["cor"], fg=BRANCO, font=fonte(8, "semi")).pack(
                    side="left", padx=(px(8), 0))
        titulo = p.get("titulo") or "(sem título)"
        rotulo(meio, titulo if len(titulo) <= 90 else titulo[:88] + "…", 10).pack(anchor="w")
        for d in p["destinos"]:
            self.linha_destino(meio, p, d)

        esperando = any(d["estado"] == "agendado" for d in p["destinos"])
        if esperando:
            Botao(botoes, "Postar agora", lambda: self.postar_agora(p), largura=110, altura=26, tam=9).pack(
                pady=(0, px(4)))
            if all(d["estado"] in ("agendado", "cancelado") for d in p["destinos"]):
                Botao(botoes, "Mudar...", lambda: JanelaAgendar(self.app, post=p), largura=110, altura=26,
                      tam=9).pack(pady=(0, px(4)))
            Botao(botoes, "Cancelar", lambda: self.cancelar(p), largura=110, altura=26, tam=9).pack()
        item = item_da_origem(p.get("origem"))
        if item:
            self.app.em_segundo_plano(lambda: imagem_do_corte(item),
                                      lambda im: im and img.config(image=self.foto(encaixar(im, w, h))))

    def linha_destino(self, meio, p, d):
        dl = tk.Frame(meio, bg=BRANCO)
        dl.pack(anchor="w", fill="x", pady=(px(3), 0))
        texto, cor = redes.ESTADOS.get(d["estado"], (d["estado"], APAGADO))
        tk.Label(dl, text="●", bg=BRANCO, fg=COR_REDE.get(d["rede"], AZUL), font=fonte(9)).pack(side="left")
        rotulo(dl, f"{redes.NOMES.get(d['rede'], d['rede'])} {d['nome']}:", 9).pack(side="left", padx=(px(2), px(4)))
        rotulo(dl, texto, 9, "semi", cor).pack(side="left")
        if d.get("link"):
            link(dl, "Abrir", lambda: webbrowser.open(d["link"])).pack(side="left", padx=(px(10), 0))
        if d["estado"] == "erro" and p.get("tem_arquivo"):
            link(dl, "Tentar de novo", lambda: self.tentar(d)).pack(side="left", padx=(px(10), 0))
        if d["estado"] == "rascunho":
            rotulo(dl, "(abra a notificação do TikTok no celular)", 9, cor=APAGADO).pack(side="left", padx=(px(8), 0))
        if d["estado"] == "erro" and d.get("erro"):
            rotulo(meio, d["erro"], 9, cor=VERMELHO, wraplength=px(560), justify="left").pack(anchor="w", padx=(px(14), 0))

    def acao(self, funcao, pronto, pergunta=None, durante=None):
        if pergunta and not messagebox.askyesno(NOME, pergunta, parent=self.app.raiz):
            return
        if durante:
            self.app.aviso_rapido(durante)

        def depois(res):
            if isinstance(res, Exception):
                messagebox.showinfo(NOME, str(res), parent=self.app.raiz)
            elif pronto:
                self.app.aviso_rapido(pronto)
            self.recarregar()
        self.app.em_segundo_plano(funcao, depois)

    def postar_agora(self, p):
        self.acao(lambda: redes.postar_agora(self.app.cfg, p["id"]),
                  "Mandei para a rede. O aviso chega no WhatsApp quando sair.",
                  f"Postar agora?\n\n{p.get('titulo') or ''}", "Postando... pode levar um minuto.")

    def cancelar(self, p):
        self.acao(lambda: redes.cancelar(self.app.cfg, p["id"]), "Postagem cancelada.",
                  f"Cancelar esta postagem?\n\n{p.get('titulo') or ''}\n\nO vídeo não vai sair.")

    def tentar(self, d):
        self.acao(lambda: redes.tentar_de_novo(self.app.cfg, d["id"]), "Tentando de novo. O aviso chega no WhatsApp.",
                  durante="Tentando de novo... pode levar um minuto.")


class JanelaEscolher(Dialogo):
    """Escolher os cortes para programar (dos ultimos videos cortados)."""

    def __init__(self, app):
        super().__init__(app, "Nova postagem")
        comandos = barra_de_comandos(self)
        Botao(comandos, "Cancelar", self.destroy, largura=90).pack(side="right")
        Botao(comandos, "Continuar", self.continuar, largura=110, principal=True).pack(side="right", padx=(0, px(8)))
        instrucao(self, "Quais cortes você quer postar?")
        rotulo(self, "Clique num corte (segure Ctrl para escolher vários). Clicar no nome do vídeo escolhe "
                     "todos os cortes dele.", 9, cor=APAGADO, wraplength=px(580), justify="left").pack(
            anchor="w", padx=px(24), pady=(0, px(8)))
        caixa = tk.Frame(self, bg=BRANCO)
        caixa.pack(fill="both", expand=True, padx=px(24), pady=(0, px(14)))
        self.arvore = ttk.Treeview(caixa, columns=("nota",), height=14, selectmode="extended")
        self.arvore.heading("#0", text="Corte")
        self.arvore.heading("nota", text="Nota da IA")
        self.arvore.column("#0", width=px(480))
        self.arvore.column("nota", width=px(90), anchor="center")
        barra = ttk.Scrollbar(caixa, orient="vertical", command=self.arvore.yview)
        self.arvore.configure(yscrollcommand=barra.set)
        self.arvore.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.itens = {}
        credito = app.cfg["video"]["credito"].strip()
        for n, pasta in enumerate(controle.resultados_recentes(15)):
            itens = controle.ler_resultado(pasta, credito)
            if not itens:
                continue
            pai = self.arvore.insert("", "end", text=controle.nome_original(pasta), open=(n == 0))
            for item in itens:
                nota = f"{float(item['nota']):.0f}/10" if item.get("nota") is not None else ""
                iid = self.arvore.insert(pai, "end", text=f"{item['numero']:02d}. {item['titulo']}", values=(nota,))
                self.itens[iid] = item
        if not self.itens:
            self.arvore.insert("", "end", text="Nenhum corte pronto ainda. Faça os cortes primeiro, na aba Cortes.")
        self.arvore.bind("<Double-1>", lambda e: self.arvore.identify_row(e.y) in self.itens and self.continuar())
        self.abrir()

    def escolhidos(self):
        out = []
        for iid in self.arvore.selection():
            for f in (self.arvore.get_children(iid) or (iid,)):
                if f in self.itens and self.itens[f] not in out:
                    out.append(self.itens[f])
        return out

    def continuar(self):
        itens = self.escolhidos()
        if not itens:
            messagebox.showinfo(NOME, "Escolha pelo menos um corte.", parent=self)
            return
        self.destroy()
        JanelaAgendar(self.app, itens=itens)


class JanelaAgendar(Dialogo):
    """Programa um ou varios cortes (`itens`) para as contas conectadas, ou muda
    horario e legenda de uma postagem que ainda nao saiu (`post`)."""

    def __init__(self, app, itens=None, post=None):
        self.itens, self.post = list(itens or []), post
        self.editando = post is not None
        n = len(self.itens)
        super().__init__(app, "Mudar postagem" if self.editando else "Programar postagem")
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.enviando = self.cancelado = False
        self.contas, self.marcadas = [], {}
        self.infos_tiktok, self.chave_tiktok, self.max_duracao = None, None, 0
        self.ultima = carregar_json(ARQ_ULTIMA_POSTAGEM, {})
        self.nichos, self.postagens_resp, self.escolha_nicho = [], None, None

        comandos = barra_de_comandos(self)
        Botao(comandos, "Cancelar", self.fechar, largura=90).pack(side="right")
        self.ok = Botao(comandos, "Agendar", self.confirmar, largura=160, altura=32, principal=True)
        self.ok.pack(side="right", padx=(0, px(8)))
        self.msg = rotulo(comandos, "", 9, cor=VERMELHO, wraplength=px(400), justify="left")
        self.msg.pack(side="left")

        if self.editando:
            titulo = "Mudar horário ou legenda"
        else:
            titulo = "Programar a postagem do corte" if n == 1 else f"Programar {n} cortes"
        instrucao(self, titulo)

        corpo = tk.Frame(self, bg=BRANCO)
        corpo.pack(fill="both", expand=True, padx=px(24), pady=(0, px(4)))
        esq = tk.Frame(corpo, bg=BRANCO)
        esq.pack(side="left", anchor="n")
        wc, hc = px(126), px(224)
        self.capa = miniatura(esq, wc, hc)
        self.capa.config(image=self.vazio(wc, hc))
        self.capa.pack()
        nome = (post.get("titulo") or "") if self.editando else (self.itens[0]["titulo"] if n == 1 else f"{n} cortes")
        rotulo(esq, nome if len(nome) <= 70 else nome[:68] + "…", 9, wraplength=wc, justify="left").pack(
            anchor="w", pady=(px(6), 0))
        self.dir = tk.Frame(corpo, bg=BRANCO)
        self.dir.pack(side="left", fill="both", expand=True, padx=(px(18), 0))

        # --- contas -------------------------------------------------------------------
        if self.editando:
            g = grupo(self.dir, "Vai para", padx=0)
            for d in post["destinos"]:
                if d["estado"] != "cancelado":
                    rotulo(g, f"{redes.NOMES.get(d['rede'], d['rede'])}   {d['nome']}").pack(anchor="w")
        else:
            self.caixa_contas = grupo(self.dir, "Postar em", padx=0)
            rotulo(self.caixa_contas, "Carregando as contas...", 9, cor=APAGADO).pack(anchor="w")

        # --- quando -------------------------------------------------------------------
        g = grupo(self.dir, "Quando", padx=0)
        self.modo_quando = tk.StringVar(value="agendar")
        if not self.editando:
            ttk.Radiobutton(g, text="Agora", value="agora", variable=self.modo_quando,
                            style="Branco.TRadiobutton", command=self.atualizar).pack(anchor="w")
            self.radio_nicho = ttk.Radiobutton(g, text="Nos próximos horários livres do nicho", value="nicho",
                                               variable=self.modo_quando, style="Branco.TRadiobutton",
                                               command=self.atualizar)
            self.radio_nicho.pack(anchor="w", pady=(px(2), 0))
            self.radio_nicho.state(["disabled"])
        linha = tk.Frame(g, bg=BRANCO)
        linha.pack(anchor="w", pady=(px(2), 0))
        if self.editando:
            rotulo(linha, "Sai em:").pack(side="left", padx=(0, px(8)))
        else:
            ttk.Radiobutton(linha, text="Agendar para:", value="agendar", variable=self.modo_quando,
                            style="Branco.TRadiobutton", command=self.atualizar).pack(side="left", padx=(0, px(8)))
        self.horario = EscolhaHorario(linha, self.atualizar)
        self.horario.pack(side="left")
        if self.editando:
            self.horario.definir(post["quando"])
        self.intervalo = None
        if n > 1:
            l2 = tk.Frame(g, bg=BRANCO)
            l2.pack(anchor="w", pady=(px(8), 0))
            rotulo(l2, "Depois, um corte a cada:").pack(side="left", padx=(0, px(8)))
            nomes = [t for t, _ in INTERVALOS]
            self.intervalo = ttk.Combobox(l2, values=nomes, state="readonly", width=10, font=fonte(10))
            self.intervalo.set(self.ultima.get("intervalo") if self.ultima.get("intervalo") in nomes else "1 dia")
            self.intervalo.bind("<<ComboboxSelected>>", lambda e: self.atualizar())
            self.intervalo.pack(side="left")
        self.previsao = rotulo(g, "", 9, cor=APAGADO)
        self.previsao.pack(anchor="w", pady=(px(6), 0))

        # --- legenda ------------------------------------------------------------------
        self.texto = None
        g = grupo(self.dir, "Legenda", padx=0)
        if n == 1 or self.editando:
            caixa = tk.Frame(g, bg=BRANCO)
            caixa.pack(fill="x")
            self.texto = tk.Text(caixa, height=6, width=56, wrap="word", font=fonte(10), bd=0, undo=True,
                                 padx=px(6), pady=px(4), highlightthickness=1, highlightbackground=BORDA,
                                 highlightcolor=AZUL)
            barra = ttk.Scrollbar(caixa, orient="vertical", command=self.texto.yview)
            self.texto.configure(yscrollcommand=barra.set)
            self.texto.pack(side="left", fill="x", expand=True)
            barra.pack(side="right", fill="y")
            self.texto.insert("1.0", (post.get("legenda") or "") if self.editando
                              else (self.itens[0].get("legenda") or self.itens[0]["titulo"]))
            self.contador = rotulo(g, "", 9, cor=APAGADO)
            self.contador.pack(anchor="e")
            self.texto.bind("<KeyRelease>", lambda e: self.contar())
            self.contar()
        else:
            rotulo(g, "Cada corte vai com a própria legenda (a mesma do POSTAGENS.txt).", 9, cor=APAGADO).pack(anchor="w")

        # --- TikTok "postar direto" (aparece quando uma conta nesse modo e marcada) ---------
        self.tiktok = grupo(self.dir, "TikTok: postar direto", padx=0, mostrar=False)

        # --- YouTube Shorts (aparece quando uma conta do YouTube e marcada) ------------------
        self.youtube = grupo(self.dir, "YouTube Shorts", padx=0, mostrar=False)
        linha = tk.Frame(self.youtube, bg=BRANCO)
        linha.pack(anchor="w")
        rotulo(linha, "Quem pode ver:", 9).pack(side="left", padx=(0, px(6)))
        self.privacidade_yt = ttk.Combobox(linha, state="readonly", width=22, font=fonte(9),
                                           values=list(redes.PRIVACIDADE_YOUTUBE.values()))
        self.privacidade_yt.current(0)
        self.privacidade_yt.pack(side="left")
        rotulo(self.youtube, f"O título do Short é o título do corte (até {redes.MAX_TITULO_YOUTUBE} letras) e "
                             "a descrição é a legenda. Corte em pé de até 3 minutos vira Short sozinho.", 9,
               cor=APAGADO, wraplength=px(430), justify="left").pack(anchor="w", pady=(px(6), 0))

        # --- andamento do envio para o site ------------------------------------------------
        self.andamento = tk.Frame(self.dir, bg=BRANCO)
        self.barra = Barra(self.andamento, largura=430, altura=18)
        self.barra.pack(anchor="w")
        self.andamento_txt = rotulo(self.andamento, "", 9, cor=APAGADO)
        self.andamento_txt.pack(anchor="w", pady=(px(3), 0))

        self.atualizar()
        previa = item_da_origem(post.get("origem")) if self.editando else self.itens[0]
        if previa:
            self.app.em_segundo_plano(lambda: imagem_do_corte(previa),
                                      lambda im: im and self.capa.config(image=self.foto(encaixar(im, wc, hc))))
        self.abrir()
        if not self.editando:
            self.carregar_contas()

    # --- contas ---------------------------------------------------------------------------
    def carregar_contas(self):
        def buscar():
            contas = redes.contas(self.app.cfg)
            try:
                self.postagens_resp = redes.postagens(self.app.cfg)  # horarios que ja estao tomados
            except redes.ErroRede:
                self.postagens_resp = None
            return contas
        self.app.em_segundo_plano(buscar, self.montar_contas)

    def montar_contas(self, r):
        if not self.existe():
            return
        caixa = self.caixa_contas
        limpar(caixa)
        self.contas, self.marcadas = [], {}
        if isinstance(r, Exception):
            rotulo(caixa, str(r), 9, cor=VERMELHO, wraplength=px(430), justify="left").pack(anchor="w")
            if isinstance(r, (redes.SemSenha, redes.SenhaErrada)):
                Botao(caixa, "Ligar ao site...", lambda: JanelaSenha(self.app, self.carregar_contas),
                      largura=130).pack(anchor="w", pady=(px(6), 0))
            else:
                Botao(caixa, "Tentar de novo", self.carregar_contas, largura=120).pack(anchor="w", pady=(px(6), 0))
            self.atualizar()
            return
        self.contas = list(r["contas"])
        if not self.contas:
            rotulo(caixa, "Nenhuma conta conectada ainda.", 9, cor=APAGADO).pack(anchor="w")
            Botao(caixa, "Conectar contas...", self.ir_para_contas, largura=140, principal=True).pack(
                anchor="w", pady=(px(6), 0))
            self.atualizar()
            return
        self.nichos = list(r.get("nichos") or [])
        nome_nicho = {n["id"]: n["nome"] for n in self.nichos}
        if self.nichos:
            linha = tk.Frame(caixa, bg=BRANCO)
            linha.pack(anchor="w", pady=(0, px(6)))
            rotulo(linha, "Nicho:").pack(side="left", padx=(0, px(8)))
            self.escolha_nicho = ttk.Combobox(linha, state="readonly", width=28, font=fonte(10),
                                              values=["(escolher as contas na mão)"] + [n["nome"] for n in self.nichos])
            self.escolha_nicho.current(0)
            self.escolha_nicho.bind("<<ComboboxSelected>>", lambda e: self.usar_nicho())
            self.escolha_nicho.pack(side="left")
        antes = set(self.ultima.get("contas") or [])
        boas = [c for c in self.contas if not c.get("problema")]
        for c in self.contas:
            marcada = (c["id"] in antes) if antes else len(boas) <= 2
            var = tk.BooleanVar(value=marcada and not c.get("problema"))
            texto = f"{redes.NOMES[c['rede']]}   {redes.nome_conta(c)}"
            if c.get("nicho") in nome_nicho:
                texto += f"   · {nome_nicho[c['nicho']]}"
            if c["rede"] == "tiktok":
                texto += "   (postar direto)" if c.get("modo") == "direto" else "   (rascunho)"
            if c.get("problema"):
                texto += "   (precisa conectar de novo)"
            cb = ttk.Checkbutton(caixa, text=texto, variable=var, style="Branco.TCheckbutton", command=self.atualizar)
            if c.get("problema"):
                cb.state(["disabled"])
            cb.pack(anchor="w", pady=px(1))
            self.marcadas[c["id"]] = var
        # Da ultima vez foi por nicho? Comeca no mesmo nicho (e nos horarios dele, se foi assim)
        ultimo = next((i for i, n in enumerate(self.nichos) if n["id"] == self.ultima.get("nicho")), None)
        if ultimo is not None and self.escolha_nicho is not None:
            self.escolha_nicho.current(ultimo + 1)
            self.usar_nicho(self.ultima.get("modo") == "nicho")
        self.atualizar()

    def nicho_atual(self):
        if self.escolha_nicho is None or self.escolha_nicho.current() <= 0:
            return None
        return self.nichos[self.escolha_nicho.current() - 1]

    def usar_nicho(self, nos_horarios=True):
        """Escolheu um nicho: marca so as contas dele e, se ele tem grade, usa os proximos horarios livres."""
        nicho = self.nicho_atual()
        if nicho:
            for c in self.contas:
                self.marcadas[c["id"]].set(c.get("nicho") == nicho["id"] and not c.get("problema"))
            if nos_horarios and nicho["horarios"].get("horas"):
                self.modo_quando.set("nicho")
        if not (nicho and nicho["horarios"].get("horas")) and self.modo_quando.get() == "nicho":
            self.modo_quando.set("agendar")
        self.atualizar()

    def ir_para_contas(self):
        self.destroy()
        self.app.abrir_aba("contas")

    def escolhidas(self):
        return [c for c in self.contas if self.marcadas.get(c["id"]) is not None and self.marcadas[c["id"]].get()]

    def diretas(self):
        return [c for c in self.escolhidas() if c["rede"] == "tiktok" and c.get("modo") == "direto"]

    # --- horario e textos -------------------------------------------------------------------
    def passo(self):
        return dict(INTERVALOS).get(self.intervalo.get(), 86400) if self.intervalo else 0

    def horarios_do_lote(self):
        """Um horario (epoch) para cada corte, conforme o "Quando" escolhido.
        Devolve (lista, problema); a lista sai vazia quando nao da."""
        n = max(1, len(self.itens))
        modo = self.modo_quando.get()
        if modo == "nicho":
            nicho = self.nicho_atual()
            if not nicho:
                return [], "Escolha o nicho."
            ids = [c["id"] for c in self.escolhidas()] or [c["id"] for c in self.contas if c.get("nicho") == nicho["id"]]
            lista = redes.proximos_horarios(nicho["horarios"], n, redes.ocupados(self.postagens_resp, ids))
            if len(lista) < n:
                return [], f"Só achei {len(lista)} horário(s) livre(s) do nicho nos próximos 90 dias."
            return lista, None
        inicio = time.time() if modo == "agora" else self.horario.epoch()
        if inicio is None:
            return [], "Confira a hora digitada."
        return [inicio + i * self.passo() for i in range(n)], None

    def atualizar(self):
        """Refaz a previsao do horario e o texto do botao; mostra ou esconde o TikTok."""
        modo = self.modo_quando.get()
        agora = modo == "agora"
        self.horario.habilitar(modo == "agendar" or self.editando)
        if self.intervalo is not None:
            self.intervalo.configure(state="disabled" if modo == "nicho" else "readonly")
        if not self.editando:
            nicho = self.nicho_atual()
            com_grade = bool(nicho and nicho["horarios"].get("horas"))
            self.radio_nicho.state(["!disabled"] if com_grade else ["disabled"])
            self.radio_nicho.configure(text=f"Nos próximos horários livres do {nicho['nome']}: "
                                            f"{redes.texto_horarios(nicho['horarios'])}" if com_grade
                                       else "Nos próximos horários livres do nicho (escolha um nicho com horários)")
        n = max(1, len(self.itens))
        lista, problema = self.horarios_do_lote()
        if problema:
            self.previsao.config(text=problema)
        elif n == 1:
            self.previsao.config(text="Sai assim que terminar de enviar para o site." if agora
                                 else f"Sai {redes.data_hora(lista[0])}.")
        else:
            primeiro = "assim que enviar" if agora else redes.data_hora(lista[0])
            if modo == "nicho" and n <= 5:  # poucos cortes: mostra o horario de cada um
                self.previsao.config(text="Vão sair: " + ", ".join(redes.data_hora(x) for x in lista) + ".")
            else:
                self.previsao.config(text=f"1º corte {primeiro}, último {redes.data_hora(lista[-1])}.")
        if self.editando:
            self.ok.mudar("Salvar")
        elif agora and n == 1:
            self.ok.mudar("Postar agora")
        else:
            self.ok.mudar("Agendar" if n == 1 else f"Agendar {n} cortes")
        if not self.editando:
            self.atualizar_tiktok()
            self.atualizar_youtube()

    def atualizar_youtube(self):
        moldura = self.youtube.master
        if not any(c["rede"] == "youtube" for c in self.escolhidas()):
            moldura.pack_forget()
        elif not moldura.winfo_ismapped():
            moldura.pack(fill="x", pady=(0, px(12)))

    def contar(self):
        n = len(self.texto.get("1.0", "end-1c"))
        self.contador.config(text=f"{n} de {redes.MAX_LEGENDA} letras", fg=VERMELHO if n > redes.MAX_LEGENDA else APAGADO)

    def legenda(self):
        return self.texto.get("1.0", "end-1c").strip() if self.texto else None

    # --- TikTok postar direto (regras do TikTok: escolher a privacidade sem nada marcado,
    #     interacoes desmarcadas, divulgacao comercial e o aviso de musica) -----------------
    def atualizar_tiktok(self):
        diretas = self.diretas()
        moldura = self.tiktok.master
        if not diretas:
            moldura.pack_forget()
            return
        if not moldura.winfo_ismapped():
            moldura.pack(fill="x", pady=(0, px(12)))
        chave = tuple(c["id"] for c in diretas)
        if chave == self.chave_tiktok:
            return
        self.chave_tiktok, self.infos_tiktok = chave, None
        limpar(self.tiktok)
        rotulo(self.tiktok, "Lendo as opções da conta no TikTok...", 9, cor=APAGADO).pack(anchor="w")
        self.app.em_segundo_plano(lambda: [redes.tiktok_info(self.app.cfg, c["id"]) for c in diretas],
                                  lambda r: chave == self.chave_tiktok and self.montar_tiktok(r))

    def montar_tiktok(self, infos):
        if not self.existe():
            return
        limpar(self.tiktok)
        if isinstance(infos, Exception):
            rotulo(self.tiktok, f"Não consegui ler as opções da conta: {infos}", 9, cor=VERMELHO,
                   wraplength=px(430), justify="left").pack(anchor="w")
            return
        self.infos_tiktok = infos
        nomes = ", ".join(i.get("creator_nickname") or i.get("creator_username") or "?" for i in infos)
        rotulo(self.tiktok, f"Conta: {nomes}", 9, "semi").pack(anchor="w")
        opcoes = None
        for i in infos:
            o = list(i.get("privacy_level_options") or [])
            opcoes = o if opcoes is None else [x for x in opcoes if x in o]
        self.privacidades = opcoes or []
        self.privs_visiveis = list(self.privacidades)
        linha = tk.Frame(self.tiktok, bg=BRANCO)
        linha.pack(anchor="w", pady=(px(6), 0))
        rotulo(linha, "Quem pode ver:").pack(side="left", padx=(0, px(8)))
        self.privacidade = ttk.Combobox(linha, state="readonly", width=24, font=fonte(10),
                                        values=[redes.PRIVACIDADE.get(x, x) for x in self.privacidades])
        self.privacidade.pack(side="left")  # comeca sem nada: o TikTok exige que a pessoa escolha
        linha = tk.Frame(self.tiktok, bg=BRANCO)
        linha.pack(anchor="w", pady=(px(6), 0))
        self.permitir = {}
        for chave, texto, campo in (("comentarios", "Permitir comentários", "comment_disabled"),
                                    ("dueto", "Permitir dueto", "duet_disabled"),
                                    ("stitch", "Permitir stitch", "stitch_disabled")):
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(linha, text=texto, variable=var, style="Branco.TCheckbutton")
            if any(i.get(campo) for i in infos):
                cb.state(["disabled"])  # desligado nas configuracoes da conta no TikTok
            cb.pack(side="left", padx=(0, px(12)))
            self.permitir[chave] = var
        self.comercial, self.sua_marca, self.de_marca = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        self.cb_comercial = ttk.Checkbutton(self.tiktok, text="Divulgação de conteúdo comercial", variable=self.comercial,
                                            style="Branco.TCheckbutton", command=self.atualizar_comercial)
        self.cb_comercial.pack(anchor="w", pady=(px(6), 0))
        self.caixa_comercial = tk.Frame(self.tiktok, bg=BRANCO)
        ttk.Checkbutton(self.caixa_comercial, text='Sua marca (o vídeo fica marcado como "Conteúdo promocional")',
                        variable=self.sua_marca, style="Branco.TCheckbutton",
                        command=self.atualizar_comercial).pack(anchor="w", padx=(px(22), 0))
        ttk.Checkbutton(self.caixa_comercial, text='Conteúdo de marca (fica marcado como "Parceria paga")',
                        variable=self.de_marca, style="Branco.TCheckbutton",
                        command=self.atualizar_comercial).pack(anchor="w", padx=(px(22), 0))
        self.consentimento = rotulo(self.tiktok, "", 9, wraplength=px(430), justify="left")
        self.consentimento.pack(anchor="w", pady=(px(6), 0))
        self.max_duracao = min(int(i.get("max_video_post_duration_sec") or 0) or 600 for i in infos)
        rotulo(self.tiktok, "O TikTok pode levar alguns minutos para mostrar o vídeo no perfil. Até aprovar o "
                            "seu app, só funciona \"Só eu\", com a conta privada.", 9, cor=APAGADO,
               wraplength=px(430), justify="left").pack(anchor="w", pady=(px(4), 0))
        self.atualizar_comercial()

    def atualizar_comercial(self):
        if self.comercial.get():
            self.caixa_comercial.pack(anchor="w", after=self.cb_comercial)
        else:
            self.caixa_comercial.pack_forget()
        marca = self.comercial.get() and self.de_marca.get()
        # Conteudo de marca nao pode ser "Só eu" (regra do TikTok): a opcao some da lista
        atual = self.privacidade_escolhida()
        self.privs_visiveis = [x for x in self.privacidades if not (marca and x == "SELF_ONLY")]
        self.privacidade.configure(values=[redes.PRIVACIDADE.get(x, x) for x in self.privs_visiveis])
        if atual in self.privs_visiveis:
            self.privacidade.current(self.privs_visiveis.index(atual))
        else:
            self.privacidade.set("")
        self.consentimento.config(text=(
            "Ao postar, você concorda com a Política de Conteúdo de Marca e a Confirmação de Uso de Música do TikTok."
            if marca else "Ao postar, você concorda com a Confirmação de Uso de Música do TikTok."))

    def privacidade_escolhida(self):
        i = self.privacidade.current()
        return self.privs_visiveis[i] if 0 <= i < len(self.privs_visiveis) else None

    def opcoes_tiktok(self):
        if self.infos_tiktok is None:
            raise ValueError("Espere carregar as opções do TikTok (ou desmarque a conta).")
        priv = self.privacidade_escolhida()
        if not priv:
            raise ValueError("Escolha quem pode ver o vídeo no TikTok.")
        comercial = self.comercial.get()
        if comercial and not (self.sua_marca.get() or self.de_marca.get()):
            raise ValueError("Em conteúdo comercial, marque Sua marca, Conteúdo de marca ou os dois.")
        return {"privacidade": priv,
                **{k: v.get() for k, v in self.permitir.items()},
                "sua_marca": comercial and self.sua_marca.get(),
                "conteudo_de_marca": comercial and self.de_marca.get()}

    # --- confirmar ----------------------------------------------------------------------------
    def erro(self, texto):
        self.msg.config(text=texto)

    def confirmar(self):
        if self.enviando:
            return
        self.erro("")
        if self.editando:
            self.salvar_edicao()
            return
        escolhidas = self.escolhidas()
        if not escolhidas:
            self.erro("Marque pelo menos uma conta.")
            return
        agora = self.modo_quando.get() == "agora"
        quandos, problema = self.horarios_do_lote()
        if problema:
            self.erro(problema)
            return
        if not agora and quandos[0] < time.time() + 60:
            self.erro("Esse horário já passou. Escolha outro (ou marque Agora).")
            return
        legenda = self.legenda()
        if legenda is not None and len(legenda) > redes.MAX_LEGENDA:
            self.erro(f"A legenda passa de {redes.MAX_LEGENDA} letras.")
            return
        opcoes_tt, maximo = {}, 0
        if self.diretas():
            try:
                opcoes_tt = self.opcoes_tiktok()
            except ValueError as e:
                self.erro(str(e))
                return
            maximo = self.max_duracao
        opcoes_yt = {"privacidade": list(redes.PRIVACIDADE_YOUTUBE)[max(self.privacidade_yt.current(), 0)]}
        limite_yt = redes.MAX_SHORT if any(c["rede"] == "youtube" for c in escolhidas) else 0
        destinos = [{"conta": c["id"],
                     "opcoes": opcoes_tt if c["rede"] == "tiktok" and c.get("modo") == "direto"
                     else opcoes_yt if c["rede"] == "youtube" else {}}
                    for c in escolhidas]
        nicho = self.nicho_atual()
        gravar_json(ARQ_ULTIMA_POSTAGEM, {"contas": [c["id"] for c in escolhidas],
                                          "nicho": nicho["id"] if nicho else None,
                                          "modo": self.modo_quando.get(),
                                          "intervalo": self.intervalo.get() if self.intervalo
                                          else self.ultima.get("intervalo")})
        self.enviando = True
        self.ok.ativar(False)
        self.andamento.pack(fill="x", pady=(0, px(8)))
        self.barra.mudar(0)
        self.andamento_txt.config(text="Enviando para o site...")
        cfg, itens = self.app.cfg, list(self.itens)

        def trabalho():
            feitos = []
            try:
                for i, item in enumerate(itens):
                    if self.cancelado:
                        raise redes.ErroRede("Envio cancelado.")
                    if maximo or limite_yt:
                        dur = cortes.info_video(item["arquivo"])["dur"]
                        if maximo and dur > maximo:
                            raise redes.ErroRede(f"O corte {item['numero']:02d} tem {dur:.0f} s, e essa conta do "
                                                 f"TikTok só aceita até {maximo} s.")
                        if limite_yt and dur > limite_yt:
                            raise redes.ErroRede(f"O corte {item['numero']:02d} tem {dur:.0f} s, e o YouTube "
                                                 "Shorts só aceita até 3 minutos.")
                    quando = quandos[i]
                    if agora:
                        quando = max(quando, time.time())
                    leg = legenda if legenda is not None else (item.get("legenda") or item["titulo"])
                    redes.agendar(cfg, item, quando, leg, destinos,
                                  lambda f, i=i: self.app.fila.put((self.mostrar_andamento, (i, f))),
                                  lambda: self.cancelado)
                    feitos.append(item)
            except Exception as e:
                if not isinstance(e, redes.ErroRede):
                    registrar_erro(traceback.format_exc())
                return {"feitos": feitos, "erro": e}
            return {"feitos": feitos, "erro": None}
        self.app.em_segundo_plano(trabalho, lambda r: self.terminou(r, agora))

    def mostrar_andamento(self, dados):
        i, fracao = dados
        if not self.existe() or self.cancelado:
            return
        n = len(self.itens)
        self.barra.mudar((i + fracao) / n * 100)
        qual = f" o corte {i + 1} de {n}" if n > 1 else ""
        self.andamento_txt.config(text=f"Enviando para o site{qual}... {int(fracao * 100)}%")

    def terminou(self, r, agora):
        self.enviando = False
        if isinstance(r, Exception):
            r = {"feitos": [], "erro": r}
        feitos, erro, n = r["feitos"], r["erro"], len(self.itens)
        tela = self.app.telas["postagens"]
        if self.app.atual is tela:
            tela.recarregar()
        if self.cancelado:
            if self.existe():
                self.destroy()
            if feitos:
                self.app.aviso_rapido(f"Parei o envio. {len(feitos)} corte(s) já tinham ficado agendados.")
            return
        if erro is not None and not feitos:
            if self.existe():
                self.ok.ativar(True)
                self.andamento.pack_forget()
                self.erro(str(erro))
            return
        if self.existe():
            self.destroy()
        if erro is not None:
            messagebox.showinfo(NOME, f"{len(feitos)} de {n} cortes foram agendados. O resto deu erro:\n\n{erro}",
                                parent=self.app.raiz)
        elif agora:
            self.app.aviso_rapido("Enviado! O site já está postando. O aviso chega no WhatsApp quando sair.")
        else:
            self.app.aviso_rapido(("Postagem agendada!" if n == 1 else f"{n} cortes agendados!")
                                  + " Veja na aba Postagens.")
        self.app.empurrar_postagens(agora=agora)

    def salvar_edicao(self):
        quando = self.horario.epoch()
        if quando is None:
            self.erro("Confira a hora digitada.")
            return
        if quando < time.time() + 60:
            self.erro("Esse horário já passou. Escolha outro.")
            return
        legenda = self.legenda()
        if len(legenda) > redes.MAX_LEGENDA:
            self.erro(f"A legenda passa de {redes.MAX_LEGENDA} letras.")
            return
        self.enviando = True
        self.ok.ativar(False)

        def depois(res):
            self.enviando = False
            if isinstance(res, Exception):
                if self.existe():
                    self.ok.ativar(True)
                    self.erro(str(res))
                return
            if self.existe():
                self.destroy()
            self.app.aviso_rapido("Postagem mudada.")
            self.app.telas["postagens"].recarregar()
        self.app.em_segundo_plano(lambda: redes.editar(self.app.cfg, self.post["id"], quando, legenda), depois)

    def fechar(self):
        if self.enviando and not self.editando:
            if not messagebox.askyesno(NOME, "Parar o envio para o site?", parent=self):
                return
            self.cancelado = True
            self.andamento_txt.config(text="Parando...")
            return  # a janela fecha quando o envio parar
        self.destroy()


class JanelaAjustes(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.raiz, bg=BRANCO)
        self.app = app
        self.title(f"Ajustes - {NOME}")
        self.resizable(False, False)
        self.transient(app.raiz)
        if ICONE_ICO.exists():
            self.iconbitmap(str(ICONE_ICO))
        cfg = app.cfg

        comandos = barra_de_comandos(self)
        Botao(comandos, "Cancelar", self.destroy, largura=90).pack(side="right")
        Botao(comandos, "Salvar", self.salvar, largura=90, principal=True).pack(side="right", padx=px(8))
        instrucao(self, "Ajustes dos cortes")

        legenda = grupo(self, "Legenda")
        rotulo(legenda, "Cor da palavra em destaque:").pack(anchor="w")
        self.cor = cfg["video"]["cor_destaque"].strip().lower() or "amarelo"
        self.cores = tk.Canvas(legenda, width=px(9 * 34), height=px(34), bg=BRANCO,
                               highlightthickness=0, cursor="hand2")
        self.cores.pack(anchor="w", pady=(px(6), px(2)))
        self.cores.bind("<Button-1>", self.clicar_cor)
        self.nome_cor = rotulo(legenda, "", 9, cor=APAGADO)
        self.nome_cor.pack(anchor="w")
        self.desenhar_cores()
        rotulo(legenda, "Crédito do canal original (aparece no vídeo):").pack(anchor="w", pady=(px(10), 0))
        self.credito = self.campo(legenda, cfg["video"]["credito"], "Exemplo: @nomedocanal")

        geral = grupo(self, "Cortes")
        rotulo(geral, "Quantos cortes por vídeo:").pack(anchor="w")
        padrao = int(cfg["geral"]["quantidade_cortes"] or 5)
        self.qtd = EscolhaQtd(geral, sorted(set(QTDS + [padrao])), padrao)
        self.qtd.pack(anchor="w", pady=(px(4), px(10)))
        rotulo(geral, "Assunto do canal (ajuda a inteligência artificial a escolher):").pack(anchor="w")
        self.tema = self.campo(geral, cfg["ia"]["tema_do_canal"], "Exemplo: podcast de tecnologia, com humor")

        baixador = grupo(self, "Baixador de vídeos (yt-dlp)")
        linha = tk.Frame(baixador, bg=BRANCO)
        linha.pack(fill="x")
        self.versao = rotulo(linha, "Versão: conferindo...", 10)
        self.versao.pack(side="left")
        self.atualizar = Botao(linha, "Atualizar o baixador", self.atualizar_baixador, largura=160)
        self.atualizar.pack(side="right")
        rotulo(baixador, "O YouTube muda sempre. Se um link parar de baixar, clique em Atualizar.", 9,
               cor=APAGADO).pack(anchor="w", pady=(px(4), 0))
        app.em_segundo_plano(controle.versao_ytdlp, self.mostrar_versao)

        self.montar_modelo_local(cfg)
        self.grab_set()

    # --- modelo de IA local (carregado pelo lms do LM Studio, sem abrir a janela dele) ---
    def montar_modelo_local(self, cfg):
        ia = grupo(self, "Modelo de IA local (roda na placa de vídeo)")
        rotulo(ia, "Pasta dos modelos (.gguf):").pack(anchor="w")
        linha = tk.Frame(ia, bg=BRANCO)
        linha.pack(fill="x", pady=(px(3), 0))
        self.pasta = ttk.Entry(linha, font=fonte(10), width=52)
        self.pasta.insert(0, controle.opcao_ia(cfg, "pasta_modelos") or controle.PASTA_MODELOS_PADRAO)
        self.pasta.pack(side="left", ipady=px(2))
        self.pasta.bind("<Return>", lambda e: self.atualizar_ia())
        Botao(linha, "Procurar...", self.escolher_pasta, largura=90, altura=26).pack(side="left", padx=(px(8), 0))
        rotulo(ia, "Baixe o arquivo .gguf, ponha nesta pasta, escolha na lista e clique em Carregar.", 9,
               cor=APAGADO).pack(anchor="w")

        quadro = tk.Frame(ia, bg=BRANCO)
        quadro.pack(fill="x", pady=(px(8), 0))
        self.lista = ttk.Treeview(quadro, columns=("modelo", "tamanho", "situacao"), show="headings",
                                  height=5, selectmode="browse")
        self.lista.heading("modelo", text="Modelo", anchor="w")
        self.lista.heading("tamanho", text="Tamanho", anchor="e")
        self.lista.heading("situacao", text="Situação", anchor="w")
        self.lista.column("modelo", width=px(330), stretch=True)
        self.lista.column("tamanho", width=px(80), anchor="e", stretch=False)
        self.lista.column("situacao", width=px(160), stretch=False)
        self.lista.tag_configure("carregado", foreground=VERDE)
        rolar = ttk.Scrollbar(quadro, orient="vertical", command=self.lista.yview)
        self.lista.configure(yscrollcommand=rolar.set)
        self.lista.pack(side="left", fill="x", expand=True)
        rolar.pack(side="left", fill="y")
        self.lista.bind("<Double-1>", lambda e: self.carregar_modelo())
        self.itens_ia = {}

        botoes = tk.Frame(ia, bg=BRANCO)
        botoes.pack(fill="x", pady=(px(8), 0))
        self.b_carregar = Botao(botoes, "Carregar", self.carregar_modelo, largura=100, principal=True)
        self.b_carregar.pack(side="left")
        self.b_descarregar = Botao(botoes, "Descarregar", self.descarregar_modelo, largura=110)
        self.b_descarregar.pack(side="left", padx=(px(8), 0))
        self.b_testar = Botao(botoes, "Testar", self.testar_modelo, largura=80)
        self.b_testar.pack(side="left", padx=(px(8), 0))
        link(botoes, "Atualizar a lista", self.atualizar_ia).pack(side="right")

        self.situacao_ia = rotulo(ia, "Conferindo...", 9, justify="left", anchor="w", wraplength=px(600))
        self.situacao_ia.pack(fill="x", pady=(px(8), 0))
        self.placa_ia = rotulo(ia, "", 9, justify="left", anchor="w")
        self.placa_ia.pack(fill="x")
        self.resposta_ia = rotulo(ia, "", 9, cor=APAGADO, justify="left", anchor="w", wraplength=px(600))
        self.resposta_ia.pack(fill="x")
        linha_api = tk.Frame(ia, bg=BRANCO)
        linha_api.pack(fill="x", pady=(px(4), 0))
        self.url_api = controle.url_lm(cfg)
        rotulo(linha_api, f"Endereço para o app e para scripts: {self.url_api}", 9,
               cor=APAGADO).pack(side="left")
        link(linha_api, "Copiar", self.copiar_endereco).pack(side="left", padx=(px(8), 0))

        self.ocupado = False
        self.carregado = None   # chave do modelo de texto carregado agora (para o Testar)
        self.atualizar_ia()

    def pasta_ia(self):
        return Path(os.path.expandvars(os.path.expanduser(self.pasta.get().strip()
                                                          or controle.PASTA_MODELOS_PADRAO)))

    def pasta_ia_para_salvar(self):
        """Vazio quando e a pasta do LM Studio (o padrao); senao o caminho por extenso
        (o .ini trata o % de %USERPROFILE% como formula)."""
        pasta = self.pasta_ia()
        padrao = Path(os.path.expandvars(controle.PASTA_MODELOS_PADRAO))
        return "" if str(pasta).rstrip("\\/").lower() == str(padrao).lower() else str(pasta)

    def escolher_pasta(self):
        inicio = self.pasta_ia()
        pasta = filedialog.askdirectory(parent=self, title="Pasta dos modelos (.gguf)",
                                        initialdir=str(inicio) if inicio.is_dir() else str(Path.home()))
        if pasta:
            self.pasta.delete(0, "end")
            self.pasta.insert(0, str(Path(pasta)))
            cortes.salvar_opcao("ia", "pasta_modelos", self.pasta_ia_para_salvar())
            self.atualizar_ia()

    def ocupar(self, texto):
        self.ocupado = True
        for b in (self.b_carregar, self.b_descarregar, self.b_testar):
            b.ativar(False)
        self.mostrar_ia(texto, cor=AZUL_ESCURO)

    def liberar(self):
        self.ocupado = False
        for b in (self.b_carregar, self.b_descarregar, self.b_testar):
            b.ativar(True)

    def mostrar_ia(self, texto, cor=TEXTO):
        if self.winfo_exists():
            self.situacao_ia.config(text=texto, fg=cor)

    def atualizar_ia(self):
        """Procura os .gguf da pasta e confere o que esta carregado (no app ou no LM Studio)."""
        if self.ocupado:
            return
        self.ocupar("Conferindo os modelos...")
        pasta, cfg = self.pasta_ia(), self.app.cfg

        def olhar():
            arquivos = controle.listar_gguf(pasta)
            sit = controle.situacao_modelo_local(cfg)
            proprio = sit["proprio"]
            for item in arquivos:
                if proprio and controle._mesmo_arquivo(proprio.get("arquivo", ""), item["arquivo"]):
                    item["situacao"] = "app"
                elif controle.modelo_do_arquivo(item["arquivo"], sit["lmstudio"]):
                    item["situacao"] = "lmstudio"
                else:
                    item["situacao"] = ""
            return pasta, arquivos, sit
        self.app.em_segundo_plano(olhar, self.mostrar_modelos)

    def mostrar_modelos(self, resultado):
        if not self.winfo_exists():
            return
        self.liberar()
        if isinstance(resultado, Exception):
            self.mostrar_ia(f"Não consegui conferir os modelos: {resultado}", cor=VERMELHO)
            return
        pasta, arquivos, sit = resultado
        escolhido = self.item_escolhido()
        self.lista.delete(*self.lista.get_children())
        self.itens_ia = {}
        gb = lambda b: f"{b / 1024 ** 3:.1f}".replace(".", ",")  # noqa: E731
        for item in arquivos:
            situacao = {"app": "✔ Carregado", "lmstudio": "No LM Studio"}.get(item["situacao"], "")
            iid = self.lista.insert("", "end", values=(item["nome"], f"{gb(item['bytes'])} GB", situacao),
                                    tags=("carregado",) if item["situacao"] == "app" else ())
            self.itens_ia[iid] = item
            if (escolhido and item["arquivo"] == escolhido["arquivo"]) or (not escolhido and item["situacao"]):
                self.lista.selection_set(iid)
                self.lista.see(iid)

        proprio, lmstudio = sit["proprio"], sit["lmstudio"]
        self.carregado = (proprio.get("apelido") if proprio else
                          lmstudio[0].get("identifier") if lmstudio else None)
        if not sit["motor"]:
            texto, cor = ("Falta o motor llama.cpp com Vulkan. Ele vem com o LM Studio: abra o LM Studio e "
                          "baixe o \"Vulkan llama.cpp\" na aba Runtime.", VERMELHO)
        elif proprio:
            ram = sit.get("ram_proprio")
            texto = f"Carregado: {Path(proprio.get('arquivo', '')).name} (nome na API: {proprio.get('apelido')})."
            if sit.get("saude") != "ok":
                texto += "\nAinda carregando..."
            texto += ("\nO modelo inteiro está na placa de vídeo." if sit.get("inteiro_na_placa") else
                      "\nNão coube inteiro: uma parte está no processador e na RAM.")
            if ram is not None:
                texto += f" RAM usada pelo modelo: {gb(ram)} GB."
            cor = VERDE
        elif lmstudio or sit["lmstudio_motores"]:
            nomes = ", ".join(c.get("identifier", "?") for c in lmstudio) or "um modelo"
            texto = (f"O LM Studio está com {nomes} carregado, prendendo uma cópia na RAM.\n"
                     "Clique em Carregar para o app assumir sem ocupar a RAM.")
            cor = AZUL_ESCURO
        elif sit["porta_ocupada"]:
            texto, cor = f"Outro programa está usando o endereço {self.url_api}.", VERMELHO
        else:
            texto, cor = "Nenhum modelo carregado. Escolha um na lista e clique em Carregar.", TEXTO
        if not arquivos:
            texto += ("\nNão achei nenhum .gguf nesta pasta." if pasta.is_dir() else
                      "\nEssa pasta não existe.")
        self.mostrar_ia(texto, cor=cor)
        self.placa_ia.config(text="Placa de vídeo: conferindo a memória...")
        self.app.em_segundo_plano(controle.memoria_da_placa, self.mostrar_placa)

    def mostrar_placa(self, placa):
        if not self.winfo_exists():
            return
        if isinstance(placa, Exception) or not placa:
            self.placa_ia.config(text="")
            return
        nome, usado, total = placa
        gb = lambda b: f"{b / 1024 ** 3:.1f}".replace(".", ",")  # noqa: E731
        inicio = f"Placa de vídeo{' ' + nome if nome else ''}: "
        if usado is None:
            texto = inicio + f"{gb(total)} GB de memória."
        else:
            texto = inicio + f"{gb(usado)}" + (f" de {gb(total)} GB em uso." if total else " GB em uso.")
        ram = controle.ram_do_pc()
        if ram:
            texto += f"  RAM livre no PC: {gb(ram[0])} de {gb(ram[1])} GB."
        self.placa_ia.config(text=texto)

    def item_escolhido(self):
        sel = self.lista.selection()
        return self.itens_ia.get(sel[0]) if sel else None

    def carregar_modelo(self, trocar=None):
        if self.ocupado:
            return
        item = self.item_escolhido()
        if not item:
            self.mostrar_ia("Escolha um modelo na lista primeiro.", cor=VERMELHO)
            return
        arq = item["arquivo"]
        cortes.salvar_opcao("ia", "pasta_modelos", self.pasta_ia_para_salvar())
        self.resposta_ia.config(text="")
        self.ocupar(f"Carregando {arq.name}...")
        cfg = self.app.cfg
        avisar = lambda texto: self.app.fila.put((lambda t: self.mostrar_ia(t, cor=AZUL_ESCURO), texto))  # noqa: E731
        self.app.em_segundo_plano(lambda: controle.carregar_modelo_local(cfg, arq, trocar, avisar),
                                  self.carregou)

    def carregou(self, r):
        if not self.winfo_exists():
            return
        self.liberar()
        if isinstance(r, Exception):
            self.mostrar_ia(f"Não consegui carregar: {r}", cor=VERMELHO)
            return
        if r.get("outros"):
            lista = "\n".join(f"  • {o}" for o in r["outros"])
            if messagebox.askyesno(
                    NOME, f"Para carregar este modelo, sai da frente:\n{lista}\n\n"
                          "Programas usando a IA agora (como a análise das lives) ficam sem resposta "
                          "por alguns segundos, até o modelo novo terminar de carregar.\n\nContinuar?",
                    parent=self):
                self.carregar_modelo(trocar=True)
            else:
                self.atualizar_ia()
            return
        if not r.get("ok"):
            self.mostrar_ia(r.get("texto") or "Não consegui carregar o modelo.", cor=VERMELHO)
            return
        self.app.recarregar_config()
        self.app.atualizar_status()
        self.app.aviso_rapido(r.get("texto") or "Modelo carregado.")
        self.atualizar_ia()

    def descarregar_modelo(self):
        if self.ocupado:
            return
        if self.carregado and not messagebox.askyesno(
                NOME, f"Descarregar o modelo {self.carregado}?\n\nA placa de vídeo e a RAM ficam livres. "
                      "Programas que estiverem usando a IA (como a análise das lives) param de receber "
                      "respostas.", parent=self):
            return
        self.resposta_ia.config(text="")
        self.ocupar("Descarregando...")
        cfg = self.app.cfg

        def pronto(r):
            if not self.winfo_exists():
                return
            self.liberar()
            if isinstance(r, Exception):
                self.mostrar_ia(f"Não consegui descarregar: {r}", cor=VERMELHO)
                return
            ok, texto = r
            self.app.atualizar_status()
            if not ok:
                self.mostrar_ia(texto, cor=VERMELHO)
                return
            self.app.aviso_rapido(texto)
            self.atualizar_ia()
        self.app.em_segundo_plano(lambda: controle.descarregar_modelos_locais(cfg), pronto)

    def testar_modelo(self):
        if self.ocupado:
            return
        if not self.carregado:
            self.mostrar_ia("Carregue um modelo primeiro.", cor=VERMELHO)
            return
        chave, cfg = self.carregado, self.app.cfg
        self.resposta_ia.config(text=f"Perguntando ao {chave}...", fg=AZUL_ESCURO)
        for b in (self.b_carregar, self.b_descarregar, self.b_testar):
            b.ativar(False)
        self.ocupado = True

        def pronto(r):
            if not self.winfo_exists():
                return
            self.liberar()
            if isinstance(r, Exception):
                self.resposta_ia.config(text=f"O modelo não respondeu: {r}", fg=VERMELHO)
                return
            segundos, texto = r
            tempo = f"{segundos:.1f}".replace(".", ",")
            self.resposta_ia.config(text=f"Resposta em {tempo} s: “{texto}”", fg=TEXTO)
        self.app.em_segundo_plano(lambda: controle.testar_modelo(cfg, chave), pronto)

    def copiar_endereco(self):
        self.clipboard_clear()
        self.clipboard_append(self.url_api)
        self.app.aviso_rapido("Endereço copiado.")

    def mostrar_versao(self, versao):
        if isinstance(versao, Exception) or not versao:
            self.versao.config(text="Versão: não instalado (clique em Atualizar)")
        else:
            self.versao.config(text=f"Versão: {versao}")

    def atualizar_baixador(self):
        self.atualizar.ativar(False)
        self.versao.config(text="Atualizando (pode levar 1 minuto)...")

        def pronto(resultado):
            self.atualizar.ativar(True)
            if isinstance(resultado, Exception):
                self.versao.config(text="Não consegui atualizar (sem internet?)")
                return
            ok, detalhe = resultado
            self.versao.config(text=f"Atualizado! Versão: {detalhe}" if ok else
                               "Não consegui atualizar (sem internet?)")
        self.app.em_segundo_plano(controle.atualizar_ytdlp, pronto)

    def campo(self, pai, valor, dica):
        e = ttk.Entry(pai, font=fonte(10), width=48)
        e.insert(0, valor.strip())
        e.pack(anchor="w", pady=(px(3), 0), ipady=px(2))
        rotulo(pai, dica, 9, cor=APAGADO).pack(anchor="w")
        return e

    def desenhar_cores(self):
        cv = self.cores
        cv.delete("all")
        for i, (nome, rgb) in enumerate(cortes.CORES_RGB.items()):
            x, y, t = px(3 + i * 34), px(3), px(26)
            if nome == self.cor:
                cv.create_rectangle(x - px(2), y - px(2), x + t + px(2), y + t + px(2),
                                    outline=AZUL, width=px(2))
            cv.create_rectangle(x, y, x + t, y + t, fill="#%02x%02x%02x" % rgb, outline="#707070")
        self.nome_cor.config(text=f"Escolhida: {self.cor}")

    def clicar_cor(self, e):
        i = int(e.x // px(34))
        nomes = list(cortes.CORES_RGB)
        if 0 <= i < len(nomes):
            self.cor = nomes[i]
            self.desenhar_cores()

    def salvar(self):
        cortes.salvar_opcao("video", "cor_destaque", self.cor)
        cortes.salvar_opcao("geral", "quantidade_cortes", self.qtd.valor)
        cortes.salvar_opcao("video", "credito", self.credito.get())
        cortes.salvar_opcao("ia", "tema_do_canal", self.tema.get())
        cortes.salvar_opcao("ia", "pasta_modelos", self.pasta_ia_para_salvar())
        self.app.recarregar_config()
        self.destroy()
        self.app.aviso_rapido("Ajustes salvos.")


# ----------------------------------------------------------------------------
# O app
# ----------------------------------------------------------------------------

class App:
    def __init__(self, video=None):
        global ESCALA
        try:  # letras nitidas em tela com zoom do Windows
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        identidade_windows()
        self.raiz = tk.Tk()
        ESCALA = max(1.0, self.raiz.winfo_fpixels("1i") / 96)
        self.raiz.title(NOME)
        self.raiz.configure(bg=BRANCO)
        if ICONE_ICO.exists():
            self.raiz.iconbitmap(default=str(ICONE_ICO))  # vale para todas as janelas do app
        self.raiz.after(300, lambda: preparar_fixar(self.raiz))
        larg = min(px(980), self.raiz.winfo_screenwidth() - 40)
        alt = min(px(760), self.raiz.winfo_screenheight() - 80)
        x = (self.raiz.winfo_screenwidth() - larg) // 2
        y = max(0, (self.raiz.winfo_screenheight() - alt) // 2 - 20)
        self.raiz.geometry(f"{larg}x{alt}+{x}+{y}")
        self.raiz.minsize(min(px(880), larg), min(px(680), alt))
        self.raiz.report_callback_exception = self.erro_inesperado
        self.raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        self.raiz.bind_all("<MouseWheel>", self.roda_do_mouse)
        self.estilos()

        self.fila = queue.Queue()
        self.proc = None
        self.desistir_de_comecar = False
        self.cfg = cortes.carregar_config()
        self.erro_ffmpeg = None
        try:
            cortes.FFMPEG, cortes.FFPROBE = cortes.achar_ffmpeg()
        except cortes.ErroAmigavel as e:
            self.erro_ffmpeg = str(e)

        self.montar_moldura()
        self.telas = {"inicio": TelaInicio(self), "trabalhando": TelaTrabalhando(self),
                      "pronto": TelaPronta(self), "erro": TelaErro(self)}
        if SITE:
            self.telas.update(postagens=TelaPostagens(self), contas=TelaContas(self))
        self.atual = None
        self.tela_cortes = "inicio"
        self.postagens_pendentes, self.empurrando = None, False
        self.nichos = []
        self.raiz.after(50, self.olhar_fila)
        if SITE:
            self.raiz.after(8000, self.vigiar_postagens)
        # O vigia do WhatsApp (icones ocultos, perto do relogio) liga junto com o
        # app, se este PC ja tem a senha do site. Se ja estiver ligado, nada muda.
        if zap and zap.senha(self.cfg):
            self.raiz.after(1500, lambda: self.em_segundo_plano(controle.ligar_vigia, lambda r: None))

        if self.erro_ffmpeg:
            self.ir("erro", titulo="Falta instalar uma peça", texto=formatar.texto_erro(self.erro_ffmpeg))
        elif controle.rodando_agora():
            self.ir("trabalhando")  # corte comecado pelo WhatsApp ou pelo .bat
        else:
            self.ir("inicio", video=video)

    def estilos(self):
        """Controles nativos do Windows (opcoes, caixas de grupo, campos, rolagem)."""
        estilo = ttk.Style(self.raiz)
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")
        estilo.configure("Branco.TRadiobutton", background=BRANCO, foreground=TEXTO, font=fonte(10))
        estilo.configure("Branco.TCheckbutton", background=BRANCO, foreground=TEXTO, font=fonte(10))
        estilo.configure("Treeview", font=fonte(10), rowheight=px(24))
        estilo.configure("Treeview.Heading", font=fonte(10))
        estilo.configure("Branco.TLabelframe", background=BRANCO)
        estilo.configure("Branco.TLabelframe.Label", background=BRANCO, foreground=TEXTO, font=fonte(10))

    def montar_moldura(self):
        """Faixa do topo (cores do site) e barra de status embaixo - fixas em todas as telas."""
        topo = tk.Frame(self.raiz, bg=MARINHO)
        topo.pack(side="top", fill="x")
        dentro = tk.Frame(topo, bg=MARINHO)
        dentro.pack(fill="x", padx=px(20), pady=px(10))
        arq_icone = cortes.BASE / "app_arquivos" / ("icone_66.png" if ESCALA >= 1.4 else "icone_44.png")
        if arq_icone.exists():
            self.icone = tk.PhotoImage(file=str(arq_icone))
            tk.Label(dentro, image=self.icone, bg=MARINHO).pack(side="left", padx=(0, px(12)))
        textos = tk.Frame(dentro, bg=MARINHO)
        textos.pack(side="left")
        tk.Label(textos, text=NOME, bg=MARINHO, fg="#FFFFFF", font=fonte(18, "semi")).pack(anchor="w")
        tk.Label(textos, text="Cortes de vídeos longos para TikTok, Reels e Kwai", bg=MARINHO,
                 fg=CINZA_TOPO, font=fonte(9)).pack(anchor="w")

        # Abas: o texto da aba atual fica branco, com um filete ciano embaixo
        nav = tk.Frame(dentro, bg=MARINHO)
        nav.pack(side="right", anchor="s")
        self.abas = {}
        abas = (("cortes", "Cortes"), ("postagens", "Postagens"), ("contas", "Contas")) if SITE else ()
        for chave, texto in abas:
            caixa = tk.Frame(nav, bg=MARINHO)
            caixa.pack(side="left", padx=(px(22), 0))
            r = tk.Label(caixa, text=texto, bg=MARINHO, fg=CINZA_TOPO, font=fonte(11, "semi"), cursor="hand2")
            r.pack()
            filete = tk.Frame(caixa, bg=MARINHO, height=px(3))
            filete.pack(fill="x", pady=(px(4), 0))
            r.bind("<Button-1>", lambda e, k=chave: self.abrir_aba(k))
            r.bind("<Enter>", lambda e, k=chave: self.abas[k][0].config(fg=BRANCO))
            r.bind("<Leave>", lambda e: self.marcar_aba())
            self.abas[chave] = (r, filete)
        self.aba_atual = "cortes"
        tk.Frame(self.raiz, bg=CIANO, height=px(2)).pack(side="top", fill="x")

        status = tk.Frame(self.raiz, bg=FACE)
        status.pack(side="bottom", fill="x")
        tk.Frame(status, bg="#D7D7D7", height=1).pack(side="top", fill="x")
        self.status_ia = tk.Label(status, text="", bg=FACE, fg=TEXTO, font=fonte(9), anchor="w")
        self.status_ia.pack(side="left", padx=px(10), pady=px(4))
        tk.Label(status, text="Use só vídeos de quem deixou você cortar, e sempre dê o crédito.",
                 bg=FACE, fg=APAGADO, font=fonte(9)).pack(side="right", padx=px(10))
        self.status_texto, self.status_aviso_ate = "", 0

        self.meio = tk.Frame(self.raiz, bg=BRANCO)
        self.meio.pack(fill="both", expand=True)

    # --- telas ---------------------------------------------------------------------
    def trocar(self, nome):
        """Poe a tela `nome` no lugar da atual, sem mexer no que ela mostra."""
        if self.atual is not None:
            self.atual.pack_forget()
            self.atual.ao_sair()
        self.atual = self.telas[nome]
        self.atual.pack(fill="both", expand=True)
        if nome in TELAS_CORTES:
            self.tela_cortes = nome
        self.aba_atual = "cortes" if nome in TELAS_CORTES else nome
        self.marcar_aba()

    def ir(self, nome, **kw):
        self.trocar(nome)
        self.atual.mostrar(**kw)

    def abrir_aba(self, aba):
        """Clique numa aba do topo. "Cortes" volta para onde estava (sem perder
        o video escolhido nem o andamento de um corte rodando)."""
        if aba != "cortes":
            if self.atual is not self.telas[aba]:
                self.ir(aba)
            return
        nome = self.tela_cortes
        if self.atual is self.telas[nome]:
            return
        self.trocar(nome)
        if nome == "trabalhando":
            self.atual.ligar()
        elif nome == "inicio":
            self.atual.montar_recentes()

    def voltar_ao_inicio(self, aviso=None):
        """Botao Voltar: volta para a tela inicial SEM esquecer o video escolhido
        (o "Fazer outro video" e que comeca do zero)."""
        self.trocar("inicio")
        self.atual.montar_recentes()
        self.atualizar_status()
        if aviso:
            self.aviso_rapido(aviso)

    def marcar_aba(self):
        for chave, (r, filete) in self.abas.items():
            ativa = chave == self.aba_atual
            r.config(fg=BRANCO if ativa else CINZA_TOPO)
            filete.config(bg=CIANO if ativa else MARINHO)

    def programar(self, itens):
        if not itens:
            self.aviso_rapido("Não tem corte aqui para programar.")
            return
        JanelaAgendar(self, itens=itens)

    def vigiar_postagens(self):
        """Com o app aberto, da um empurrao no agendador do site (o Cron dele faz
        isso sozinho; assim sai na hora certa mesmo sem o Cron). A cada 1 min se
        tem postagem esperando, senao a cada 5 min."""
        self.empurrar_postagens()
        self.raiz.after(60_000 if self.postagens_pendentes else 300_000, self.vigiar_postagens)

    def empurrar_postagens(self, agora=False):
        if not SITE or self.empurrando or not redes.ligado(self.cfg):
            return
        self.empurrando = True

        def rodar():
            try:
                return redes.processar(self.cfg)
            except redes.ErroRede:
                return None  # site fora do ar ou sem a parte das redes: tenta depois

        def depois(r):
            self.empurrando = False
            if isinstance(r, dict):
                self.postagens_pendentes = r.get("pendentes")
                if (r.get("feitos") or agora) and self.atual is self.telas["postagens"]:
                    self.telas["postagens"].recarregar()
        self.em_segundo_plano(rodar, depois)

    def atualizar_status(self):
        """Barra de status: a IA esta ligada? os avisos do WhatsApp estao ligados?"""
        def mostrar(ligado):
            if ligado is True:
                ia = "Inteligência artificial: ligada"
            elif controle.pode_ligar_lm(self.cfg):
                ia = "Inteligência artificial: desligada (ela é ligada sozinha quando precisar)"
            else:
                ia = "Inteligência artificial: desligada. Peça para um adulto abrir o LM Studio"
            if zap and zap.avisos_ligados(self.cfg):
                ia += "    |    Avisos no WhatsApp: ligados"
            self.status_texto = ia
            if time.time() >= self.status_aviso_ate:
                self.status_ia.config(text=ia, fg=TEXTO, font=fonte(9))
        self.em_segundo_plano(lambda: controle.lm_ligado(self.cfg, timeout=2), mostrar)

    def aviso_rapido(self, texto):
        """Mensagem passageira na barra de status (como o Windows faz)."""
        self.status_aviso_ate = time.time() + 4
        self.status_ia.config(text=texto, fg=AZUL_ESCURO, font=fonte(9, "semi"))

        def voltar():
            if time.time() >= self.status_aviso_ate:
                self.status_ia.config(text=self.status_texto, fg=TEXTO, font=fonte(9))
        self.raiz.after(4100, voltar)

    def abrir_ajustes(self):
        JanelaAjustes(self)

    def recarregar_config(self):
        self.cfg = cortes.carregar_config()
        inicio = self.telas["inicio"]
        padrao = int(self.cfg["geral"]["quantidade_cortes"] or 5)
        if padrao in inicio.qtd.botoes:
            inicio.qtd.mudar(padrao)
        if inicio.tipo.get() != tipo_salvo(self.cfg):
            inicio.tipo.set(tipo_salvo(self.cfg))
            inicio.mostrar_tipo()
            inicio.atualizar_botoes()

    def roda_do_mouse(self, e):
        try:
            if e.widget.winfo_toplevel() is not self.raiz:
                return  # roda numa janela de dialogo: nao rola a tela de tras
        except (tk.TclError, AttributeError):
            pass
        rolagem = getattr(self.atual, "rolagem", None)
        if rolagem is not None:
            rolagem.rolar(e.delta)

    # --- segundo plano ---------------------------------------------------------------
    def em_segundo_plano(self, funcao, depois):
        """Roda `funcao` numa linha separada (para a janela nao travar) e chama
        `depois(resultado)` na janela. Se der erro, `depois` recebe a excecao."""
        def rodar():
            try:
                resultado = funcao()
            except Exception as e:
                # erro do site, video privado, download cancelado: ja vem explicado, nao e defeito
                ja_explicado = (cortes.ErroAmigavel, controle.DownloadCancelado) + ((redes.ErroRede,) if SITE else ())
                if not isinstance(e, ja_explicado):
                    registrar_erro(traceback.format_exc())
                resultado = e
            self.fila.put((depois, resultado))
        threading.Thread(target=rodar, daemon=True).start()

    def olhar_fila(self):
        try:
            while True:
                depois, resultado = self.fila.get_nowait()
                try:
                    depois(resultado)
                except tk.TclError:
                    pass  # a tela mudou enquanto a miniatura carregava
        except queue.Empty:
            pass
        self.raiz.after(50, self.olhar_fila)

    # --- cortar ----------------------------------------------------------------------
    def fazer_cortes(self, video, qtd, tipo=None):
        if controle.rodando_agora():
            self.ir("trabalhando")
            self.aviso_rapido("Já tem um corte rodando. Mostrando ele.")
            return
        self.desistir_de_comecar = False
        tela = self.telas["trabalhando"]
        self.ir("trabalhando", video=video, preparando=True)
        avisar = lambda texto: self.fila.put((tela.mostrar_frase_ia, texto))  # noqa: E731
        self.em_segundo_plano(lambda: controle.preparar_lm_studio(self.cfg, avisar),
                              lambda problema: self.depois_de_preparar(problema, video, qtd, tipo))

    def depois_de_preparar(self, problema, video, qtd, tipo=None):
        if self.desistir_de_comecar:
            return
        if isinstance(problema, Exception):
            problema = f"Erro ao preparar a inteligência artificial: {problema}"
        if problema:
            self.ir("erro", titulo="A inteligência artificial está desligada", texto=problema, video=video)
            return
        self.proc = controle.iniciar_cortes([video], SCRIPT, qtd=qtd, tipo=tipo)
        self.telas["trabalhando"].comecou()

    # --- erros e fechar ----------------------------------------------------------------
    def erro_inesperado(self, tipo, valor, tb):
        registrar_erro("".join(traceback.format_exception(tipo, valor, tb)))
        messagebox.showerror(NOME, f"Deu um erro no app:\n{valor}\n\n"
                                   f"Os detalhes ficaram em logs\\app_erros.log")

    def fechar(self):
        if controle.rodando_agora() or (self.proc is not None and self.proc.poll() is None):
            if not messagebox.askyesno(NOME, "Os cortes continuam sozinhos, mesmo com a janela fechada.\n\n"
                                             "Fechar a janela?", parent=self.raiz):
                return
        inicio = self.telas.get("inicio")
        if inicio is not None and inicio.parar_download is not None:
            if not messagebox.askyesno(NOME, "Um vídeo está sendo baixado. Fechar a janela cancela o "
                                             "download.\n\nFechar mesmo assim?", parent=self.raiz):
                return
            inicio.parar_download.set()
            self.raiz.after(1600, self.raiz.destroy)  # tempo de parar o yt-dlp e limpar as partes
            return
        self.raiz.destroy()


def main():
    video = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        App(video).raiz.mainloop()
    except Exception:
        registrar_erro(traceback.format_exc())
        try:
            messagebox.showerror(NOME, "O app não conseguiu abrir.\n"
                                       "Os detalhes ficaram em logs\\app_erros.log")
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
