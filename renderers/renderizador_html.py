"""Gera o HTML com MathML navegavel e fala em portugues.

E o unico formato em que a formula pode ser NAVEGADA: com MathML real,
o leitor de tela permite entrar na fracao, inspecionar o numerador,
sair, entrar na raiz.

A estrategia atual e a terceira tentativa: o MathML fica no documento
com aria-hidden, e por cima vai um wrapper com role="math" e a fala em
portugues no aria-label. Assim a leitura corrida sai em portugues e a
arvore continua disponivel para exploracao. As duas tentativas
anteriores falharam de formas opostas — rotulo direto no <math>
achatava a exploracao, e aria-describedby e descricao complementar,
entao o resultado variava conforme o navegador.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from renderers.filtros_de_perfil import aplicar_filtro_de_perfil
from pipeline.gestor_de_verbosidade import normalizar_perfil
from pipeline.higienizador import remover_marcadores_tecnicos


def gerar_html(document: dict[str, Any], output_path: Path, profile_name: str = "html") -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        gerar_html_como_texto(document, profile_name), encoding="utf-8"
    )
    return output_path


def gerar_html_como_texto(document: dict[str, Any],
                       profile_name: str = "html") -> str:
    profile = normalizar_perfil(profile_name)
    blocks = aplicar_filtro_de_perfil(_all_blocks(document), profile_name)

    toc = []
    body = []
    for block in blocks:
        if block.get("type") == "heading":
            toc.append((block.get("level", 1), block.get("title", block.get("text", "")), block.get("id", "")))
        body.append(_render_block(block, profile))

    html = ["<!doctype html>", f'<html lang="{escape(document.get("language", "pt-BR"))}">', "<head>", '<meta charset="utf-8">', '<meta name="viewport" content="width=device-width, initial-scale=1">', f"<title>{escape(document.get('title', 'Documento acessível'))}</title>", "<style>", "body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.6;max-width:980px;margin:0 auto;padding:2rem;background:#fafafa;color:#1c1c1c}", "nav.toc{background:#fff;border:1px solid #ddd;border-radius:12px;padding:1rem 1.25rem;margin-bottom:1.5rem}", "nav.toc ul{margin:0;padding-left:1.2rem}", "pre{overflow:auto;background:#111;color:#f4f4f4;padding:1rem;border-radius:10px}", "code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}", "details{background:#fff;border:1px solid #ddd;border-radius:10px;padding:.75rem 1rem;margin:1rem 0}", "aside.meta{background:#f3f4f6;border-left:4px solid #7c3aed;padding:.75rem 1rem;margin:1.5rem 0}", "</style>", "</head>", "<body>", f'<main aria-label="{escape(document.get("title", "Documento acessível"))}">']
    if toc:
        html.append('<nav class="toc" aria-label="Sumário"><strong>Sumário</strong><ul>')
        for level, title, link_id in toc:
            html.append(f'<li class="lvl-{level}"><a href="#{escape(link_id)}">{escape(title)}</a></li>')
        html.append("</ul></nav>")
    html.extend(body)
    if profile.get("developer_debug"):
        html.append(
            '<aside class="meta" aria-hidden="true">'
            "<h2>Metadados técnicos</h2><p>"
            + escape(str(document.get("metadata", {})))
            + "</p></aside>"
        )
    html.append("</main></body></html>")
    return "\n".join(html)


def _all_blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for section in document.get("sections", []):
        blocks.extend(_collect_section(section))
    return blocks


def _collect_section(section: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = [{"type": "heading", "level": section.get("level", 1), "title": section.get("title", ""), "id": section.get("id", "")}] if section.get("title") else []
    blocks.extend(section.get("blocks", []))
    for child in section.get("children", []):
        blocks.extend(_collect_section(child))
    return blocks


def _render_block(block: dict[str, Any], profile: dict[str, Any]) -> str:
    block_type = block.get("type")
    block_id = escape(block.get("id", ""))
    if block_type == "heading":
        level = min(max(int(block.get("level", 1)), 1), 6)
        return f'<h{level} id="{block_id}">{escape(block.get("title", block.get("text", "")))}</h{level}>'
    if block_type == "paragraph":
        return f'<p id="{block_id}">{escape(block.get("text", ""))}</p>'
    if block_type == "code":
        return f'<pre id="{block_id}"><code>{escape(block.get("text", ""))}</code></pre>'
    if block_type == "list":
        tag = "ol" if block.get("ordered") else "ul"
        atributo_start = ""
        if block.get("ordered") and int(block.get("start") or 1) != 1:
            atributo_start = f' start="{int(block["start"])}"'

        items = "".join(f"<li>{escape(str(item))}</li>" for item in block.get("items", []))
        return f'<{tag}{atributo_start} id="{block_id}">{items}</{tag}>'
    if block_type == "table":
        rows = block.get("rows", [])
        if not rows:
            return ""
        header = rows[0]
        body_rows = rows[1:] or []
        idiomas = block.get("cell_languages") or []
        idioma_doc = str(block.get("language") or "pt-BR")

        def _celula(tag: str, valor: Any, i: int, j: int) -> str:
            atributo = ""
            try:
                from pipeline.localizacao import codigo_bcp47, precisa_marcar

                idioma = idiomas[i][j] if i < len(idiomas) and j < len(
                    idiomas[i]
                ) else ""
                if precisa_marcar(idioma, idioma_doc):
                    atributo = f' lang="{escape(codigo_bcp47(idioma))}"'
            except Exception:
                atributo = ""
            escopo = ' scope="col"' if tag == "th" else ""
            return f"<{tag}{escopo}{atributo}>{escape(str(valor))}</{tag}>"

        thead = "<tr>" + "".join(
            _celula("th", cell, 0, j) for j, cell in enumerate(header)
        ) + "</tr>"
        tbody = "".join(
            "<tr>" + "".join(
                _celula("td", cell, i, j) for j, cell in enumerate(row)
            ) + "</tr>"
            for i, row in enumerate(body_rows, start=1)
        )

        caption = escape(str(block.get("caption") or "").strip())
        resumo = escape(str(block.get("summary") or "").strip())
        tag_caption = f"<caption>{caption}</caption>" if caption else ""
        antes = (
            f'<p class="sintese-tabela" id="{block_id}-resumo">{resumo}</p>'
            if resumo else ""
        )
        eixos = _render_eixos(block)
        return (
            f"{antes}{eixos}"
            f'<table id="{block_id}"'
            + (f' aria-describedby="{block_id}-resumo"' if resumo else "")
            + f">{tag_caption}<thead>{thead}</thead>"
            f"<tbody>{tbody}</tbody></table>"
        )
    if block_type == "image":
        return _render_image(block)

    if block_type == "math":
        mathml = block.get("mathml")
        fala = (block.get("speech_pt_br") or "").strip()
        if mathml:
            id_estavel = str(block.get("math_id") or block_id)
            from pipeline.matematica.serializacao_matematica import (
                adicionar_ids_de_navegacao,
            )

            mathml_final = adicionar_ids_de_navegacao(
                mathml, id_estavel
            )
            if 'xml:lang="pt-BR"' not in mathml_final:
                mathml_final = mathml_final.replace(
                    "<math ", '<math xml:lang="pt-BR" ', 1
                )
            if fala:
                mathml_final = mathml_final.replace(
                    "<math ", '<math aria-hidden="true" ', 1
                )
                return (
                    f'<p id="{block_id}">'
                    f'<span class="formula-leitura-continua" role="math" '
                    f'id="{escape(id_estavel)}-formula" '
                    f'aria-label="{escape(fala)}">'
                    f"{mathml_final}</span></p>"
                )
            return f'<p id="{block_id}">{mathml_final}</p>' 
        texto_mtext = escape(fala or block.get("text", ""))
        rotulo = f' role="math" aria-label="{escape(fala)}"' if fala else ""
        return (
            f'<p id="{block_id}"><math xml:lang="pt-BR"{rotulo}>'
            f"<mtext>{texto_mtext}</mtext></math></p>"
        )
    if block_type in {"details", "note", "warning", "quote"}:
        summary = escape(block.get("title", block_type.title()))
        content = escape(block.get("text", ""))
        if profile.get("collapsible"):
            return f'<details id="{block_id}"><summary>{summary}</summary><p>{content}</p></details>'
        return f'<section id="{block_id}"><h2>{summary}</h2><p>{content}</p></section>'
    return f'<p id="{block_id}">{escape(block.get("text", ""))}</p>'

def _render_image(block: dict[str, Any]) -> str:
    block_id = escape(str(block.get("id", "")))

    if block.get("decorative"):
        return "<!-- imagem decorativa: sem conteudo didatico -->"

    alt = escape(block.get("alt_text") or block.get("text") or "")
    desc = escape(block.get("long_description") or "")

    metadata = block.get("metadata", {}) or {}
    caminho = (
        block.get("asset_path")
        or metadata.get("asset_path")
        or metadata.get("src")
        or ""
    )

    atributo_src = f' src="{escape(str(caminho))}"' if caminho else ""

    details = (
        f"<details><summary>Descrição da imagem</summary>"
        f"<p>{desc}</p></details>"
    ) if desc else ""

    return (
        f'<figure id="{block_id}">'
        f'<img{atributo_src} alt="{alt}">'
        f"{details}</figure>"
    )


def _render_eixos(block: dict[str, Any]) -> str:
    eixos = block.get("axes") or {}
    if not isinstance(eixos, dict) or not eixos:
        return ""

    itens: list[str] = []
    for chave, rotulo_eixo in (("x", "Eixo horizontal"), ("y", "Eixo vertical")):
        eixo = eixos.get(chave) or {}
        if not isinstance(eixo, dict):
            continue
        partes: list[str] = []
        if eixo.get("label"):
            partes.append(escape(str(eixo["label"])))
        if eixo.get("unit"):
            partes.append(f"em {escape(str(eixo['unit']))}")
        if eixo.get("min") is not None and eixo.get("max") is not None:
            partes.append(f"de {eixo['min']} a {eixo['max']}")
        if eixo.get("step") is not None:
            partes.append(f"intervalo {eixo['step']}")
        if partes:
            itens.append(f"<li>{rotulo_eixo}: {', '.join(partes)}.</li>")

    if not itens:
        return ""
    return f'<ul class="eixos-do-grafico">{"".join(itens)}</ul>'
