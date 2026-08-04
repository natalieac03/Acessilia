"""Extrai as regioes da pagina e recorta as imagens."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import fitz


@dataclass
class Region:
    bbox: tuple[float, float, float, float]
    type: str
    text: str
    image_bytes: bytes | None
    confidence: float
    page_num: int
    metadata: dict[str, Any] = field(default_factory=dict)


MONOSPACE_FONTS = {
    "courier",
    "consolas",
    "monaco",
    "menlo",
    "monospace",
    "dejavu sans mono",
    "liberation mono",
    "courier new",
    "lucida console",
    "source code pro",
    "fira code",
    "sf mono",
    "jetbrains mono",
    "cascadia code",
    "droid sans mono",
    "ubuntu mono",
    "inconsolata",
    "anonymous pro",
}

LIST_LINE_PATTERNS = (
    "- ",
    "* ",
    "+ ",
    "• ",
    "‣ ",
    "⁃ ",
    "o ",
    "§ ",
    "→ ",
    "⇒ ",
)


@dataclass
class PageProfile:

    kind: str
    text_chars: int = 0
    coverage: float = 0.0
    image_count: int = 0

    @property
    def tem_camada_textual(self) -> bool:
        return self.kind in ("digital", "mixed")


COBERTURA_TEXTUAL_MINIMA = 0.001

CHARS_MINIMOS_DIGITAL = 8

COBERTURA_IMAGEM_DE_PAGINA = 0.60


def estimar_cobertura_textual(page: fitz.Page) -> float:
    try:
        area_pagina = page.rect.width * page.rect.height
        if area_pagina <= 0:
            return 0.0
        blocos = page.get_text("dict").get("blocks", [])
        area_texto = 0.0
        for bloco in blocos:
            if bloco.get("type") != 0:
                continue
            x0, y0, x1, y1 = bloco.get("bbox", (0, 0, 0, 0))
            area_texto += max(0.0, x1 - x0) * max(0.0, y1 - y0)
        return min(1.0, area_texto / area_pagina)
    except Exception:
        return 0.0


def _maior_cobertura_de_imagem(page: fitz.Page, imagens: list) -> float:
    try:
        area_pagina = page.rect.width * page.rect.height
        if area_pagina <= 0:
            return 0.0
    except Exception:
        return 0.0
    maior = 0.0
    for info in imagens:
        bbox = info.get("bbox") or (0, 0, 0, 0)
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            continue
        area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        maior = max(maior, area / area_pagina)
    return min(1.0, maior)


def classificar_perfil_da_pagina(page: fitz.Page) -> PageProfile:
    try:
        texto = (page.get_text("text") or "").strip()
    except Exception:
        texto = ""
    try:
        imagens = page.get_image_info(xrefs=True) or []
    except Exception:
        imagens = []

    cobertura = estimar_cobertura_textual(page)
    cobertura_imagem = _maior_cobertura_de_imagem(page, imagens)
    tem_texto = (
        len(texto) >= CHARS_MINIMOS_DIGITAL
        and cobertura >= COBERTURA_TEXTUAL_MINIMA
    )

    if cobertura_imagem >= COBERTURA_IMAGEM_DE_PAGINA and not tem_texto:
        kind = "scanned"
    elif tem_texto:
        kind = "mixed" if imagens else "digital"
    else:
        kind = "scanned"

    return PageProfile(
        kind=kind,
        text_chars=len(texto),
        coverage=round(cobertura, 4),
        image_count=len(imagens),
    )


def extract_regions(page: fitz.Page) -> list[Region]:
    regions: list[Region] = []
    page_num = page.number + 1

    perfil = classificar_perfil_da_pagina(page)

    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get(
        "blocks", []
    )

    for block in blocks:
        bbox = tuple(block.get("bbox", (0, 0, 0, 0)))
        block_type = block.get("type")

        if block_type == 0:
            region = _text_block_to_region(block, bbox, page_num)
            if region and region.text.strip():
                region.metadata["page_profile"] = perfil.kind
                region.metadata["source"] = (
                    "text-layer" if perfil.tem_camada_textual else "ocr"
                )
                regions.append(region)

        elif block_type == 1:
            region = _image_block_to_region(block, bbox, page_num)
            if region:
                region.metadata["page_profile"] = perfil.kind
                regions.append(region)

    for regiao_img in extrair_imagens_da_pagina(page, page_num):
        if not _sobrepoe_alguma(regiao_img.bbox, [r.bbox for r in regions
                                                  if r.type == "image"],
                                limiar=0.60):
            regiao_img.metadata["page_profile"] = perfil.kind
            regions.append(regiao_img)

    _fill_gaps_with_unknown(page, regions, page_num, perfil)

    from pipeline.ordem_de_leitura import ordenar_por_leitura

    regions = ordenar_por_leitura(regions)
    return regions


def _starts_with_list_marker(text: str) -> bool:
    stripped = text.strip()
    for pattern in LIST_LINE_PATTERNS:
        if stripped.startswith(pattern):
            return True
    if len(stripped) > 1 and stripped[0].isdigit() and stripped[1] in (".", ")"):
        if len(stripped) > 2 and stripped[2].isdigit():
            return False
        return True
    if (
        len(stripped) > 2
        and stripped[0].isalpha()
        and stripped[1] in (".", ")")
        and stripped[2] == " "
    ):
        return True
    return False


def _text_block_to_region(
    block: dict[str, Any],
    bbox: tuple[float, float, float, float],
    page_num: int,
) -> Region | None:
    lines = block.get("lines", [])
    if not lines:
        return None

    full_text = ""
    total_chars = 0
    font_sizes: list[float] = []
    all_monospace = True
    line_texts: list[str] = []

    for line in lines:
        spans = line.get("spans", [])
        line_text = ""
        for span in spans:
            text = span.get("text", "")
            line_text += text + " "
            full_text += text + " "
            total_chars += len(text)
            font_sizes.append(span.get("size", 0))
            font_name = span.get("font", "").lower()
            is_mono = any(mf in font_name for mf in MONOSPACE_FONTS)
            if not is_mono:
                all_monospace = False
        line_texts.append(line_text.strip())

    full_text = full_text.strip()

    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if area <= 0:
        return None

    text_density = total_chars / area if area > 0 else 0
    avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 0

    subtype = ""
    if all_monospace and total_chars >= 10:
        subtype = "code"
    elif line_texts and _starts_with_list_marker(line_texts[0]):
        subtype = "list"

    return Region(
        bbox=bbox,
        type="text",
        text=full_text,
        image_bytes=None,
        confidence=min(text_density * 50, 1.0),
        page_num=page_num,
        metadata={
            "total_chars": total_chars,
            "text_density": round(text_density, 4),
            "avg_font_size": round(avg_font_size, 1),
            "line_count": len(lines),
            "subtype": subtype,
        },
    )


def _normalizar_digest(valor: Any) -> str:
    if isinstance(valor, (bytes, bytearray)):
        return valor.hex()
    return str(valor or "")


def extrair_imagens_da_pagina(
    page: fitz.Page, page_num: int
) -> list[Region]:
    regioes: list[Region] = []
    doc = page.parent
    vistos: set[tuple[str, tuple]] = set()

    try:
        infos = page.get_image_info(xrefs=True) or []
    except Exception:
        return regioes

    for indice, info in enumerate(infos, 1):
        try:
            xref = int(info.get("xref") or 0)
            bbox = tuple(float(v) for v in (info.get("bbox") or (0, 0, 0, 0)))
        except (TypeError, ValueError):
            continue
        if xref <= 0 or _area(bbox) <= 0:
            continue

        try:
            base = doc.extract_image(xref)
        except Exception:
            continue
        if not base or not base.get("image"):
            continue

        digest = _normalizar_digest(info.get("digest"))
        chave = (digest or str(xref), tuple(round(v, 1) for v in bbox))
        if chave in vistos:
            continue
        vistos.add(chave)

        regioes.append(Region(
            bbox=bbox,
            type="image",
            text="",
            image_bytes=base["image"],
            confidence=1.0,
            page_num=page_num,
            metadata={
                "source": "pymupdf_image_info",
                "has_image_data": True,
                "xref": xref,
                "width_px": info.get("width"),
                "height_px": info.get("height"),
                "extension": base.get("ext", "png"),
                "digest": digest,
                "image_index": indice,
            },
        ))

    return regioes


def _image_block_to_region(
    block: dict[str, Any],
    bbox: tuple[float, float, float, float],
    page_num: int,
) -> Region | None:
    if _area(bbox) < 200:
        return None

    return Region(
        bbox=bbox,
        type="image",
        text="",
        image_bytes=None,
        confidence=0.3,
        page_num=page_num,
        metadata={
            "has_image_data": False,
            "source": "text-block",
            "aguarda_associacao_por_xref": True,
        },
    )


LIMIAR_AREA_DESCONHECIDA = 8000.0
LIMIAR_SOBREPOSICAO = 0.10
DENSIDADE_MINIMA_NAO_BRANCA = 0.02
DPI_SONDAGEM = 100


def _area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _sobreposicao_maxima(
    bbox: tuple[float, float, float, float],
    conhecidas: list[tuple[float, float, float, float]],
) -> float:
    area = _area(bbox)
    if area <= 0:
        return 1.0
    maior = 0.0
    for outra in conhecidas:
        ox0 = max(bbox[0], outra[0])
        oy0 = max(bbox[1], outra[1])
        ox1 = min(bbox[2], outra[2])
        oy1 = min(bbox[3], outra[3])
        if ox0 < ox1 and oy0 < oy1:
            maior = max(maior, ((ox1 - ox0) * (oy1 - oy0)) / area)
    return maior


def _sobrepoe_alguma(
    bbox: tuple[float, float, float, float],
    outras: list[tuple[float, float, float, float]],
    limiar: float = LIMIAR_SOBREPOSICAO,
) -> bool:
    return _sobreposicao_maxima(bbox, outras) > limiar


def densidade_nao_branca(
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    dpi: int = DPI_SONDAGEM,
) -> float:
    try:
        pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(bbox), colorspace=fitz.csGRAY)
    except Exception:
        return 0.0
    amostras = pix.samples
    if not amostras:
        return 0.0
    nao_brancos = sum(1 for valor in amostras if valor < 245)
    return nao_brancos / len(amostras)


def deve_criar_regiao_desconhecida(
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    conhecidas: list[tuple[float, float, float, float]],
) -> bool:
    if _sobreposicao_maxima(bbox, conhecidas) > LIMIAR_SOBREPOSICAO:
        return False
    if _area(bbox) < LIMIAR_AREA_DESCONHECIDA:
        return False
    return densidade_nao_branca(page, bbox) >= DENSIDADE_MINIMA_NAO_BRANCA


def _fill_gaps_with_unknown(
    page: fitz.Page,
    regions: list[Region],
    page_num: int,
    perfil: PageProfile | None = None,
) -> None:
    page_rect = page.rect
    page_w = page_rect.width
    page_h = page_rect.height

    if not regions:
        regions.append(
            Region(
                bbox=(0, 0, page_w, page_h),
                type="unknown",
                text="",
                image_bytes=None,
                confidence=0.0,
                page_num=page_num,
                metadata={
                    "motivo": "pagina sem regioes extraidas",
                    "page_profile": perfil.kind if perfil else "",
                },
            )
        )
        return

    if perfil is not None and perfil.kind == "digital":
        return

    conhecidas = [r.bbox for r in regions]
    covered = _merge_bboxes(conhecidas)
    _add_unknown_gaps(
        page, covered, page_w, page_h, regions, page_num, conhecidas
    )


def _merge_bboxes(
    bboxes: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    if not bboxes:
        return []
    sorted_b = sorted(bboxes, key=lambda b: (b[1], b[0]))
    merged = [list(sorted_b[0])]
    for b in sorted_b[1:]:
        if b[1] <= merged[-1][3] + 5:
            merged[-1][2] = max(merged[-1][2], b[2])
            merged[-1][3] = max(merged[-1][3], b[3])
        else:
            merged.append(list(b))
    return [tuple(b) for b in merged]


def _add_unknown_gaps(
    page: fitz.Page,
    covered: list[tuple[float, float, float, float]],
    page_w: float,
    page_h: float,
    regions: list[Region],
    page_num: int,
    conhecidas: list[tuple[float, float, float, float]],
) -> None:
    y_stops = sorted({0} | {c[3] for c in covered} | {page_h})
    for i in range(len(y_stops) - 1):
        y0 = y_stops[i]
        y1 = y_stops[i + 1]
        if y1 - y0 < 20:
            continue

        gap_x_stops = sorted(
            {0} | {c[2] for c in covered if c[1] < y1 and c[3] > y0} | {page_w}
        )
        for j in range(len(gap_x_stops) - 1):
            x0 = gap_x_stops[j]
            x1 = gap_x_stops[j + 1]
            if x1 - x0 < 30:
                continue

            bbox = (x0, y0, x1, y1)
            if not deve_criar_regiao_desconhecida(page, bbox, conhecidas):
                continue

            regions.append(
                Region(
                    bbox=bbox,
                    type="unknown",
                    text="",
                    image_bytes=None,
                    confidence=0.0,
                    page_num=page_num,
                    metadata={
                        "motivo": "lacuna com densidade de pixel",
                        "densidade": round(
                            densidade_nao_branca(page, bbox), 4
                        ),
                    },
                )
            )


def crop_region_to_image(
    page: fitz.Page, bbox: tuple[float, float, float, float], dpi: int = 200
) -> bytes:
    clip = fitz.Rect(bbox)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    return pix.tobytes("png")


PONTOS_POR_POLEGADA = 72.0

MIN_PIXELS_MENOR_LADO = 800
MAX_PIXELS_MAIOR_LADO = 2200
DPI_BASE = 200
DPI_MAXIMO = 900

MIN_PIXELS_LEGIVEL = 40


def compute_adaptive_dpi(bbox: tuple[float, float, float, float]) -> int:
    largura_pt = max(0.0, bbox[2] - bbox[0])
    altura_pt = max(0.0, bbox[3] - bbox[1])
    menor_pt = min(largura_pt, altura_pt)
    maior_pt = max(largura_pt, altura_pt)

    if menor_pt <= 0 or maior_pt <= 0:
        return DPI_BASE

    dpi_desejado = MIN_PIXELS_MENOR_LADO * PONTOS_POR_POLEGADA / menor_pt

    dpi_teto_memoria = MAX_PIXELS_MAIOR_LADO * PONTOS_POR_POLEGADA / maior_pt

    dpi = min(dpi_desejado, dpi_teto_memoria, DPI_MAXIMO)
    dpi = max(dpi, DPI_BASE)
    return int(dpi)


def regiao_legivel(largura_px: int, altura_px: int) -> bool:
    return min(largura_px, altura_px) >= MIN_PIXELS_LEGIVEL
