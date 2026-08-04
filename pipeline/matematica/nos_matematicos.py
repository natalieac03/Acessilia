"""Modelo de dados dos nos de texto e de matematica.

Um paragrafo e uma SEQUENCIA de nos, nao uma string: MixedParagraph
com filhos TextNode e MathNode, e o mesmo vale para celula de tabela.

O MathNode guarda ao mesmo tempo o texto de origem, a arvore e as
serializacoes. A origem nunca e substituida — ela e a evidencia de que
a conversao esta certa e e o que o revisor humano precisa ver.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field

Caixa = tuple[float, float, float, float]

StatusRevisao = Literal["draft", "needs_review", "reviewed", "approved"]

_STATUS_NAO_PUBLICAVEIS = {"draft", "needs_review"}


class TextNode(BaseModel):
    type: Literal["text"] = "text"
    source_text: str


class MathNode(BaseModel):

    type: Literal["math"] = "math"
    source_text: str
    source_bbox: Caixa | None = None
    ast: dict = Field(default_factory=dict)
    latex: str = ""
    mathml: str = ""
    omml: str = ""
    speech_pt_br: str = ""
    speech_pt_br_concisa: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    uncertainties: list[str] = Field(default_factory=list)
    validation_issues: list[dict] = Field(default_factory=list)
    review_status: StatusRevisao = "draft"

    @property
    def bloqueia_publicacao(self) -> bool:
        if any(i.get("severity") == "BLOCKER" for i in self.validation_issues):
            return True
        return self.review_status in _STATUS_NAO_PUBLICAVEIS

    @property
    def completo(self) -> bool:
        return bool(self.ast and self.mathml and self.speech_pt_br)


InlineNode = Union[TextNode, MathNode]


class MixedParagraph(BaseModel):
    type: Literal["paragraph"] = "paragraph"
    children: list[InlineNode] = Field(default_factory=list)

    @property
    def source_text(self) -> str:
        return "".join(c.source_text for c in self.children)

    @property
    def tem_matematica(self) -> bool:
        return any(isinstance(c, MathNode) for c in self.children)

    def nos_matematicos(self) -> list[MathNode]:
        return [c for c in self.children if isinstance(c, MathNode)]

    @property
    def bloqueia_publicacao(self) -> bool:
        return any(n.bloqueia_publicacao for n in self.nos_matematicos())


class MixedTableCell(BaseModel):
    row: int
    column: int
    headers: list[str] = Field(default_factory=list)
    children: list[InlineNode] = Field(default_factory=list)

    @property
    def source_text(self) -> str:
        return "".join(c.source_text for c in self.children)

    def nos_matematicos(self) -> list[MathNode]:
        return [c for c in self.children if isinstance(c, MathNode)]

    @property
    def bloqueia_publicacao(self) -> bool:
        return any(n.bloqueia_publicacao for n in self.nos_matematicos())


def construir_no_matematico(
    source_text: str,
    geometria=None,
    bbox: Caixa | None = None,
    modo_fala: str = "estrutural",
) -> MathNode:
    from pipeline.matematica.arvore_matematica import construir_ast
    from pipeline.matematica.cobertura_matematica import validar_cobertura_simbolica
    from pipeline.matematica.serializacao_matematica import para_latex, para_mathml
    from pipeline.matematica.fala_matematica import gerar_fala_matematica

    resultado = construir_ast(source_text, geometria)
    latex = para_latex(resultado.ast)
    mathml = para_mathml(resultado.ast, latex)
    fala = gerar_fala_matematica(resultado.ast, modo=modo_fala)
    cobertura = validar_cobertura_simbolica(
        evidence=source_text, ast=resultado.ast, speech=fala,
        latex=latex, mathml=mathml,
        nao_consumidos=resultado.nao_consumidos,
    )

    incertezas = list(fala.avisos)
    if not resultado.completa:
        incertezas.append("o parser nao explicou a expressao inteira")

    if cobertura.bloqueia_publicacao or not resultado.completa:
        status: StatusRevisao = "needs_review"
    elif cobertura.aprovada:
        status = "reviewed"
    else:
        status = "draft"

    confianca = 0.95 if (cobertura.aprovada and resultado.completa) else (
        0.6 if not cobertura.bloqueia_publicacao else 0.3
    )

    return MathNode(
        source_text=source_text,
        source_bbox=bbox,
        ast=resultado.ast.to_dict(),
        latex=latex,
        mathml=mathml,
        speech_pt_br=fala.texto,
        confidence=confianca,
        uncertainties=incertezas,
        validation_issues=[i.to_dict() for i in cobertura.issues],
        review_status=status,
    )


def construir_paragrafo_misto(
    texto: str, geometria=None, modo_fala: str = "estrutural"
) -> MixedParagraph:
    from pipeline.matematica.matematica_inline import segmentar_bloco_misto

    resultado = segmentar_bloco_misto(texto)
    if not resultado.aceita:
        return MixedParagraph(children=[TextNode(source_text=texto)])

    filhos: list[InlineNode] = []
    for segmento in resultado.segments:
        if segmento.type == "text":
            filhos.append(TextNode(source_text=segmento.source_text))
            continue
        filhos.append(construir_no_matematico(
            segmento.source_text, geometria, segmento.bbox, modo_fala
        ))

    paragrafo = MixedParagraph(children=filhos)
    if paragrafo.source_text != texto:
        return MixedParagraph(children=[TextNode(source_text=texto)])
    return paragrafo


def construir_celula_mista(
    texto: str, row: int, column: int, headers: list[str] | None = None,
    geometria=None, modo_fala: str = "estrutural",
) -> MixedTableCell:
    from pipeline.matematica.evidencia_matematica import RegionContext
    from pipeline.matematica.matematica_inline import (
        detectar_candidatos_matematicos,
        segmentar_bloco_misto,
    )

    contexto = RegionContext(
        tipo_regiao="table", e_celula=True,
        e_cabecalho=(row == 0),
        texto_vizinho=" ".join(headers or []),
    )
    candidatos = detectar_candidatos_matematicos(texto, geometria, contexto)
    resultado = segmentar_bloco_misto(texto, candidatos)

    filhos: list[InlineNode] = []
    if resultado.aceita:
        for segmento in resultado.segments:
            if segmento.type == "text":
                filhos.append(TextNode(source_text=segmento.source_text))
            else:
                filhos.append(construir_no_matematico(
                    segmento.source_text, geometria, segmento.bbox, modo_fala
                ))
    else:
        filhos = [TextNode(source_text=texto)]

    celula = MixedTableCell(
        row=row, column=column, headers=list(headers or []), children=filhos
    )
    if celula.source_text != texto:
        return MixedTableCell(
            row=row, column=column, headers=list(headers or []),
            children=[TextNode(source_text=texto)],
        )
    return celula


def resumo_de_publicacao(nos: list[Any]) -> dict:
    matematicos: list[MathNode] = []
    for no in nos:
        if isinstance(no, MathNode):
            matematicos.append(no)
        elif hasattr(no, "nos_matematicos"):
            matematicos.extend(no.nos_matematicos())

    bloqueadores = [n for n in matematicos if n.bloqueia_publicacao]
    return {
        "total_matematico": len(matematicos),
        "bloqueadores": len(bloqueadores),
        "publicavel_como_final": not bloqueadores,
        "pendencias": [
            {
                "source_text": n.source_text,
                "review_status": n.review_status,
                "issues": [
                    i.get("message", "") for i in n.validation_issues
                    if i.get("severity") == "BLOCKER"
                ] or [
                    i.get("message", "") for i in n.validation_issues
                ] or n.uncertainties,
            }
            for n in bloqueadores
        ],
    }


class Blocker(Exception):
    pass


def _normalizar_espacos(texto: str) -> str:
    import re

    return re.sub(r"\s+", " ", texto or "").strip()


def validar_reconstrucao(original: str, segments: list) -> None:
    reconstruido = "".join(
        (s.get("source_text", "") if isinstance(s, dict)
         else getattr(s, "source_text", "")) for s in (segments or [])
    )
    if _normalizar_espacos(reconstruido) != _normalizar_espacos(original):
        raise Blocker(
            "Conteudo textual perdido na segmentacao "
            f"({len(original)} -> {len(reconstruido)} caracteres)"
        )


def remover_espacos_e_estilo(ast: dict | Any) -> dict:
    dados = ast if isinstance(ast, dict) else (
        ast.to_dict() if hasattr(ast, "to_dict") else {}
    )
    if not isinstance(dados, dict):
        return {}

    _ESTILO = {"source_notation", "bbox", "start", "end", "origem"}
    canonico: dict = {}
    for chave, valor in sorted(dados.items()):
        if chave in _ESTILO:
            continue
        if isinstance(valor, dict):
            canonico[chave] = remover_espacos_e_estilo(valor)
        elif isinstance(valor, list):
            canonico[chave] = [
                remover_espacos_e_estilo(v) if isinstance(v, dict) else v
                for v in valor
            ]
        elif isinstance(valor, str):
            limpo = _normalizar_espacos(valor)
            if limpo:
                canonico[chave] = limpo
        elif valor not in (None, [], {}):
            canonico[chave] = valor
    return canonico


def indexar_formula(ast) -> str:
    import hashlib
    import json

    try:
        canonico = remover_espacos_e_estilo(ast)
        serial = json.dumps(canonico, sort_keys=True, ensure_ascii=False)
    except Exception:
        serial = str(ast)
    return hashlib.sha1(serial.encode("utf-8")).hexdigest()[:16]


def indexar_ocorrencias(nos: list) -> dict[str, list]:
    indice: dict[str, list] = {}
    for no in nos or []:
        try:
            chave = indexar_formula(no.ast if hasattr(no, "ast") else no)
        except Exception:
            continue
        indice.setdefault(chave, []).append(no)
    return indice


def comparar_ocorrencias_equivalentes(nos: list) -> list[dict]:
    problemas: list[dict] = []
    for chave, ocorrencias in sorted(indexar_ocorrencias(nos).items()):
        if len(ocorrencias) < 2:
            continue
        latex = {(o.latex or "").strip() for o in ocorrencias if o.latex}
        mathml = {(o.mathml or "").strip() for o in ocorrencias if o.mathml}
        falas = {
            (o.speech_pt_br or "").strip()
            for o in ocorrencias if o.speech_pt_br
        }
        origens = [o.source_text for o in ocorrencias]

        if len(latex) > 1 or len(mathml) > 1:
            problemas.append({
                "severity": "BLOCKER",
                "hash": chave,
                "message": (f"{len(ocorrencias)} ocorrencias equivalentes com "
                            "serializacoes diferentes: uma das leituras esta "
                            "errada"),
                "ocorrencias": origens,
                "divergencia": sorted(latex)[:2] or sorted(mathml)[:2],
            })
        elif len(falas) > 1:
            problemas.append({
                "severity": "WARNING",
                "hash": chave,
                "message": (f"{len(ocorrencias)} ocorrencias equivalentes com "
                            "falas diferentes"),
                "ocorrencias": origens,
                "divergencia": sorted(falas)[:2],
            })
    return problemas
