# pup_cortes

Cortes automáticos de vídeos longos para TikTok, Reels, Shorts e Kwai, feitos no seu PC.
Você escolhe o vídeo (ou cola o link), a IA local acha os melhores momentos e o programa entrega
os cortes em pé (9:16), com capa, título, legenda e hashtags prontos para postar.

Tudo roda no Windows, sem serviço pago: Whisper para ouvir, um modelo de IA local
(servidor no formato OpenAI, como o do LM Studio) para escolher e escrever, e FFmpeg para montar.

## O que ele faz

**Dois tipos de vídeo**

| | Com fala (podcast, entrevista, live falada) | Gameplay (jogo, quase sem fala) |
|---|---|---|
| Como acha os momentos | O Whisper transcreve tudo e a IA lê e escolhe | A IA **assiste**: mede som e movimento de cada segundo e dá notas a 1 imagem a cada 10 s (gráficos, ação, coisas curiosas) |
| Enquadramento | Segue o rosto de quem fala (ou fundo desfocado) | Tela cheia, só o jogo |
| Texto no vídeo | Legenda animada palavra por palavra + título | Gancho escrito pela IA nos primeiros segundos |
| Marca d'água | Crédito opcional (`credito`) | Nenhuma |
| Modelo de IA | Qualquer modelo de texto (ex.: Gemma) | Modelo com visão (ex.: Qwen3.5 com o arquivo `mmproj`) |

**Além disso**

- Baixa o vídeo pelo link (YouTube, Instagram, TikTok, Kwai, Twitch) com o yt-dlp.
- Faz uma capa (thumbnail) para cada corte e o `POSTAGENS.txt` com título, legenda e hashtags.
- Usa a placa de vídeo para montar os vídeos (NVIDIA NVENC ou AMD AMF; sem placa, usa o processador).
  No modo Gameplay o volume sai normalizado em -14 LUFS.
- Carrega o modelo de IA local pelo próprio app (Ajustes > Modelo de IA local): roda o `llama-server`
  que vem com o LM Studio, inteiro na placa de vídeo e sem prender cópia na RAM.

## Requisitos

- Windows 10 ou 11.
- Python 3.12 (o `1_INSTALAR.bat` instala se faltar) e FFmpeg (instala pelo `winget`).
- Um servidor de IA local no formato OpenAI em `http://localhost:1234/v1`
  (LM Studio, ou o botão "Carregar" dos Ajustes, que usa o motor do LM Studio).
- Opcional: placa de vídeo NVIDIA ou AMD (mais rápido). O Whisper usa a NVIDIA se tiver.

## Instalação

```bat
git clone <endereco-deste-repositorio> pup_cortes
cd pup_cortes
1_INSTALAR.bat
6_CRIAR_ATALHO_NA_AREA_DE_TRABALHO.bat
```

- O `1_INSTALAR.bat` cria o ambiente (`.venv`), instala o `requirements.txt` e o FFmpeg,
  e cria o `configuracoes.ini` a partir do `configuracoes.exemplo.ini`.
- O `6_CRIAR_ATALHO...bat` gera o `pup_cortes.exe` a partir de `app_arquivos/pup_cortes.cs`
  (compilador C# que já vem no Windows) e põe o atalho na área de trabalho.
- Evite pastas com acento ou dentro do OneDrive.

## Atualizar

Abra o `7_ATUALIZAR.bat`. Ele faz o `git pull`, confere os componentes e refaz o `pup_cortes.exe`
se precisar. O `configuracoes.ini`, a pasta `entrada` e a pasta `saida` não são mexidos.
(Funciona se a pasta veio pelo `git clone`; quem baixou em .zip precisa baixar de novo.)

## Como usar

**Pelo app (jeito fácil):** abra o atalho `pup_cortes`, escolha o vídeo ou cole o link, marque o tipo
de vídeo (Com fala ou Gameplay), escolha quantos cortes e clique em **Fazer cortes**.
Os cortes ficam em `saida\<nome do vídeo>\`.

**Pelos .bat:**

| Arquivo | Para quê |
|---|---|
| `2_GERAR_CORTES.bat` | Corta os vídeos da pasta `entrada` (ou arraste um vídeo em cima dele) |
| `3_GERAR_CAPAS.bat` | Refaz as capas de vídeos já cortados |
| `7_ATUALIZAR.bat` | Baixa a versão nova do GitHub (sem mexer nas suas configurações e vídeos) |

**Pela linha de comando:**

```bat
.venv\Scripts\python.exe cortes.py video.mp4 --qtd 8
.venv\Scripts\python.exe cortes.py live.mp4 --tipo gameplay
.venv\Scripts\python.exe cortes.py --modo desfoque
```

## Configurações

Ficam no `configuracoes.ini` (abra com o Bloco de Notas; cada opção tem explicação).
Ele não vai para o GitHub porque guarda os ajustes e caminhos de cada computador.
Se ele não existir, o programa cria a partir do `configuracoes.exemplo.ini`.
O modelo é o `configuracoes.exemplo.ini`.

| Seção | Principais opções |
|---|---|
| `[geral]` | `quantidade_cortes`, `duracao_minima`, `duracao_maxima`, `idioma`, `tipo_video` (fala ou gameplay) |
| `[gameplay]` | `jogo` (ajuda nos ganchos), `duracao` (padrão 40 s), `gancho_segundos` (padrão 4) |
| `[ia]` | `endereco_lm_studio`, `modelo`, `tema_do_canal`, `pasta_modelos`, `modelo_local` |
| `[whisper]` | `modelo_whisper` (large-v3-turbo, large-v3 ou small), `usar_gpu` |
| `[video]` | `modo` (auto, rosto, desfoque), `legenda`, `cor_destaque`, `credito`, `capa`, `qualidade_download` |

## Arquivos

| Arquivo | O que é |
|---|---|
| `app_cortes.pyw` | O app com janela |
| `cortes.py` | O motor: transcreve, escolhe, corta, faz capas e o `POSTAGENS.txt` |
| `gameplay.py` | O modo Gameplay (a IA assiste as imagens) |
| `controle.py` | Liga a IA local, baixa vídeos e roda o `cortes.py` em segundo plano |
| `formatar.py` | Textos curtos da tela (duração, data, mensagens de erro) |
| `app_arquivos/` | Ícones e o código do `pup_cortes.exe` (`pup_cortes.cs` + `criar_exe.bat`) |
| `LEIA-ME.txt` | Manual completo, passo a passo, com os problemas comuns |

## Avisos

- Só corte vídeos de quem deixou você cortar, e dê o crédito.
- Em gameplay, se o rádio do jogo estiver tocando no trecho, a plataforma pode reivindicar os
  direitos da música.
