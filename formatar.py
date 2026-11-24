# -*- coding: utf-8 -*-
"""Textos curtos para mostrar ao usuario (duracao, data, mensagens de erro)."""

import datetime


def duracao(seg):
    """45 -> "45 s", 750 -> "13 min", 3900 -> "1h05"."""
    seg = int(round(seg or 0))
    if seg < 60:
        return f"{seg} s"
    if seg < 3600:
        return f"{round(seg / 60)} min"
    return f"{seg // 3600}h{seg % 3600 // 60:02d}"


def quando(epoch):
    """"hoje as 14:32", "ontem as 09:10" ou "15/10 as 14:32"."""
    if not epoch:
        return "?"
    t = datetime.datetime.fromtimestamp(epoch)
    dias = (datetime.date.today() - t.date()).days
    hora = t.strftime("%H:%M")
    if dias == 0:
        return f"hoje às {hora}"
    if dias == 1:
        return f"ontem às {hora}"
    return t.strftime("%d/%m") + f" às {hora}"


def texto_erro(erro):
    """Tira o recuo das mensagens de erro do cortes.py (feitas para a janela preta)."""
    linhas = [l.strip() for l in str(erro).strip().splitlines()]
    return "\n".join(l for l in linhas if l)[:1500]
