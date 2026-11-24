# -*- coding: utf-8 -*-
"""
CONTROLE DOS CORTES - pecas comuns ao vigia do WhatsApp e ao app pup_cortes

Os dois fazem a mesma coisa por baixo: rodam o cortes.py sem janela,
acompanham o andamento pelo status.json, cancelam no meio e ligam o
LM Studio quando ele esta desligado. Fica tudo aqui para os dois se
comportarem igual.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import cortes

try:  # integracao com o site (opcional, fica fora do repositorio)
    import whatsapp_cortes as zap
except ImportError:
    zap = None

ARQ_LOG = cortes.BASE / "logs" / "ultimo_corte.log"
CONTEXTO_MINIMO = 8192   # Context Length ao carregar o modelo no LM Studio


def sem_janela():
    """Flag para processos filhos nao abrirem janela preta (nem os FFmpeg deles)."""
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def salvar_senha(senha):
    """Grava a senha do PC (a que liga este PC ao site) no configuracoes.ini.
    Quem instalou antes da versao com WhatsApp nao tem a secao [whatsapp]:
    ela entra inteira, com as explicacoes."""
    if zap is None:
        raise RuntimeError("A integracao com o site (whatsapp_cortes.py) nao esta instalada.")
    arq = cortes.BASE / "configuracoes.ini"
    texto = arq.read_text(encoding="utf-8") if arq.exists() else ""
    if re.search(r"(?m)^\s*\[whatsapp\]", texto):
        cortes.salvar_opcao("whatsapp", "senha", senha)
    else:
        arq.write_text(texto.rstrip() + "\n\n\n" + zap.SECAO_INI.format(senha=senha), encoding="utf-8")


# ----------------------------------------------------------------------------
# status.json (gravado pelo cortes.py)
# ----------------------------------------------------------------------------

def ler_status():
    try:
        return json.loads(cortes.ARQ_STATUS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def gravar_status(st):
    try:
        tmp = cortes.ARQ_STATUS.with_name("status.tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, cortes.ARQ_STATUS)
    except Exception:
        pass


def detalhe_etapa(st):
    etapa = st.get("etapa")
    if etapa == "conferindo":
        return "conferindo o LM Studio"
    if etapa == "transcrevendo":
        return f"transcrevendo a fala ({st.get('pct') or 0}%)"
    if etapa == "escolhendo":
        p, t = st.get("parte") or 0, st.get("partes") or 0
        return "escolhendo os melhores momentos" + (f" (parte {p} de {t})" if t else "")
    if etapa == "gerando":
        return f"gerando os cortes ({st.get('corte') or 0} de {st.get('cortes_total') or 0})"
    return "começando"


# ----------------------------------------------------------------------------
# Processos
# ----------------------------------------------------------------------------

def pid_vivo(pid, nome="python"):
    """O processo ainda existe e e um python (ou o `nome` dado)? (o Windows
    reaproveita numeros de processo, entao so "existe" nao basta)"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)

    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        codigo = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(codigo)) or codigo.value != 259:  # STILL_ACTIVE
            return False
        buf = ctypes.create_unicode_buffer(1024)
        tam = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(tam)):
            return nome in Path(buf.value).name.lower()
        return True
    finally:
        k32.CloseHandle(h)


def matar(pid):
    """Fecha o cortes.py e os FFmpeg que ele abriu (/T = a arvore toda)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, creationflags=sem_janela())
    else:
        try:
            os.kill(int(pid), 9)
        except OSError:
            pass


def rodando_agora(st=None):
    """Tem corte rodando (por qualquer caminho: vigia, app ou .bat)?"""
    st = ler_status() if st is None else st
    return st.get("estado") == "rodando" and pid_vivo(st.get("pid"))


def python_do_programa():
    """python.exe do .venv (o app roda no pythonw, que nao tem saida de texto)."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console if console.exists() else exe)


def iniciar_cortes(videos, script=None, via_whatsapp=False, qtd=None, tipo=None):
    """Roda o cortes.py sem janela, com a saida em logs/ultimo_corte.log.
    O processo e independente: continua mesmo se quem abriu for fechado.

    O processo devolvido traz `.execucao`, a etiqueta que o cortes.py grava no
    status.json. E por ela que se reconhece a rodada, NAO pelo numero do
    processo: o python.exe do .venv e so um lancador que abre o Python de
    verdade como outro processo, com outro numero."""
    ARQ_LOG.parent.mkdir(exist_ok=True)
    execucao = uuid.uuid4().hex
    env = dict(os.environ, PYTHONIOENCODING="utf-8", CORTES_EXECUCAO=execucao)
    env.pop("CORTES_VIA_WHATSAPP", None)
    if via_whatsapp:
        env["CORTES_VIA_WHATSAPP"] = "1"
    cmd = [python_do_programa(), "-u", str(script or cortes.BASE / "cortes.py"), *map(str, videos)]
    if qtd:
        cmd += ["--qtd", str(int(qtd))]
    if tipo in ("fala", "gameplay"):  # sem tipo: o cortes.py usa o do configuracoes.ini
        cmd += ["--tipo", tipo]
    with open(ARQ_LOG, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=str(cortes.BASE), stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, creationflags=sem_janela())
    proc.execucao = execucao
    return proc


def cancelar_corte(pid):
    """Para o corte, marca "cancelado" no status.json (para ninguem achar que
    ele "parou no meio") e apaga a pasta _temp. Devolve o status de antes."""
    matar(pid)
    for _ in range(100):
        if not pid_vivo(pid):
            break
        time.sleep(0.1)
    st = ler_status()
    antes = dict(st)
    if st.get("estado") == "rodando":
        st.update(estado="cancelado", fim=time.time())
        gravar_status(st)
    if st.get("video"):
        shutil.rmtree(cortes.PASTA_SAIDA / cortes.nome_seguro(Path(st["video"]).stem, 60) / "_temp",
                      ignore_errors=True)
    return antes


def cauda_log(linhas=8):
    try:
        texto = ARQ_LOG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    uteis = [l.rstrip() for l in texto.splitlines() if l.strip() and not set(l.strip()) <= {"="}]
    return "\n".join(uteis[-linhas:])[-900:]


# ----------------------------------------------------------------------------
# LM Studio
# ----------------------------------------------------------------------------

def achar_lms():
    """A linha de comando do LM Studio (lms), que liga o servidor e carrega modelos."""
    exe = "lms.exe" if os.name == "nt" else "lms"
    for p in (Path.home() / ".lmstudio" / "bin" / exe,
              Path.home() / ".cache" / "lm-studio" / "bin" / exe):
        if p.exists():
            return p
    w = shutil.which("lms")
    return Path(w) if w else None


def rodar_lms(lms, args, timeout):
    # stdin vazio: se o lms resolver perguntar alguma coisa, ele desiste em vez de ficar esperando
    try:
        r = subprocess.run([str(lms), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=sem_janela())
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def url_lm(cfg):
    # 127.0.0.1 em vez de localhost: o Windows tenta o IPv6 primeiro e cada
    # pergunta ao LM Studio (que atende no IPv4) demorava 2 s a mais
    return cfg["ia"]["endereco_lm_studio"].rstrip("/").replace("://localhost", "://127.0.0.1")


def lm_ligado(cfg, timeout=3):
    try:
        with urllib.request.urlopen(url_lm(cfg) + "/models", timeout=timeout):
            return True
    except Exception:
        return False


def pode_ligar_lm(cfg):
    return cortes.sim(cfg["whatsapp"]["ligar_lm_studio"]) and achar_lms() is not None


def preparar_lm_studio(cfg, avisar=lambda texto: None):
    """O LM Studio precisa estar ligado e com um modelo carregado. Tenta resolver
    sozinho pelo lms, avisando o andamento por `avisar(texto)`.
    Devolve o texto do problema (sem enfeites), ou None se esta tudo certo.

    Com um modelo escolhido nos Ajustes (modelo local), quem atende e o
    llama-server do proprio app: ele entra no lugar do LM Studio quando a IA
    esta desligada ou quando o LM Studio esta ligado sem modelo."""
    url = url_lm(cfg)
    pode = cortes.sim(cfg["whatsapp"]["ligar_lm_studio"])
    lms = achar_lms() if pode else None

    if servidor_proprio():
        avisar("Esperando o modelo local terminar de carregar…")
        return None if esperar_servidor(cfg, 600) else "O modelo local não respondeu. Veja logs\\servidor_ia.log."
    arq_local = arquivo_modelo_local(cfg) if pode else None
    if arq_local and achar_llama_server():
        if lm_ligado(cfg):
            modelos = cortes.modelos_lm_studio(url)
            if modelos is None or any(m.get("state") == "loaded" and m.get("type") != "embeddings"
                                      for m in modelos):
                return None  # ja tem modelo atendendo (aberto pelo usuario no LM Studio): usa ele
            if lms:
                soltar_lmstudio(lms, avisar)
        avisar("Ligando a inteligência artificial (modelo local na placa de vídeo), um minutinho…")
        r = iniciar_servidor(cfg, arq_local, avisar)
        return None if r["ok"] else r["texto"]

    if not lm_ligado(cfg):
        if not lms:
            motivo = "" if pode else " (ligar sozinho está desativado no configuracoes.ini)"
            return (f"O LM Studio está desligado{motivo}.\n"
                    "No PC: abra o LM Studio, carregue o modelo e ligue o servidor na aba Developer.")
        avisar("O LM Studio estava desligado. Ligando o servidor, um minutinho…")
        rodar_lms(lms, ["server", "start"], 120)
        for _ in range(30):
            if lm_ligado(cfg):
                break
            time.sleep(1)
        else:
            return ("Tentei ligar o servidor do LM Studio, mas ele não respondeu. "
                    "Vai precisar ligar no PC (aba Developer).")

    modelos = cortes.modelos_lm_studio(url)
    if modelos is None:
        return None  # LM Studio antigo, sem a API que diz o que esta carregado: o cortes.py confere
    textos = [m for m in modelos if m.get("type") != "embeddings" and m.get("id")]
    if any(m.get("state") == "loaded" for m in textos):
        return None
    if not lms:
        return ("O LM Studio está ligado, mas sem modelo carregado. "
                "Carregue o Gemma no PC (Context Length 8192 ou mais).")
    # O modelo do configuracoes.ini; se estiver vazio, o ultimo carregado pelos
    # Ajustes do app; depois o Gemma (o que o programa foi pensado para usar);
    # se nao tiver nenhum desses, o primeiro.
    ids = [m["id"] for m in textos]
    local = opcao_ia(cfg, "modelo_local")
    gemma = [i for i in ids if "gemma" in i.lower()]
    escolhido = (cfg["ia"]["modelo"].strip() or (local if local in ids else "")
                 or (gemma or ids or [""])[0])
    if not escolhido:
        return "Não achei nenhum modelo baixado no LM Studio."
    avisar(f"Carregando o modelo {escolhido} no LM Studio, um minutinho…")
    ok, saida = carregar_no_lms(lms, escolhido)
    if cortes.modelos_carregados(url):
        return None
    return (f"Não consegui carregar o modelo no LM Studio:\n{saida[-300:]}\n\n"
            "Carregue no PC e tente de novo.")


# ----------------------------------------------------------------------------
# Modelo de IA local (Ajustes > "Modelo de IA local")
# ----------------------------------------------------------------------------
# O app roda o proprio llama-server (o motor que vem com o LM Studio, com Vulkan
# para a placa AMD) com o .gguf escolhido, de qualquer pasta:
#   - todas as camadas e o contexto na placa de video (-ngl all);
#   - sem prender o modelo na RAM (--load-mode none). O LM Studio carrega com
#     "mmap+mlock" (a opcao Keep Model in Memory), que trava uma copia do modelo
#     na RAM mesmo com ele inteiro na placa: num PC de 16 GB nao sobrava memoria;
#   - sem o "pensar" antes de responder (--reasoning off): bem mais rapido.
# Ele atende no mesmo endereco do LM Studio (http://127.0.0.1:1234/v1, formato
# OpenAI) e com o mesmo nome de modelo (ex.: qwen/qwen3.5-9b), entao o cortes.py
# e os scripts nao mudam. Antes, o LM Studio descarrega e desliga o servidor dele
# (o app pergunta). O llama-server continua ligado com o app fechado; o botao
# "Descarregar" desliga.

PASTA_LMSTUDIO = Path.home() / ".lmstudio"
PASTA_MODELOS_PADRAO = r"%USERPROFILE%\.lmstudio\models"
ARQ_SERVIDOR = cortes.BASE / "logs" / "servidor_ia.json"   # pid, arquivo e porta do llama-server do app
ARQ_LOG_SERVIDOR = cortes.BASE / "logs" / "servidor_ia.log"
PARALELO = 4   # perguntas atendidas ao mesmo tempo (igual ao LM Studio)
NOME_EXE = "llama-server"


def opcao_ia(cfg, chave):
    """Opcao nova da secao [ia] (pode faltar no .ini de quem instalou antes).
    raw: um caminho com % (como %USERPROFILE%) nao e tratado como formula."""
    return cfg.get("ia", chave, raw=True, fallback="").strip()


def pasta_modelos_lmstudio():
    return PASTA_LMSTUDIO / "models"


def pasta_modelos(cfg):
    """A pasta dos modelos escolhida nos Ajustes (vazia = a do LM Studio)."""
    texto = opcao_ia(cfg, "pasta_modelos") or PASTA_MODELOS_PADRAO
    return Path(os.path.expandvars(os.path.expanduser(texto)))


def arquivo_modelo_local(cfg):
    """O .gguf carregado pela ultima vez nos Ajustes (None se nao tiver ou sumiu)."""
    texto = opcao_ia(cfg, "modelo_local")
    if not texto.lower().endswith(".gguf"):
        return None
    arq = Path(os.path.expandvars(texto))
    return arq if arq.is_file() else None


def eh_mmproj(arq):
    """mmproj-*.gguf e a parte de "visao" de um modelo: vai junto com ele, nao sozinha."""
    return Path(arq).name.lower().startswith("mmproj")


def _mesmo_arquivo(a, b):
    try:
        return os.path.samefile(a, b)  # vale tambem para link (o mesmo arquivo com dois nomes)
    except OSError:
        return False


def no_lugar_do_lmstudio(arq):
    """O arquivo esta em models\\<autor>\\<repositorio>\\ (onde o LM Studio procura)?"""
    try:
        rel = Path(arq).resolve().relative_to(pasta_modelos_lmstudio().resolve())
    except (ValueError, OSError):
        return False
    return len(rel.parts) == 3


def listar_gguf(pasta, limite=300):
    """Os .gguf da pasta e das subpastas, sem os mmproj. O mesmo arquivo com dois
    nomes (um link) aparece uma vez so."""
    pasta = Path(pasta)
    if not pasta.is_dir():
        return []
    achados = {}
    try:
        for arq in pasta.rglob("*.gguf"):
            if eh_mmproj(arq):
                continue
            try:
                st = arq.stat()
            except OSError:
                continue
            chave = (st.st_dev, st.st_ino) if st.st_ino else str(arq).lower()
            if chave in achados and not no_lugar_do_lmstudio(arq):
                continue
            achados[chave] = {"arquivo": arq, "nome": arq.name, "bytes": st.st_size}
            if len(achados) >= limite:
                break
    except OSError:
        pass  # pasta sem permissao no meio do caminho: fica o que deu para ler
    return sorted(achados.values(), key=lambda i: i["nome"].lower())


def mmproj_de(arq):
    """A parte de "visao" (mmproj) do modelo, se estiver na mesma pasta: a unica
    da pasta quando ali so tem um modelo, ou a que tem o nome parecido."""
    arq = Path(arq)
    try:
        todos = list(arq.parent.glob("*.gguf"))
    except OSError:
        return None
    visoes = [p for p in todos if eh_mmproj(p)]
    if len(visoes) == 1 and len(todos) == 2:
        return visoes[0]
    nome = arq.stem.lower()

    def parecido(p):
        resto = re.sub(r"^mmproj[-_. ]*(model[-_. ]*)?", "", p.stem.lower())
        return len(os.path.commonprefix([nome, resto]))
    melhores = sorted(visoes, key=parecido, reverse=True)
    return melhores[0] if melhores and parecido(melhores[0]) >= 6 else None


# --- o que o LM Studio tem (para dar o mesmo nome e para tirar ele da frente) ---

def _lms_json(lms, *args, timeout=60):
    """O que o lms devolve com --json (so a saida normal: avisos vao para o stderr)."""
    try:
        r = subprocess.run([str(lms), *args, "--json"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=sem_janela())
    except Exception:
        return None
    texto = r.stdout.strip()
    inicio = min([i for i in (texto.find("["), texto.find("{")) if i >= 0], default=-1)
    if r.returncode != 0 or inicio < 0:
        return None
    try:
        return json.loads(texto[inicio:])
    except json.JSONDecodeError:
        return None


def modelos_baixados_lms(lms):
    """Os modelos que o LM Studio conhece (lms ls)."""
    dados = _lms_json(lms, "ls")
    return [m for m in dados if isinstance(m, dict)] if isinstance(dados, list) else []


def modelos_na_memoria_lms(lms):
    """Os modelos carregados agora no LM Studio (lms ps), sem os de "embedding"."""
    dados = _lms_json(lms, "ps")
    return [m for m in dados if isinstance(m, dict) and m.get("type") == "llm"] if isinstance(dados, list) else []


def servidor_lmstudio_ligado(lms):
    dados = _lms_json(lms, "server", "status", timeout=30)
    return isinstance(dados, dict) and bool(dados.get("running"))


def caminhos_do_modelo(m):
    """Onde ficam os arquivos de um modelo do lms ls / lms ps: o proprio .gguf,
    ou a pasta do repositorio quando e um modelo do catalogo do LM Studio
    (ex.: qwen/qwen3.5-9b, cujo manifest.json diz de onde vem o arquivo)."""
    base = pasta_modelos_lmstudio()
    caminho = str(m.get("path") or "").strip("/\\")
    if not caminho:
        return []
    if caminho.lower().endswith(".gguf"):
        return [base / caminho]
    pastas = [base / caminho]
    try:
        manifesto = json.loads((PASTA_LMSTUDIO / "hub" / "models" / caminho / "manifest.json")
                               .read_text(encoding="utf-8"))
        for dep in manifesto.get("dependencies", []):
            for fonte in dep.get("sources", []):
                if fonte.get("user") and fonte.get("repo"):
                    pastas.append(base / fonte["user"] / fonte["repo"])
    except Exception:
        pass
    return pastas


def modelo_do_arquivo(arq, modelos):
    """O modelo do lms (ls ou ps) que usa este .gguf, ou None."""
    arq = Path(arq)
    for m in modelos:
        for lugar in caminhos_do_modelo(m):
            if lugar.suffix.lower() == ".gguf":
                if _mesmo_arquivo(lugar, arq):
                    return m
            elif lugar.is_dir() and arq.parent.resolve() == lugar.resolve():
                return m
    return None


def apelido(arq, lms=None):
    """O nome do modelo na API: o mesmo do LM Studio quando ele conhece o arquivo
    (ex.: qwen/qwen3.5-9b, que os scripts ja usam); senao o nome do arquivo."""
    lms = lms or achar_lms()
    if lms:
        m = modelo_do_arquivo(arq, modelos_baixados_lms(lms))
        if m and m.get("modelKey"):
            return m["modelKey"]
    return Path(arq).stem


def motores_do_lmstudio():
    """Numeros dos llama-server abertos pelo LM Studio (todos menos o do app):
    cada um e um modelo carregado nele, ocupando a placa e a RAM."""
    try:
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {NOME_EXE}.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=30, creationflags=sem_janela())
    except Exception:
        return []
    meu = (servidor_proprio() or {}).get("pid")
    pids = []
    for linha in r.stdout.splitlines():
        partes = [p.strip('"') for p in linha.split('","')]
        if len(partes) > 1 and partes[1].isdigit() and int(partes[1]) != meu:
            pids.append(int(partes[1]))
    return pids


def soltar_lmstudio(lms, avisar=lambda texto: None):
    """Descarrega os modelos do LM Studio e desliga o servidor dele: libera a
    placa, a RAM e a porta 1234 para o llama-server do app."""
    if motores_do_lmstudio() or modelos_na_memoria_lms(lms):
        avisar("Descarregando o modelo do LM Studio...")
        rodar_lms(lms, ["unload", "--all"], 120)
    if servidor_lmstudio_ligado(lms):
        avisar("Desligando o servidor do LM Studio...")
        rodar_lms(lms, ["server", "stop"], 60)
    for _ in range(20):  # o motor dele leva um instante para sair
        if not motores_do_lmstudio():
            break
        time.sleep(1)


# --- o llama-server do app ---

def achar_llama_server():
    """O llama-server do LM Studio com Vulkan (o que usa a placa AMD), da versao mais nova."""
    achados = []
    for pasta in (PASTA_LMSTUDIO / "extensions" / "backends").glob("llama.cpp-*vulkan*"):
        exe = pasta / (NOME_EXE + (".exe" if os.name == "nt" else ""))
        if exe.exists():
            m = re.search(r"-(\d+(?:\.\d+)*)$", pasta.name)
            versao = tuple(int(x) for x in m.group(1).split(".")) if m else ()
            achados.append((versao, str(exe)))
    return Path(max(achados)[1]) if achados else None


def porta_lm(cfg):
    from urllib.parse import urlparse
    return urlparse(url_lm(cfg)).port or 1234


def servidor_proprio():
    """O llama-server que o app abriu ({pid, arquivo, apelido, porta, ...}), se ainda estiver aberto."""
    try:
        dados = json.loads(ARQ_SERVIDOR.read_text(encoding="utf-8"))
    except Exception:
        return None
    return dados if isinstance(dados, dict) and pid_vivo(dados.get("pid"), NOME_EXE) else None


def saude(porta, timeout=3):
    """"ok" (pronto), "carregando" ou None (ninguem atendendo)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/health", timeout=timeout) as r:
            return "ok" if r.status == 200 else "carregando"
    except urllib.error.HTTPError as e:
        return "carregando" if e.code == 503 else None
    except Exception:
        return None


def esperar_servidor(cfg, limite, avisar=lambda texto: None, proc=None):
    """Espera o llama-server do app ficar pronto. True se ficou."""
    porta, inicio = porta_lm(cfg), time.time()
    while time.time() - inicio < limite:
        if proc is not None and proc.poll() is not None:
            return False
        if proc is None and not servidor_proprio():
            return False
        if saude(porta) == "ok":
            return True
        avisar(f"Carregando na placa de vídeo... {int(time.time() - inicio)} s")
        time.sleep(1)
    return False


def cauda_log_servidor(linhas=6):
    try:
        texto = ARQ_LOG_SERVIDOR.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    uteis = [l.strip() for l in texto.splitlines() if l.strip()]
    return "\n".join(uteis[-linhas:])[-700:]


def iniciar_servidor(cfg, arq, avisar=lambda texto: None, camadas="all"):
    """Abre o llama-server com o modelo. Devolve {"ok", "texto"}.
    camadas="all": tudo na placa. Se nao couber, tenta "auto" (o que sobrar fica
    no processador e na RAM) e avisa."""
    exe = achar_llama_server()
    if not exe:
        return {"ok": False, "texto": "Não achei o llama-server com Vulkan. Ele vem com o LM Studio: abra o "
                                      "LM Studio e baixe o motor \"Vulkan llama.cpp\" (aba Runtime)."}
    arq = Path(arq)
    porta = porta_lm(cfg)
    nome = apelido(arq)
    visao = mmproj_de(arq)
    threads = max(2, (os.cpu_count() or 4) // 2 - 3)   # o 5900X tem 12 nucleos: 9, como o LM Studio
    args = [str(exe), "--model", str(arq), "--host", "127.0.0.1", "--port", str(porta),
            "--alias", nome, "--n-gpu-layers", camadas, "--ctx-size", str(CONTEXTO_MINIMO),
            "--parallel", str(PARALELO), "--kv-unified", "--flash-attn", "on", "--jinja",
            "--load-mode", "none", "--reasoning", "off", "--threads", str(threads), "--no-webui"]
    if visao:
        args += ["--mmproj", str(visao)]
    ARQ_LOG_SERVIDOR.parent.mkdir(exist_ok=True)
    flags = (0x00000008 | 0x00000200) if os.name == "nt" else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    with open(ARQ_LOG_SERVIDOR, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(args, cwd=str(exe.parent), stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    ARQ_SERVIDOR.write_text(json.dumps({"pid": proc.pid, "arquivo": str(arq), "apelido": nome, "porta": porta,
                                        "visao": str(visao) if visao else "", "camadas": camadas,
                                        "inicio": time.time()}, ensure_ascii=False), encoding="utf-8")
    avisar("Carregando na placa de vídeo...")
    if not esperar_servidor(cfg, 900, avisar, proc):
        cauda = cauda_log_servidor(12)
        if proc.poll() is None:
            matar(proc.pid)
        ARQ_SERVIDOR.unlink(missing_ok=True)
        if camadas == "all" and re.search(r"out of (device )?memory|OutOfDeviceMemory|failed to allocate|"
                                          r"unable to allocate|not enough memory", cauda, re.I):
            avisar("Não coube inteiro na placa de vídeo. Dividindo com o processador...")
            r = iniciar_servidor(cfg, arq, avisar, camadas="auto")
            if r["ok"]:
                r["texto"] += "\nNão coube inteiro na placa de vídeo: uma parte ficou no processador e na RAM."
            return r
        return {"ok": False, "texto": f"O modelo não carregou:\n{cauda or 'sem detalhes'}"}
    cortes.salvar_opcao("ia", "modelo_local", str(arq))
    # com -ngl all o llama-server so sobe se o modelo inteiro couber na placa
    detalhe = " inteiro na placa de vídeo" if camadas == "all" else " (parte no processador)"
    return {"ok": True, "texto": f"Modelo {nome} carregado{detalhe}."}


def parar_servidor_proprio():
    dados = servidor_proprio()
    if dados:
        matar(dados["pid"])
        for _ in range(50):
            if not pid_vivo(dados["pid"], NOME_EXE):
                break
            time.sleep(0.2)
    ARQ_SERVIDOR.unlink(missing_ok=True)
    return dados


def carregar_modelo_local(cfg, arq, trocar=None, avisar=lambda texto: None):
    """Carrega o .gguf na placa de video pelo llama-server do app. Devolve:
    - {"ok": True, "texto": ...} quando carregou (ou ja estava);
    - {"ok": False, "outros": [textos]} quando tem outro modelo na frente (do app ou
      do LM Studio) e `trocar` nao e True: quem chamou pergunta e chama de novo
      com trocar=True;
    - {"ok": False, "texto": ...} quando nao deu certo."""
    arq = Path(arq)
    if not arq.is_file():
        return {"ok": False, "texto": f"O arquivo não está mais lá:\n{arq}"}
    if not achar_llama_server():
        return iniciar_servidor(cfg, arq, avisar)  # devolve a explicacao de que falta o motor
    proprio = servidor_proprio()
    if proprio and _mesmo_arquivo(proprio.get("arquivo", ""), arq) and saude(porta_lm(cfg)) == "ok":
        cortes.salvar_opcao("ia", "modelo_local", str(arq))
        return {"ok": True, "texto": f"O modelo {proprio.get('apelido') or arq.stem} já estava carregado."}

    lms = achar_lms()
    outros = []
    if proprio:
        outros.append(f"o modelo {Path(proprio.get('arquivo', '')).name} (carregado pelo app)")
    lmstudio = bool(lms) and (bool(motores_do_lmstudio()) or servidor_lmstudio_ligado(lms))
    if lmstudio:
        nomes = ", ".join(m.get("identifier", "?") for m in modelos_na_memoria_lms(lms))
        outros.append(f"o LM Studio{' com ' + nomes if nomes else ''} (ele sai e libera a porta)")
    elif not proprio and lm_ligado(cfg, timeout=2):
        return {"ok": False, "texto": f"Outro programa está usando o endereço {url_lm(cfg)}. Feche ele e tente de novo."}
    if outros and trocar is not True:
        return {"ok": False, "outros": outros}

    if proprio:
        avisar("Descarregando o modelo anterior...")
        parar_servidor_proprio()
    if lmstudio:
        soltar_lmstudio(lms, avisar)
    for _ in range(30):
        if not lm_ligado(cfg, timeout=1):
            break
        time.sleep(1)
    else:
        return {"ok": False, "texto": f"O endereço {url_lm(cfg)} continua ocupado. Feche o LM Studio e tente de novo."}
    return iniciar_servidor(cfg, arq, avisar)


def descarregar_modelos_locais(cfg):
    """Desliga o llama-server do app e descarrega o que o LM Studio tiver na
    memoria (libera a placa e a RAM). Devolve (ok, texto)."""
    feitos = []
    if parar_servidor_proprio():
        feitos.append("app")
    lms = achar_lms()
    if lms and (motores_do_lmstudio() or (servidor_lmstudio_ligado(lms) and modelos_na_memoria_lms(lms))):
        rodar_lms(lms, ["unload", "--all"], 120)
        feitos.append("LM Studio")
        for _ in range(20):
            if not motores_do_lmstudio():
                break
            time.sleep(1)
    if not feitos:
        return True, "Nenhum modelo estava carregado."
    if servidor_proprio() or motores_do_lmstudio():
        return False, "Não consegui descarregar tudo. Tente de novo."
    return True, "Modelo descarregado. A placa de vídeo e a RAM ficaram livres."


def situacao_modelo_local(cfg):
    """O que a parte "Modelo de IA local" dos Ajustes mostra (a memoria vem a
    parte, pelo memoria_da_placa: a primeira leitura do Windows demora)."""
    proprio = servidor_proprio()
    lms = achar_lms()
    motores = motores_do_lmstudio()
    return {"motor": achar_llama_server() is not None,
            "proprio": proprio,
            "saude": saude(porta_lm(cfg)) if proprio else None,
            "inteiro_na_placa": (proprio.get("camadas") == "all") if proprio else None,
            "ram_proprio": ram_do_processo(proprio["pid"]) if proprio else None,
            "lmstudio": modelos_na_memoria_lms(lms) if lms and motores else [],
            "lmstudio_motores": motores,
            "porta_ocupada": (not proprio) and lm_ligado(cfg, timeout=2)}


def ram_do_processo(pid):
    """Bytes de RAM que o processo esta usando (o "conjunto de trabalho" do Gerenciador de Tarefas)."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Contadores(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Contadores), wintypes.DWORD)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        c = Contadores()
        c.cb = ctypes.sizeof(c)
        return c.WorkingSetSize if k32.K32GetProcessMemoryInfo(h, ctypes.byref(c), c.cb) else None
    finally:
        k32.CloseHandle(h)


def ram_do_pc():
    """(bytes disponiveis, bytes no total) da RAM do PC."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Estado(ctypes.Structure):  # MEMORYSTATUSEX
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    e = Estado()
    e.dwLength = ctypes.sizeof(e)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e)):
        return None
    return e.ullAvailPhys, e.ullTotalPhys


def carregar_no_lms(lms, chave):
    """Carrega inteiro na placa de video (--gpu max), com contexto para o cortes.py."""
    return rodar_lms(lms, ["load", chave, "--gpu", "max", "--context-length", str(CONTEXTO_MINIMO), "-y"], 600)


def _memoria_em_uso_na_placa():
    """Bytes em uso na memoria da placa de video (o maior entre as placas), pelo
    contador do Windows "GPU Adapter Memory\\Dedicated Usage" (o mesmo do Gerenciador
    de Tarefas). Pelo nome em ingles, que vale no Windows em portugues. None se falhar."""
    import ctypes
    from ctypes import wintypes
    pdh = ctypes.WinDLL("pdh")
    for f in (pdh.PdhOpenQueryW, pdh.PdhAddEnglishCounterW, pdh.PdhCollectQueryData,
              pdh.PdhGetFormattedCounterArrayW, pdh.PdhCloseQuery):
        f.restype = ctypes.c_long
    pdh.PdhOpenQueryW.argtypes = (wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p))
    pdh.PdhAddEnglishCounterW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_size_t,
                                          ctypes.POINTER(ctypes.c_void_p))
    pdh.PdhCollectQueryData.argtypes = (ctypes.c_void_p,)
    pdh.PdhGetFormattedCounterArrayW.argtypes = (ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                                 ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
    pdh.PdhCloseQuery.argtypes = (ctypes.c_void_p,)

    class Valor(ctypes.Structure):  # PDH_FMT_COUNTERVALUE com PDH_FMT_LARGE
        _fields_ = [("status", wintypes.DWORD), ("numero", ctypes.c_longlong)]

    class Item(ctypes.Structure):  # PDH_FMT_COUNTERVALUE_ITEM_W
        _fields_ = [("nome", ctypes.c_wchar_p), ("valor", Valor)]

    consulta, contador = ctypes.c_void_p(), ctypes.c_void_p()
    if pdh.PdhOpenQueryW(None, 0, ctypes.byref(consulta)) != 0:
        return None
    try:
        if (pdh.PdhAddEnglishCounterW(consulta, r"\GPU Adapter Memory(*)\Dedicated Usage", 0,
                                      ctypes.byref(contador)) != 0
                or pdh.PdhCollectQueryData(consulta) != 0):
            return None
        tam, qtd = wintypes.DWORD(0), wintypes.DWORD(0)
        pdh.PdhGetFormattedCounterArrayW(contador, 0x400, ctypes.byref(tam), ctypes.byref(qtd), None)
        if not tam.value:
            return None
        buf = ctypes.create_string_buffer(tam.value)
        if pdh.PdhGetFormattedCounterArrayW(contador, 0x400, ctypes.byref(tam), ctypes.byref(qtd), buf) != 0:
            return None
        itens = ctypes.cast(buf, ctypes.POINTER(Item * qtd.value)).contents
        valores = [i.valor.numero for i in itens if i.valor.status in (0, 1)]  # 0/1 = valor valido
        return max(valores) if valores else None
    finally:
        pdh.PdhCloseQuery(consulta)


def memoria_da_placa():
    """(nome, bytes em uso ou None, bytes no total) da placa de video com mais memoria,
    ou None. O total vem do registro do Windows; o uso, do contador da placa."""
    nome, total = "", 0
    try:
        import winreg
        classe = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, classe) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as s:
                        mem = winreg.QueryValueEx(s, "HardwareInformation.qwMemorySize")[0]
                        desc = winreg.QueryValueEx(s, "DriverDesc")[0]
                except OSError:
                    continue
                mem = int.from_bytes(mem, "little") if isinstance(mem, bytes) else int(mem)
                if mem > total:
                    nome, total = desc, mem
    except Exception:
        pass
    try:
        usado = _memoria_em_uso_na_placa() if os.name == "nt" else None
    except Exception:
        usado = None
    return (nome, usado, total) if total or usado else None


def testar_modelo(cfg, chave):
    """Pergunta rapida ao modelo carregado. Devolve (segundos, resposta).
    reasoning_effort "none": sem o "pensar" antes de responder (fica bem mais rapido)."""
    url = url_lm(cfg) + "/chat/completions"
    payload = {"model": chave, "temperature": 0.2, "max_tokens": 80, "reasoning_effort": "none",
               "messages": [{"role": "user", "content": "Responda em uma frase curta, em português do "
                                                        "Brasil: você está funcionando?"}]}
    inicio = time.time()
    for _ in range(2):
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                dados = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 400 and "reasoning_effort" in payload:
                payload.pop("reasoning_effort")  # modelo que nao aceita a opcao: tenta sem
                continue
            raise cortes.ErroAmigavel(f"O LM Studio respondeu com erro {e.code}.")
        except Exception as e:
            raise cortes.ErroAmigavel(f"O modelo não respondeu ({e}).")
    else:
        raise cortes.ErroAmigavel("O modelo não aceitou a pergunta.")
    texto = (dados.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()
    return time.time() - inicio, texto or "(resposta vazia)"


# ----------------------------------------------------------------------------
# Resultados (pasta saida)
# ----------------------------------------------------------------------------

def legenda_para_postar(corte, credito):
    """O mesmo texto do POSTAGENS.txt: legenda, credito e hashtags."""
    linhas = [corte.get("descricao") or corte.get("titulo") or ""]
    if credito:
        linhas.append(f"Creditos: {credito}")
    if corte.get("hashtags"):
        linhas.append(" ".join(corte["hashtags"]))
    return "\n".join(l for l in linhas if l)


def ler_resultado(pasta, credito=""):
    """Cortes prontos de uma pasta da saida, com titulo, nota, capa e legenda.
    So entram os .mp4 feitos depois da ultima escolha da IA - sobras de uma
    rodada antiga com mais cortes ficariam com o titulo errado."""
    pasta = Path(pasta)
    arq_escolhidos = pasta / "cortes_escolhidos.json"
    try:
        escolhidos = json.loads(arq_escolhidos.read_text(encoding="utf-8"))
        desde = arq_escolhidos.stat().st_mtime - 5
    except Exception:
        escolhidos, desde = [], 0
    itens = []
    for mp4 in sorted(pasta.glob("corte_*.mp4")):
        m = re.match(r"corte_(\d+)_", mp4.name)
        if not m or mp4.stat().st_mtime < desde:
            continue
        n = int(m.group(1))
        c = escolhidos[n - 1] if 0 < n <= len(escolhidos) and isinstance(escolhidos[n - 1], dict) else {}
        if escolhidos and not c:
            continue
        capa = mp4.with_name(mp4.stem + "_capa.jpg")
        itens.append({"arquivo": mp4, "numero": n, "titulo": c.get("titulo") or mp4.stem,
                      "nota": c.get("nota"), "capa": capa if capa.exists() else None,
                      "legenda": legenda_para_postar(c, credito) if c else ""})
    return itens


def nome_original(pasta):
    """Nome do video original, lido da 1a linha do POSTAGENS.txt."""
    try:
        primeira = (Path(pasta) / "POSTAGENS.txt").read_text(encoding="utf-8").split("\n", 1)[0]
        if primeira.startswith("CORTES DE:"):
            return primeira.split(":", 1)[1].strip()
    except Exception:
        pass
    return Path(pasta).name.replace("_", " ")


def resultados_recentes(limite=4):
    """Pastas da saida com cortes prontos, da mais nova para a mais velha."""
    if not cortes.PASTA_SAIDA.exists():
        return []
    pastas = [p for p in cortes.PASTA_SAIDA.iterdir() if (p / "POSTAGENS.txt").exists()]
    pastas.sort(key=lambda p: (p / "POSTAGENS.txt").stat().st_mtime, reverse=True)
    return pastas[:limite]


# ----------------------------------------------------------------------------
# Vigia do WhatsApp na bandeja e rede do PC (para ligar a distancia)
# ----------------------------------------------------------------------------

PORTA_VIGIA = 47391   # o vigia segura esta porta local: so um aberto por vez


def vigia_rodando():
    """Tem um vigia aberto? (ele segura a PORTA_VIGIA enquanto roda)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", PORTA_VIGIA))
        return False
    except OSError:
        return True
    finally:
        s.close()


def pythonw_do_programa():
    """pythonw.exe do .venv: roda sem abrir janela preta."""
    exe = Path(sys.executable)
    sem_tela = exe.with_name("pythonw.exe")
    return str(sem_tela if sem_tela.exists() else exe)


def ligar_vigia():
    """Abre o vigia na bandeja (sem janela). Devolve False se ele já estava aberto.
    O vigia fica independente: continua rodando quando quem abriu fecha."""
    if vigia_rodando():
        return False
    flags = (0x00000008 | 0x00000200) if os.name == "nt" else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen([pythonw_do_programa(), str(cortes.BASE / "vigia_bandeja.pyw")],
                     cwd=str(cortes.BASE), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def abrir_configuracao_do_vigia():
    """Janela (com console) para colar a senha do PC: a bandeja não tem onde digitar."""
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    subprocess.Popen([python_do_programa(), str(cortes.BASE / "vigia_whatsapp.py"), "--configurar"],
                     cwd=str(cortes.BASE), creationflags=flags)


_REDE = None


def rede_do_pc():
    """Placas de rede ligadas: endereço físico (MAC, que o bot usa para ligar o PC
    pelo Wake on LAN), IP e se é no cabo. Lido uma vez só: não muda com o PC ligado."""
    global _REDE
    if _REDE is not None:
        return _REDE
    script = (
        "Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | ForEach-Object { "
        "$ip = Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 -ErrorAction "
        "SilentlyContinue | Select-Object -First 1; [pscustomobject]@{ nome = $_.Name; "
        "mac = $_.MacAddress; cabo = ($_.MediaType -eq '802.3'); ip = $ip.IPAddress; "
        "prefixo = $ip.PrefixLength } } | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=40, creationflags=sem_janela())
        dados = json.loads(r.stdout or "[]")
        dados = [dados] if isinstance(dados, dict) else dados
        _REDE = [{"mac": str(d["mac"]).replace("-", ":").upper(), "ip": d.get("ip") or "",
                  "prefixo": int(d.get("prefixo") or 0), "cabo": bool(d.get("cabo")),
                  "nome": d.get("nome") or ""}
                 for d in dados if d.get("mac")]
        _REDE.sort(key=lambda d: not d["cabo"])  # o cabo primeiro: é o que acorda o PC
    except Exception:
        _REDE = []
    return _REDE


# ----------------------------------------------------------------------------
# Baixar video por link (yt-dlp)
# ----------------------------------------------------------------------------
# O yt-dlp e o Deno (motor de JavaScript que o YouTube passou a exigir) moram
# no .venv do programa: vem no 1_INSTALAR.bat (requirements.txt) e o botao
# "Atualizar o baixador" dos Ajustes atualiza, porque o YouTube muda sempre.

LINK_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# (trecho da mensagem de erro do yt-dlp, em minusculas) -> explicacao
ERROS_DOWNLOAD = (
    ("private video", "Esse vídeo é privado. Só dá para baixar vídeo público ou não listado."),
    ("sign in to confirm your age", "O YouTube pede login para esse vídeo (restrição de idade). "
                                    "Não dá para baixar por aqui."),
    ("not a bot", "O YouTube bloqueou os downloads por um tempo (achou que era robô). "
                  "Espere um pouco e tente de novo."),
    ("members-only", "Esse vídeo é só para membros do canal."),
    ("join this channel", "Esse vídeo é só para membros do canal."),
    ("this live event will begin", "Essa live ainda não começou."),
    ("premieres in", "Esse vídeo ainda não estreou."),
    ("unavailable", "Esse vídeo não está disponível (foi apagado, bloqueado ou é privado)."),
    ("unsupported url", "Esse link não é de um vídeo que o programa sabe baixar."),
    ("is not a valid url", "Isso não parece um link de vídeo."),
    ("http error 403", "O YouTube recusou o download. Em Ajustes, clique em \"Atualizar o "
                       "baixador\" e tente de novo."),
    ("requested format is not available", "O YouTube não ofereceu esse vídeo para download. Em "
                                          "Ajustes, clique em \"Atualizar o baixador\"."),
    ("unable to download", "A internet caiu ou o YouTube não respondeu. Tente de novo."),
)


class DownloadCancelado(Exception):
    """Quem pediu o download desistiu no meio."""


def qualidade_download(cfg):
    """Altura máxima do vídeo baixado ([video] qualidade_download no .ini).
    1080 é o equilíbrio: o corte sai em 1080x1920 e o download não fica enorme."""
    valor = str(cfg["video"].get("qualidade_download", "1080")).strip().lower()
    if valor.startswith(("max", "máx")):
        return 4320
    try:
        return max(360, min(4320, int(valor)))
    except ValueError:
        return 1080


def nome_do_video(arquivo):
    """"Titulo [abc123].mp4" -> "Titulo" (para as mensagens)."""
    return re.sub(r"\s*\[[\w-]+\]$", "", Path(arquivo).stem).strip() or Path(arquivo).name


def achar_link(texto):
    """O primeiro link http(s) do texto (do jeito que veio: maiúsculas importam)."""
    m = LINK_RE.search(texto or "")
    return m.group(0).rstrip(".,;)]") if m else ""


def _deno():
    """O deno.exe do .venv (pip install deno); se nao tiver, o do Windows."""
    pasta = Path(sys.executable).parent
    for nome in ("deno.exe", "deno"):
        if (pasta / nome).exists():
            return str(pasta / nome)
    return shutil.which("deno") or ""


def comando_ytdlp():
    """Como rodar o yt-dlp: o do .venv do programa; se o .venv ainda nao tiver,
    o yt-dlp instalado no Windows. None se nao houver nenhum."""
    import importlib.util
    if importlib.util.find_spec("yt_dlp") is not None:
        cmd = [python_do_programa(), "-m", "yt_dlp"]
    else:
        solto = shutil.which("yt-dlp")
        if not solto:
            return None
        cmd = [solto]
    deno = _deno()
    if deno:
        cmd += ["--js-runtimes", f"deno:{deno}"]
    return cmd


def versao_ytdlp():
    """Versão do yt-dlp que o programa usa ("" se não houver nenhum)."""
    cmd = comando_ytdlp()
    if not cmd:
        return ""
    base = cmd[:3] if len(cmd) > 1 and cmd[1] == "-m" else cmd[:1]
    try:
        r = subprocess.run([*base, "--version"], capture_output=True, text=True, timeout=60,
                           creationflags=sem_janela())
        linhas = r.stdout.strip().splitlines()
        return linhas[-1] if r.returncode == 0 and linhas else ""
    except Exception:
        return ""


def atualizar_ytdlp():
    """Atualiza o yt-dlp e o Deno do .venv. Devolve (deu_certo, versao_ou_erro)."""
    r = subprocess.run([python_do_programa(), "-m", "pip", "install", "--upgrade", "--quiet",
                        "yt-dlp[default]", "deno"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600, creationflags=sem_janela())
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()[-400:]
    return True, versao_ytdlp()


def _explicar_erro(erros, cauda):
    texto = " ".join(erros + cauda).lower()
    for trecho, explicacao in ERROS_DOWNLOAD:
        if trecho in texto:
            return explicacao
    ultimo = (erros or cauda or ["sem detalhes"])[-1]
    return f"Não consegui baixar o vídeo.\n{ultimo.replace('ERROR:', '').strip()[:300]}"


def baixar_video(url, pasta=None, altura=1080, progresso=None, parar=None):
    """Baixa o video do link e devolve o caminho do arquivo .mp4.

    - Prefere H.264 (o formato mais leve de abrir) ate `altura` linhas, com o
      audio junto, num .mp4 so. Nome: "Titulo [id].mp4", na pasta entrada.
    - `progresso(etapa, porcentagem, titulo)`: etapa e "preparando", "video",
      "audio" ou "juntando".
    - `parar`: um threading.Event; ligado, o download para (DownloadCancelado).
    - Erro: cortes.ErroAmigavel com a explicacao em portugues.
    """
    import threading
    from collections import deque

    cmd = comando_ytdlp()
    if not cmd:
        raise cortes.ErroAmigavel("O baixador de vídeos (yt-dlp) não está instalado. "
                                  "Rode o 1_INSTALAR.bat de novo.")
    if not achar_link(url):
        raise cortes.ErroAmigavel("Isso não parece um link de vídeo (precisa começar com https://).")
    pasta = Path(pasta or cortes.PASTA_ENTRADA)
    pasta.mkdir(parents=True, exist_ok=True)
    ffmpeg = cortes.FFMPEG or cortes.achar_ffmpeg()[0]
    avisar = progresso or (lambda etapa, pct, titulo: None)

    # As partes (video e audio separados, .part) ficam em entrada\_baixando:
    # so o .mp4 pronto aparece na entrada, onde o cortes.py e o "cortes fila"
    # procuram videos.
    temporaria = pasta / "_baixando" / uuid.uuid4().hex[:8]  # uma por download
    args = [*cmd, "--newline", "--progress", "--color", "never", "--no-playlist",
            "--windows-filenames", "--no-mtime",
            "-f", "bv*+ba/b", "-S", f"res:{int(altura)},vcodec:h264,acodec:m4a",
            "--merge-output-format", "mp4", "--ffmpeg-location", str(Path(ffmpeg).parent),
            "--progress-template", "download:[baixando] %(progress._percent_str)s|%(info.vcodec)s",
            "--print", "before_dl:[titulo] %(title)s",
            "--print", "after_move:[arquivo] %(filepath)s",
            "-P", f"home:{pasta}", "-P", f"temp:{temporaria}",
            "-o", "%(title).90B [%(id)s].%(ext)s",
            achar_link(url)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", env=env, creationflags=sem_janela())

    def vigiar_cancelamento():
        while proc.poll() is None:
            if parar is not None and parar.is_set():
                matar(proc.pid)
                return
            time.sleep(0.3)
    threading.Thread(target=vigiar_cancelamento, daemon=True).start()

    titulo, arquivo, erros, cauda = "", "", [], deque(maxlen=12)
    avisar("preparando", 0.0, "")
    for linha in proc.stdout:
        linha = linha.strip()
        if not linha:
            continue
        cauda.append(linha)
        if linha.startswith("[titulo] "):
            titulo = linha[9:].strip()
            avisar("preparando", 0.0, titulo)
        elif linha.startswith("[baixando] "):
            pct_txt, _, vcodec = linha[11:].partition("|")
            m = re.search(r"([\d.]+)\s*%", pct_txt)
            etapa = "audio" if vcodec.strip().lower() == "none" else "video"
            avisar(etapa, float(m.group(1)) if m else 0.0, titulo)
        elif linha.startswith("[Merger]") or linha.startswith("[VideoConvertor]"):
            avisar("juntando", 100.0, titulo)
        elif linha.startswith("[arquivo] "):
            arquivo = linha[10:].strip()
        elif linha.startswith("ERROR"):
            erros.append(linha)
    proc.wait()
    if parar is not None and parar.is_set():
        time.sleep(0.5)  # o Windows solta os arquivos do processo morto
    shutil.rmtree(temporaria, ignore_errors=True)
    try:
        temporaria.parent.rmdir()  # _baixando some quando nao tem mais nada dentro
    except OSError:
        pass

    if parar is not None and parar.is_set():
        raise DownloadCancelado()
    if arquivo and Path(arquivo).exists():
        return Path(arquivo)
    raise cortes.ErroAmigavel(_explicar_erro(erros, list(cauda)))
