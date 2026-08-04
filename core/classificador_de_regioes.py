"""Decide o tipo de cada regiao extraida do PDF.

Classifica em texto limpo, texto escaneado, formula, tabela, imagem ou
desconhecido — e essa decisao determina o caminho da regiao no
pipeline inteiro.

A funcao parece_formula e uma heuristica conservadora calibrada com
casos reais, inclusive formulas embaralhadas pelo OCR: exige texto
curto (formula de material didatico nao passa de ~220 caracteres),
presenca de simbolo forte, notacao de funcao ou coeficiente colado, e
baixa proporcao de palavras de prosa no trecho.
"""

from __future__ import annotations

from core.extrator_de_regioes import Region

TEXT_CLEAN_MIN_DENSITY = 0.015
TEXT_CLEAN_MIN_CHARS = 20
SCANNED_MAX_DENSITY = 0.005
IMAGE_CONFIDENCE_THRESHOLD = 0.5
UNKNOWN_MIN_AREA = 8000
UNKNOWN_MIN_DIM = 40

DOCLING_CLASSIFICATION = {
    "image": "embedded_image",
    "table": "table",
    "formula": "formula",
    "heading": "text_clean",
    "caption": "text_clean",
    "list": "list_block",
    "code": "code_block",
    "callout": "callout_box",
    "text": "text_clean",
}


_ORIGENS_CONFIAVEIS = ("text-layer", "docling")


def _pagina_digital(region: Region) -> bool:
    return region.metadata.get("page_profile") in ("digital", "mixed")


def classificar_regiao(region: Region, perfil: str | None = None) -> str:
    if perfil is None:
        perfil = region.metadata.get("page_profile")

    if region.metadata.get("source") == "docling":
        docling_type = region.type
        result = DOCLING_CLASSIFICATION.get(docling_type)
        if result:
            return result

    if region.type == "image":
        if region.image_bytes is not None and region.confidence >= IMAGE_CONFIDENCE_THRESHOLD:
            return "embedded_image"
        if _region_area(region) > UNKNOWN_MIN_AREA:
            return "unknown"
        return "ignore"

    if region.type == "table":
        if region.text.strip():
            return "table"
        if _region_area(region) > UNKNOWN_MIN_AREA:
            return "table"
        return "ignore"

    if region.type == "formula":
        if _region_area(region) > 500:
            return "formula"
        return "ignore"

    if region.type == "text":
        total_chars = region.metadata.get("total_chars", 0)
        text_density = region.metadata.get("text_density", 0)
        area = _region_area(region)
        subtype = region.metadata.get("subtype", "")

        if subtype == "code" and total_chars >= 10:
            return "code_block"
        if subtype == "list" and total_chars >= 10:
            line_count = region.metadata.get("line_count", 0)
            if line_count >= 2 or total_chars >= 50:
                return "list_block"

        origem_confiavel = region.metadata.get("source") in _ORIGENS_CONFIAVEIS
        if region.text.strip() and (
            _pagina_digital(region) or origem_confiavel
        ):
            return "text_clean"

        if total_chars >= TEXT_CLEAN_MIN_CHARS and text_density >= TEXT_CLEAN_MIN_DENSITY:
            return "text_clean"

        if total_chars > 5 and text_density >= SCANNED_MAX_DENSITY:
            return "text_scanned"

        if area > UNKNOWN_MIN_AREA and not _is_too_thin_or_small(region):
            return "unknown"
        return "ignore"

    if region.type == "unknown":
        area = _region_area(region)
        if area > UNKNOWN_MIN_AREA and not _is_too_thin_or_small(region):
            return "unknown"
        return "ignore"

    return "ignore"


import re as _re

_PADRAO_FUNCAO = _re.compile(
    r"\b[A-Za-z][a-z\'\u2032i\u0131n]?\s?\(\s*[a-z]\s*\)"
)
_PADRAO_FUNCAO_NUMERICA = _re.compile(r"\b[A-Za-z]\s?\(\s*\d")
_PADRAO_COEFICIENTE = _re.compile(
    r"\b\d+\s?[a-wyz]\b"
    r"|\b[a-z]\d\b"
    r"|\d[a-z]\d"
    r"|[\u00b2\u00b3]"
)
_SIMBOLOS_FORTES = ("=", "\u00b1", "\u221a", "\u222b", "\u2211", "\u2264", "\u2265")


def parece_formula(texto: str) -> bool:
    if not texto:
        return False
    texto = texto.strip()
    if len(texto) > 220:
        return False

    tem_simbolo = any(s in texto for s in _SIMBOLOS_FORTES)
    tem_funcao = bool(
        _PADRAO_FUNCAO.search(texto) or _PADRAO_FUNCAO_NUMERICA.search(texto)
    )
    coeficientes = len(_PADRAO_COEFICIENTE.findall(texto))

    tokens = texto.split()
    if not tokens:
        return False
    palavras_prosa = sum(1 for t in tokens if t.isalpha() and len(t) >= 4)
    proporcao_prosa = palavras_prosa / len(tokens)

    if tem_simbolo and (tem_funcao or coeficientes >= 1) and proporcao_prosa < 0.5:
        return True
    if tem_funcao and coeficientes >= 2 and proporcao_prosa < 0.4:
        return True
    if (
        texto.count("=") >= 2
        and proporcao_prosa < 0.3
        and any(ch.isdigit() for ch in texto)
    ):
        return True
    return False


def reclassificar_para_formula(classification: str, texto: str) -> str:
    if classification in ("text_clean", "text_scanned", "unknown") and parece_formula(
        texto or ""
    ):
        return "formula"
    return classification


def regiao_precisa_de_visao(classification: str) -> bool:
    return classification in ("text_scanned", "embedded_image", "unknown", "table", "formula")


def regiao_tem_marcadores(classification: str) -> bool:
    return classification in (
        "code_block", "callout_box", "list_block", "embedded_image",
        "formula",
    )


def chave_de_prompt_da_regiao(classification: str) -> str:
    return {
        "embedded_image": "regiao_imagem",
        "text_scanned": "regiao_texto_escaneado",
        "unknown": "regiao_texto_escaneado",
        "table": "regiao_tabela",
        "formula": "regiao_formula",
    }.get(classification, "regiao_texto_escaneado")


def _region_area(region: Region) -> float:
    return (region.bbox[2] - region.bbox[0]) * (region.bbox[3] - region.bbox[1])


def _is_too_thin_or_small(region: Region) -> bool:
    w = region.bbox[2] - region.bbox[0]
    h = region.bbox[3] - region.bbox[1]
    if w < UNKNOWN_MIN_DIM or h < UNKNOWN_MIN_DIM:
        return True
    if w > 0 and h > 0 and (w / h > 15 or h / w > 15):
        return True
    return False
