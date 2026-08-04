"""Converte o texto dos agentes em blocos estruturados.

Transforma o que os agentes produziram sobre a pagina em blocos
tipados — paragrafo, titulo, tabela, formula, imagem, lista — que e o
formato que o documento canonico e os renderizadores consomem.

Tambem encaminha cada recurso matematico para a camada correspondente
e separa o que precisa virar arvore do que segue como texto.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from pipeline.higienizador import higienizar_texto_do_bloco


MARCADOR_DECORATIVA = "[imagem decorativa]"


def _latex_para_mathml(latex: str) -> str | None:
    if not latex:
        return None
    try:
        import latex2mathml.converter as _conv
        from xml.sax.saxutils import escape as _xml_escape

        bruto = _conv.convert(latex)
        partes = re.match(r"^(<math[^>]*>)(.*)(</math>)$", bruto, re.S)
        if not partes:
            return bruto
        abre, corpo, fecha = partes.groups()
        anotacao = (
            '<annotation encoding="application/x-tex">'
            f"{_xml_escape(latex)}</annotation>"
        )
        return f"{abre}<semantics><mrow>{corpo}</mrow>{anotacao}</semantics>{fecha}"
    except Exception:
        return None


def _celulas_matematicas(rows: list) -> list[list[int]]:
    try:
        from pipeline.matematica.matematica_inline import segmentar_matematica
    except Exception:
        return []
    marcadas: list[list[int]] = []
    for indice_linha, linha in enumerate(rows or []):
        if indice_linha == 0:
            continue
        for indice_coluna, celula in enumerate(linha or []):
            texto = str(celula or "").strip()
            if not texto:
                continue
            segmentos = segmentar_matematica(texto, celula=True)
            if any(s["tipo"] == "math" for s in segmentos):
                marcadas.append([indice_linha, indice_coluna])
    return marcadas


def _bloco_tabela(rows: list, metadata: dict | None = None) -> dict[str, Any]:
    bloco: dict[str, Any] = {"type": "table", "rows": rows}
    meta = dict(metadata or {})
    celulas = _celulas_matematicas(rows)
    if celulas:
        meta["math_cells"] = celulas
    if meta:
        bloco["metadata"] = meta
    return bloco


def _bloco_decorativo() -> dict[str, Any]:
    return {"type": "image", "text": "", "alt_text": "", "decorative": True}


def converter_texto_em_blocos(
    text: str, catalogo=None
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            blocks.append(
                {
                    "type": "heading",
                    "level": len(heading_match.group(1)),
                    "text": higienizar_texto_do_bloco(
                        heading_match.group(2).strip()
                    ),
                }
            )
            i += 1
            continue
        plain_heading = _extract_plain_heading(stripped, len(blocks))
        if plain_heading is not None:
            blocks.append(plain_heading)
            i += 1
            continue
        marker_block = _try_parse_marker_block(lines, i, catalogo)
        if marker_block is not None:
            block, consumed = marker_block
            if isinstance(block, list):
                blocks.extend(block)
            else:
                blocks.append(block)
            i = consumed
            continue
        if re.match(r"^(?:[-*+]\s+)", stripped):
            blocks.append(
                {
                    "type": "list",
                    "ordered": False,
                    "items": [higienizar_texto_do_bloco(stripped[2:].strip())],
                }
            )
            i += 1
            continue
        if re.match(r"^(?:\(?\d+\)|\d+\))\s+", stripped):
            _m_num = re.match(r"^\(?(\d+)\)?\)?", stripped)
            blocks.append(
                {
                    "type": "list",
                    "ordered": True,
                    "start": int(_m_num.group(1)) if _m_num else 1,
                    "items": [
                        higienizar_texto_do_bloco(
                            re.sub(r"^(?:\(?\d+\)|\d+\))\s+", "", stripped),
                        )
                    ],
                }
            )
            i += 1
            continue
        if re.match(r"^\d+\.\s+", stripped):
            _m_num = re.match(r"^(\d+)\.", stripped)
            blocks.append(
                {
                    "type": "list",
                    "ordered": True,
                    "start": int(_m_num.group(1)) if _m_num else 1,
                    "items": [
                        higienizar_texto_do_bloco(
                            re.sub(r"^\d+\.\s+", "", stripped),
                        )
                    ],
                }
            )
            i += 1
            continue
        if stripped.startswith("```"):
            blocks.append({"type": "code", "text": stripped})
            i += 1
            continue
        if _looks_like_table_row(stripped):
            rows, end_index = _parse_table_rows(lines, i)
            if rows:
                blocks.append(_bloco_tabela(rows))
                i = end_index + 1
                continue
        if stripped == MARCADOR_DECORATIVA:
            blocks.append(_bloco_decorativo())
            i += 1
            continue
        blocks.extend(_blocos_de_paragrafo(stripped, catalogo))
        i += 1
    return _attach_ids(blocks)


_CONTADOR_DE_FLUXO = 0


def _blocos_de_paragrafo(texto: str, catalogo=None) -> list[dict[str, Any]]:
    try:
        from pipeline.matematica.matematica_inline import segmentar_matematica

        segmentos = segmentar_matematica(texto)
    except Exception:
        segmentos = []

    if not any(s["tipo"] == "math" for s in segmentos):
        return [{"type": "paragraph", "text": higienizar_texto_do_bloco(texto)}]

    global _CONTADOR_DE_FLUXO
    _CONTADOR_DE_FLUXO += 1
    fluxo = f"fx{_CONTADOR_DE_FLUXO}"

    pendente = ""
    blocos: list[dict[str, Any]] = []
    for segmento in segmentos:
        conteudo = segmento["conteudo"]
        if segmento["tipo"] == "text":
            junto = pendente + conteudo
            pendente = ""
            if not junto.strip():
                continue
            if not any(c.isalnum() for c in junto):
                pendente = junto
                continue
            blocos.append({
                "type": "paragraph",
                "text": higienizar_texto_do_bloco(junto),
                "grupo_fluxo": fluxo,
            })
            continue
        bloco_math = _bloco_math_de_expressao(conteudo, catalogo)
        bloco_math["grupo_fluxo"] = fluxo
        blocos.append(bloco_math)

    if len(blocos) == 1:
        blocos[0].pop("grupo_fluxo", None)

    return blocos


def _pipeline_matematico_ligado() -> bool:
    import os

    valor = (os.getenv("USAR_PIPELINE_MATEMATICO", "true") or "").strip()
    return valor.lower() not in ("false", "0", "nao", "não", "off")


def _bloco_math_pela_via_antiga(
    expressao: str, fonte: str, leitura: str = ""
) -> dict[str, Any]:
    try:
        from pipeline.matematica.normalizador_matematico import normalizar_latex

        latex = normalizar_latex(expressao)
    except Exception:
        latex = expressao
    bloco: dict[str, Any] = {
        "type": "math",
        "text": higienizar_texto_do_bloco(leitura or expressao),
        "latex": latex,
        "metadata": {
            "origem": expressao,
            "fonte": fonte,
            "motor": "legado",
        },
    }
    mathml = _latex_para_mathml(latex)
    if mathml:
        bloco["mathml"] = mathml
    return bloco


def _bloco_math_de_expressao(
    expressao: str,
    catalogo=None,
    contexto=None,
    fonte: str = "inline",
    leitura: str = "",
) -> dict[str, Any]:
    if not _pipeline_matematico_ligado():
        return _bloco_math_pela_via_antiga(expressao, fonte, leitura)

    try:
        from core.math import PipelineMatematico
        from pipeline.matematica.evidencia_matematica import RegionContext

        evidencia = None
        if catalogo is not None:
            try:
                evidencia = catalogo.buscar(expressao)
            except Exception:
                evidencia = None

        vizinhos: list[str] = []
        if catalogo is not None:
            try:
                vizinhos = catalogo.vizinhos_de(expressao)
            except Exception:
                vizinhos = []

        no = PipelineMatematico().processar(
            evidencia if evidencia is not None else expressao,
            contexto or RegionContext(tipo_regiao="formula"),
            vizinhos=vizinhos or None,
        )
    except Exception:
        return _bloco_math_pela_via_antiga(expressao, fonte, leitura)

    if not (no.latex or "").strip():
        return _bloco_math_pela_via_antiga(expressao, fonte, leitura)

    fala = higienizar_texto_do_bloco(no.speech_pt_br or leitura or expressao)

    metadata: dict[str, Any] = {
        "origem": expressao,
        "fonte": fonte,
        "motor": "pipeline_matematico",
        "com_geometria": bool(
            evidencia is not None and getattr(evidencia, "geometry", None)
        ),
    }
    if vizinhos:
        metadata["vizinhos_disponiveis"] = len(vizinhos)
        expandida = (no.source_text or "") != expressao
        metadata["fronteira_expandida"] = expandida
        if expandida and catalogo is not None:
            try:
                catalogo.registrar_consumo(expressao, vizinhos)
            except Exception:
                pass
    if leitura:
        metadata["leitura_do_especialista"] = leitura
    if no.uncertainties:
        metadata["incertezas"] = list(no.uncertainties)

    bloco: dict[str, Any] = {
        "type": "math",
        "text": fala,
        "speech_pt_br": no.speech_pt_br,
        "latex": no.latex,
        "source_text": no.source_text,
        "review_status": no.review_status,
        "metadata": metadata,
    }
    if no.mathml:
        bloco["mathml"] = no.mathml
    if no.omml:
        bloco["omml"] = no.omml
    if no.validation_issues:
        bloco["validation_issues"] = list(no.validation_issues)
    return bloco


def _attach_ids(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, block in enumerate(blocks, start=1):
        block.setdefault("id", f"blk-{uuid4().hex[:10]}-{index}")
    return _enriquecer(blocks)


def _enriquecer(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from pipeline.matematica.podador import podar_blocos
    except Exception:
        return blocks
    return podar_blocos(blocks)

def _e_separador_markdown(line: str) -> bool:
    limpa = line.strip()
    return (
        "|" in limpa
        and "-" in limpa
        and set(limpa) <= set("-:| \t")
    )


def _looks_like_table_row(line: str) -> bool:
    limpa = line.strip()
    if not limpa or "|" not in limpa:
        return False
    if limpa.startswith("|") and limpa.endswith("|"):
        return True
    if _e_separador_markdown(limpa):
        return True
    celulas = [c.strip() for c in limpa.split("|")]
    return len(celulas) >= 2 and all(celulas)


def _bloco_de_tabela_confiavel(linhas: list[str], inicio: int) -> bool:
    contagens: list[int] = []
    for linha in linhas[inicio:]:
        limpa = linha.strip()
        if not _looks_like_table_row(limpa):
            break
        if _e_separador_markdown(limpa):
            return True
        contagens.append(len(limpa.strip("|").split("|")))
    if len(contagens) < 2:
        return False
    return contagens[0] == contagens[1] >= 2


def _extract_plain_heading(
    line: str,
    current_blocks: int,
) -> dict[str, Any] | None:
    prefixed = re.match(
        (
            r"^(?:titulo|t[ií]tulo|secao|se[cç][aã]o|"
            r"capitulo|cap[ií]tulo(?:\s+\d+)?)\s*:\s*(.+)$"
        ),
        line,
        re.IGNORECASE,
    )
    if prefixed:
        keyword = line.split(":", 1)[0].strip().lower()
        level = 1 if "titulo" in keyword or "título" in keyword else 2
        return {
            "type": "heading",
            "level": level,
            "text": higienizar_texto_do_bloco(prefixed.group(1).strip()),
        }

    if _looks_like_upper_heading(line):
        level = 1 if current_blocks == 0 else 2
        return {
            "type": "heading",
            "level": level,
            "text": higienizar_texto_do_bloco(line),
        }
    return None


def _try_parse_marker_block(
    lines: list[str],
    i: int,
    catalogo=None,
) -> tuple[dict[str, Any], int] | None:
    stripped = lines[i].strip()
    m = re.match(r"^In[íi]cio de (.+):$", stripped, re.IGNORECASE)
    if not m:
        return None

    type_name = m.group(1).strip()
    end_marker = f"Fim de {type_name}"

    content_lines: list[str] = []
    j = i + 1
    while j < len(lines):
        if lines[j].strip() == end_marker:
            j += 1
            break
        content_lines.append(lines[j])
        j += 1

    type_key = type_name.lower().replace(" ", "-")

    if type_key in ("lista",):
        items = []
        for cl in content_lines:
            cl_stripped = cl.strip()
            if cl_stripped:
                item_text = re.sub(r"^[-*+]\s+", "", cl_stripped).strip()
                items.append(higienizar_texto_do_bloco(item_text))
        return {"type": "list", "ordered": False, "items": items}, j

    if type_key in ("código-fonte", "codigo-fonte"):
        code_text = "\n".join(cl.rstrip("\n") for cl in content_lines).strip()
        return {"type": "code", "text": code_text}, j

    if type_key == "imagem":
        linhas_conteudo = [cl.strip() for cl in content_lines]
        texto_bruto = "\n".join(l for l in linhas_conteudo if l)
        if not texto_bruto or texto_bruto == MARCADOR_DECORATIVA:
            return _bloco_decorativo(), j

        indices_pipe = [
            k for k, l in enumerate(linhas_conteudo) if _looks_like_table_row(l)
        ]
        if indices_pipe and _bloco_de_tabela_confiavel(
            linhas_conteudo, indices_pipe[0]
        ):
            resultado: list[dict[str, Any]] = []
            intro = " ".join(
                l for l in linhas_conteudo[: indices_pipe[0]] if l
            ).strip()
            if intro:
                resultado.append(
                    {"type": "paragraph", "text": higienizar_texto_do_bloco(intro)}
                )
            rows, fim = _parse_table_rows(linhas_conteudo, indices_pipe[0])
            if rows:
                resultado.append(
                    _bloco_tabela(rows, {"source_visual_type": "chart"})
                )
                depois = " ".join(
                    l for l in linhas_conteudo[fim + 1 :] if l
                ).strip()
                if depois:
                    resultado.append(
                        {"type": "paragraph", "text": higienizar_texto_do_bloco(depois)}
                    )
                return resultado, j

        text = higienizar_texto_do_bloco(texto_bruto)
        bloco_img: dict[str, Any] = {"type": "image", "text": text}
        if catalogo is not None:
            try:
                asset = catalogo.proximo_asset_sem_uso()
                if asset is not None:
                    bloco_img["asset_id"] = asset.asset_id
                    bloco_img["asset_path"] = asset.asset_path
                    bloco_img["page_number"] = asset.page_number
                    bloco_img.setdefault("metadata", {}).update({
                        "asset_base": str(asset.absolute_path.parent.parent),
                        "source_bbox": list(asset.source_bbox or ()),
                        "digest": asset.digest,
                    })
            except Exception:
                pass
        return bloco_img, j

    if type_key in ("fórmula", "formula"):
        linhas_f = [cl.strip() for cl in content_lines if cl.strip()]
        conteudo = "\n".join(linhas_f)
        if not conteudo or conteudo == MARCADOR_DECORATIVA:
            return _bloco_decorativo(), j

        MARCADOR_INCERTEZA = "[verificacao incerta]"
        incerta = False
        latex = ""
        leitura = ""
        extras: list[str] = []
        for l in linhas_f:
            if l.startswith(MARCADOR_INCERTEZA):
                incerta = True
                l = l[len(MARCADOR_INCERTEZA) :].strip()
                if not l:
                    continue
            maiuscula = l.upper()
            if maiuscula.startswith("LATEX:"):
                latex = l[len("LATEX:") :].strip()
            elif maiuscula.startswith("LEITURA:"):
                leitura = l[len("LEITURA:") :].strip()
            else:
                extras.append(l)

        if not latex:
            achado = re.search(r"\$([^$]+)\$", conteudo)
            if achado:
                latex = achado.group(1).strip()
                extras = [
                    re.sub(r"\$[^$]+\$", "", l).strip() for l in extras
                ]
                extras = [l for l in extras if l]

        latex = latex.strip().strip("$").strip()
        texto_extra = " ".join(extras).strip()

        if not latex and not leitura:
            leitura = texto_extra
            texto_extra = ""

        if not latex:
            bloco_math = {
                "type": "math",
                "text": higienizar_texto_do_bloco(leitura),
                "latex": "",
            }
            if incerta and bloco_math["text"]:
                bloco_math["text"] = (
                    f"{MARCADOR_INCERTEZA} {bloco_math['text']}"
                )
            if texto_extra:
                return [
                    bloco_math,
                    {"type": "paragraph",
                     "text": higienizar_texto_do_bloco(texto_extra)},
                ], j
            return bloco_math, j

        origem_preferida = latex
        evidencia_da_regiao = None
        if catalogo is not None:
            try:
                evidencia_da_regiao = catalogo.buscar(latex) or catalogo.buscar(
                    leitura
                )
            except Exception:
                evidencia_da_regiao = None
        if evidencia_da_regiao is not None:
            origem_preferida = evidencia_da_regiao.raw_text or origem_preferida

        bloco_math = _bloco_math_de_expressao(
            origem_preferida,
            catalogo,
            fonte="marcador_formula",
            leitura=leitura,
        )

        incompleta = any(
            "nao explicou a expressao inteira" in str(aviso)
            for aviso in (
                (bloco_math.get("metadata") or {}).get("incertezas") or []
            )
        )
        if incompleta:
            bloco_math = {
                "type": "math",
                "text": higienizar_texto_do_bloco(leitura or latex),
                "latex": latex,
                "review_status": "needs_review",
                "metadata": {"origem": latex, "fonte": "marcador_formula",
                             "motor": "legado_por_incompletude"},
            }
            mathml = _latex_para_mathml(latex)
            if mathml:
                bloco_math["mathml"] = mathml
        if incerta and bloco_math.get("text"):
            bloco_math["text"] = (
                f"{MARCADOR_INCERTEZA} {bloco_math['text']}"
            )
            bloco_math["review_status"] = "needs_review"
            bloco_math.setdefault("metadata", {})[
                "marcador_do_critico_visual"
            ] = True

        if texto_extra:
            return [
                bloco_math,
                {"type": "paragraph", "text": higienizar_texto_do_bloco(texto_extra)},
            ], j
        return bloco_math, j

    callout_types = {
        "nota", "citação", "citacao", "barra lateral",
        "aviso", "dica", "importante", "box",
    }
    if type_key in callout_types:
        text = higienizar_texto_do_bloco(
            "\n".join(cl.strip() for cl in content_lines if cl.strip())
        )
        return {"type": "callout", "text": text, "callout_type": type_name}, j

    return None


def _looks_like_upper_heading(line: str) -> bool:
    has_letter = any(ch.isalpha() for ch in line)
    if not has_letter:
        return False
    if len(line) > 90:
        return False
    if line.endswith((".", ";", "!", "?")):
        return False
    if ":" in line:
        return False
    return line == line.upper()


def _parse_table_rows(
    lines: list[str],
    start_index: int,
) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    i = start_index

    while i < len(lines):
        stripped = lines[i].strip()
        if not _looks_like_table_row(stripped):
            break
        if _e_separador_markdown(stripped):
            i += 1
            continue
        cells = [
            higienizar_texto_do_bloco(cell.strip())
            for cell in stripped.strip("|").split("|")
        ]
        if cells and all(set(cell) <= {"-", ":"} for cell in cells):
            i += 1
            continue
        rows.append(cells)
        i += 1

    return rows, i - 1


def separar_recursos_matematicos(
    bloco: dict[str, Any], ja_explicadas: set[str] | None = None
) -> dict[str, Any]:
    novo = dict(bloco)
    ja_explicadas = ja_explicadas if ja_explicadas is not None else set()

    chave = (novo.get("latex") or novo.get("source_text") or "").strip()
    explicacao = (novo.get("metadata", {}) or {}).get("explicacao", "")

    if explicacao and chave:
        if chave in ja_explicadas:
            metadata = dict(novo.get("metadata") or {})
            metadata.pop("explicacao", None)
            metadata["explicacao_suprimida"] = "ja explicada neste documento"
            novo["metadata"] = metadata
        else:
            ja_explicadas.add(chave)

    novo["_recursos"] = {
        "fala": novo.get("speech_pt_br") or novo.get("text") or "",
        "mathml": novo.get("mathml") or "",
        "omml": novo.get("omml") or "",
        "explicacao": (novo.get("metadata", {}) or {}).get("explicacao", ""),
    }
    return novo
