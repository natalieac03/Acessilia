"""Captura a geometria da pagina enquanto o PDF esta aberto.

Posicao, tamanho e fonte de cada trecho so existem enquanto o
documento esta carregado. Depois de fechado, essa informacao nao esta
em lugar nenhum.

Isso tem consequencia semantica direta: e a geometria que prova que o
"2" de "ax2" estava elevado — o span dele fica acima da linha de base
e tem fonte menor. Sem ela, resta heuristica textual.
"""

from __future__ import annotations

from typing import Any

from pipeline.catalogo_de_evidencias import (
    CatalogoDeEvidencias,
    realinhar_geometria,
)
from pipeline.matematica.captura_matematica import construir_evidencia

Caixa = tuple[float, float, float, float]

_SOBREPOSICAO_MINIMA = 0.55


def _area(caixa: Caixa | None) -> float:
    if not caixa or len(caixa) < 4:
        return 0.0
    x0, y0, x1, y1 = caixa[:4]
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _area_da_intersecao(a: Caixa | None, b: Caixa | None) -> float:
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0
    ax0, ay0, ax1, ay1 = a[:4]
    bx0, by0, bx1, by1 = b[:4]
    largura = min(ax1, bx1) - max(ax0, bx0)
    altura = min(ay1, by1) - max(ay0, by0)
    if largura <= 0 or altura <= 0:
        return 0.0
    return largura * altura


def fracao_contida(bloco_bbox: Caixa | None, regiao_bbox: Caixa | None) -> float:
    area_bloco = _area(bloco_bbox)
    if area_bloco <= 0:
        return 0.0
    return _area_da_intersecao(bloco_bbox, regiao_bbox) / area_bloco


def blocos_de_texto_da_pagina(page: Any) -> list[dict]:
    try:
        dados = page.get_text("dict") or {}
    except Exception:
        return []
    blocos: list[dict] = []
    for bloco in dados.get("blocks", []) or []:
        if bloco.get("type", 0) != 0:
            continue
        if not bloco.get("lines"):
            continue
        blocos.append(bloco)
    return blocos


def bloco_unificado_da_regiao(
    blocos: list[dict], regiao_bbox: Caixa | None
) -> dict | None:
    if not blocos or not regiao_bbox:
        return None
    linhas: list[dict] = []
    for bloco in blocos:
        if fracao_contida(bloco.get("bbox"), regiao_bbox) < _SOBREPOSICAO_MINIMA:
            continue
        for linha in bloco.get("lines", []) or []:
            if linha.get("spans"):
                linhas.append(linha)
    if not linhas:
        return None

    def ordem(linha: dict) -> tuple[float, float]:
        caixa = linha.get("bbox") or (0.0, 0.0, 0.0, 0.0)
        return (round(float(caixa[1]), 1), float(caixa[0]))

    linhas.sort(key=ordem)
    return {"bbox": tuple(regiao_bbox), "lines": linhas}


def evidencia_da_regiao(
    *,
    blocos: list[dict],
    regiao: Any,
    document_id: str,
    page_number: int,
    region_id: str,
    recorte_png: str | None = None,
    extraction_engine: str = "pymupdf",
):
    texto = str(getattr(regiao, "text", "") or "")
    bbox = getattr(regiao, "bbox", None) or (0.0, 0.0, 0.0, 0.0)
    bloco = bloco_unificado_da_regiao(blocos, bbox)

    try:
        evidencia = construir_evidencia(
            document_id=document_id,
            region_id=region_id,
            page_number=page_number,
            bbox=tuple(bbox),
            raw_text=texto,
            bloco=bloco,
            image_crop_path=recorte_png,
            extraction_engine=extraction_engine,
        )
    except Exception:
        return None

    alinhada = realinhar_geometria(evidencia.geometry, texto)
    if alinhada is None:
        return evidencia.model_copy(
            update={
                "geometry": None,
                "superscript_candidates": [],
                "subscript_candidates": [],
            }
        )

    sobrescritos = [
        {
            "text": s.text,
            "start": s.start,
            "end": s.end,
            "baseline_shift": s.baseline_shift,
            "font_size": s.font_size,
        }
        for s in alinhada.spans
        if s.parece_sobrescrito and s.text.strip()
    ]
    subscritos = [
        {
            "text": s.text,
            "start": s.start,
            "end": s.end,
            "baseline_shift": s.baseline_shift,
            "font_size": s.font_size,
        }
        for s in alinhada.spans
        if s.parece_subscrito and s.text.strip()
    ]
    return evidencia.model_copy(
        update={
            "geometry": alinhada,
            "superscript_candidates": sobrescritos,
            "subscript_candidates": subscritos,
        }
    )


def catalogar_pagina(
    *,
    page: Any,
    regioes: list,
    document_id: str,
    page_number: int,
) -> CatalogoDeEvidencias:
    catalogo = CatalogoDeEvidencias(
        document_id=document_id, page_number=page_number
    )
    try:
        blocos = blocos_de_texto_da_pagina(page)
    except Exception:
        blocos = []

    for indice, regiao in enumerate(regioes or []):
        texto = str(getattr(regiao, "text", "") or "")
        if not texto.strip():
            continue
        region_id = f"{document_id}-p{page_number}-r{indice}"
        try:
            evidencia = evidencia_da_regiao(
                blocos=blocos,
                regiao=regiao,
                document_id=document_id,
                page_number=page_number,
                region_id=region_id,
            )
        except Exception:
            evidencia = None
        catalogo.registrar(evidencia)
    return catalogo
