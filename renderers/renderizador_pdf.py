"""Gera o PDF visual.

Produz um PDF legivel e bem diagramado, mas que NAO e PDF/UA — faltam
marcacao estrutural (tags), ordem logica de leitura declarada e
metadados de acessibilidade. Um PDF sem tags e, para leitor de tela,
pouco mais que um bloco de texto sem hierarquia.

Por isso o arquivo recebe o sufixo "_visual" e nao "_acessivel": serve
como referencia para impressao ou para quem enxerga acompanhar o
material. A leitura assistida e coberta com muito mais qualidade pelo
HTML e pelo DOCX.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer

from pipeline.gestor_de_verbosidade import filtrar_blocos_por_perfil


class _DocTemplate(SimpleDocTemplate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._outline = []
        self._last_outline_level = -1

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and getattr(flowable, "_heading_id", None):
            self.canv.bookmarkPage(flowable._heading_id)
            self._outline.append((flowable._heading_level - 1, flowable.getPlainText(), flowable._heading_id))
        super().afterFlowable(flowable)

    def handle_pageEnd(self):
        if self._outline:
            for level, text, key in self._outline:
                safe_level = self._normalize_outline_level(level)
                self.canv.addOutlineEntry(
                    text,
                    key,
                    level=safe_level,
                    closed=False,
                )
                self._last_outline_level = safe_level
            self._outline.clear()
        super().handle_pageEnd()

    def _normalize_outline_level(self, raw_level: int) -> int:
        target = max(int(raw_level), 0)
        if self._last_outline_level < 0:
            return 0
        if target > self._last_outline_level + 1:
            return self._last_outline_level + 1
        return target


def gerar_pdf(document: dict[str, Any], output_path: Path, profile_name: str = "pdf", title: str | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("A11yTitle", parent=styles["Title"], alignment=TA_CENTER, spaceAfter=12))
    styles.add(ParagraphStyle("A11yHeading1", parent=styles["Heading1"], spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle("A11yHeading2", parent=styles["Heading2"], spaceBefore=8, spaceAfter=4))
    styles.add(ParagraphStyle("A11yBody", parent=styles["BodyText"], leading=14, spaceAfter=6))
    doc = _DocTemplate(str(output_path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=title or document.get("title", "Documento acessível"), author="a11y-devs-describer")
    story = [Paragraph(title or document.get("title", "Documento acessível"), styles["A11yTitle"]), Spacer(1, 6 * mm)]
    toc = _build_toc(document)
    if toc:
        story.append(Paragraph("Sumario", styles["A11yHeading1"]))
        for level, heading_title, heading_id in toc:
            indent = "&nbsp;" * (level - 1) * 4
            story.append(Paragraph(f'{indent}<link href="#{heading_id}">{heading_title}</link>', styles["A11yBody"]))
        story.append(PageBreak())
    for section in document.get("sections", []):
        _render_section(story, section, styles, profile_name)
    doc.build(story)
    return output_path


def _build_toc(document: dict[str, Any]) -> list[tuple[int, str, str]]:
    toc: list[tuple[int, str, str]] = []
    for section in document.get("sections", []):
        toc.extend(_section_toc(section))
    return toc


def _section_toc(section: dict[str, Any]) -> list[tuple[int, str, str]]:
    entries = []
    if section.get("title"):
        entries.append((section.get("level", 1), section["title"], section.get("id", "")))
    for child in section.get("children", []):
        entries.extend(_section_toc(child))
    return entries


def _render_section(story, section: dict[str, Any], styles, profile_name: str) -> None:
    if section.get("title"):
        style_name = {1: "A11yHeading1", 2: "Heading2"}.get(section.get("level", 1), "A11yHeading2")
        paragraph = Paragraph(f'<a name="{section.get("id", "")}"/>{section["title"]}', styles[style_name])
        paragraph._heading_id = section.get("id", "")
        paragraph._heading_level = section.get("level", 1)
        story.append(paragraph)
    for block in filtrar_blocos_por_perfil(section.get("blocks", []), profile_name):
        _render_block(story, block, styles)
    for child in section.get("children", []):
        _render_section(story, child, styles, profile_name)


def _render_block(story, block: dict[str, Any], styles) -> None:
    block_type = block.get("type")
    if block_type == "heading":
        paragraph = Paragraph(f'<a name="{block.get("id", "")}"/>{block.get("title", block.get("text", ""))}', styles["A11yHeading2"])
        paragraph._heading_id = block.get("id", "")
        paragraph._heading_level = block.get("level", 1)
        story.append(paragraph)
    elif block_type == "paragraph":
        story.append(Paragraph(block.get("text", ""), styles["A11yBody"]))
    elif block_type == "code":
        story.append(Preformatted(block.get("text", ""), styles["A11yBody"], dedent=False))
    elif block_type == "list":
        items = [Paragraph(str(item), styles["A11yBody"]) for item in block.get("items", [])]
        inicio = int(block.get("start") or 1)
        if block.get("ordered") and inicio != 1:
            for k, item in enumerate(block.get("items", [])):
                story.append(
                    Paragraph(f"{inicio + k}. {item}", styles["A11yBody"])
                )
        else:
            story.append(ListFlowable(items, bulletType="1" if block.get("ordered") else "bullet"))
    elif block_type == "table":
        _render_table(story, block, styles)
    elif block_type == "image" and block.get("decorative"):
        pass
    elif block_type == "image":
        _render_image(story, block, styles)
    elif block_type in {"details", "note", "warning", "quote", "math"}:
        text = block.get("long_description") or block.get("alt_text") or block.get("text", "")
        story.append(Paragraph(text, styles["A11yBody"]))
    else:
        story.append(Paragraph(block.get("text", ""), styles["A11yBody"]))

_LARGURA_MAXIMA_PT = 400


def _render_image(story, block: dict, styles) -> None:
    from pathlib import Path

    alt = block.get("alt_text") or block.get("text") or ""
    descricao = block.get("long_description") or ""
    caminho = block.get("asset_path") or (
        block.get("metadata", {}) or {}
    ).get("asset_path")

    if caminho:
        arquivo = Path(caminho)
        if not arquivo.is_absolute():
            base = (block.get("metadata", {}) or {}).get("asset_base")
            if base:
                arquivo = Path(base) / caminho
        if arquivo.exists():
            try:
                from reportlab.platypus import Image as ImagemPDF

                imagem = ImagemPDF(str(arquivo))
                if imagem.drawWidth > _LARGURA_MAXIMA_PT:
                    proporcao = _LARGURA_MAXIMA_PT / imagem.drawWidth
                    imagem.drawWidth = _LARGURA_MAXIMA_PT
                    imagem.drawHeight = imagem.drawHeight * proporcao
                story.append(imagem)
            except Exception:
                pass

    texto = descricao or alt
    if texto:
        story.append(Paragraph(texto, styles["A11yBody"]))


def _render_table(story, block: dict, styles) -> None:
    rows = block.get("rows", [])
    if not rows:
        return

    caption = str(block.get("caption") or "").strip()
    if caption:
        story.append(Paragraph(f"<b>{caption}</b>", styles["A11yBody"]))

    resumo = str(block.get("summary") or "").strip()
    if resumo:
        story.append(Paragraph(resumo, styles["A11yBody"]))

    try:
        from reportlab.lib import colors
        from reportlab.platypus import Table as TabelaPDF
        from reportlab.platypus import TableStyle

        dados = [[str(c) for c in linha] for linha in rows]
        tabela = TabelaPDF(dados, repeatRows=1)
        tabela.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(tabela)
    except Exception:
        for row in rows:
            story.append(
                Paragraph(" | ".join(str(c) for c in row), styles["A11yBody"])
            )
