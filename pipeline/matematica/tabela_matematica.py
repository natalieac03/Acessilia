"""Processa a tabela em dois niveis: a estrutura e a celula.

A grade tabular e uma coisa; o conteudo misto de cada celula e outra.
Tratar celula como texto comum foi o que produziu as falhas de leitura
em materiais com tabela.

A funcao que processa uma celula recebe os IRMAOS da mesma linha, nao
so a celula isolada: o contexto da linha e evidencia de alta qualidade,
porque celulas vizinhas se validam mutuamente.
"""

from __future__ import annotations

import re
import unicodedata

from pipeline.matematica.cobertura_matematica import ValidationIssue
from pipeline.matematica.nos_matematicos import (
    MathNode,
    MixedTableCell,
    TextNode,
    construir_no_matematico,
)


def construir_contexto_da_linha(
    headers: list[str], sibling_cells: list[str]
) -> str:
    partes = [h.strip() for h in (headers or []) if h and h.strip()]
    partes += [c.strip() for c in (sibling_cells or []) if c and c.strip()]
    return " · ".join(partes)


def processar_celula(
    cell_text: str,
    row_index: int,
    col_index: int,
    headers: list[str] | None = None,
    sibling_cells: list[str] | None = None,
    geometria=None,
    modo_fala: str = "estrutural",
) -> MixedTableCell:
    from pipeline.matematica.evidencia_matematica import RegionContext
    from pipeline.matematica.matematica_inline import (
        detectar_candidatos_matematicos,
        segmentar_bloco_misto,
    )

    contexto_linha = construir_contexto_da_linha(headers, sibling_cells)
    contexto = RegionContext(
        tipo_regiao="table",
        e_celula=True,
        e_cabecalho=(row_index == 0),
        texto_vizinho=contexto_linha,
    )

    candidatos = detectar_candidatos_matematicos(cell_text, geometria, contexto)
    resultado = segmentar_bloco_misto(cell_text, candidatos)

    filhos: list = []
    if resultado.aceita:
        for segmento in resultado.segments:
            if segmento.type == "text":
                filhos.append(TextNode(source_text=segmento.source_text))
            else:
                filhos.append(construir_no_matematico(
                    segmento.source_text, geometria, segmento.bbox, modo_fala
                ))
    else:
        filhos = [TextNode(source_text=cell_text)]

    celula = MixedTableCell(
        row=row_index, column=col_index, headers=list(headers or []),
        children=filhos,
    )
    if celula.source_text != cell_text:
        return MixedTableCell(
            row=row_index, column=col_index, headers=list(headers or []),
            children=[TextNode(source_text=cell_text)],
        )

    if contexto_linha:
        for no in celula.nos_matematicos():
            problemas = validar_celula_contra_contexto(no, contexto_linha)
            if problemas:
                no.validation_issues = list(no.validation_issues) + [
                    p.to_dict() for p in problemas
                ]
                no.review_status = "needs_review"
    return celula


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


_REGRAS_DE_CONTEXTO = (
    (("discriminante",), ("delta",),
     "o contexto identifica o discriminante; a fala precisa dizer 'delta'"),
    (("oposto do coeficiente", "oposto de"), ("menos", "oposto"),
     "o contexto fala do oposto; o sinal de menos nao pode desaparecer"),
    (("usando +", "uma usando", "mais ou menos"), ("mais ou menos",),
     "o contexto descreve as duas raizes; a fala precisa dizer "
     "'mais ou menos'"),
    (("raiz quadrada do discriminante", "raiz quadrada de delta"),
     ("raiz quadrada",),
     "o contexto confirma a raiz; o radicando precisa ser falado"),
    (("duas vezes o coeficiente", "dobro do coeficiente"), ("vezes", "produto"),
     "o contexto confirma multiplicacao; a leitura como ordinal e "
     "incorreta"),
    (("possiveis solucoes", "as duas raizes", "solucoes da equacao"),
     ("um", "dois"),
     "o contexto fala de duas solucoes indexadas; os indices nao podem "
     "ser descartados"),
)

_ORDINAIS_PROIBIDOS = ("segunda", "segundo", "primeira", "primeiro",
                       "terceira", "terceiro")


def validar_celula_contra_contexto(
    no: MathNode, contexto_linha: str
) -> list[ValidationIssue]:
    fala = _sem_acento(no.speech_pt_br)
    contexto = _sem_acento(contexto_linha)
    issues: list[ValidationIssue] = []

    for pistas, exigidos, mensagem in _REGRAS_DE_CONTEXTO:
        if not any(_sem_acento(p) in contexto for p in pistas):
            continue
        if any(_sem_acento(e) in fala for e in exigidos):
            continue
        issues.append(ValidationIssue(
            check="validar_celula_contra_contexto", severity="BLOCKER",
            message=mensagem,
            how_to_fix=("reinterpretar a celula usando a descricao da "
                        "propria linha como evidencia"),
            evidencia=f"celula: {no.speech_pt_br!r} | linha: {contexto_linha[:60]!r}",
        ))

    for ordinal in _ORDINAIS_PROIBIDOS:
        if ordinal in fala and any(
            _sem_acento(p) in contexto
            for p in ("coeficiente", "componente", "formula", "expressao")
        ):
            issues.append(ValidationIssue(
                check="validar_celula_contra_contexto", severity="BLOCKER",
                message=(f"a fala da celula contem o ordinal '{ordinal}' num "
                         "contexto matematico"),
                how_to_fix="a fala deve vir do planejador, nao do texto bruto",
                evidencia=no.speech_pt_br[:60],
            ))
            break
    return issues


def falar_celula(celula: MixedTableCell) -> str:
    partes: list[str] = []
    for filho in celula.children:
        if isinstance(filho, MathNode):
            partes.append(filho.speech_pt_br or filho.source_text)
        else:
            texto = filho.source_text.strip()
            if texto:
                partes.append(texto)
    return re.sub(r"\s{2,}", " ", " ".join(partes)).strip()


def falar_linha(
    celulas: list[MixedTableCell], headers: list[str] | None = None,
    numero_da_linha: int | None = None,
) -> str:
    linhas: list[str] = []
    if numero_da_linha is not None:
        linhas.append(f"Linha {numero_da_linha}.")
    rotulos = headers or (celulas[0].headers if celulas else [])
    for indice, celula in enumerate(celulas):
        conteudo = falar_celula(celula)
        if not conteudo:
            continue
        rotulo = rotulos[indice] if indice < len(rotulos) else ""
        linhas.append(f"{rotulo}: {conteudo}." if rotulo else f"{conteudo}.")
    return " ".join(linhas)


def falar_tabela(
    linhas: list[list[MixedTableCell]], headers: list[str] | None = None,
    primeira_linha_e_cabecalho: bool = True,
) -> str:
    if not linhas:
        return ""
    rotulos = list(headers or [])
    inicio = 0
    if not rotulos and primeira_linha_e_cabecalho:
        rotulos = [falar_celula(c) for c in linhas[0]]
        inicio = 1

    partes: list[str] = []
    if rotulos:
        partes.append("Tabela com as colunas: " + ", ".join(rotulos) + ".")
    for deslocamento, celulas in enumerate(linhas[inicio:], start=inicio + 1):
        partes.append(falar_linha(celulas, rotulos, numero_da_linha=deslocamento))
    return "\n".join(partes)


def validar_tabela(
    linhas_origem: list[list[str]],
    linhas_processadas: list[list[MixedTableCell]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if len(linhas_origem) != len(linhas_processadas):
        issues.append(ValidationIssue(
            check="validar_tabela", severity="BLOCKER",
            message=(f"a tabela tinha {len(linhas_origem)} linha(s) e o "
                     f"processamento produziu {len(linhas_processadas)}"),
            how_to_fix="reprocessar a tabela sem descartar linhas",
        ))
    for indice, (origem, processada) in enumerate(
        zip(linhas_origem, linhas_processadas)
    ):
        if len(origem) != len(processada):
            issues.append(ValidationIssue(
                check="validar_tabela", severity="BLOCKER",
                message=(f"a linha {indice} tinha {len(origem)} celula(s) e "
                         f"produziu {len(processada)}"),
                how_to_fix="conferir a extracao das celulas desta linha",
            ))

    for indice_linha, processada in enumerate(linhas_processadas):
        origem = (linhas_origem[indice_linha]
                  if indice_linha < len(linhas_origem) else [])
        for indice_coluna, celula in enumerate(processada):
            if celula.row != indice_linha or celula.column != indice_coluna:
                issues.append(ValidationIssue(
                    check="validar_tabela", severity="ERROR",
                    message=(f"celula em ({indice_linha},{indice_coluna}) "
                             f"registra posicao ({celula.row},{celula.column})"),
                    how_to_fix="preservar row/column ao construir a celula",
                ))
            if indice_coluna < len(origem):
                if celula.source_text != origem[indice_coluna]:
                    issues.append(ValidationIssue(
                        check="validar_tabela", severity="BLOCKER",
                        message=(f"a celula ({indice_linha},{indice_coluna}) "
                                 "nao reproduz o texto de origem"),
                        how_to_fix="a segmentacao da celula perdeu conteudo",
                        evidencia=f"{origem[indice_coluna]!r} -> "
                                  f"{celula.source_text!r}",
                    ))
            if indice_coluna == 0 and indice_linha > 0:
                bruto = (origem[0] if origem else "").strip()
                if bruto and not celula.source_text.strip():
                    issues.append(ValidationIssue(
                        check="validar_tabela", severity="BLOCKER",
                        message=(f"a primeira coluna da linha {indice_linha} "
                                 "foi descartada como decorativa"),
                        how_to_fix=("simbolos da coluna de identificacao sao "
                                    "conteudo, nao decoracao"),
                        evidencia=bruto[:40],
                    ))

    for indice_linha, processada in enumerate(linhas_processadas):
        if indice_linha == 0 or len(processada) < 2:
            continue
        primeira, *resto = processada
        contexto = construir_contexto_da_linha(
            primeira.headers, [falar_celula(c) for c in resto]
        )
        for no in primeira.nos_matematicos():
            issues.extend(validar_celula_contra_contexto(no, contexto))

    return issues


def validar_derivacao_unica(
    celulas: list[MixedTableCell], texto_txt: str = "", texto_mp3: str = "",
) -> list[ValidationIssue]:
    if not texto_txt or not texto_mp3:
        return []
    def _normalizar(texto: str) -> str:
        return re.sub(r"\s+", " ", texto or "").strip().lower()

    if _normalizar(texto_txt) != _normalizar(texto_mp3):
        return [ValidationIssue(
            check="validar_derivacao_unica", severity="BLOCKER",
            message=("o TXT e o MP3 da tabela divergem: uma das saidas nao "
                     "foi derivada dos mesmos nos"),
            how_to_fix=("os dois formatos devem ler o mesmo "
                        "MixedTableCell/MathNode"),
            evidencia=f"txt: {texto_txt[:40]!r} | mp3: {texto_mp3[:40]!r}",
        )]
    return []


def processar_tabela(
    linhas: list[list[str]], headers: list[str] | None = None,
    geometria=None, modo_fala: str = "estrutural",
) -> tuple[list[list[MixedTableCell]], list[ValidationIssue]]:
    rotulos = list(headers or (linhas[0] if linhas else []))
    processadas: list[list[MixedTableCell]] = []

    for indice_linha, linha in enumerate(linhas):
        celulas: list[MixedTableCell] = []
        for indice_coluna, texto in enumerate(linha):
            irmas = [c for i, c in enumerate(linha) if i != indice_coluna]
            celulas.append(processar_celula(
                texto, indice_linha, indice_coluna, rotulos, irmas,
                geometria, modo_fala,
            ))
        processadas.append(celulas)

    return processadas, validar_tabela(linhas, processadas)
