# -*- coding: utf-8 -*-
"""
CORTES AUTOMATICOS
Pega um video longo (podcast, live, entrevista) e devolve cortes prontos
para TikTok, Reels, Kwai e Shorts: em pe (9:16), seguindo o rosto e com
legenda animada.

Etapas:
  1. Whisper transcreve a fala (com o tempo de cada palavra)
  2. O modelo do LM Studio (ex.: Gemma) escolhe os melhores momentos
  3. O FFmpeg corta, enquadra em 9:16 e queima a legenda

Uso:
  python cortes.py                      -> processa todos os videos da pasta "entrada"
  python cortes.py video.mp4            -> processa so esse video
  python cortes.py video.mp4 --qtd 8    -> pede 8 cortes
  python cortes.py --modo desfoque      -> forca o modo (auto, rosto, desfoque)
  python cortes.py live.mp4 --tipo gameplay -> jogo quase sem fala: a IA assiste as imagens
                                           (gameplay.py; tela cheia, gancho, sem marca d'agua)

Opcional: avisos e comandos pelo WhatsApp (whatsapp_cortes.py e vigia_whatsapp.py,
integracao particular com o site, fora do repositorio). Sem eles tudo funciona.
O andamento fica em status.json, que o vigia le para responder "cortes status".
"""

import argparse
import configparser
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import unicodedata
from pathlib import Path

try:
    import whatsapp_cortes as zap
except Exception:  # arquivo nao copiado para a pasta: segue sem WhatsApp
    zap = None

BASE = Path(__file__).resolve().parent
PASTA_ENTRADA = BASE / "entrada"
PASTA_SAIDA = BASE / "saida"
EXTENSOES = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".flv", ".ts"}

LARGURA, ALTURA = 1080, 1920

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ----------------------------------------------------------------------------
# Mensagens
# ----------------------------------------------------------------------------

def titulo(txt):
    print("\n" + "=" * 64)
    print("  " + txt)
    print("=" * 64)


def passo(txt):
    print(f"\n>> {txt}")


def aviso(txt):
    print(f"   [AVISO] {txt}")


class ErroAmigavel(Exception):
    """Erro com explicacao em portugues para o usuario."""


# ----------------------------------------------------------------------------
# Configuracoes
# ----------------------------------------------------------------------------

PADRAO = {
    "geral": {
        "quantidade_cortes": "5",
        "duracao_minima": "20",
        "duracao_maxima": "60",
        "idioma": "pt",
        "tipo_video": "fala",
    },
    "gameplay": {
        "jogo": "",
        "duracao": "40",
        "gancho_segundos": "4",
    },
    "ia": {
        "endereco_lm_studio": "http://localhost:1234/v1",
        "modelo": "",
        "tema_do_canal": "",
    },
    "whisper": {
        "modelo_whisper": "large-v3-turbo",
        "usar_gpu": "sim",
    },
    "video": {
        "modo": "auto",
        "legenda": "sim",
        "cor_destaque": "amarelo",
        "palavras_por_vez": "3",
        "titulo_na_tela": "sim",
        "credito": "",
        "usar_placa_de_video_no_encode": "sim",
        "capa": "sim",
        "fonte_capa": "",
        "qualidade_download": "1080",
    },
    "whatsapp": {
        "senha": "",
        "avisos": "sim",
        "avisar_inicio": "sim",
        "ligar_lm_studio": "sim",
        "endereco": "",
    },
}


def carregar_config():
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    cfg.read_dict(PADRAO)
    arq = BASE / "configuracoes.ini"
    exemplo = BASE / "configuracoes.exemplo.ini"
    if not arq.exists() and exemplo.exists():  # primeira vez (ex.: baixado do GitHub, sem o .ini)
        try:
            shutil.copyfile(exemplo, arq)
        except OSError:
            pass
    if arq.exists():
        cfg.read(arq, encoding="utf-8")
    return cfg


def sim(valor):
    return str(valor).strip().lower() in {"sim", "s", "yes", "y", "true", "1", "verdadeiro"}


def salvar_opcao(secao, chave, valor):
    """Grava uma opcao no configuracoes.ini sem mexer no resto (comentarios,
    ordem e outras secoes ficam como estao). Usado pelo app e pelo vigia."""
    valor = re.sub(r"[#;\r\n]", " ", str(valor)).strip()  # '#' e ';' viram comentario no .ini
    arq = BASE / "configuracoes.ini"
    texto = arq.read_text(encoding="utf-8") if arq.exists() else ""
    partes = re.split(r"(?m)^(?=[ \t]*\[)", texto)  # um pedaco por secao
    cabecalho = re.compile(r"[ \t]*\[" + re.escape(secao) + r"\]")
    linha = re.compile(r"(?m)^([ \t]*" + re.escape(chave) + r"[ \t]*=).*$")
    for i, p in enumerate(partes):
        if cabecalho.match(p):
            if linha.search(p):
                partes[i] = linha.sub(lambda m: m.group(1) + " " + valor, p, count=1)
            else:
                partes[i] = re.sub(r"^([^\n]*)\n?", lambda m: m.group(1) + f"\n{chave} = {valor}\n", p, count=1)
            break
    else:
        partes.append(f"\n[{secao}]\n{chave} = {valor}\n")
    arq.write_text("".join(partes), encoding="utf-8")


# ----------------------------------------------------------------------------
# Andamento (status.json) e avisos pelo WhatsApp
# ----------------------------------------------------------------------------

ARQ_STATUS = BASE / "status.json"
_STATUS = {}


def status(**campos):
    """Grava o andamento em status.json - o vigia do WhatsApp le daqui para
    responder "cortes status". E so informativo: se falhar, o corte segue."""
    _STATUS.update(campos)
    _STATUS["atualizado"] = time.time()
    try:
        tmp = ARQ_STATUS.with_name("status.tmp")
        tmp.write_text(json.dumps(_STATUS, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, ARQ_STATUS)
    except Exception:
        pass


def avisar(cfg, nome, *args):
    """Manda o aviso `nome` (msg_<nome> do whatsapp_cortes.py) para o WhatsApp
    da loja, se estiver configurado. Nunca atrapalha o corte."""
    if zap is None or not zap.avisos_ligados(cfg):
        return
    try:
        ok = zap.enviar(cfg, getattr(zap, "msg_" + nome)(*args))
    except Exception:
        ok = False
    if ok:
        print("   (aviso enviado no WhatsApp)")
    else:
        aviso("Nao consegui mandar o aviso no WhatsApp (sem internet?). Os cortes nao foram afetados.")


# ----------------------------------------------------------------------------
# FFmpeg
# ----------------------------------------------------------------------------

def achar_ffmpeg():
    locais = [BASE / "ffmpeg" / "bin", BASE / "ffmpeg", BASE]
    exe = ".exe" if os.name == "nt" else ""
    for pasta in locais:
        f, p = pasta / f"ffmpeg{exe}", pasta / f"ffprobe{exe}"
        if f.exists() and p.exists():
            return str(f), str(p)
    f, p = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if f and p:
        return f, p
    raise ErroAmigavel(
        "FFmpeg nao encontrado.\n"
        "   Rode o 1_INSTALAR.bat de novo, ou instale com o comando:\n"
        "   winget install -e --id Gyan.FFmpeg\n"
        "   Depois FECHE e abra a janela de novo."
    )


FFMPEG, FFPROBE = None, None


def info_video(caminho):
    cmd = [FFPROBE, "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", str(caminho)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ErroAmigavel(f"Nao consegui ler o video: {caminho.name}\n   {r.stderr.strip()[:300]}")
    dados = json.loads(r.stdout)
    video = next((s for s in dados["streams"] if s.get("codec_type") == "video"), None)
    audio = next((s for s in dados["streams"] if s.get("codec_type") == "audio"), None)
    if not video:
        raise ErroAmigavel(f"O arquivo {caminho.name} nao tem imagem de video.")
    w, h = int(video["width"]), int(video["height"])
    rot = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = abs(int(float(sd["rotation"])))
    if str(video.get("tags", {}).get("rotate", "0")) in {"90", "270"}:
        rot = 90
    if rot in (90, 270):
        w, h = h, w
    fps_txt = video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"
    try:
        n, d = fps_txt.split("/")
        fps = float(n) / float(d) if float(d) else 30.0
    except Exception:
        fps = 30.0
    if not (5 <= fps <= 240):
        fps = 30.0
    fps = min(fps, 60.0)
    dur = float(dados["format"].get("duration") or video.get("duration") or 0)
    return {"w": w, "h": h, "fps": fps, "dur": dur, "audio": audio is not None}


_ENCODER = None


def escolher_encoder(cfg):
    """Usa a placa de video (NVIDIA: NVENC; AMD: AMF) se der; senao, o processador."""
    global _ENCODER
    if _ENCODER:
        return _ENCODER
    if sim(cfg["video"]["usar_placa_de_video_no_encode"]):
        placas = [
            ("NVIDIA", ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                        "-cq", "21", "-b:v", "0", "-maxrate", "16M", "-bufsize", "32M"]),
            ("AMD", ["-c:v", "h264_amf", "-quality", "quality", "-rc", "vbr_peak",
                     "-b:v", "12M", "-maxrate", "16M"]),
        ]
        for marca, enc in placas:
            teste = [FFMPEG, "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                     "color=black:s=1080x1920:d=0.3", enc[0], enc[1], "-f", "null", "-"]
            r = subprocess.run(teste, capture_output=True)
            if r.returncode == 0:
                _ENCODER = enc
                print(f"   Encode: placa de video {marca} (rapido)")
                return _ENCODER
    _ENCODER = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    print("   Encode: processador (libx264)")
    return _ENCODER


# ----------------------------------------------------------------------------
# 1) Transcricao com Whisper
# ----------------------------------------------------------------------------

def preparar_cuda_windows():
    """No Windows, avisa onde estao as DLLs da NVIDIA instaladas pelo pip."""
    if os.name != "nt":
        return
    import site
    pastas = []
    try:
        pastas += site.getsitepackages()
    except Exception:
        pass
    try:
        pastas.append(site.getusersitepackages())
    except Exception:
        pass
    for sp in pastas:
        nv = Path(sp) / "nvidia"
        if nv.is_dir():
            for b in nv.glob("*/bin"):
                try:
                    os.add_dll_directory(str(b))
                except Exception:
                    pass
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


def carregar_audio(caminho):
    """Extrai o audio com o FFmpeg (mono, 16 kHz) direto para a memoria.
    Assim o Whisper nao depende do PyAV, que muda entre versoes."""
    import numpy as np
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-i", str(caminho), "-vn", "-map", "0:a:0",
           "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        erro = r.stderr.decode("utf-8", "replace").strip()[-300:]
        raise ErroAmigavel(f"Nao consegui extrair o audio do video.\n   {erro}")
    return np.frombuffer(r.stdout, np.float32).copy()


def _rodar_whisper(audio, nome_modelo, dispositivo, idioma, duracao):
    from faster_whisper import WhisperModel
    tipo = "float16" if dispositivo == "cuda" else "int8"
    modelo = WhisperModel(nome_modelo, device=dispositivo, compute_type=tipo)
    segs, inf = modelo.transcribe(
        audio,
        language=idioma or None,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=5,
        condition_on_previous_text=False,
    )
    saida = []
    ultimo_pct = -1
    for s in segs:
        palavras = [{"ini": round(w.start, 2), "fim": round(w.end, 2), "p": w.word.strip()}
                    for w in (s.words or []) if w.word.strip()]
        saida.append({"ini": round(s.start, 2), "fim": round(s.end, 2),
                      "texto": s.text.strip(), "palavras": palavras})
        if duracao:
            pct = int(min(100, s.end / duracao * 100))
            if pct >= ultimo_pct + 5:
                ultimo_pct = pct
                print(f"   Transcrevendo... {pct}%", flush=True)
                status(pct=pct)
    return {"idioma": inf.language, "segmentos": saida}


def transcrever(caminho, pasta_saida, cfg, duracao):
    cache = pasta_saida / "transcricao.json"
    if cache.exists():
        print("   Usando transcricao ja feita antes (apague transcricao.json para refazer).")
        return json.loads(cache.read_text(encoding="utf-8"))

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        raise ErroAmigavel("O Whisper nao esta instalado. Rode o 1_INSTALAR.bat.")

    nome = cfg["whisper"]["modelo_whisper"].strip() or "large-v3-turbo"
    idioma = cfg["geral"]["idioma"].strip()
    print(f"   Modelo Whisper: {nome}  (na primeira vez ele baixa o modelo, pode demorar)")
    inicio = time.time()
    print("   Extraindo o audio...", flush=True)
    audio = carregar_audio(caminho)

    resultado = None
    if sim(cfg["whisper"]["usar_gpu"]):
        preparar_cuda_windows()
        try:
            resultado = _rodar_whisper(audio, nome, "cuda", idioma, duracao)
            print("   Whisper rodou na placa de video.")
        except Exception as e:
            aviso(f"Nao deu para usar a placa de video no Whisper ({str(e)[:160]}).")
            aviso("Vou usar o processador. Funciona, so fica mais lento.")
    if resultado is None:
        resultado = _rodar_whisper(audio, nome, "cpu", idioma, duracao)

    if not resultado["segmentos"]:
        raise ErroAmigavel("O Whisper nao encontrou fala nesse video.")
    cache.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"   Transcricao pronta em {time.time() - inicio:.0f}s "
          f"({len(resultado['segmentos'])} trechos).")
    return resultado


# ----------------------------------------------------------------------------
# 2) Escolha dos melhores momentos com o LM Studio
# ----------------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "cortes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "inicio": {"type": "number"},
                    "fim": {"type": "number"},
                    "titulo": {"type": "string"},
                    "texto_capa": {"type": "string"},
                    "nota": {"type": "number"},
                    "motivo": {"type": "string"},
                    "descricao": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["inicio", "fim", "titulo", "texto_capa", "nota", "descricao", "hashtags"],
            },
        }
    },
    "required": ["cortes"],
}


def _post_json(url, payload, timeout):
    import requests
    return requests.post(url, json=payload, timeout=timeout)


def modelos_lm_studio(url):
    """Lista da API propria do LM Studio (/api/v0/models), que diz quais
    modelos estao CARREGADOS. Devolve None se essa API nao existir."""
    import requests
    base = re.sub(r"/v1/?$", "", url.rstrip("/"))
    try:
        r = requests.get(f"{base}/api/v0/models", timeout=5)
        r.raise_for_status()
        return [m for m in r.json().get("data", []) if isinstance(m, dict)]
    except Exception:
        return None


def modelos_carregados(url):
    """Modelos de texto ja carregados na memoria. Com o "JIT loading" do LM
    Studio ligado, o /v1/models lista TODOS os baixados - e escolher um que nao
    esta carregado faria o LM Studio carregar outro modelo por cima."""
    return [m.get("id", "") for m in (modelos_lm_studio(url) or [])
            if m.get("state") == "loaded" and m.get("type") != "embeddings"]


def detectar_modelo(cfg):
    import requests
    url = cfg["ia"]["endereco_lm_studio"].rstrip("/")
    modelo = cfg["ia"]["modelo"].strip()
    try:
        r = requests.get(f"{url}/models", timeout=10)
        r.raise_for_status()
        ids = [m.get("id", "") for m in r.json().get("data", [])]
    except Exception:
        raise ErroAmigavel(
            "Nao consegui falar com o LM Studio.\n"
            "   1. Abra o LM Studio\n"
            "   2. Carregue o modelo (ex.: Gemma 4 12B)\n"
            "   3. Va na aba 'Developer' (icone </>) e ligue o servidor (Status: Running)\n"
            f"   O endereco configurado e: {url}"
        )
    if modelo:
        return modelo
    bons = [i for i in (modelos_carregados(url) or ids) if "embed" not in i.lower()]
    if not bons:
        raise ErroAmigavel("O LM Studio esta aberto, mas nenhum modelo esta carregado. "
                           "Carregue o Gemma e tente de novo.")
    return bons[0]


def _extrair_json(texto):
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S)
    texto = texto.replace("```json", "").replace("```", "")
    tentativas = []
    for abre, fecha in (("{", "}"), ("[", "]")):
        ini, fim = texto.find(abre), texto.rfind(fecha)
        if ini != -1 and fim > ini:
            tentativas.append((ini, texto[ini:fim + 1]))
    for _, trecho in sorted(tentativas):  # o que aparece primeiro no texto
        try:
            dados = json.loads(trecho)
        except json.JSONDecodeError:
            continue
        if isinstance(dados, list):
            return {"cortes": dados}
        if isinstance(dados, dict):
            if "cortes" not in dados and "inicio" in dados:
                return {"cortes": [dados]}
            return dados
    return None


def perguntar_ia(cfg, modelo, sistema, usuario):
    url = cfg["ia"]["endereco_lm_studio"].rstrip("/") + "/chat/completions"
    payload = {
        "model": modelo,
        "messages": [{"role": "system", "content": sistema},
                     {"role": "user", "content": usuario}],
        "temperature": 0.3,
        "max_tokens": 2500,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "cortes", "strict": True, "schema": SCHEMA}},
    }
    for tentativa in range(2):
        try:
            r = _post_json(url, payload, timeout=900)
        except Exception as e:
            aviso(f"Falha ao falar com o LM Studio: {e}")
            return None
        if r.status_code == 400 and "response_format" in payload:
            payload.pop("response_format")  # modelo/versao sem suporte a JSON estruturado
            continue
        if r.status_code != 200:
            txt = r.text[:300]
            if "context" in txt.lower() or "token" in txt.lower():
                aviso("O texto ficou grande demais para o modelo. No LM Studio, aumente o "
                      "'Context Length' do modelo para 8192 ou mais.")
            aviso(f"LM Studio respondeu com erro {r.status_code}: {txt}")
            return None
        try:
            conteudo = r.json()["choices"][0]["message"]["content"] or ""
        except Exception:
            return None
        dados = _extrair_json(conteudo)
        if dados is not None:
            return dados
        if tentativa == 0:
            payload["messages"].append({"role": "assistant", "content": conteudo[:2000]})
            payload["messages"].append({"role": "user",
                                        "content": "Responda APENAS com o JSON pedido, sem texto extra."})
    return None


def dividir_em_blocos(segmentos, tam=420, sobra=60):
    """Divide a transcricao em blocos de ~7 min (com sobreposicao) para caber no modelo."""
    if not segmentos:
        return []
    blocos, ini = [], segmentos[0]["ini"]
    fim_total = segmentos[-1]["fim"]
    while ini < fim_total:
        fim = ini + tam
        bloco = [s for s in segmentos if s["fim"] > ini and s["ini"] < fim]
        if bloco:
            blocos.append(bloco)
        if fim >= fim_total:
            break
        ini = fim - sobra
    return blocos


def montar_prompt(cfg, bloco, qtd_bloco):
    dmin = int(cfg["geral"]["duracao_minima"])
    dmax = int(cfg["geral"]["duracao_maxima"])
    tema = cfg["ia"]["tema_do_canal"].strip()
    sistema = (
        "Voce e um editor especialista em cortes virais para TikTok, Instagram Reels, Kwai e "
        "YouTube Shorts no Brasil. Sua tarefa e encontrar os trechos de um video longo que "
        "funcionam sozinhos como videos curtos e prendem a atencao.\n"
        "Regras:\n"
        f"- Cada corte deve ter entre {dmin} e {dmax} segundos.\n"
        "- O corte precisa fazer sentido sozinho: comeca no inicio de uma frase e termina quando "
        "a ideia fecha (nunca no meio de uma frase).\n"
        "- Os primeiros 3 segundos precisam ter um gancho forte: pergunta, afirmacao polemica, "
        "revelacao, numero surpreendente, historia engracada ou emocionante.\n"
        "- Evite trechos que dependem de contexto anterior, saudacoes, propagandas e "
        "pedidos de like.\n"
        "- 'inicio' e 'fim' sao segundos, usando os tempos entre colchetes da transcricao.\n"
        "- 'titulo': curto e chamativo (maximo 8 palavras), em portugues.\n"
        "- 'texto_capa': texto da thumbnail, de 2 a 5 palavras de impacto que geram curiosidade "
        "(ex.: 'ELE NAO ESPERAVA ISSO', 'O ERRO QUE CUSTOU CARO'). Nao repita o titulo.\n"
        "- 'nota': de 1 a 10, o quanto o corte tem potencial de viralizar.\n"
        "- 'descricao': legenda pronta para a postagem (1 ou 2 frases).\n"
        "- 'hashtags': 3 a 5 hashtags relevantes.\n"
        "Responda SOMENTE com JSON no formato: "
        '{"cortes":[{"inicio":0,"fim":0,"titulo":"","texto_capa":"","nota":0,"motivo":"",'
        '"descricao":"","hashtags":[]}]}'
    )
    linhas = "\n".join(f"[{s['ini']:.0f}-{s['fim']:.0f}] {s['texto']}" for s in bloco)
    usuario = ""
    if tema:
        usuario += f"Tema do canal: {tema}\n\n"
    usuario += (f"Transcricao (tempos em segundos):\n{linhas}\n\n"
                f"Encontre ate {qtd_bloco} cortes neste trecho. Se nao houver nenhum trecho bom, "
                'retorne {"cortes": []}.')
    return sistema, usuario


def ajustar_corte(c, segmentos, dmin, dmax, duracao):
    """Encaixa o corte no comeco/fim de frases e respeita a duracao."""
    try:
        ini, fim = float(c["inicio"]), float(c["fim"])
    except (KeyError, TypeError, ValueError):
        return None
    if fim < ini:
        ini, fim = fim, ini
    ini, fim = max(0.0, ini), min(duracao, fim)

    # comeca no inicio da frase que contem o "inicio"
    i0 = next((i for i, s in enumerate(segmentos) if s["fim"] > ini + 0.3), None)
    if i0 is None:
        return None
    novo_ini = segmentos[i0]["ini"]
    # termina no fim da frase que contem o "fim"
    i1 = next((i for i in range(len(segmentos) - 1, -1, -1) if segmentos[i]["ini"] < fim - 0.3), i0)
    i1 = max(i1, i0)

    # curto demais: puxa as proximas frases
    while segmentos[i1]["fim"] - novo_ini < dmin and i1 + 1 < len(segmentos):
        if segmentos[i1 + 1]["fim"] - novo_ini > dmax:
            break
        i1 += 1
    # longo demais: corta frases do fim
    while segmentos[i1]["fim"] - novo_ini > dmax and i1 > i0:
        i1 -= 1
    novo_fim = segmentos[i1]["fim"]
    if novo_fim - novo_ini > dmax:  # uma frase gigante sozinha: corta pela palavra
        palavras = [w for s in segmentos[i0:i1 + 1] for w in s["palavras"]]
        dentro = [w for w in palavras if w["fim"] <= novo_ini + dmax]
        novo_fim = dentro[-1]["fim"] if dentro else novo_ini + dmax
    if novo_fim - novo_ini < min(dmin, 8):
        return None

    c = dict(c)
    c["inicio"] = max(0.0, novo_ini - 0.15)
    c["fim"] = min(duracao, novo_fim + 0.4)
    try:
        c["nota"] = float(c.get("nota", 5))
    except (TypeError, ValueError):
        c["nota"] = 5.0
    c["titulo"] = str(c.get("titulo", "")).strip().strip('"') or "Corte"
    c["texto_capa"] = str(c.get("texto_capa", "")).strip().strip('"')
    c["descricao"] = str(c.get("descricao", "")).strip()
    tags = c.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    c["hashtags"] = [("#" + t.lstrip("#")).replace(" ", "") for t in tags if str(t).strip()][:6]
    return c


def sobrepoe(a, b):
    inter = min(a["fim"], b["fim"]) - max(a["inicio"], b["inicio"])
    menor = min(a["fim"] - a["inicio"], b["fim"] - b["inicio"])
    return inter > 0.35 * menor


def escolha_sem_ia(segmentos, qtd, dmin, dmax, duracao):
    """Plano B: pega os trechos com fala mais intensa, espalhados pelo video."""
    janela = (dmin + dmax) / 2
    candidatos = []
    for i, s in enumerate(segmentos):
        fim_alvo = s["ini"] + janela
        bloco = [x for x in segmentos[i:] if x["fim"] <= fim_alvo + 5]
        if not bloco:
            continue
        palavras = sum(len(x["palavras"]) for x in bloco)
        dur = bloco[-1]["fim"] - s["ini"]
        if dur < dmin:
            continue
        candidatos.append({"inicio": s["ini"], "fim": bloco[-1]["fim"], "nota": palavras / dur,
                           "titulo": f"Corte {len(candidatos) + 1}", "descricao": "",
                           "hashtags": []})
    candidatos.sort(key=lambda c: -c["nota"])
    escolhidos = []
    for c in candidatos:
        c = ajustar_corte(c, segmentos, dmin, dmax, duracao)
        if c and not any(sobrepoe(c, e) for e in escolhidos):
            escolhidos.append(c)
        if len(escolhidos) >= qtd:
            break
    return escolhidos


def escolher_momentos(transcricao, cfg, qtd, duracao, pasta_saida):
    segmentos = transcricao["segmentos"]
    dmin = int(cfg["geral"]["duracao_minima"])
    dmax = int(cfg["geral"]["duracao_maxima"])

    modelo = detectar_modelo(cfg)
    print(f"   Modelo no LM Studio: {modelo}")
    blocos = dividir_em_blocos(segmentos)
    qtd_bloco = max(2, min(5, math.ceil(qtd * 1.6 / max(1, len(blocos))) + 1))

    candidatos = []
    for n, bloco in enumerate(blocos, 1):
        print(f"   Analisando parte {n} de {len(blocos)} "
              f"({bloco[0]['ini'] / 60:.0f}min a {bloco[-1]['fim'] / 60:.0f}min)...", flush=True)
        status(parte=n, partes=len(blocos))
        sistema, usuario = montar_prompt(cfg, bloco, qtd_bloco)
        dados = perguntar_ia(cfg, modelo, sistema, usuario)
        if not dados:
            aviso(f"A IA nao respondeu direito na parte {n}. Pulando essa parte.")
            continue
        lista = dados.get("cortes", []) if isinstance(dados, dict) else []
        for c in lista if isinstance(lista, list) else []:
            if isinstance(c, dict):
                c = ajustar_corte(c, segmentos, dmin, dmax, duracao)
                if c:
                    candidatos.append(c)

    candidatos.sort(key=lambda c: -c["nota"])
    escolhidos = []
    for c in candidatos:
        if not any(sobrepoe(c, e) for e in escolhidos):
            escolhidos.append(c)
        if len(escolhidos) >= qtd:
            break

    if not escolhidos:
        aviso("A IA nao escolheu nenhum corte. Usando o plano B (trechos com mais fala).")
        escolhidos = escolha_sem_ia(segmentos, qtd, dmin, dmax, duracao)

    (pasta_saida / "cortes_escolhidos.json").write_text(
        json.dumps(escolhidos, ensure_ascii=False, indent=1), encoding="utf-8")
    return escolhidos


# ----------------------------------------------------------------------------
# 3) Enquadramento 9:16 seguindo o rosto
# ----------------------------------------------------------------------------

_DETECTORES = None


def detectores():
    global _DETECTORES
    if _DETECTORES is None:
        import cv2
        pasta = cv2.data.haarcascades
        _DETECTORES = [cv2.CascadeClassifier(pasta + "haarcascade_frontalface_default.xml"),
                       cv2.CascadeClassifier(pasta + "haarcascade_profileface.xml")]
    return _DETECTORES


def analisar_rostos(caminho, ini, dur, info):
    """Olha o trecho em baixa resolucao (4 quadros/s) e devolve a posicao do rosto."""
    import cv2
    import numpy as np
    w, h = info["w"], info["h"]
    pw = 480
    ph = int(round(pw * h / w / 2)) * 2
    cmd = [FFMPEG, "-v", "error", "-ss", f"{ini:.3f}", "-t", f"{dur:.3f}", "-i", str(caminho),
           "-vf", f"fps=4,scale={pw}:{ph}", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frontal, perfil = detectores()
    tam = pw * ph
    posicoes, anterior = [], None
    while True:
        buf = proc.stdout.read(tam)
        if len(buf) < tam:
            break
        img = np.frombuffer(buf, np.uint8).reshape(ph, pw)
        img = cv2.equalizeHist(img)
        minimo = max(24, ph // 12)
        rostos = list(frontal.detectMultiScale(img, 1.1, 5, minSize=(minimo, minimo)))
        if not rostos:
            rostos = list(perfil.detectMultiScale(img, 1.1, 5, minSize=(minimo, minimo)))
            if not rostos:  # perfil virado para o outro lado
                esp = cv2.flip(img, 1)
                rostos = [(pw - x - rw, y, rw, rh) for (x, y, rw, rh) in
                          perfil.detectMultiScale(esp, 1.1, 5, minSize=(minimo, minimo))]
        if rostos:
            maior = max(r[2] * r[3] for r in rostos)
            grandes = [r for r in rostos if r[2] * r[3] >= 0.55 * maior]
            centros = [(r[0] + r[2] / 2) / pw for r in grandes]
            if anterior is not None:
                cx = min(centros, key=lambda c: abs(c - anterior))
            else:
                cx = (max(grandes, key=lambda r: r[2] * r[3])[0] +
                      max(grandes, key=lambda r: r[2] * r[3])[2] / 2) / pw
            posicoes.append(cx)
            anterior = cx
        else:
            posicoes.append(None)
    proc.wait()
    return posicoes


def suavizar(posicoes, largura_corte_rel):
    """Transforma as posicoes cruas em um movimento de camera suave."""
    if not posicoes:
        return [0.5]
    n = len(posicoes)
    # preenche buracos (quadros sem rosto) com o rosto mais proximo
    cheios = list(posicoes)
    ultimo = next((p for p in cheios if p is not None), 0.5)
    for i in range(n):
        if cheios[i] is None:
            cheios[i] = ultimo
        else:
            ultimo = cheios[i]
    # mediana de ~1,5 s: ignora deteccoes erradas de um quadro so
    med = []
    for i in range(n):
        janela = sorted(cheios[max(0, i - 3): i + 4])
        med.append(janela[len(janela) // 2])
    # "operador de camera": fica parado, segue devagar, e corta seco quando muda de pessoa
    zona_morta = largura_corte_rel * 0.12
    salto = largura_corte_rel * 0.6
    pos = med[0]
    saida = []
    for alvo in med:
        d = alvo - pos
        if abs(d) > salto:
            pos = alvo
        elif abs(d) > zona_morta:
            pos += d * 0.22
        saida.append(pos)
    return saida


# ----------------------------------------------------------------------------
# 4) Legenda animada (ASS)
# ----------------------------------------------------------------------------

CORES = {
    "amarelo": "&H0000FFFF", "verde": "&H0000FF00", "vermelho": "&H003030FF",
    "azul": "&H00FFA020", "laranja": "&H00008CFF", "rosa": "&H00B469FF",
    "roxo": "&H00FF50A0", "ciano": "&H00FFFF00", "branco": "&H00FFFFFF",
}


def tempo_ass(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def limpar_texto_ass(txt):
    return txt.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def agrupar_palavras(palavras, max_palavras=3, max_letras=18):
    grupos, atual = [], []
    for w in palavras:
        letras = sum(len(x["p"]) + 1 for x in atual) + len(w["p"])
        if atual and (len(atual) >= max_palavras or letras > max_letras):
            grupos.append(atual)
            atual = []
        atual.append(w)
        if re.search(r"[.!?…]$", w["p"]):
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    return grupos


def gerar_legenda(arquivo, palavras, duracao, cfg, titulo_corte):
    cor = CORES.get(cfg["video"]["cor_destaque"].strip().lower(), CORES["amarelo"])
    try:
        por_vez = max(1, min(6, int(cfg["video"]["palavras_por_vez"])))
    except ValueError:
        por_vez = 3
    credito = cfg["video"]["credito"].strip()

    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {LARGURA}
PlayResY: {ALTURA}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Legenda,Arial Black,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,7,3,2,70,70,500,1
Style: Titulo,Arial Black,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,230,1
Style: Credito,Arial,38,&H40FFFFFF,&H40FFFFFF,&H80000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,2,60,60,110,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    linhas = []
    if sim(cfg["video"]["titulo_na_tela"]) and titulo_corte:
        linhas.append(f"Dialogue: 1,{tempo_ass(0)},{tempo_ass(min(5.0, duracao))},Titulo,,0,0,0,,"
                      f"{{\\fad(150,300)}}{limpar_texto_ass(titulo_corte.upper())}")
    if credito:
        linhas.append(f"Dialogue: 1,{tempo_ass(0)},{tempo_ass(duracao)},Credito,,0,0,0,,"
                      f"Creditos: {limpar_texto_ass(credito)}")

    if sim(cfg["video"]["legenda"]) and palavras:
        grupos = agrupar_palavras(palavras, por_vez)
        for gi, g in enumerate(grupos):
            fim_grupo = g[-1]["fim"]
            prox = grupos[gi + 1][0]["ini"] if gi + 1 < len(grupos) else duracao
            if prox - fim_grupo < 0.6:  # evita a legenda "piscar" entre grupos
                fim_grupo = prox
            else:
                fim_grupo = min(fim_grupo + 0.3, prox)
            textos = [limpar_texto_ass(w["p"].upper()) for w in g]
            for wi, w in enumerate(g):
                ini = w["ini"] if wi > 0 else min(w["ini"], g[0]["ini"])
                fim = g[wi + 1]["ini"] if wi + 1 < len(g) else fim_grupo
                if fim <= ini:
                    fim = ini + 0.05
                partes = []
                for k, t in enumerate(textos):
                    if k == wi:
                        partes.append(f"{{\\c{cor}\\fscx112\\fscy112}}{t}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}")
                    else:
                        partes.append(t)
                linhas.append(f"Dialogue: 0,{tempo_ass(ini)},{tempo_ass(fim)},Legenda,,0,0,0,,"
                              + " ".join(partes))

    Path(arquivo).write_text(cab + "\n".join(linhas) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# 4b) Capa (thumbnail)
# ----------------------------------------------------------------------------

CORES_RGB = {
    "amarelo": (255, 230, 0), "verde": (60, 255, 60), "vermelho": (255, 50, 50),
    "azul": (40, 160, 255), "laranja": (255, 140, 0), "rosa": (255, 105, 180),
    "roxo": (170, 80, 255), "ciano": (0, 230, 255), "branco": (255, 255, 255),
}


def garantir_pillow():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        print("   Instalando o componente de imagens (Pillow), so na primeira vez...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pillow"])
        if r.returncode != 0:
            aviso("Nao consegui instalar o Pillow. Rode o 1_INSTALAR.bat de novo.")
            return False
        import importlib
        importlib.invalidate_caches()
        return True


def achar_fonte(cfg):
    escolhida = cfg["video"].get("fonte_capa", "").strip().strip('"')
    pastas = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
              Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
              Path("/usr/share/fonts/truetype/liberation"), Path("/usr/share/fonts/truetype/dejavu"),
              Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
    if escolhida:
        p = Path(escolhida)
        if p.exists():
            return str(p)
        for pasta in pastas:
            if (pasta / escolhida).exists():
                return str(pasta / escolhida)
        aviso(f"Fonte '{escolhida}' nao encontrada. Usando a padrao.")
    nomes = ["ariblk.ttf", "Arial Black.ttf", "impact.ttf", "Impact.ttf", "seguibl.ttf",
             "arialbd.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"]
    for nome in nomes:
        for pasta in pastas:
            if (pasta / nome).exists():
                return str(pasta / nome)
    return None


def _ler_quadro(caminho, t, largura=None):
    """Le um quadro do video no tempo t (segundos) como array RGB."""
    import numpy as np
    vf = f"scale={largura}:-2" if largura else "null"
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", str(caminho),
           "-frames:v", "1", "-vf", vf, "-f", "image2pipe", "-vcodec", "png", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    import cv2
    img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
    return None if img is None else cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def escolher_quadro(caminho, ini, fim):
    """Olha varios quadros do corte e escolhe o mais nitido, de preferencia com rosto."""
    import cv2
    import numpy as np
    margem = min(1.0, (fim - ini) * 0.1)
    tempos = np.linspace(ini + margem, fim - margem, 16)
    frontal = detectores()[0]
    melhor = None
    for t in tempos:
        img = _ler_quadro(caminho, t, 640)
        if img is None:
            continue
        cinza = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        hh, ww = cinza.shape
        rostos = frontal.detectMultiScale(cv2.equalizeHist(cinza), 1.1, 5,
                                          minSize=(max(24, hh // 12),) * 2)
        if len(rostos):
            x, y, rw, rh = max(rostos, key=lambda r: r[2] * r[3])
            regiao = cinza[y:y + rh, x:x + rw]
            area = rw * rh / (ww * hh)
            # centro horizontal, e onde o rosto comeca/termina na vertical (0 a 1)
            cx = ((x + rw / 2) / ww, y / hh, min(1.0, (y + rh * 1.25) / hh))
        else:
            regiao, area, cx = cinza, 0.0, None
        nitidez = cv2.Laplacian(regiao, cv2.CV_64F).var()
        nota = math.log1p(nitidez) + (3 + 40 * area if cx is not None else 0)
        if cinza.mean() < 45:
            nota -= 2
        if melhor is None or nota > melhor[0]:
            melhor = (nota, float(t), cx)
    if melhor is None:
        return (ini + fim) / 2, None
    return melhor[1], melhor[2]


def _quebrar_linhas(desenho, palavras, fonte, largura_max):
    linhas, atual = [], []
    for p in palavras:
        teste = " ".join(atual + [p])
        if atual and desenho.textlength(teste, font=fonte) > largura_max:
            linhas.append(atual)
            atual = [p]
        else:
            atual.append(p)
    if atual:
        linhas.append(atual)
    return linhas


def gerar_capa(caminho, info, corte, arquivo, cfg, tela_cheia=False):
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

    if tela_cheia and corte.get("capa_t") is not None:
        t, rosto = float(corte["capa_t"]), None  # gameplay: o quadro que a IA deu a maior nota
    else:
        t, rosto = escolher_quadro(caminho, corte["inicio"], corte["fim"])
    cx, rosto_topo, rosto_base = rosto if rosto else (None, None, None)
    if tela_cheia:  # gameplay: o mesmo recorte do video (so o jogo, sem fundo desfocado)
        cx, rosto_topo, rosto_base = float(corte.get("cx", 0.5)), None, None
    quadro = _ler_quadro(caminho, t)
    if quadro is None:
        raise RuntimeError("nao consegui ler o quadro do video")
    img = Image.fromarray(quadro)
    w, h = img.size

    # --- Monta a imagem em pe (9:16) ---
    cw = int(round(h * 9 / 16))
    if cx is not None and cw < w:
        x = int(round(cx * w - cw / 2))
        x = max(0, min(w - cw, x))
        capa = img.crop((x, 0, x + cw, h)).resize((LARGURA, ALTURA), Image.LANCZOS)
    else:
        rosto_topo = rosto_base = None  # no modo desfocado o rosto muda de lugar
        escala = max(LARGURA / w, ALTURA / h)
        fundo = img.resize((int(w * escala) + 1, int(h * escala) + 1), Image.LANCZOS)
        fl, fa = fundo.size
        fundo = fundo.crop(((fl - LARGURA) // 2, (fa - ALTURA) // 2,
                            (fl - LARGURA) // 2 + LARGURA, (fa - ALTURA) // 2 + ALTURA))
        fundo = ImageEnhance.Brightness(fundo.filter(ImageFilter.GaussianBlur(40))).enhance(0.6)
        escala = min(LARGURA / w, ALTURA / h)
        frente = img.resize((int(w * escala), int(h * escala)), Image.LANCZOS)
        y = max(0, int(ALTURA * 0.40 - frente.size[1] / 2))
        fundo.paste(frente, ((LARGURA - frente.size[0]) // 2, y))
        capa = fundo

    capa = ImageEnhance.Contrast(capa).enhance(1.07)
    capa = ImageEnhance.Color(capa).enhance(1.15)
    capa = capa.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2)).convert("RGBA")

    # --- Onde vai o texto: abaixo do rosto, ou no topo se nao couber ---
    H = ALTURA
    if rosto_base is not None:
        abaixo = (max(H * 0.45, rosto_base * H + 40), H * 0.82)
        if abaixo[1] - abaixo[0] >= 300:
            regiao, texto_no_topo = abaixo, False
        else:
            regiao, texto_no_topo = (H * 0.08, max(H * 0.25, rosto_topo * H - 30)), True
    else:
        regiao, texto_no_topo = (H * 0.50, H * 0.80), False

    # --- Escurece a area do texto para ele aparecer bem ---
    grad = Image.new("L", (1, ALTURA))
    for yy in range(ALTURA):
        pos = (ALTURA - yy) if texto_no_topo else yy
        r = (pos - ALTURA * 0.42) / (ALTURA * 0.58)
        grad.putpixel((0, yy), int(235 * max(0.0, min(1.0, r)) ** 1.3))
    sombra = Image.new("RGBA", (LARGURA, ALTURA), (0, 0, 0, 255))
    sombra.putalpha(grad.resize((LARGURA, ALTURA)))
    capa = Image.alpha_composite(capa, sombra)

    # --- Texto ---
    texto = (corte.get("texto_capa") or corte.get("titulo") or "").strip().upper()
    texto = re.sub(r"\s+", " ", texto)
    caminho_fonte = achar_fonte(cfg)
    if texto:
        def fonte_tam(tam):
            return ImageFont.truetype(caminho_fonte, tam) if caminho_fonte else ImageFont.load_default(tam)

        camada = Image.new("RGBA", capa.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(camada)
        palavras = texto.split()
        largura_max = LARGURA - 120
        espaco = regiao[1] - regiao[0]
        # o maior tamanho que cabe na largura e na altura livre (sem cobrir o rosto)
        for tam in range(190, 64, -6):
            fonte = fonte_tam(tam)
            linhas = _quebrar_linhas(d, palavras, fonte, largura_max)
            cabe_larg = all(d.textlength(" ".join(l), font=fonte) <= largura_max for l in linhas)
            if len(linhas) <= 4 and cabe_larg and int(tam * 1.08) * len(linhas) + tam // 7 <= espaco:
                break
        cor = CORES_RGB.get(cfg["video"]["cor_destaque"].strip().lower(), CORES_RGB["amarelo"])
        candidatas = [p for p in palavras if len(re.sub(r"\W", "", p)) >= 4] or palavras
        destaque = max(candidatas, key=lambda p: len(re.sub(r"\W", "", p)))

        alt_linha = int(tam * 1.08)
        bloco = alt_linha * len(linhas)
        # um pouco acima do meio da regiao livre
        y = int(regiao[0] + max(0, espaco - bloco) * (0.5 if texto_no_topo else 0.3))
        contorno = max(6, tam // 14)
        esp = d.textlength(" ", font=fonte)
        posicoes = []
        for linha in linhas:
            larg = d.textlength(" ".join(linha), font=fonte)
            x = (LARGURA - larg) / 2
            for p in linha:
                posicoes.append((x, y, p))
                x += d.textlength(p, font=fonte) + esp
            y += alt_linha

        # sombra borrada atras do texto
        sombra_txt = Image.new("RGBA", capa.size, (0, 0, 0, 0))
        ds = ImageDraw.Draw(sombra_txt)
        for x, yy, p in posicoes:
            ds.text((x + 8, yy + 10), p, font=fonte, fill=(0, 0, 0, 200),
                    stroke_width=contorno, stroke_fill=(0, 0, 0, 200))
        capa = Image.alpha_composite(capa, sombra_txt.filter(ImageFilter.GaussianBlur(12)))
        for x, yy, p in posicoes:
            d.text((x, yy), p, font=fonte, fill=cor if p == destaque else (255, 255, 255),
                   stroke_width=contorno, stroke_fill=(0, 0, 0))
        capa = Image.alpha_composite(capa, camada)

    credito = cfg["video"]["credito"].strip()
    if credito:
        d = ImageDraw.Draw(capa)
        f = ImageFont.truetype(caminho_fonte, 40) if caminho_fonte else ImageFont.load_default(40)
        txt = f"Creditos: {credito}"
        d.text(((LARGURA - d.textlength(txt, font=f)) / 2, 90), txt, font=f,
               fill=(255, 255, 255, 230), stroke_width=3, stroke_fill=(0, 0, 0))

    capa.convert("RGB").save(arquivo, "JPEG", quality=92)
    return arquivo


# ----------------------------------------------------------------------------
# 5) Renderizacao
# ----------------------------------------------------------------------------

def nome_seguro(txt, limite=50):
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    txt = re.sub(r"[^\w\s-]", "", txt).strip().lower()
    txt = re.sub(r"[\s_-]+", "_", txt)
    return txt[:limite].strip("_") or "corte"


def _rodar(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-800:])


def render_desfoque(caminho, ini, dur, info, saida, legenda, encoder, pasta_tmp):
    fps = info["fps"]
    filtro = (f"[0:v]fps={fps:.3f},split=2[a][b];"
              f"[a]scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=increase,"
              f"crop={LARGURA}:{ALTURA},boxblur=24:2,eq=brightness=-0.12[fundo];"
              f"[b]scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=decrease[frente];"
              f"[fundo][frente]overlay=(W-w)/2:(H-h)/2")
    if legenda:
        filtro += f",ass={legenda}"
    filtro += ",format=yuv420p[v]"
    cmd = [FFMPEG, "-y", "-hide_banner", "-v", "error",
           "-ss", f"{ini:.3f}", "-t", f"{dur:.3f}", "-i", str(caminho),
           "-filter_complex", filtro, "-map", "[v]"]
    if info["audio"]:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    cmd += encoder + ["-movflags", "+faststart", str(saida)]
    _rodar(cmd, pasta_tmp)


def render_rosto(caminho, ini, dur, info, saida, legenda, encoder, pasta_tmp, trilha):
    import numpy as np
    w, h, fps = info["w"], info["h"], info["fps"]
    cw = int(round(h * 9 / 16 / 2)) * 2
    tam = w * h * 3

    dec = [FFMPEG, "-v", "error", "-ss", f"{ini:.3f}", "-t", f"{dur:.3f}", "-i", str(caminho),
           "-vf", f"fps={fps:.3f}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    vf = f"scale={LARGURA}:{ALTURA}:flags=lanczos"
    if legenda:
        vf += f",ass={legenda}"
    vf += ",format=yuv420p"
    enc = [FFMPEG, "-y", "-hide_banner", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{cw}x{h}", "-r", f"{fps:.3f}", "-i", "-"]
    if info["audio"]:
        enc += ["-ss", f"{ini:.3f}", "-t", f"{dur:.3f}", "-i", str(caminho),
                "-map", "0:v", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
    enc += ["-vf", vf] + encoder + ["-movflags", "+faststart", "-shortest", str(saida)]

    p_dec = subprocess.Popen(dec, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    p_enc = subprocess.Popen(enc, stdin=subprocess.PIPE, stderr=subprocess.PIPE, cwd=pasta_tmp)
    n_trilha = len(trilha)
    i = 0
    try:
        while True:
            buf = p_dec.stdout.read(tam)
            if len(buf) < tam:
                break
            # posicao da camera neste quadro (a trilha tem 4 pontos por segundo)
            t = i / fps * 4
            k = int(t)
            frac = t - k
            a = trilha[min(k, n_trilha - 1)]
            b = trilha[min(k + 1, n_trilha - 1)]
            cx = a + (b - a) * frac
            x = int(round(cx * w - cw / 2))
            x = max(0, min(w - cw, x))
            quadro = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            p_enc.stdin.write(np.ascontiguousarray(quadro[:, x:x + cw]).tobytes())
            i += 1
    except BrokenPipeError:
        pass
    finally:
        try:
            p_enc.stdin.close()
        except Exception:
            pass
        p_dec.stdout.close()
        p_dec.wait()
    erro = p_enc.stderr.read().decode("utf-8", "replace")
    p_enc.wait()
    if p_enc.returncode != 0:
        raise RuntimeError(erro.strip()[-800:])


def gerar_corte(caminho, info, corte, numero, pasta_saida, transcricao, cfg, modo_forcado):
    ini, fim = corte["inicio"], corte["fim"]
    dur = fim - ini
    pasta_tmp = pasta_saida / "_temp"
    pasta_tmp.mkdir(exist_ok=True)

    palavras = [{"ini": w["ini"] - ini, "fim": w["fim"] - ini, "p": w["p"]}
                for s in transcricao["segmentos"] for w in s["palavras"]
                if w["ini"] >= ini - 0.05 and w["fim"] <= fim + 0.3]
    nome_leg = f"legenda_{numero:02d}.ass"
    gerar_legenda(pasta_tmp / nome_leg, palavras, dur, cfg, corte["titulo"])
    usa_legenda = (sim(cfg["video"]["legenda"]) or sim(cfg["video"]["titulo_na_tela"])
                   or bool(cfg["video"]["credito"].strip()))
    legenda = nome_leg if usa_legenda else None

    arquivo = pasta_saida / f"corte_{numero:02d}_{nome_seguro(corte['titulo'])}.mp4"
    encoder = escolher_encoder(cfg)

    modo = modo_forcado or cfg["video"]["modo"].strip().lower()
    cw = int(round(info["h"] * 9 / 16 / 2)) * 2
    if cw >= info["w"]:
        modo = "desfoque"  # video ja e em pe ou quase: nao precisa recortar

    trilha = None
    if modo in ("auto", "rosto"):
        try:
            posicoes = analisar_rostos(caminho, ini, dur, info)
        except Exception as e:
            aviso(f"Detector de rosto falhou ({str(e)[:120]}). Usando fundo desfocado.")
            posicoes, modo = [], "auto"
        achados = sum(p is not None for p in posicoes)
        taxa = achados / max(1, len(posicoes))
        if modo == "auto" and taxa < 0.35:
            print(f"   Poucos rostos nesse trecho ({taxa:.0%}). Usando fundo desfocado.")
            modo = "desfoque"
        else:
            modo = "rosto"
            trilha = suavizar(posicoes, cw / info["w"])

    def renderizar(enc):
        if modo == "rosto":
            render_rosto(caminho, ini, dur, info, arquivo, legenda, enc, pasta_tmp, trilha)
        else:
            render_desfoque(caminho, ini, dur, info, arquivo, legenda, enc, pasta_tmp)

    try:
        renderizar(encoder)
    except RuntimeError as e:
        if "nvenc" in " ".join(encoder) or "amf" in " ".join(encoder):
            aviso("Encode pela placa de video falhou neste corte. Tentando pelo processador...")
            global _ENCODER
            _ENCODER = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
            renderizar(_ENCODER)
        else:
            raise RuntimeError(str(e))
    return arquivo, modo


def mmss(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def escrever_relatorio(pasta_saida, video, resultados, cfg):
    credito = cfg["video"]["credito"].strip()
    linhas = [f"CORTES DE: {video.name}", f"Gerado em: {time.strftime('%d/%m/%Y %H:%M')}", ""]
    for arq, corte, modo in resultados:
        linhas += [
            "-" * 60,
            f"ARQUIVO: {arq.name}",
            f"Trecho do original: {mmss(corte['inicio'])} ate {mmss(corte['fim'])} "
            f"({corte['fim'] - corte['inicio']:.0f}s) | Nota da IA: {corte['nota']:.0f}/10 | Modo: {modo}",
            f"TITULO: {corte['titulo']}",
            f"TEXTO DA CAPA: {corte.get('texto_capa') or corte['titulo']}",
            "",
            "LEGENDA PARA POSTAR:",
            corte["descricao"] or corte["titulo"],
        ]
        if credito:
            linhas.append(f"Creditos: {credito}")
        if corte["hashtags"]:
            linhas.append(" ".join(corte["hashtags"]))
        linhas.append("")
    (pasta_saida / "POSTAGENS.txt").write_text("\n".join(linhas), encoding="utf-8")


# ----------------------------------------------------------------------------
# Principal
# ----------------------------------------------------------------------------

def processar(video, cfg, qtd, modo_forcado, num=1, total=1):
    titulo(f"VIDEO: {video.name}")
    t_video = time.time()
    pasta_saida = PASTA_SAIDA / nome_seguro(video.stem, 60)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    info = info_video(video)
    print(f"   {info['w']}x{info['h']} | {info['fps']:.0f} fps | {mmss(info['dur'])} de duracao")
    if not info["audio"]:
        raise ErroAmigavel("Esse video nao tem audio, entao nao da para achar os melhores momentos.")

    passo("1/3 Transcrevendo a fala (Whisper)")
    status(video=video.name, duracao=info["dur"], etapa="transcrevendo", pct=0,
           parte=0, partes=0, corte=0, cortes_total=0)
    transcricao = transcrever(video, pasta_saida, cfg, info["dur"])

    passo("2/3 Escolhendo os melhores momentos (IA do LM Studio)")
    status(etapa="escolhendo")
    cortes = escolher_momentos(transcricao, cfg, qtd, info["dur"], pasta_saida)
    print(f"   {len(cortes)} corte(s) escolhido(s):")
    for i, c in enumerate(cortes, 1):
        print(f"     {i:02d}. [{mmss(c['inicio'])}-{mmss(c['fim'])}] nota {c['nota']:.0f} - {c['titulo']}")

    passo("3/3 Gerando os videos (9:16 + legenda)")
    status(etapa="gerando", cortes_total=len(cortes))
    resultados = []
    erros, ultimo_erro = 0, ""
    for i, c in enumerate(cortes, 1):
        print(f"   Corte {i} de {len(cortes)}: {c['titulo']}", flush=True)
        status(corte=i)
        t0 = time.time()
        try:
            arq, modo = gerar_corte(video, info, c, i, pasta_saida, transcricao, cfg, modo_forcado)
            resultados.append((arq, c, modo))
            print(f"   OK -> {arq.name} ({time.time() - t0:.0f}s)")
        except Exception as e:
            aviso(f"Erro ao gerar o corte {i}: {e}")
            erros, ultimo_erro = erros + 1, str(e)
            continue
        if sim(cfg["video"].get("capa", "sim")) and garantir_pillow():
            try:
                capa = gerar_capa(video, info, c, arq.with_name(arq.stem + "_capa.jpg"), cfg)
                print(f"   Capa -> {capa.name}")
            except Exception as e:
                aviso(f"Erro ao gerar a capa do corte {i}: {e}")

    shutil.rmtree(pasta_saida / "_temp", ignore_errors=True)
    escrever_relatorio(pasta_saida, video, resultados, cfg)
    if not resultados:
        if not cortes:
            raise ErroAmigavel("Nenhum trecho foi escolhido (o video e curto demais para a "
                               "duracao minima dos cortes?).")
        raise ErroAmigavel(f"Nenhum dos {len(cortes)} cortes deu certo. Ultimo erro:\n"
                           f"{ultimo_erro[-400:]}")
    print(f"\n   Pronto! {len(resultados)} corte(s) em: {pasta_saida}")
    print("   Titulos, legendas e hashtags para postar: POSTAGENS.txt")

    segundos = time.time() - t_video
    _STATUS.setdefault("resultados", []).append(
        {"video": video.name, "cortes": len(resultados), "erros": erros,
         "segundos": round(segundos), "pasta": pasta_saida.name})
    status()
    avisar(cfg, "pronto", video.name, info["dur"],
           [(arq.name, c["titulo"], c["nota"]) for arq, c, _ in resultados],
           erros, segundos, pasta_saida.name, num, total)
    return pasta_saida


def so_capas(video, cfg):
    """Gera (ou refaz) so as capas de um video que ja foi cortado antes."""
    titulo(f"CAPAS: {video.name}")
    pasta_saida = PASTA_SAIDA / nome_seguro(video.stem, 60)
    arq_cortes = pasta_saida / "cortes_escolhidos.json"
    if not arq_cortes.exists():
        raise ErroAmigavel(f"Esse video ainda nao foi cortado ({video.name}).\n"
                           "   Rode primeiro o 2_GERAR_CORTES.bat.")
    if not garantir_pillow():
        return
    info = info_video(video)
    cortes = json.loads(arq_cortes.read_text(encoding="utf-8"))
    for i, c in enumerate(cortes, 1):
        nome = pasta_saida / f"corte_{i:02d}_{nome_seguro(c.get('titulo', 'corte'))}_capa.jpg"
        try:
            gerar_capa(video, info, c, nome, cfg)
            print(f"   OK -> {nome.name}")
        except Exception as e:
            aviso(f"Erro na capa {i}: {e}")
    print(f"\n   Pronto! Capas em: {pasta_saida}")
    print("   Quer mudar o texto de uma capa? Edite o 'texto_capa' no arquivo")
    print("   cortes_escolhidos.json (Bloco de Notas) e rode o 3_GERAR_CAPAS.bat de novo.")


def main():
    global FFMPEG, FFPROBE
    parser = argparse.ArgumentParser(description="Gera cortes automaticos de videos longos.")
    parser.add_argument("videos", nargs="*", help="video(s) para cortar")
    parser.add_argument("--qtd", type=int, help="quantidade de cortes por video")
    parser.add_argument("--modo", choices=["auto", "rosto", "desfoque"], help="enquadramento")
    parser.add_argument("--tipo", choices=["fala", "gameplay"],
                        help="fala (ouve e poe legenda) ou gameplay (a IA assiste as imagens)")
    parser.add_argument("--capas", action="store_true",
                        help="gera so as capas de videos que ja foram cortados")
    args = parser.parse_args()

    titulo("CORTES AUTOMATICOS")
    cfg = None
    try:
        cfg = carregar_config()
        FFMPEG, FFPROBE = achar_ffmpeg()
        PASTA_ENTRADA.mkdir(exist_ok=True)
        PASTA_SAIDA.mkdir(exist_ok=True)

        if args.videos:
            videos = [Path(v.strip('"')).resolve() for v in args.videos]
        else:
            videos = sorted(p for p in PASTA_ENTRADA.iterdir() if p.suffix.lower() in EXTENSOES)
        videos = [v for v in videos if v.exists() and v.suffix.lower() in EXTENSOES]
        if not videos:
            print("\n   Nenhum video encontrado.")
            print(f"   Coloque os videos na pasta: {PASTA_ENTRADA}")
            print("   ou arraste o video em cima do 2_GERAR_CORTES.bat")
            return 1

        if args.capas:
            for v in videos:
                try:
                    so_capas(v, cfg)
                except ErroAmigavel as e:
                    print(f"\n   [ERRO] {e}")
            return 0

        qtd = args.qtd or int(cfg["geral"]["quantidade_cortes"])
        tipo = args.tipo or ("gameplay" if cfg["geral"]["tipo_video"].strip().lower() == "gameplay" else "fala")
        _STATUS.clear()
        # execucao: etiqueta de quem abriu (vigia/app), para reconhecer esta rodada
        status(estado="rodando", pid=os.getpid(), execucao=os.environ.get("CORTES_EXECUCAO"),
               inicio=time.time(), fim=None,
               videos=[v.name for v in videos], videos_total=len(videos), video_num=0,
               video=None, etapa="conferindo", resultados=[], tipo=tipo)
        detectar_modelo(cfg)  # confere o LM Studio antes de gastar tempo transcrevendo

        # Pelo WhatsApp o vigia ja respondeu "vou cortar"; aviso de inicio so
        # quando foi pelo 2_GERAR_CORTES.bat.
        if os.environ.get("CORTES_VIA_WHATSAPP") != "1" and sim(cfg["whatsapp"]["avisar_inicio"]):
            avisar(cfg, "inicio", [v.name for v in videos])
        falhas = 0
        for n, v in enumerate(videos, 1):
            status(video_num=n, video=v.name)
            try:
                if tipo == "gameplay":
                    import gameplay
                    gameplay.processar(sys.modules[__name__], v, cfg, qtd, n, len(videos))
                else:
                    processar(v, cfg, qtd, args.modo, n, len(videos))
            except Exception as e:
                falhas += 1
                if isinstance(e, ErroAmigavel):
                    motivo = str(e)
                else:  # erro de programa: mostra tudo na janela e segue para o proximo video
                    traceback.print_exc()
                    motivo = f"Erro inesperado: {e}"
                print(f"\n   [ERRO] {motivo}")
                _STATUS["resultados"].append({"video": v.name, "erro": motivo[:500]})
                status()
                avisar(cfg, "erro", v.name, motivo, n, len(videos))
        if len(videos) > 1:
            avisar(cfg, "fim_geral", _STATUS["resultados"], time.time() - _STATUS["inicio"])
        status(estado="erro" if falhas else "concluido", fim=time.time(), etapa=None)
        return 1 if falhas else 0
    except KeyboardInterrupt:
        print("\n   Cancelado.")
        if _STATUS.get("estado") == "rodando":
            status(estado="cancelado", fim=time.time())
            avisar(cfg, "cancelado")
        return 1
    except Exception as e:  # antes do primeiro video: FFmpeg, LM Studio...
        if isinstance(e, ErroAmigavel):
            motivo = str(e)
        else:
            traceback.print_exc()
            motivo = f"Erro inesperado: {e}"
        print(f"\n   [ERRO] {motivo}")
        if cfg is not None and not args.capas:
            status(estado="erro", pid=os.getpid(), execucao=os.environ.get("CORTES_EXECUCAO"),
                   erro=motivo[:500], fim=time.time())
            avisar(cfg, "nao_comecou", motivo)
        return 1


if __name__ == "__main__":
    sys.exit(main())
