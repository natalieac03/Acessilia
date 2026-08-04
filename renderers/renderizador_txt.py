"""Gera o TXT — o formato que vira audio e que o leitor de tela le.

E o formato mais importante do sistema por dois motivos: e lido direto
pela tecnologia assistiva e e a fonte do MP3. Se um simbolo escapar
aqui, escapa para o audio, e no audio nao ha como voltar e reler.

A regra e absoluta: nada de simbolo. Nem "=", nem "²", nem digito —
tudo vira palavra. Tabela e linearizada (anatomia primeiro, depois
"cabecalho: valor" por linha), formula usa a fala vinda da arvore, e
blocos que nasceram do mesmo paragrafo sao reagrupados numa linha so,
para a frase nao virar tres falas separadas no TTS.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pipeline.gestor_de_verbosidade import filtrar_blocos_por_perfil
from pipeline.higienizador import remover_marcadores_tecnicos


def gerar_txt_como_texto(document: dict[str, Any],
                      profile_name: str = "txt") -> str:
    lines: list[str] = []
    for section in document.get("sections", []):
        lines.extend(_render_section(section, profile_name))
    texto = "\n".join(
        remover_marcadores_tecnicos(line)
        for line in lines if line is not None
    ).strip()

    from pipeline.matematica.verbalizador_de_simbolos import verbalizar_texto

    return verbalizar_texto(texto)


def gerar_txt(document: dict[str, Any], output_path: Path, profile_name: str = "txt") -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        gerar_txt_como_texto(document, profile_name), encoding="utf-8"
    )
    return output_path


def _render_section(section: dict[str, Any], profile_name: str) -> list[str]:
    lines: list[str] = []
    if section.get("title"):
        lines.append(section["title"])
    lines.extend(_reagrupar_fluxo(
        filtrar_blocos_por_perfil(section.get("blocks", []), profile_name),
        _render_block,
    ))
    for child in section.get("children", []):
        lines.extend(_render_section(child, profile_name))
    return lines


def _tabela_transposta(rows: list) -> bool:
    if len(rows) < 2 or len(rows[0]) < 2:
        return False

    def _e_numero(c: str) -> bool:
        limpo = str(c).strip().replace(".", "").replace(",", "")
        limpo = limpo.replace("%", "").replace("R$", "").replace(" ", "")
        limpo = limpo.replace("km/h", "").replace("m²", "").replace("-", "")
        return bool(limpo) and limpo.isdigit()

    primeira_linha_valores = [c for c in rows[0][1:]]
    numericos_no_topo = sum(_e_numero(c) for c in primeira_linha_valores)
    rotulos_na_coluna = [str(r[0]) for r in rows[1:] if r]
    textuais_na_coluna = sum(
        1 for c in rotulos_na_coluna if c and not _e_numero(c)
    )

    topo_e_numerico = numericos_no_topo >= max(1, len(primeira_linha_valores) // 2)
    coluna_e_textual = textuais_na_coluna >= max(1, len(rotulos_na_coluna) // 2)
    return topo_e_numerico and coluna_e_textual


def _linearizar_tabela(rows: list) -> list[str]:
    if not rows:
        return []

    if _tabela_transposta(rows):
        eixo_nome = str(rows[0][0])
        series_nomes = [str(r[0]) for r in rows[1:]]
        n_colunas = len(rows[0])
        from pipeline.matematica.vocabulario_de_fala import numero_por_extenso

        linhas = [
            f"Tabela com {numero_por_extenso(len(rows[0]) - 1)} "
            f"registros e {numero_por_extenso(len(rows))} atributos. "
            f"Eixo: {eixo_nome}. Séries: {', '.join(series_nomes)}."
        ]
        for coluna in range(1, n_colunas):
            eixo_valor = str(rows[0][coluna]) if coluna < len(rows[0]) else ""
            pares = []
            for r in rows[1:]:
                nome = str(r[0])
                valor = str(r[coluna]) if coluna < len(r) else ""
                pares.append(f"{nome}: {valor}")
            linhas.append(
                f"{eixo_nome} {eixo_valor} — " + "; ".join(pares) + "."
            )
        return linhas

    cabecalhos = [str(c) for c in rows[0]]
    cabecalhos = [
        c for c in cabecalhos
        if c.strip().rstrip(".").lower() != "tabela"
    ]
    if not cabecalhos:
        cabecalhos = [str(c) for c in rows[0]]
    from pipeline.matematica.vocabulario_de_fala import (
        numero_por_extenso,
        numero_por_extenso_feminino,
    )

    linhas = [
        f"Tabela com {numero_por_extenso(max(0, len(rows) - 1))} "
        f"registros e "
        f"{numero_por_extenso_feminino(len(cabecalhos))} colunas. "
        f"Cabeçalhos: {', '.join(cabecalhos)}."
    ]
    if len(rows) == 1:
        return ["Tabela sem registros de dados. "
                f"Cabeçalhos: {', '.join(cabecalhos)}."]
    for numero, row in enumerate(rows[1:], start=1):
        numero = numero_por_extenso(numero)
        valores = [str(c) for c in row]
        pares = "; ".join(
            f"{cab}: {val}" for cab, val in zip(cabecalhos, valores)
        )
        sobra = valores[len(cabecalhos):]
        if sobra:
            pares += "; " + "; ".join(sobra)
        linhas.append(f"Linha {numero}: {pares}.")
    return linhas


def _juntar_no_fluxo(partes: list[str]) -> str:
    texto = ""
    for parte in partes:
        parte = (parte or "").strip()
        if not parte:
            continue
        if not texto:
            texto = parte
            continue
        if parte[0] in ".,;:!?)]}%":
            texto = f"{texto}{parte}"
        else:
            texto = f"{texto} {parte}"
    return _RE_PONTUACAO_DUPLA.sub(r"\1", texto)


_RE_PONTUACAO_DUPLA = re.compile(r"([.,;:!?])\1+")


def _reagrupar_fluxo(
    blocos: list[dict[str, Any]], render: Any
) -> list[str]:
    linhas: list[str] = []
    acumulado: list[str] = []
    fluxo_atual: str | None = None

    def _fechar():
        nonlocal acumulado, fluxo_atual
        if acumulado:
            junto = _juntar_no_fluxo(acumulado)
            if junto:
                linhas.append(junto)
        acumulado = []
        fluxo_atual = None

    for bloco in blocos:
        fluxo = bloco.get("grupo_fluxo")
        partes = render(bloco)
        if not fluxo:
            _fechar()
            linhas.extend(partes)
            continue
        if fluxo != fluxo_atual:
            _fechar()
            fluxo_atual = fluxo
        acumulado.extend(partes)
    _fechar()
    return linhas


def _render_block(block: dict[str, Any]) -> list[str]:
    block_type = block.get("type")
    if block_type == "heading":
        return [block.get("title", block.get("text", ""))]
    if block_type == "paragraph":
        from pipeline.matematica.verbalizador_de_simbolos import (
            traduzir_operadores_residuais,
        )

        return [traduzir_operadores_residuais(
            block.get("text", ""), agressivo=False
        )]
    if block_type == "code":
        return [block.get("text", "")]
    if block_type == "list":
        if block.get("ordered"):
            inicio = int(block.get("start") or 1)
            return [
                f"{inicio + k}. {item}"
                for k, item in enumerate(block.get("items", []))
            ]
        return [f"- {item}" for item in block.get("items", [])]
    if block_type == "table":
        from pipeline.matematica.vocabulario_de_fala import (
            texto_com_numeros_por_extenso,
        )

        from pipeline.matematica.verbalizador_de_simbolos import (
            verbalizar_celula,
        )

        rows_faladas = [
            [verbalizar_celula(str(c)) for c in row]
            for row in (block.get("rows") or [])
        ]
        linhas = [
            texto_com_numeros_por_extenso(linha)
            for linha in _linearizar_tabela(rows_faladas)
        ]
        resumo = str(block.get("summary") or "").strip()
        if resumo:
            linhas.insert(0, f"Como ler: {resumo}")
        metadata = block.get("metadata") or {}
        if metadata.get("source_visual_type") == "chart":
            linhas.insert(0, "Dados extraidos de um grafico.")
        return linhas
    if block_type == "image":
        if block.get("decorative"):
            return []
        alt = (block.get("alt_text") or block.get("text") or "").strip()
        longa = (block.get("long_description") or "").strip()
        if not longa:
            return [alt] if alt else []
        if not alt or longa.lower().startswith(alt.lower()[:40]):
            return [longa]
        return [alt, longa]
    if block_type == "math":
        return [block.get("speech_pt_br") or block.get("text", "")]
    if block_type in {"details", "note", "warning", "quote"}:
        return [block.get("text", "")]
    return [block.get("text", "")]
