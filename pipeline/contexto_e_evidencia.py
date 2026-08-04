"""Garante que o contexto oriente relevancia sem criar fato.

O experimento que expos o problema: a mesma fotografia de flores,
colocada num material de Botanica e num de Arte, gerou descricoes com
fatos DIFERENTES — a especie apareceu numa e nao na outra, sem nunca
ter sido confirmada visualmente. Ela veio do texto da aula.

E correto que cada disciplina priorize aspectos diferentes. O que nao
pode mudar e o conjunto de FATOS: quem le os dois materiais deve
receber a mesma informacao sobre a imagem.
"""

from __future__ import annotations

from typing import Any

TIPOS_SEM_CONTEXTO = ("embedded_image", "imagem", "image", "unknown")

DISTANCIA_VIZINHO = 120.0

LIMITE_CONTEXTO = 400


def _bbox(regiao: Any) -> tuple[float, float, float, float]:
    try:
        return tuple(float(v) for v in getattr(regiao, "bbox", (0, 0, 0, 0)))
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0, 0.0)


def _distancia_vertical(a, b) -> float:
    if a[3] <= b[1]:
        return b[1] - a[3]
    if b[3] <= a[1]:
        return a[1] - b[3]
    return 0.0


def contexto_reduzido(
    regiao_alvo: Any,
    regioes: list[Any],
    textos_limpos: list[str] | None = None,
) -> str:
    if not regioes:
        return ""

    alvo = _bbox(regiao_alvo)
    vizinhos: list[tuple[float, str]] = []

    for regiao in regioes:
        if regiao is regiao_alvo:
            continue
        texto = str(getattr(regiao, "text", "") or "").strip()
        if not texto:
            continue
        distancia = _distancia_vertical(alvo, _bbox(regiao))
        if distancia <= DISTANCIA_VIZINHO:
            vizinhos.append((distancia, texto))

    vizinhos.sort(key=lambda p: p[0])
    juntos: list[str] = []
    total = 0
    for _, texto in vizinhos:
        custo = len(texto) + (1 if juntos else 0)
        if total + custo > LIMITE_CONTEXTO:
            break
        juntos.append(texto)
        total += custo
    return "\n".join(juntos)


def contexto_para(
    classificacao: str,
    regiao: Any,
    regioes: list[Any],
    contexto_da_pagina: str = "",
) -> str | None:
    if classificacao in TIPOS_SEM_CONTEXTO:
        return None
    reduzido = contexto_reduzido(regiao, regioes)
    return reduzido or None


_MARCADORES_DE_IDENTIDADE = (
    "cerejeira", "sakura", "ipe", "ipê", "jacaranda", "jacarandá",
    "orquidea", "orquídea", "rosa-do-deserto",
)


def fatos_nao_confirmados(descricao: str, contexto: str) -> list[str]:
    if not descricao or not contexto:
        return []
    desc = descricao.lower()
    ctx = contexto.lower()
    return [
        termo for termo in _MARCADORES_DE_IDENTIDADE
        if termo in desc and termo in ctx
    ]


def normalizar_para_comparacao(descricao: str) -> set[str]:
    import re

    palavras = re.findall(r"[a-zà-ú]{4,}", (descricao or "").lower())
    vazias = {
        "para", "como", "esta", "essa", "esse", "isso", "pela", "pelo",
        "mais", "menos", "entre", "sobre", "onde", "quando", "todos",
        "todas", "cada", "outro", "outra", "imagem", "fotografia",
        "centro", "fundo", "parte", "lado", "direita", "esquerda",
    }
    return {p for p in palavras if p not in vazias}
