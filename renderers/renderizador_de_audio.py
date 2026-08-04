"""Monta o roteiro de locucao a partir da fala ja aprovada.

Le a fala derivada da arvore e monta o roteiro com pausas entre
blocos, sabendo gerar SSML para controlar entonacao e ritmo.

Este renderizador NAO interpreta matematica: se a fala estiver errada,
o erro esta no planejador de fala. Corrigir aqui produziria duas
versoes divergentes da mesma expressao, que e exatamente o defeito que
a arquitetura de arvore unica eliminou.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_PAUSA_ENTRE_BLOCOS_MS = 400
_PAUSA_ENTRE_SECOES_MS = 700


def montar_roteiro(document: dict[str, Any]) -> list[dict]:
    roteiro: list[dict] = []

    def _bloco(tipo: str, texto: str, pausa: int, origem: str = ""):
        from pipeline.higienizador import remover_marcadores_tecnicos

        limpo = re.sub(
            r"\s{2,}", " ", remover_marcadores_tecnicos(texto)
        ).strip()
        if limpo:
            roteiro.append({"tipo": tipo, "texto": limpo,
                            "pausa_ms": pausa, "origem": origem})

    def _percorrer(secao: dict):
        if secao.get("title"):
            _bloco("titulo", secao["title"], _PAUSA_ENTRE_SECOES_MS)
        for bloco in secao.get("blocks", []) or []:
            tipo = bloco.get("type")
            if tipo == "math":
                _bloco("math",
                       bloco.get("speech_pt_br") or bloco.get("text", ""),
                       _PAUSA_ENTRE_BLOCOS_MS,
                       origem=bloco.get("source_text", ""))
            elif tipo == "image" and bloco.get("decorative"):
                continue
            elif tipo == "table":
                _bloco("tabela", _falar_tabela_do_bloco(bloco),
                       _PAUSA_ENTRE_BLOCOS_MS)
            else:
                _bloco(tipo or "paragrafo", bloco.get("text", ""),
                       _PAUSA_ENTRE_BLOCOS_MS)
            for filho in bloco.get("children", []) or []:
                if isinstance(filho, dict) and filho.get("type") == "math":
                    _bloco("math", filho.get("speech_pt_br", ""),
                           _PAUSA_ENTRE_BLOCOS_MS,
                           origem=filho.get("source_text", ""))
        for filha in secao.get("children", []) or []:
            _percorrer(filha)

    for secao in document.get("sections", []) or []:
        _percorrer(secao)
    return roteiro


def _falar_tabela_do_bloco(bloco: dict) -> str:
    linhas = bloco.get("rows") or []
    if not linhas:
        return ""
    cabecalhos = [str(c) for c in linhas[0]]
    registros = linhas[1:]
    partes = [
        f"Tabela com {len(registros)} registros. "
        "Colunas: " + ", ".join(cabecalhos) + "."
    ]
    for indice, linha in enumerate(registros, start=1):
        celulas = []
        for coluna, valor in enumerate(linha):
            rotulo = cabecalhos[coluna] if coluna < len(cabecalhos) else ""
            celulas.append(f"{rotulo}: {valor}." if rotulo else f"{valor}.")
        partes.append(f"Registro {indice}. " + " ".join(celulas))
    return " ".join(partes)


def gerar_ssml(document: dict[str, Any], titulo: str | None = None) -> str:
    from xml.sax.saxutils import escape

    idioma_doc = str(document.get("language") or "pt-BR")
    estrangeiros = _termos_estrangeiros(document, idioma_doc)

    partes = ["<speak>"]
    if titulo:
        partes.append(f"  {escape(titulo)}")
        partes.append(f'  <break time="{_PAUSA_ENTRE_SECOES_MS}ms"/>')
    for item in montar_roteiro(document):
        partes.append(f"  {_marcar_idiomas(item['texto'], estrangeiros)}")
        partes.append(f'  <break time="{item["pausa_ms"]}ms"/>')
    partes.append("</speak>")
    return "\n".join(partes)


def _termos_estrangeiros(
    document: dict[str, Any], idioma_doc: str
) -> dict[str, str]:
    mapa: dict[str, str] = {}
    try:
        from pipeline.localizacao import codigo_bcp47, precisa_marcar
    except Exception:
        return mapa

    def _varrer(blocos):
        for bloco in blocos or []:
            idiomas = bloco.get("cell_languages") or []
            linhas = bloco.get("rows") or []
            for i, linha in enumerate(linhas):
                for j, celula in enumerate(linha):
                    if i >= len(idiomas) or j >= len(idiomas[i]):
                        continue
                    idioma = idiomas[i][j]
                    texto = str(celula).strip()
                    if texto and precisa_marcar(idioma, idioma_doc):
                        mapa[texto] = codigo_bcp47(idioma)

    def _secao(secao):
        _varrer(secao.get("blocks"))
        for filha in secao.get("children") or []:
            _secao(filha)

    for secao in document.get("sections") or []:
        _secao(secao)
    _varrer(document.get("blocks"))
    return mapa


def _marcar_idiomas(texto: str, estrangeiros: dict[str, str]) -> str:
    from xml.sax.saxutils import escape

    if not estrangeiros:
        return escape(texto)

    import re as _re

    padrao = "|".join(
        _re.escape(t) for t in sorted(estrangeiros, key=len, reverse=True)
    )

    resultado: list[str] = []
    posicao = 0
    for achado in _re.finditer(rf"\b(?:{padrao})\b", texto):
        resultado.append(escape(texto[posicao:achado.start()]))
        termo = achado.group(0)
        codigo = estrangeiros.get(termo, "")
        if codigo:
            resultado.append(
                f'<lang xml:lang="{codigo}">{escape(termo)}</lang>'
            )
        else:
            resultado.append(escape(termo))
        posicao = achado.end()
    resultado.append(escape(texto[posicao:]))
    return "".join(resultado)


def gerar_roteiro_de_audio(document: dict[str, Any], output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    texto = "\n\n".join(item["texto"] for item in montar_roteiro(document))
    output_path.write_text(texto, encoding="utf-8")
    return output_path
