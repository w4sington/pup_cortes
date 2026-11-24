# -*- coding: utf-8 -*-
"""
CORTES DE GAMEPLAY (jogo, quase sem fala)
Em vez de OUVIR a fala, a IA ASSISTE o video:
  1. Mede o som e o movimento de cada segundo e guarda 1 quadro a cada 10 s
     (a placa de video decodifica; quase nada fica na RAM)
  2. O modelo com visao (ex.: Qwen3.5) da notas a cada quadro: graficos, acao, curiosidade
  3. Junta tudo, escolhe os melhores trechos e a IA escreve o gancho de cada um
  4. Corta em pe (9:16) em TELA CHEIA (so o jogo), gancho nos primeiros segundos,
     sem marca d'agua e sem credito
Chamado pelo cortes.py quando o tipo do video e "gameplay" (--tipo gameplay ou
[geral] tipo_video = gameplay). `m` e o proprio cortes.py (FFmpeg, status, IA...).
"""

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

INTERVALO = 10          # segundos entre os quadros que a IA olha
FPS_MOV = 2             # amostras por segundo para medir o movimento
MW, MH = 160, 90        # tamanho minusculo para medir movimento e brilho
RUINS = {"menu_mapa", "carregando"}
CATEGORIAS = ("grafico", "acao", "curioso")
LETRAS_LINHA = 15       # Arial Black 84 px: ~15 letras cabem na largura do celular
FONTES = ["C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"]

PERGUNTA_QUADRO = (
    "Este e um quadro de uma gameplay{jogo}. Responda SO com um JSON, sem texto fora dele:\n"
    '{{"cena": "o que aparece, em ate 12 palavras, em portugues",\n'
    ' "tipo": "um de: dirigindo, a_pe, combate, perseguicao, acidente, voo, barco, paisagem, cutscene, '
    'interior, menu_mapa, carregando, outro",\n'
    ' "grafico": nota 0 a 10 de quanto a imagem impressiona pelos graficos (luz, agua, reflexos, cidade, natureza),\n'
    ' "acao": nota 0 a 10 de quanta acao ou caos tem,\n'
    ' "curioso": nota 0 a 10 de quanto mostra algo inusitado ou que da vontade de comentar}}'
)

PERGUNTA_GANCHO = (
    "Estas imagens sao de um trecho de {dur:.0f} segundos de uma gameplay{jogo}, para um video curto "
    "em pe (TikTok, Reels, Shorts) SEM narracao. O que acontece no trecho, quadro a quadro:\n{cenas}\n"
    "O trecho foi escolhido por: {motivo}.\n\n"
    "Escreva em portugues do Brasil e responda SO com um JSON, sem texto fora dele:\n"
    '{{"gancho": "frase curta em MAIUSCULAS, ate 40 letras, que faz a pessoa parar de rolar o feed",\n'
    ' "titulo": "titulo do video, ate 60 letras",\n'
    ' "texto_capa": "2 a 4 palavras em MAIUSCULAS para a capa",\n'
    ' "descricao": "legenda da postagem: 1 ou 2 frases e uma pergunta para o publico comentar",\n'
    ' "hashtags": ["#exemplo", "5 hashtags"]}}\n'
    "Exemplos de gancho: OLHA A ÁGUA DO GTA VI / DÁ PRA PILOTAR AVIÃO AGRÍCOLA NO GTA VI / "
    "TENTEI SUBIR ESSE BARRANCO... / ISSO É GTA VI. NÃO É FILME.\n"
    "Regras: português do Brasil correto e natural, COM acentos (GRÁFICOS, ÁGUA, AVIÃO, NÃO, É). "
    "Só fale do que aparece nas imagens; não invente. Sem emoji. "
    "Hashtags só sobre o jogo e o que aparece no trecho."
)


# ----------------------------------------------------------------------------
# 1) Som, movimento, brilho e quadros (uma passada so pelo video)
# ----------------------------------------------------------------------------

def _passe_video(m, video, pasta, dur, progresso, hw):
    qdir = pasta / "quadros"
    shutil.rmtree(qdir, ignore_errors=True)
    qdir.mkdir(parents=True)
    entrada = (["-hwaccel", "d3d11va"] if hw else []) + ["-i", str(video)]
    # format=yuv420p logo na entrada: o d3d11va entrega nv12 e alguns filtros estragam a cor
    filtro = (f"[0:v]format=yuv420p,split=2[a][b];[a]fps={FPS_MOV},scale={MW}:{MH},format=gray[m];"
              f"[b]fps=1/{INTERVALO},scale=512:-2[q]")
    cmd = ([m.FFMPEG, "-v", "error"] + entrada + ["-an", "-sn", "-filter_complex", filtro,
           "-map", "[q]", "-q:v", "4", str(qdir / "%05d.jpg"), "-map", "[m]", "-f", "rawvideo", "pipe:1"])
    import numpy as np
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=MW * MH * 64)
    erros = []
    threading.Thread(target=lambda: erros.append(p.stderr.read()), daemon=True).start()
    tam = MW * MH
    anterior, difs, brilho = None, [], []
    while True:
        b = p.stdout.read(tam)
        if len(b) < tam:
            break
        f = np.frombuffer(b, np.uint8).astype(np.int16)
        difs.append(0.0 if anterior is None else float(np.abs(f - anterior).mean()) / 255.0)
        brilho.append(float(f.mean()) / 255.0)
        anterior = f
        if len(difs) % (FPS_MOV * 30) == 0:
            progresso(len(difs) / FPS_MOV / max(1.0, dur))
    p.wait()
    if p.returncode != 0 or len(difs) < FPS_MOV * 2:
        raise RuntimeError((erros[0] if erros else b"").decode("utf-8", "replace").strip()[-300:] or "sem quadros")

    def por_segundo(x):
        x = np.array(x, np.float32)
        return x[: len(x) // FPS_MOV * FPS_MOV].reshape(-1, FPS_MOV).mean(axis=1)
    np.save(pasta / "movimento.npy", por_segundo(difs))
    np.save(pasta / "brilho.npy", por_segundo(brilho))


def _passe_audio(m, video, pasta, tem_audio):
    import numpy as np
    vols = []
    if tem_audio:
        sr = 8000
        p = subprocess.Popen([m.FFMPEG, "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr),
                              "-f", "s16le", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        while True:
            b = p.stdout.read(sr * 2)
            if len(b) < sr * 2:
                break
            a = np.frombuffer(b, np.int16).astype(np.float32) / 32768
            vols.append(20 * np.log10(np.sqrt(np.mean(a * a)) + 1e-6))
        p.wait()
    np.save(pasta / "volume.npy", np.array(vols, np.float32))


def analisar(m, video, info, pasta, progresso):
    """Grava em `pasta`: quadros/NNNNN.jpg, movimento.npy, brilho.npy, volume.npy. Retoma se ja fez."""
    pasta.mkdir(parents=True, exist_ok=True)
    feito = pasta / "analise_ok.txt"
    if feito.exists() and (pasta / "movimento.npy").exists() and (pasta / "volume.npy").exists():
        print("   Som e movimento ja medidos antes (reaproveitando).")
        return
    t = threading.Thread(target=_passe_audio, args=(m, video, pasta, info["audio"]))
    t.start()
    try:
        _passe_video(m, video, pasta, info["dur"], progresso, hw=os.name == "nt")
    except Exception as e:
        m.aviso(f"Decodificar pela placa de video falhou ({str(e)[:120]}). Usando o processador.")
        _passe_video(m, video, pasta, info["dur"], progresso, hw=False)
    t.join()
    feito.write_text("ok", encoding="utf-8")


# ----------------------------------------------------------------------------
# 2) A IA olha os quadros
# ----------------------------------------------------------------------------

def _url(cfg):
    return cfg["ia"]["endereco_lm_studio"].rstrip("/") + "/chat/completions"


def _perguntar_com_imagens(m, cfg, modelo, texto, imagens, max_tokens):
    conteudo = [{"type": "text", "text": texto}]
    for img in imagens:
        conteudo.append({"type": "image_url",
                         "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}})
    corpo = {"model": modelo, "max_tokens": max_tokens, "temperature": 0.2, "reasoning_effort": "none",
             "messages": [{"role": "user", "content": conteudo}]}
    r = m._post_json(_url(cfg), corpo, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"IA respondeu {r.status_code}: {r.text[:200]}")
    txt = (r.json()["choices"][0]["message"].get("content") or "").strip()
    dados = m._extrair_json(txt)
    if not isinstance(dados, dict):
        raise RuntimeError(f"resposta sem JSON: {txt[:120]}")
    return dados


def _nota(x):
    try:
        return max(0.0, min(10.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _descrever_um(m, cfg, modelo, pergunta, q):
    try:
        d = _perguntar_com_imagens(m, cfg, modelo, pergunta, [q.read_bytes()], 160)
        d = {"cena": str(d.get("cena", ""))[:120], "tipo": str(d.get("tipo", "outro")).strip().lower(),
             "grafico": _nota(d.get("grafico")), "acao": _nota(d.get("acao")), "curioso": _nota(d.get("curioso"))}
    except Exception as e:
        d = {"erro": str(e)[:200]}
    d.update({"quadro": q.stem, "t": (int(q.stem) - 1) * INTERVALO})
    return d


def descrever(m, cfg, modelo, pasta, jogo, progresso, juntos=4):
    """Uma linha por quadro em descricoes.jsonl. Retoma de onde parou.
    `juntos` perguntas de uma vez: o servidor da IA responde varias ao mesmo tempo
    quase no tempo de uma (a placa le o modelo uma vez para todas)."""
    from concurrent.futures import ThreadPoolExecutor
    saida = pasta / "descricoes.jsonl"
    feitos = {}
    if saida.exists():
        for linha in saida.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(linha)
                feitos[d["quadro"]] = d
            except Exception:
                pass
    quadros = sorted((pasta / "quadros").glob("*.jpg"))
    faltam = [q for q in quadros if not (q.stem in feitos and "erro" not in feitos[q.stem])]
    pergunta = PERGUNTA_QUADRO.format(jogo=f" do jogo {jogo}" if jogo else "")
    seguidos, t0, n = 0, time.time(), 0
    with open(saida, "a", encoding="utf-8") as f, ThreadPoolExecutor(juntos) as ex:
        for d in ex.map(lambda q: _descrever_um(m, cfg, modelo, pergunta, q), faltam):
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            progresso((len(quadros) - len(faltam) + n) / max(1, len(quadros)))
            if "erro" not in d:
                seguidos = 0
                continue
            seguidos += 1
            if seguidos >= 6:
                ex.shutdown(cancel_futures=True)
                txt = d["erro"].lower()
                if any(p in txt for p in ("image", "imagem", "vision", "mmproj", "multimodal")):
                    raise m.ErroAmigavel(
                        "O modelo de IA carregado nao enxerga imagens, e o modo Gameplay precisa disso.\n"
                        "   Em Ajustes > Modelo de IA local, carregue um modelo com visao (ex.: Qwen3.5),\n"
                        "   com o arquivo mmproj na mesma pasta do .gguf.")
                raise m.ErroAmigavel(f"A IA parou de responder ao olhar os quadros.\n   {d['erro'][:200]}")
            if n % 100 == 0:
                print(f"   {n}/{len(faltam)} quadros ({n / (time.time() - t0):.1f} por segundo)", flush=True)
    print(f"   A IA olhou {n} quadros em {time.time() - t0:.0f}s")


# ----------------------------------------------------------------------------
# 3) Escolher os trechos
# ----------------------------------------------------------------------------

def _suavizar(x, k):
    import numpy as np
    return np.convolve(x, np.ones(k) / k, mode="same") if len(x) else x


def _z(x):
    import numpy as np
    return (x - np.median(x)) / (np.std(x) + 1e-6)


def escolher(pasta, info, qtd, dur_alvo, dmin):
    """Nota de cada janela de 10 s nas 3 categorias, e pega os picos alternando as
    categorias (para os cortes nao serem todos iguais), sem sobrepor."""
    import numpy as np
    mov = np.load(pasta / "movimento.npy")
    vol = np.load(pasta / "volume.npy")
    brilho = np.load(pasta / "brilho.npy")
    desc = {}
    for linha in (pasta / "descricoes.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(linha)
        except Exception:
            continue
        if "erro" not in d:
            desc[d["t"] // INTERVALO] = d
    n_seg = len(mov)
    if len(vol) < n_seg:  # video sem som (ou som mais curto): silencio
        vol = np.concatenate([vol, np.full(n_seg - len(vol), -90.0, np.float32)])
    nj = n_seg // INTERVALO
    if nj < 2:
        return []
    m_ = mov[: nj * INTERVALO].reshape(nj, INTERVALO)
    v_ = vol[: nj * INTERVALO].reshape(nj, INTERVALO)
    pico_som = _z(v_.max(axis=1) - _suavizar(v_.mean(axis=1), 30))  # explosao/batida acima do normal da regiao
    pico_mov = _z(m_.max(axis=1))
    g = np.array([desc.get(i, {}).get("grafico", 0) for i in range(nj)], float)
    a = np.array([desc.get(i, {}).get("acao", 0) for i in range(nj)], float)
    c = np.array([desc.get(i, {}).get("curioso", 0) for i in range(nj)], float)
    ruim_j = np.array([desc.get(i, {}).get("tipo") in RUINS for i in range(nj)])
    notas = {
        "grafico": _suavizar(g, 3) + 0.2 * _suavizar(c, 3),
        "acao": 0.6 * _suavizar(a, 2) + 0.9 * np.clip(pico_som, 0, 4) + 0.5 * np.clip(pico_mov, 0, 4),
        "curioso": 0.8 * _suavizar(c, 2) + 0.2 * _suavizar(a, 2),
    }
    for s in notas.values():
        s[ruim_j] = -99
    # segundo ruim: tela preta/branca de transicao ou menu/carregando
    ruim_s = (brilho < 0.05) | (brilho > 0.97)
    ruim_s[: nj * INTERVALO] |= np.repeat(ruim_j, INTERVALO)
    ocupado = np.zeros(n_seg + 1, bool)
    dur_video = min(float(info["dur"]), float(n_seg))
    escolhidos, tentativas = [], 0
    ordem = list(CATEGORIAS)
    while len(escolhidos) < qtd and tentativas < qtd * 12:
        cat = ordem[tentativas % len(ordem)]
        tentativas += 1
        s = notas[cat]
        livre = np.array([not ocupado[i * INTERVALO: (i + 1) * INTERVALO].any() for i in range(nj)])
        cand = np.where(livre & (s > 0), s, -99)
        i = int(np.argmax(cand))
        if cand[i] <= 0:
            continue
        nota = float(s[i])
        s[i] = -99  # nao tenta o mesmo pico de novo nesta categoria
        pico = i * INTERVALO + INTERVALO / 2
        ini = max(0.0, min(pico - 0.4 * dur_alvo, dur_video - dur_alvo))
        fim = min(dur_video, ini + dur_alvo)
        # tira tela preta/menu das pontas
        while ini < fim and ruim_s[int(ini)]:
            ini += 1
        while fim > ini and ruim_s[min(int(fim) - 1, n_seg - 1)]:
            fim -= 1
        if fim - ini < dmin or ruim_s[int(ini):int(fim)].mean() > 0.25 or ocupado[int(ini):int(fim)].any():
            continue
        ocupado[max(0, int(ini) - 5): int(fim) + 5] = True
        js = range(int(ini) // INTERVALO, min(nj, int(fim) // INTERVALO + 1))
        # capa: o quadro (dentro do corte) que a IA achou mais bonito/curioso
        bons = [j for j in js if j in desc and ini + 1 <= j * INTERVALO <= fim - 1
                and desc[j].get("tipo") not in RUINS]
        capa_j = max(bons, key=lambda j: desc[j]["grafico"] + desc[j]["curioso"] + 0.5 * desc[j]["acao"],
                     default=None)
        escolhidos.append({
            "inicio": round(ini, 2), "fim": round(fim, 2), "categoria": cat,
            "nota": round(min(10.0, nota), 1),
            "cenas": [desc[j]["cena"] for j in js if j in desc and desc[j].get("cena")],
            "tipo": desc.get(i, {}).get("tipo", ""),
            "capa_t": capa_j * INTERVALO + 0.5 if capa_j is not None else None,
        })
    escolhidos.sort(key=lambda x: x["inicio"])
    return escolhidos


# ----------------------------------------------------------------------------
# 4) Gancho, titulo e legenda de cada trecho
# ----------------------------------------------------------------------------

MOTIVOS = {"grafico": "os graficos bonitos", "acao": "a acao (picos de som e movimento)",
           "curioso": "algo curioso ou engracado"}


def _limpar(txt, limite):
    txt = re.sub(r"[^\w\s.,!?'\"\-:%/&+()…ºª$]", "", str(txt or ""), flags=re.UNICODE)
    return re.sub(r"\s+", " ", txt).strip()[:limite]


# A IA as vezes esquece acentos ("GRAFICOS"): conserta as palavras comuns, mantendo maiusculas/minusculas
ACENTOS = {p.replace("Á", "A").replace("Â", "A").replace("Ã", "A").replace("É", "E").replace("Ê", "E")
           .replace("Í", "I").replace("Ó", "O").replace("Ô", "O").replace("Õ", "O").replace("Ú", "U")
           .replace("Ç", "C"): p for p in """
    GRÁFICO GRÁFICOS ÁGUA ÁGUAS AVIÃO AVIÕES NÃO VOCÊ VOCÊS JÁ ATÉ TAMBÉM AÇÃO PÂNTANO CAMINHÃO
    HELICÓPTERO FÍSICA INCRÍVEL INCRÍVEIS POLÍCIA PERSEGUIÇÃO EXPLOSÃO CÉU AGRÍCOLA REALÍSTICO
    VEÍCULO VEÍCULOS ÔNIBUS ESTÃO SÃO TÃO ENTÃO VÍDEO NÚMERO ÚNICO DIFÍCIL FÁCIL POSSÍVEL
    IMPOSSÍVEL LÁ AÍ MÁGICA PÔR LANÇAMENTO DIREÇÃO PISTOLÃO SAÍDA PRÉDIO PRÉDIOS LIÇÃO MANSÃO
    PERDÃO CORAÇÃO MÁQUINA MÚSICA RÁDIO BOATE ÓTIMO PÉSSIMO RÁPIDO VELOCÍMETRO TRÂNSITO""".split()}
FRASES_ACENTO = [(r"\b(ISSO|NÃO|AQUI|ELE|ELA|ASSIM) E\b", r"\1 É"), (r"\bDA PRA\b", "DÁ PRA"),
                 (r"\b(Isso|isso|Não|não) e\b", r"\1 é"), (r"\bda pra\b", "dá pra"), (r"\bDa pra\b", "Dá pra")]


def acentuar(txt):
    def troca(mm):
        w = mm.group(0)
        certo = ACENTOS.get(w.upper())
        if not certo:
            return w
        if w.isupper():
            return certo
        if w[0].isupper():
            return certo.capitalize()
        return certo.lower()
    txt = re.sub(r"\w+", troca, txt)
    for padrao, novo in FRASES_ACENTO:
        txt = re.sub(padrao, novo, txt)
    return txt


def quebrar_gancho(txt, por_linha=LETRAS_LINHA, max_linhas=3):
    palavras, linhas = txt.split(), [""]
    for p in palavras:
        if linhas[-1] and len(linhas[-1]) + 1 + len(p) > por_linha:
            linhas.append(p)
        else:
            linhas[-1] = (linhas[-1] + " " + p).strip()
    if len(linhas) > max_linhas:
        return None
    return "\n".join(linhas)


def _quadro_jpg(m, video, t, largura=512):
    r = subprocess.run([m.FFMPEG, "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={largura}:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                       capture_output=True)
    return r.stdout or None


def escrever_textos(m, cfg, modelo, video, corte, jogo):
    nome_jogo = jogo.upper() if jogo else "GAME"
    padrao = {"grafico": f"OLHA OS GRÁFICOS DO {nome_jogo}", "acao": f"OLHA O QUE ACONTECEU NO {nome_jogo}...",
              "curioso": f"VOCÊ JÁ VIU ISSO NO {nome_jogo}?"}[corte["categoria"]]
    dados = {}
    ini, fim = corte["inicio"], corte["fim"]
    imagens = [q for q in (_quadro_jpg(m, video, ini + (fim - ini) * f) for f in (0.15, 0.5, 0.85)) if q]
    cenas = "\n".join(f"- {c}" for c in corte["cenas"][:8]) or "- (sem descricao)"
    pergunta = PERGUNTA_GANCHO.format(dur=fim - ini, jogo=f" do jogo {jogo}" if jogo else "", cenas=cenas,
                                      motivo=MOTIVOS[corte["categoria"]])
    try:
        dados = _perguntar_com_imagens(m, cfg, modelo, pergunta, imagens, 400)
    except Exception as e:
        m.aviso(f"A IA nao escreveu o gancho deste corte ({str(e)[:100]}). Usando um gancho padrao.")
    gancho = acentuar(_limpar(dados.get("gancho"), 60).upper()) or padrao
    if not quebrar_gancho(gancho):
        gancho = padrao
    tags = [t if t.startswith("#") else "#" + t for t in (_limpar(x, 30).replace(" ", "") for x in
                                                           (dados.get("hashtags") or [])) if len(t) > 1][:6]
    if not tags:
        tags = ["#gameplay", "#games"] + ([f"#{re.sub(r'[^0-9A-Za-z]', '', jogo).lower()}"] if jogo else [])
    corte.update({
        "gancho": gancho,
        "titulo": acentuar(_limpar(dados.get("titulo"), 70)) or gancho.capitalize(),
        "texto_capa": acentuar(_limpar(dados.get("texto_capa"), 30).upper()) or gancho,
        "descricao": acentuar(_limpar(dados.get("descricao"), 300)),
        "hashtags": tags,
    })
    return corte


# ----------------------------------------------------------------------------
# 5) Montar o video: em pe, tela cheia, so o jogo
# ----------------------------------------------------------------------------

def _fonte():
    for f in FONTES:
        if Path(f).exists():
            return f.replace(":", "\\:")
    return None


def _volume(m, video, ini, dur):
    """1a passada do loudnorm: mede o trecho para a 2a ser linear (sem estourar o pico)."""
    r = subprocess.run([m.FFMPEG, "-hide_banner", "-nostats", "-ss", f"{ini:.3f}", "-t", f"{dur:.3f}",
                        "-i", str(video), "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        d = json.loads(r.stderr[r.stderr.rfind("{"): r.stderr.rfind("}") + 1])
        return (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={d['input_i']}:measured_TP={d['input_tp']}"
                f":measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}"
                f":offset={d['target_offset']}:linear=true")
    except Exception:
        return "loudnorm=I=-14:TP=-1.5:LRA=11"


def renderizar(m, cfg, video, info, corte, arquivo, pasta_tmp, numero):
    ini, fim = corte["inicio"], corte["fim"]
    dur = fim - ini
    w, h = info["w"], info["h"]
    cx = float(corte.get("cx", 0.5))
    if h * 9 / 16 < w:   # deitado: recorta a faixa em pe (tela cheia, so o jogo)
        enquadra = (f"crop=ih*9/16:ih:'min(max(iw*{cx}-ow/2,0),iw-ow)':0,"
                    f"scale={m.LARGURA}:{m.ALTURA}:flags=lanczos")
    else:                # ja e em pe
        enquadra = (f"scale={m.LARGURA}:{m.ALTURA}:force_original_aspect_ratio=increase,"
                    f"crop={m.LARGURA}:{m.ALTURA}")
    filtro = f"[0:v]format=yuv420p,{enquadra},setsar=1"
    segundos = float(cfg["gameplay"].get("gancho_segundos", "4") or 0)
    fonte = _fonte()
    if corte.get("gancho") and fonte:
        nome_txt = f"gancho_{numero:02d}.txt"
        (pasta_tmp / nome_txt).write_text(quebrar_gancho(corte["gancho"]) or corte["gancho"],
                                          encoding="utf-8", newline="\n")  # \r\n viraria linha em branco
        filtro += (f",drawtext=fontfile='{fonte}':textfile='{nome_txt}':fontcolor=white:fontsize=84"
                   f":borderw=9:bordercolor=black@0.95:line_spacing=10:text_align=C:x=(w-text_w)/2:y=250"
                   + (f":enable='lt(t,{segundos})'" if segundos > 0 else ""))
    filtro += ",format=yuv420p[v]"
    if info["audio"]:
        filtro += f";[0:a]{_volume(m, video, ini, dur)},alimiter=limit=0.75:level=false,aresample=48000[a]"

    def comando(hw, encoder):
        cmd = [m.FFMPEG, "-y", "-hide_banner", "-v", "error"] + (["-hwaccel", "d3d11va"] if hw else [])
        cmd += ["-ss", f"{ini:.3f}", "-t", f"{dur:.3f}", "-i", str(video), "-filter_complex", filtro, "-map", "[v]"]
        if info["audio"]:
            cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
        return cmd + encoder + ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                                "-movflags", "+faststart", str(arquivo)]

    encoder = m.escolher_encoder(cfg)
    tentativas = [(os.name == "nt", encoder), (False, encoder)]
    if "libx264" not in encoder:
        tentativas.append((False, ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]))
    ultimo = ""
    for hw, enc in tentativas:
        try:
            m._rodar(comando(hw, enc), pasta_tmp)
            return arquivo
        except RuntimeError as e:
            ultimo = str(e)
    raise RuntimeError(ultimo)


# ----------------------------------------------------------------------------
# Principal (mesmo papel do processar() do cortes.py)
# ----------------------------------------------------------------------------

def processar(m, video, cfg, qtd, num=1, total=1):
    m.titulo(f"GAMEPLAY: {video.name}")
    t_video = time.time()
    cfg["video"]["credito"] = ""          # sem marca d'agua nem credito (so nesta rodada, nao grava)
    pasta_saida = m.PASTA_SAIDA / m.nome_seguro(video.stem, 60)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    pasta_an = pasta_saida / "_analise"
    info = m.info_video(video)
    print(f"   {info['w']}x{info['h']} | {info['fps']:.0f} fps | {m.mmss(info['dur'])} de duracao")
    jogo = cfg["gameplay"].get("jogo", "").strip()
    modelo = m.detectar_modelo(cfg)

    def prog(ini, peso):
        return lambda f: m.status(pct=round(min(100.0, ini + peso * f), 1))

    m.passo("1/3 Assistindo o video: som, movimento e as imagens (IA com visao)")
    m.status(video=video.name, duracao=info["dur"], etapa="transcrevendo", pct=0, tipo="gameplay",
             parte=0, partes=0, corte=0, cortes_total=0)
    t0 = time.time()
    analisar(m, video, info, pasta_an, prog(0, 35))
    print(f"   Som e movimento medidos em {time.time() - t0:.0f}s; "
          f"{len(list((pasta_an / 'quadros').glob('*.jpg')))} quadros para a IA olhar")
    descrever(m, cfg, modelo, pasta_an, jogo, prog(35, 65))

    m.passo("2/3 Escolhendo os melhores momentos e escrevendo os ganchos")
    dmin, dmax = float(cfg["geral"]["duracao_minima"]), float(cfg["geral"]["duracao_maxima"])
    dur_alvo = max(dmin, min(dmax, float(cfg["gameplay"].get("duracao", "40") or 40)))
    cortes = escolher(pasta_an, info, qtd, dur_alvo, min(dmin, dur_alvo))
    m.status(etapa="escolhendo", partes=len(cortes), parte=0)
    from concurrent.futures import ThreadPoolExecutor
    feitos = []

    def textos(c):
        escrever_textos(m, cfg, modelo, video, c, jogo)
        feitos.append(c)
        m.status(parte=len(feitos))
    with ThreadPoolExecutor(4) as ex:   # 4 de uma vez, como os quadros
        list(ex.map(textos, cortes))
    for i, c in enumerate(cortes, 1):
        print(f"     {i:02d}. [{m.mmss(c['inicio'])}-{m.mmss(c['fim'])}] {c['categoria']:7s} "
              f"nota {c['nota']:.0f} - {c['gancho']}", flush=True)
    (pasta_saida / "cortes_escolhidos.json").write_text(json.dumps(cortes, ensure_ascii=False, indent=1),
                                                        encoding="utf-8")

    m.passo("3/3 Gerando os videos (em pe, tela cheia, so o jogo)")
    m.status(etapa="gerando", cortes_total=len(cortes))
    pasta_tmp = pasta_saida / "_temp"
    pasta_tmp.mkdir(exist_ok=True)
    resultados, erros, ultimo_erro = [], 0, ""
    for i, c in enumerate(cortes, 1):
        m.status(corte=i)
        t0 = time.time()
        arquivo = pasta_saida / f"corte_{i:02d}_{m.nome_seguro(c['titulo'])}.mp4"
        try:
            renderizar(m, cfg, video, info, c, arquivo, pasta_tmp, i)
            resultados.append((arquivo, c, "gameplay"))
            print(f"   OK -> {arquivo.name} ({time.time() - t0:.0f}s)")
        except Exception as e:
            m.aviso(f"Erro ao gerar o corte {i}: {e}")
            erros, ultimo_erro = erros + 1, str(e)
            continue
        if m.sim(cfg["video"].get("capa", "sim")) and m.garantir_pillow():
            try:
                capa = m.gerar_capa(video, info, c, arquivo.with_name(arquivo.stem + "_capa.jpg"), cfg,
                                    tela_cheia=True)
                print(f"   Capa -> {capa.name}")
            except Exception as e:
                m.aviso(f"Erro ao gerar a capa do corte {i}: {e}")

    shutil.rmtree(pasta_tmp, ignore_errors=True)
    m.escrever_relatorio(pasta_saida, video, resultados, cfg)
    if not resultados:
        if not cortes:
            raise m.ErroAmigavel("Nao achei trechos bons nesse video (curto demais, ou so menu e tela de "
                                 "carregamento?).")
        raise m.ErroAmigavel(f"Nenhum dos {len(cortes)} cortes deu certo. Ultimo erro:\n{ultimo_erro[-400:]}")
    print(f"\n   Pronto! {len(resultados)} corte(s) em: {pasta_saida}")
    print("   Titulos, legendas e hashtags para postar: POSTAGENS.txt")
    segundos = time.time() - t_video
    m._STATUS.setdefault("resultados", []).append(
        {"video": video.name, "cortes": len(resultados), "erros": erros,
         "segundos": round(segundos), "pasta": pasta_saida.name})
    m.status()
    m.avisar(cfg, "pronto", video.name, info["dur"],
             [(arq.name, c["titulo"], c["nota"]) for arq, c, _ in resultados],
             erros, segundos, pasta_saida.name, num, total)
    return pasta_saida
