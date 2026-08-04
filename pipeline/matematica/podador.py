"""Remove do documento o que nao deve chegar ao estudante.

O diagnostico que originou o modulo foi medido: numa saida real de 130
linhas, 42 delas (32%) comecavam com um rotulo de processo — "Texto
digitalizado:", "Aparece novamente:" — que o leitor de tela vocalizava
antes de cada paragrafo. Era metadado de pipeline vazando para o
material do aluno.

Tambem remove regioes duplicadas e narracao de layout, sempre por
criterio deterministico.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from core.utils.logger import logger

_SUBSTANTIVOS_DE_PROCESSO = (
    "texto", "documento", "conteudo", "conteúdo", "arquivo", "material",
    "trecho", "bloco", "pagina", "página", "imagem", "regiao", "região",
)

_TIPOLOGIAS_COMO_ROTULO = (
    "equacao", "equação", "formula", "fórmula", "expressao", "expressão",
    "grafico", "gráfico", "tabela", "fotografia", "figura", "ilustracao",
    "ilustração", "diagrama", "esquema", "quadro", "logotipo", "captura",
)

_ADJETIVOS_DE_PROCESSO = (
    "digitalizado", "digitalizada", "escaneado", "escaneada", "transcrito",
    "transcrita", "extraido", "extraída", "extraido", "reconhecido",
    "reconhecida", "textual", "digital", "visual", "indeterminado",
    "indeterminada", "academico", "acadêmico", "educacional", "explicativo",
    "explicativa", "em destaque", "puro", "simples", "corrido", "original",
    "adaptado", "processado", "identificado", "detectado", "analisado",
)

_TIPOLOGIA_ROTULO = re.compile(
    r"^\s*(?:" + "|".join(_TIPOLOGIAS_COMO_ROTULO) + r")"
    r"(?:\s+(?:" + "|".join(_ADJETIVOS_DE_PROCESSO) + r"|matem[aá]tic[ao]|"
    r"cartesian[ao]|de\s+\w+))?"
    r"\s*:\s*",
    re.IGNORECASE,
)

_ROTULO_DE_PROCESSO = re.compile(
    r"^\s*(?:" + "|".join(_SUBSTANTIVOS_DE_PROCESSO) + r")"
    r"(?:\s+(?:" + "|".join(_ADJETIVOS_DE_PROCESSO)
    + r"|com\s+equa\w+\s+\w+|matem[aá]tic[ao]))?"
    r"\s*[.:]\s+",
    re.IGNORECASE,
)

_ROTULO_SOZINHO = re.compile(
    r"^\s*(?:" + "|".join(_SUBSTANTIVOS_DE_PROCESSO + _TIPOLOGIAS_COMO_ROTULO)
    + r")"
    r"(?:\s+(?:" + "|".join(_ADJETIVOS_DE_PROCESSO) + r"))?"
    r"\s*[.:]?\s*$",
    re.IGNORECASE,
)

_REFERENCIA_VAZIA = re.compile(
    r"^\s*aparece\s+novamente\s*:\s*(?:" + "|".join(_SUBSTANTIVOS_DE_PROCESSO)
    + r")\b.*$",
    re.IGNORECASE,
)

_CHROME_DE_PAGINA = re.compile(
    r"^\s*(?:p[aá]gina|slide|folha)\s+\d+\s*(?:de|/)\s*\d+\s*\.?\s*$",
    re.IGNORECASE,
)

_ROTULO_PENDURADO = re.compile(
    r"^\s*[A-Za-zÀ-ú][A-Za-zÀ-ú\s]{2,40}:\s*$"
)

_SO_ILEGIVEL = re.compile(
    r"^\s*(?:[a-zà-úA-ZÀ-Ú ]{3,32}[.:]\s*)?"
    r"(?:(?:o\s+)?conte[uú]do\s+(?:est[aá]\s+|[eé]\s+)?)?"
    r"(?:il[eé]g[ií]vel|indetermin\w+|n[aã]o\s+(?:foi\s+)?(?:[eé]\s+)?"
    r"poss[ií]vel\s+(?:descrever|determinar|ler|identificar))"
    r"[^.]{0,90}\.?\s*$",
    re.IGNORECASE,
)


def remover_rotulo_de_processo(texto: str) -> str:
    original = str(texto or "")
    podado = _ROTULO_DE_PROCESSO.sub("", original, count=1).strip()
    if not podado or len(podado) < 3:
        return original.strip()
    if podado[0].islower() and original[:1].isupper():
        podado = podado[0].upper() + podado[1:]
    return podado


def e_ruido(texto: str, e_imagem: bool = False) -> bool:
    limpo = " ".join(str(texto or "").split())
    if not limpo:
        return True
    return bool(
        _CHROME_DE_PAGINA.match(limpo)
        or _SO_ILEGIVEL.match(limpo)
        or _REFERENCIA_VAZIA.match(limpo)
        or _ROTULO_PENDURADO.match(limpo)
        or (not e_imagem and _ROTULO_SOZINHO.match(limpo))
    )


_MARCAS_DE_LAYOUT = (
    "primeira linha", "segunda linha", "terceira linha", "quarta linha",
    "linha superior", "linha inferior", "no topo", "a esquerda",
    "a direita", "no centro", "logo abaixo", "mais abaixo",
    "sinal de igual", "sinal de menos", "sinal de mais",
    "parentese de abertura", "parentese de fechamento",
    "parênteses de abertura", "parênteses de fechamento",
    "letra x maiuscula", "ponto de multiplicacao",
    "apresenta a letra", "exibe o numero", "exibe no numerador",
)

_MINIMO_DE_MARCAS = 2


def narra_layout(texto: str) -> bool:
    alvo = unicodedata.normalize("NFKD", str(texto or "").lower())
    alvo = "".join(c for c in alvo if not unicodedata.combining(c))
    encontradas = sum(1 for marca in _MARCAS_DE_LAYOUT if marca in alvo)
    return encontradas >= _MINIMO_DE_MARCAS

_LIMIAR_DUPLICATA = 0.85

_JACCARD_COM_NUMEROS_IGUAIS = 0.55

_JACCARD_SOZINHO = 0.80

_FAIXA_DUVIDA = (0.62, _JACCARD_SOZINHO)

_MIN_PARA_SIMILARIDADE = 60

_JANELA = 6


def _chave_de_comparacao(texto: str) -> str:
    limpo = remover_rotulo_de_processo(str(texto or "")).lower()
    limpo = unicodedata.normalize("NFKD", limpo)
    limpo = "".join(c for c in limpo if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", limpo)


_NUMERO_POR_EXTENSO = (
    r"\b(?:zero|d[ou]is|duas|tres|quatro|cinco|seis|sete|oito|nove|"
    r"dez|onze|doze|treze|quatorze|catorze|quinze|dezesseis|dezessete|"
    r"dezoito|dezenove|vinte|trinta|quarenta|cinquenta|cem|mil)\b"
)


def _numeros_e_termos(texto: str) -> tuple[list[str], set[str]]:
    limpo = unicodedata.normalize("NFKD", str(texto or "").lower())
    limpo = "".join(c for c in limpo if not unicodedata.combining(c))
    numeros = re.findall(r"\d+(?:[.,]\d+)?", limpo)
    numeros += re.findall(_NUMERO_POR_EXTENSO, limpo)
    palavras = set(re.findall(r"\b[a-z]{4,}\b", limpo))
    return sorted(numeros), palavras


def _mesmo_conteudo(a: str, b: str) -> bool:
    chave_a, chave_b = _chave_de_comparacao(a), _chave_de_comparacao(b)
    if not chave_a or not chave_b:
        return False
    if chave_a == chave_b:
        return True

    numeros_a, palavras_a = _numeros_e_termos(a)
    numeros_b, palavras_b = _numeros_e_termos(b)
    uniao = palavras_a | palavras_b
    if not uniao:
        return False
    jaccard = len(palavras_a & palavras_b) / len(uniao)

    if _e_truncamento_de(numeros_a, numeros_b, jaccard, a, b):
        return True

    if min(len(chave_a), len(chave_b)) < _MIN_PARA_SIMILARIDADE:
        return False

    if numeros_a == numeros_b and jaccard >= _JACCARD_COM_NUMEROS_IGUAIS:
        return True
    if numeros_a != numeros_b:
        if _e_truncamento_de(numeros_a, numeros_b, jaccard, a, b):
            return True
        return False
    return jaccard >= _JACCARD_SOZINHO or SequenceMatcher(
        None, chave_a, chave_b
    ).ratio() >= _LIMIAR_DUPLICATA


_CONTEUDO_FORA_DO_TEXTO = ("table", "math", "list", "code")


def _e_truncamento_de(
    numeros_a: list[str], numeros_b: list[str], jaccard: float,
    texto_a: str, texto_b: str,
) -> bool:
    if jaccard < _JACCARD_COM_NUMEROS_IGUAIS:
        return False
    quebra_a = _grau_de_quebra({"type": "paragraph", "text": texto_a})
    quebra_b = _grau_de_quebra({"type": "paragraph", "text": texto_b})
    if quebra_a == quebra_b:
        return False
    curta, longa = (
        (numeros_a, numeros_b) if quebra_a > quebra_b
        else (numeros_b, numeros_a)
    )
    return len(curta) < len(longa) and longa[:len(curta)] == curta


def _texto_do_bloco(bloco: dict) -> str:
    if bloco.get("type") in _CONTEUDO_FORA_DO_TEXTO:
        return ""
    return str(bloco.get("text") or "")


_MARCAS_DE_QUEBRA = (
    "conteúdo ilegível", "conteudo ilegivel", "[ilegivel]", "[ilegível]",
)


def _grau_de_quebra(bloco: dict) -> int:
    texto = _texto_do_bloco(bloco).lower()
    if not texto:
        return 0
    quebra = sum(1 for marca in _MARCAS_DE_QUEBRA if marca in texto)
    if narra_layout(texto):
        quebra += 2
    if re.search(r"(?:é igual a|igual a|mais|menos|vezes|sobre)\s*$", texto):
        quebra += 1
    return quebra


def _mais_completo(a: dict, b: dict) -> dict:
    quebra_a, quebra_b = _grau_de_quebra(a), _grau_de_quebra(b)
    if quebra_a != quebra_b:
        return a if quebra_a < quebra_b else b
    if a.get("mathml") and not b.get("mathml"):
        return a
    if b.get("mathml") and not a.get("mathml"):
        return b
    return a if len(_texto_do_bloco(a)) >= len(_texto_do_bloco(b)) else b


def _em_duvida(a: str, b: str) -> bool:
    chave_a, chave_b = _chave_de_comparacao(a), _chave_de_comparacao(b)
    if min(len(chave_a), len(chave_b)) < _MIN_PARA_SIMILARIDADE:
        return False
    numeros_a, palavras_a = _numeros_e_termos(a)
    numeros_b, palavras_b = _numeros_e_termos(b)
    if numeros_a != numeros_b:
        return False
    uniao = palavras_a | palavras_b
    if not uniao:
        return False
    jaccard = len(palavras_a & palavras_b) / len(uniao)
    return _FAIXA_DUVIDA[0] <= jaccard < _FAIXA_DUVIDA[1]


def podar_blocos(
    blocos: list[dict[str, Any]], imagem_da_pagina: bytes | None = None
) -> list[dict[str, Any]]:
    if not blocos:
        return blocos
    try:
        return _podar(blocos, imagem_da_pagina)
    except Exception as erro:
        logger.warning("Poda de saida falhou ({}); blocos mantidos", erro)
        return blocos


def _podar(
    blocos: list[dict[str, Any]], imagem_da_pagina: bytes | None = None
) -> list[dict[str, Any]]:
    podados: list[dict[str, Any]] = []
    removidos_ruido = 0
    removidos_duplicata = 0
    julgados = 0

    for bloco in blocos:
        if not isinstance(bloco, dict):
            continue
        tipo = bloco.get("type")

        if tipo in _CONTEUDO_FORA_DO_TEXTO:
            podados.append(bloco)
            continue

        texto = _texto_do_bloco(bloco)

        if tipo == "image" and bloco.get("decorative"):
            podados.append(bloco)
            continue

        if e_ruido(texto, e_imagem=(tipo == "image")):
            removidos_ruido += 1
            continue

        limpo = (
            _ROTULO_DE_PROCESSO.sub("", texto, count=1).strip()
            if tipo == "image"
            else remover_rotulo_de_processo(texto)
        )
        if limpo != texto:
            bloco = dict(bloco, text=limpo)
            if bloco.get("alt_text"):
                bloco["alt_text"] = remover_rotulo_de_processo(
                    bloco["alt_text"]
                )

        indice_igual = None
        for recuo in range(1, min(_JANELA, len(podados)) + 1):
            candidato = podados[-recuo]
            if candidato.get("type") in _CONTEUDO_FORA_DO_TEXTO:
                continue
            if _mesmo_conteudo(limpo, _texto_do_bloco(candidato)):
                indice_igual = len(podados) - recuo
                break

        if indice_igual is not None:
            podados[indice_igual] = _mais_completo(
                podados[indice_igual], bloco
            )
            removidos_duplicata += 1
            continue

        for recuo in range(1, min(_JANELA, len(podados)) + 1):
            candidato = podados[-recuo]
            if candidato.get("type") in _CONTEUDO_FORA_DO_TEXTO:
                continue
            texto_anterior = _texto_do_bloco(candidato)
            if not _em_duvida(limpo, texto_anterior):
                continue
            veredito = _consultar_juiz(
                texto_anterior, limpo, imagem_da_pagina
            )
            julgados += 1
            if not veredito.decidiu:
                break
            indice = len(podados) - recuo
            podados[indice] = (
                candidato if veredito.manter == "a" else bloco
            )
            podados[indice].setdefault("metadata", {})[
                "duplicata_julgada"
            ] = veredito.to_dict()
            removidos_duplicata += 1
            indice_igual = indice
            break

        if indice_igual is not None:
            continue

        podados.append(bloco)

    if removidos_ruido or removidos_duplicata or julgados:
        logger.info(
            "Poda: {} ruido, {} duplicata(s), {} par(es) julgado(s) "
            "({} -> {})",
            removidos_ruido, removidos_duplicata, julgados,
            len(blocos), len(podados),
        )
    return podados


def _consultar_juiz(texto_a: str, texto_b: str, imagem: bytes | None):
    class _Abstencao:
        decidiu = False
        manter = "ambos"

        def to_dict(self):
            return {"decidiu": False, "manter": "ambos"}

    return _Abstencao()

