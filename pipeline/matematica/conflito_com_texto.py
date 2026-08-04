"""Detecta divergencia entre a formula e a prosa que a descreve."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from pipeline.matematica.arvore_matematica import (
    Integer,
    NoAST,
    Numero,
    Power,
    Relation,
)


@dataclass
class ConflitoEntreFonteEFormula:
    tipo_de_conflito: str
    valor_da_formula: str
    valor_do_texto: str
    severidade: str = "BLOQUEADOR"
    caminho_na_arvore: str = ""
    evidencias: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "severity": self.severidade,
            "tipo": self.tipo_de_conflito,
            "valor_da_formula": self.valor_da_formula,
            "valor_do_texto": self.valor_do_texto,
            "evidencias": list(self.evidencias),
        }


_EXPOENTES_NOMEADOS = {
    "ao quadrado": 2,
    "ao cubo": 3,
}

_NUMEROS_POR_EXTENSO = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
    "nove": 9, "dez": 10, "onze": 11, "doze": 12, "vinte": 20,
    "trinta": 30, "cem": 100, "mil": 1000,
}


def _sem_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def _numero_do_texto(trecho: str) -> int | None:
    trecho = trecho.strip()
    if trecho.isdigit():
        return int(trecho)
    return _NUMEROS_POR_EXTENSO.get(trecho)


def _expoentes_da_arvore(ast: NoAST) -> list[int]:
    expoentes = []
    for no in ast.percorrer():
        if isinstance(no, Power):
            if isinstance(no.expoente, Integer):
                expoentes.append(no.expoente.valor)
            elif isinstance(no.expoente, Numero):
                try:
                    expoentes.append(int(no.expoente.valor))
                except (TypeError, ValueError):
                    pass
    return expoentes


def _resultados_da_arvore(ast: NoAST) -> list[int]:
    resultados = []
    for no in ast.percorrer():
        if isinstance(no, Relation) and "=" in (no.operadores or
                                                [no.operador]):
            ultimo = no.operandos[-1] if no.operandos else None
            if isinstance(ultimo, Integer):
                resultados.append(ultimo.valor)
    return resultados


def detectar_conflitos(
    texto_vizinho: str, ast: NoAST,
) -> list[ConflitoEntreFonteEFormula]:
    conflitos: list[ConflitoEntreFonteEFormula] = []
    if not texto_vizinho or ast is None:
        return conflitos
    texto = _sem_acentos(texto_vizinho)

    expoentes_ast = _expoentes_da_arvore(ast)
    afirmados: list[tuple[int, str]] = []
    for nome, valor in _EXPOENTES_NOMEADOS.items():
        if nome in texto:
            afirmados.append((valor, nome))
    for encontrado in re.finditer(
        r"elevad[oa] a (\w+)", texto
    ):
        valor = _numero_do_texto(encontrado.group(1))
        if valor is not None:
            afirmados.append((valor, encontrado.group(0)))
    for valor, evidencia in afirmados:
        if expoentes_ast and valor not in expoentes_ast:
            conflitos.append(ConflitoEntreFonteEFormula(
                tipo_de_conflito="expoente_divergente",
                valor_da_formula=", ".join(map(str, expoentes_ast)),
                valor_do_texto=str(valor),
                evidencias=[f"texto vizinho: {evidencia!r}"],
            ))

    resultados_ast = _resultados_da_arvore(ast)
    for encontrado in re.finditer(
        r"(?:e|é)\s+igual\s+a\s+(\w+)", texto
    ):
        valor = _numero_do_texto(encontrado.group(1))
        if valor is None:
            continue
        if not resultados_ast:
            conflitos.append(ConflitoEntreFonteEFormula(
                tipo_de_conflito="resultado_ausente_na_formula",
                valor_da_formula="(sem igualdade)",
                valor_do_texto=str(valor),
                evidencias=[f"texto vizinho: {encontrado.group(0)!r}"],
            ))
        elif valor not in resultados_ast:
            conflitos.append(ConflitoEntreFonteEFormula(
                tipo_de_conflito="resultado_divergente",
                valor_da_formula=", ".join(map(str, resultados_ast)),
                valor_do_texto=str(valor),
                evidencias=[f"texto vizinho: {encontrado.group(0)!r}"],
            ))
    return conflitos
