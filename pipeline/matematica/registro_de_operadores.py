"""Tabela unica dos operadores de conjunto, logica e quantificadores.

Cada operador aparece uma vez so, com tudo junto: forma LaTeX,
caractere Unicode, fala em portugues e precedencia.

Antes desta tabela a informacao estava espalhada entre tokenizador,
parser e serializadores, cada um com a sua lista — e as listas saiam de
sincronia. Era assim que "uniao" virava a letra "U" num lugar e
operador em outro.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EspecificacaoDeOperador:
    identificador: str
    formas_latex: tuple[str, ...]
    forma_unicode: str
    kind_de_token: str
    fala: str
    mathml: str
    precedencia: int = 50


OPERADORES_DE_CONJUNTOS: dict[str, EspecificacaoDeOperador] = {
    "∪": EspecificacaoDeOperador(
        identificador="uniao", formas_latex=(r"\cup",),
        forma_unicode="∪", kind_de_token="SET_OP",
        fala="união", mathml="∪", precedencia=40,
    ),
    "∩": EspecificacaoDeOperador(
        identificador="intersecao", formas_latex=(r"\cap",),
        forma_unicode="∩", kind_de_token="SET_OP",
        fala="interseção", mathml="∩", precedencia=45,
    ),
    "∖": EspecificacaoDeOperador(
        identificador="diferenca_de_conjuntos",
        formas_latex=(r"\setminus",),
        forma_unicode="∖", kind_de_token="SET_OP",
        fala="menos", mathml="∖", precedencia=40,
    ),
    "△": EspecificacaoDeOperador(
        identificador="diferenca_simetrica",
        formas_latex=(r"\triangle", r"\vartriangle"),
        forma_unicode="△", kind_de_token="SET_OP",
        fala="diferença simétrica", mathml="△", precedencia=40,
    ),
}

QUANTIFICADORES: dict[str, EspecificacaoDeOperador] = {
    "∀": EspecificacaoDeOperador(
        identificador="para_todo", formas_latex=(r"\forall",),
        forma_unicode="∀", kind_de_token="QUANTIFIER",
        fala="para todo", mathml="∀",
    ),
    "∃": EspecificacaoDeOperador(
        identificador="existe", formas_latex=(r"\exists",),
        forma_unicode="∃", kind_de_token="QUANTIFIER",
        fala="existe", mathml="∃",
    ),
    "∄": EspecificacaoDeOperador(
        identificador="nao_existe", formas_latex=(r"\nexists",),
        forma_unicode="∄", kind_de_token="QUANTIFIER",
        fala="não existe", mathml="∄",
    ),
    "∃!": EspecificacaoDeOperador(
        identificador="existe_unico", formas_latex=(r"\exists!",),
        forma_unicode="∃!", kind_de_token="QUANTIFIER",
        fala="existe exatamente um", mathml="∃!",
    ),
}

OPERADORES_LOGICOS: dict[str, EspecificacaoDeOperador] = {
    "¬": EspecificacaoDeOperador(
        identificador="negacao", formas_latex=(r"\neg", r"\lnot"),
        forma_unicode="¬", kind_de_token="LOGIC_NOT",
        fala="não", mathml="¬", precedencia=90,
    ),
    "∧": EspecificacaoDeOperador(
        identificador="e_logico", formas_latex=(r"\land", r"\wedge"),
        forma_unicode="∧", kind_de_token="LOGIC_OP",
        fala="e", mathml="∧", precedencia=30,
    ),
    "∨": EspecificacaoDeOperador(
        identificador="ou_logico", formas_latex=(r"\lor", r"\vee"),
        forma_unicode="∨", kind_de_token="LOGIC_OP",
        fala="ou", mathml="∨", precedencia=25,
    ),
    "⊕": EspecificacaoDeOperador(
        identificador="ou_exclusivo", formas_latex=(r"\oplus",),
        forma_unicode="⊕", kind_de_token="LOGIC_OP",
        fala="ou exclusivo", mathml="⊕", precedencia=25,
    ),
    "⇒": EspecificacaoDeOperador(
        identificador="implica",
        formas_latex=(r"\Rightarrow", r"\implies"),
        forma_unicode="⇒", kind_de_token="LOGIC_OP",
        fala="implica", mathml="⇒", precedencia=20,
    ),
    "⇔": EspecificacaoDeOperador(
        identificador="se_e_somente_se",
        formas_latex=(r"\Leftrightarrow", r"\iff"),
        forma_unicode="⇔", kind_de_token="LOGIC_OP",
        fala="se e somente se", mathml="⇔", precedencia=15,
    ),
    "↔": EspecificacaoDeOperador(
        identificador="se_e_somente_se",
        formas_latex=(r"\leftrightarrow",),
        forma_unicode="↔", kind_de_token="LOGIC_OP",
        fala="se e somente se", mathml="↔", precedencia=15,
    ),
}

BARRA = EspecificacaoDeOperador(
    identificador="barra_vertical", formas_latex=(r"\mid", r"\vert"),
    forma_unicode="|", kind_de_token="BARRA",
    fala="", mathml="|",
)

CONECTOR_DE_CORPO = {
    "para_todo": ",",
    "existe": "tal que",
    "existe_unico": "tal que",
    "nao_existe": "tal que",
}

SETAS: dict[str, EspecificacaoDeOperador] = {
    "→": EspecificacaoDeOperador(
        identificador="tende_a",
        formas_latex=(r"\to", r"\rightarrow", r"\longrightarrow"),
        forma_unicode="→", kind_de_token="ARROW",
        fala="tende a", mathml="→",
    ),
    "↦": EspecificacaoDeOperador(
        identificador="mapeia_para", formas_latex=(r"\mapsto",),
        forma_unicode="↦", kind_de_token="ARROW",
        fala="é levado em", mathml="↦",
    ),
}


def latex_para_unicode() -> dict[str, str]:
    mapa: dict[str, str] = {}
    for tabela in (OPERADORES_DE_CONJUNTOS, QUANTIFICADORES, SETAS,
                   OPERADORES_LOGICOS):
        for spec in tabela.values():
            for forma in spec.formas_latex:
                mapa[forma] = spec.forma_unicode
    for forma in BARRA.formas_latex:
        mapa[forma] = BARRA.forma_unicode
    return mapa


def kind_do_caractere(caractere: str) -> str | None:
    if caractere == BARRA.forma_unicode:
        return BARRA.kind_de_token
    for tabela in (OPERADORES_DE_CONJUNTOS, QUANTIFICADORES, SETAS,
                   OPERADORES_LOGICOS):
        if caractere in tabela:
            return tabela[caractere].kind_de_token
    return None


def fala_do_operador(caractere: str) -> str:
    for tabela in (OPERADORES_DE_CONJUNTOS, QUANTIFICADORES, SETAS,
                   OPERADORES_LOGICOS):
        if caractere in tabela:
            return tabela[caractere].fala
    return caractere


def latex_do_operador(caractere: str) -> str:
    for tabela in (OPERADORES_DE_CONJUNTOS, QUANTIFICADORES, SETAS,
                   OPERADORES_LOGICOS):
        if caractere in tabela:
            return tabela[caractere].formas_latex[0]
    return caractere


def precedencia_do_operador(caractere: str) -> int:
    spec = OPERADORES_DE_CONJUNTOS.get(caractere)
    return spec.precedencia if spec else 0
