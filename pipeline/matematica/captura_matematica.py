"""Captura a evidencia bruta do PDF, com geometria de cada span."""

from __future__ import annotations

from pipeline.matematica.evidencia_matematica import (
    SourceEvidence,
    SpanGeometry,
    TextGeometry,
)

_LIMIAR_DESLOCAMENTO = 0.8
_PROPORCAO_FONTE_MENOR = 0.92


def _mediana(valores: list[float]) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[meio]
    return (ordenados[meio - 1] + ordenados[meio]) / 2


def construir_geometria(bloco: dict) -> TextGeometry:
    spans: list[SpanGeometry] = []
    tamanhos: list[float] = []
    cursor = 0

    try:
        linhas = bloco.get("lines", []) or []
        for linha in linhas:
            spans_da_linha = linha.get("spans", []) or []
            tamanhos_linha = [s.get("size", 0.0) for s in spans_da_linha]
            fonte_corpo = _mediana([t for t in tamanhos_linha if t]) or 0.0
            topos_corpo = [
                (s.get("bbox") or (0, 0, 0, 0))[3]
                for s in spans_da_linha
                if s.get("size", 0.0) >= fonte_corpo * _PROPORCAO_FONTE_MENOR
                and s.get("bbox")
            ]
            baseline = _mediana(topos_corpo)

            for span in spans_da_linha:
                texto = span.get("text", "")
                caixa = span.get("bbox")
                tamanho = float(span.get("size", 0.0) or 0.0)
                tamanhos.append(tamanho)

                deslocamento = 0.0
                if caixa and baseline:
                    deslocamento = float(baseline) - float(caixa[3])
                    fonte_menor = (
                        fonte_corpo
                        and tamanho < fonte_corpo * _PROPORCAO_FONTE_MENOR
                    )
                    if not fonte_menor and abs(deslocamento) < 2.0:
                        deslocamento = 0.0

                spans.append(
                    SpanGeometry(
                        text=texto,
                        start=cursor,
                        end=cursor + len(texto),
                        bbox=tuple(caixa) if caixa else None,
                        font_size=tamanho,
                        font_name=str(span.get("font", "")),
                        baseline_shift=round(deslocamento, 2),
                    )
                )
                cursor += len(texto) + 1
    except Exception:
        pass

    return TextGeometry(
        spans=spans, font_size_dominante=_mediana([t for t in tamanhos if t])
    )


def _resumo_do_span(span: SpanGeometry) -> dict:
    return {
        "text": span.text,
        "start": span.start,
        "end": span.end,
        "baseline_shift": span.baseline_shift,
        "font_size": span.font_size,
    }


def construir_evidencia(
    *,
    document_id: str,
    region_id: str,
    page_number: int,
    bbox: tuple[float, float, float, float],
    raw_text: str,
    bloco: dict | None = None,
    image_crop_path: str | None = None,
    extraction_engine: str = "pymupdf",
) -> SourceEvidence:
    geometria = construir_geometria(bloco) if bloco else TextGeometry()

    linhas: list[str] = []
    caixas_de_linha: list[tuple[float, float, float, float]] = []
    try:
        for linha in (bloco or {}).get("lines", []) or []:
            texto_linha = "".join(
                s.get("text", "") for s in (linha.get("spans") or [])
            ).strip()
            if texto_linha:
                linhas.append(texto_linha)
                caixa = linha.get("bbox")
                if caixa:
                    caixas_de_linha.append(tuple(caixa))
    except Exception:
        pass

    sobrescritos = [
        _resumo_do_span(s)
        for s in geometria.spans
        if s.parece_sobrescrito and s.text.strip()
    ]
    subscritos = [
        _resumo_do_span(s)
        for s in geometria.spans
        if s.parece_subscrito and s.text.strip()
    ]

    return SourceEvidence(
        document_id=document_id,
        page_number=page_number,
        region_id=region_id,
        bbox=tuple(bbox),
        raw_text=raw_text,
        raw_lines=linhas or ([raw_text] if raw_text else []),
        line_bboxes=caixas_de_linha,
        image_crop_path=image_crop_path,
        font_sizes=[s.font_size for s in geometria.spans if s.font_size],
        superscript_candidates=sobrescritos,
        subscript_candidates=subscritos,
        extraction_engine=extraction_engine,
        geometry=geometria,
    )
