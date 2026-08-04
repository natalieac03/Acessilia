"""Verificacoes deterministicas de fidelidade matematica."""

from __future__ import annotations

import re
from collections import Counter
from xml.etree import ElementTree

_TOKEN_MATEMATICO = re.compile(r"\d+(?:[.,]\d+)?|[A-Za-z]+|[+\-*/=±<>≥≤]")

_IGNORAVEIS = {"\\", "left", "right", "cdot", "times", "frac", "sqrt",
               "displaystyle", "mathrm", "text", "quad", "qquad"}

_IDENTIFICADORES_MATEMATICOS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "sen", "tg", "cotg",
    "arcsin", "arccos", "arctan", "senh", "cosh", "tanh",
    "log", "ln", "lim", "exp", "sup", "inf", "max", "min", "int",
    "sum", "prod", "lim", "der", "grad", "div", "rot",
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta",
    "theta", "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron",
    "pi", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
    "varepsilon", "vartheta", "varphi", "varrho", "varsigma",
    "pm", "mp", "geq", "leq", "neq", "approx", "equiv", "propto",
    "infty", "partial", "nabla", "forall", "exists", "in", "notin",
    "subset", "supset", "cup", "cap", "emptyset", "therefore",
    "cdots", "ldots", "dots", "vdots", "ddots",
    "det", "dim", "ker", "rank", "tr", "mod", "gcd", "mdc", "mmc",
    "matrix", "pmatrix", "bmatrix", "vmatrix", "cases",
}


def _e_identificador_matematico(token: str) -> bool:
    if not token:
        return False
    if not token[0].isalpha():
        return True
    if len(token) <= 2:
        return True
    return token in _IDENTIFICADORES_MATEMATICOS


_PALAVRAS_CURTAS_DE_PROSA = {
    "da", "de", "do", "na", "no", "em", "ao", "as", "os", "um", "se",
    "ou", "e", "a", "o", "por", "com", "que",
}
_IGNORAVEIS = _IGNORAVEIS | _PALAVRAS_CURTAS_DE_PROSA


_EQUIVALENTES = {
    "±": "pm", "√": "sqrt", "Δ": "delta", "∆": "delta", "δ": "delta",
    "·": "cdot", "×": "cdot", "÷": "div", "≥": "geq", "≤": "leq",
    "≠": "neq", "π": "pi", "∑": "sum", "∫": "int", "≈": "approx",
    "/": "frac",
}
_INDICES_UNICODE = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5",
    "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
    "₆": "6", "₇": "7", "₈": "8", "₉": "9",
}


def _canonizar(texto: str) -> str:
    for simbolo, nome in _INDICES_UNICODE.items():
        texto = texto.replace(simbolo, nome)
    for simbolo, nome in _EQUIVALENTES.items():
        texto = texto.replace(simbolo, f" {nome} ")
    texto = re.sub(r"(?<=\d)\s+[xX]\s+(?=\d)", " cdot ", texto)
    return texto.replace("\\", " ")


def _tokens_relevantes(texto: str) -> Counter:
    achados = _TOKEN_MATEMATICO.findall(_canonizar(texto or ""))
    return Counter(
        t.lower() for t in achados
        if t.lower() not in _IGNORAVEIS
        and _e_identificador_matematico(t.lower())
    )


def verificar_cobertura(origem: str, saida: str) -> list[str]:
    if not origem or not saida:
        return []
    faltando = _tokens_relevantes(origem) - _tokens_relevantes(saida)
    problemas = []
    for token, quantas in sorted(faltando.items()):
        problemas.append(
            f"termo '{token}' presente na origem ({quantas}x a mais) "
            "desapareceu na saida"
        )
    return problemas


def _sem_namespace(tag: str) -> str:
    return tag.split("}")[-1]


def validar_arvore_mathml(mathml: str, latex: str = "") -> list[str]:
    if not mathml or not mathml.strip():
        return ["MathML ausente"]
    try:
        raiz = ElementTree.fromstring(mathml)
    except ElementTree.ParseError as erro:
        return [f"MathML nao e XML valido: {erro}"]
    if not _sem_namespace(raiz.tag).endswith("math"):
        return ["MathML nao tem <math> como raiz"]

    problemas: list[str] = []
    tags = [_sem_namespace(e.tag) for e in raiz.iter()]

    if "\\frac" in latex and "mfrac" not in tags:
        problemas.append("LaTeX tem \\frac mas o MathML nao tem <mfrac>")
    if "\\sqrt" in latex and not {"msqrt", "mroot"} & set(tags):
        problemas.append("LaTeX tem \\sqrt mas o MathML nao tem <msqrt>")
    if "mfrac" not in tags:
        for elemento in raiz.iter():
            if _sem_namespace(elemento.tag) == "mo" and (
                elemento.text or ""
            ).strip() in ("/", "&#x0002F;", "\u2044"):
                problemas.append(
                    "divisao representada como <mo>/</mo> em vez de "
                    "<mfrac> - o leitor de tela nao navega numerador e "
                    "denominador"
                )
                break
    for elemento in raiz.iter():
        if _sem_namespace(elemento.tag) != "msup":
            continue
        filhos = list(elemento)
        if not filhos:
            continue
        base = filhos[0]
        if _sem_namespace(base.tag) == "mo":
            conteudo = (base.text or "").strip()
            if conteudo in (")", "\u0029", "&#x00029;", "]"):
                problemas.append(
                    "expoente aplicado ao parentese de fechamento, nao ao "
                    "grupo: a base de <msup> deveria ser um <mrow>"
                )
                break
    return problemas


_PISTAS_DE_FALA = (
    (r"\\frac", ("fracao", "fração", "sobre", "dividido")),
    (r"\\sqrt", ("raiz",)),
    (r"\^", ("quadrado", "cubo", "potencia", "potência", "elevado",
             "ao quadrado")),
)


def verificar_coerencia_latex_leitura(latex: str, leitura: str) -> list[str]:
    if not latex or not leitura:
        return []
    alvo = leitura.lower()
    problemas = []
    for padrao, pistas in _PISTAS_DE_FALA:
        if re.search(padrao, latex) and not any(p in alvo for p in pistas):
            nome = padrao.replace("\\\\", "\\").strip("\\^")
            problemas.append(
                f"a leitura falada nao menciona a estrutura '{nome or 'potencia'}' "
                "presente no LaTeX"
            )
    return problemas


def verificar_preservacao_do_texto(original: str, segmentos: list[dict]) -> list[str]:
    recomposto = "".join(s.get("conteudo", "") for s in segmentos)
    if recomposto != original:
        return [
            "a segmentacao alterou o texto do bloco "
            f"({len(original)} -> {len(recomposto)} caracteres)"
        ]
    return []


def verificar_consistencia_ocorrencias(
    expressoes: list[tuple[str, str]],
) -> list[str]:
    por_origem: dict[str, set[str]] = {}
    for origem, latex in expressoes:
        chave = re.sub(r"\s+", "", (origem or "").lower())
        if not chave:
            continue
        por_origem.setdefault(chave, set()).add((latex or "").strip())

    problemas = []
    for chave, versoes in sorted(por_origem.items()):
        versoes = {v for v in versoes if v}
        if len(versoes) > 1:
            problemas.append(
                f"a expressao '{chave[:40]}' foi convertida de "
                f"{len(versoes)} formas diferentes: {sorted(versoes)[:3]}"
            )
    return problemas


def auditar_formula(
    origem: str, latex: str, mathml: str, leitura: str,
) -> dict:
    try:
        problemas: list[str] = []
        problemas += verificar_cobertura(origem, latex)
        problemas += validar_arvore_mathml(mathml, latex)
        problemas += verificar_coerencia_latex_leitura(latex, leitura)
        return {"aprovada": not problemas, "problemas": problemas}
    except Exception as erro:
        return {"aprovada": True, "problemas": [],
                "erro_interno": f"{type(erro).__name__}: {erro}"}
