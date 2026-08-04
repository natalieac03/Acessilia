"""Assinatura estrutural da arvore, para comparar formulas.

Duas formulas so sao consideradas iguais se a ARVORE for igual.
Layout parecido nao basta: a formula da velocidade media e a da
aceleracao media tem exatamente a mesma cara (fracao com delta em cima
e embaixo) e significam coisas diferentes.

Isso veio de um caso real — a formula da aceleracao sumiu de um
material, trocada por "o mesmo elemento visual aparece novamente",
porque a deduplicacao comparava aparencia. Hash de imagem e bbox nao
servem para declarar equivalencia.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class AssinaturaSimbolica:

    symbols: set[str] = field(default_factory=set)
    numbers: set[str] = field(default_factory=set)
    operators: set[str] = field(default_factory=set)

    def __sub__(self, outra: "AssinaturaSimbolica") -> "AssinaturaSimbolica":
        return AssinaturaSimbolica(
            symbols=self.symbols - outra.symbols,
            numbers=self.numbers - outra.numbers,
            operators=self.operators - outra.operators,
        )

    def __bool__(self) -> bool:
        return bool(self.symbols or self.numbers or self.operators)

    def to_dict(self) -> dict:
        return {
            "symbols": sorted(self.symbols),
            "numbers": sorted(self.numbers),
            "operators": sorted(self.operators),
        }

    def descrever(self) -> str:
        partes = []
        if self.symbols:
            partes.append("simbolos: " + ", ".join(sorted(self.symbols)))
        if self.numbers:
            partes.append("numeros: " + ", ".join(sorted(self.numbers)))
        if self.operators:
            partes.append("operadores: " + ", ".join(sorted(self.operators)))
        return "; ".join(partes)


_EQUALS, _POWER, _SUBTRACT, _ADD = "equals", "power", "subtract", "add"
_MULTIPLY, _DIVIDE, _SQRT, _PLUSMINUS = "multiply", "divide", "sqrt", "plusminus"
_NEGATE, _SUBSCRIPT, _GROUP = "negate", "subscript", "group"
_GEQ, _LEQ, _NEQ, _GT, _LT = "geq", "leq", "neq", "gt", "lt"
_FUNCAO = "function"

_GREGAS_NOMES = {
    "Δ": "Delta", "∆": "Delta", "δ": "delta", "π": "pi", "α": "alpha",
    "β": "beta", "γ": "gamma", "θ": "theta", "λ": "lambda", "μ": "mu",
    "σ": "sigma", "ω": "omega", "Σ": "Sigma", "Ω": "Omega", "Φ": "Phi",
}
_SOBRESCRITOS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUBSCRITOS = "₀₁₂₃₄₅₆₇₈₉"
_INDICE_PARA_DIGITO = {
    **{c: str(i) for i, c in enumerate(_SOBRESCRITOS)},
    **{c: str(i) for i, c in enumerate(_SUBSCRITOS)},
}


def assinatura_da_origem(texto: str) -> AssinaturaSimbolica:
    fonte = texto or ""
    assinatura = AssinaturaSimbolica()

    for simbolo, nome in _GREGAS_NOMES.items():
        if simbolo in fonte:
            assinatura.symbols.add(nome)
    fonte_sem_grega = fonte
    for simbolo in _GREGAS_NOMES:
        fonte_sem_grega = fonte_sem_grega.replace(simbolo, " ")

    sem_conector = re.sub(r"\b(?:e|ou)\b", " ", fonte_sem_grega,
                          flags=re.IGNORECASE)
    sem_funcao = re.sub(
        r"\b(?:sen|sin|cos|tan|tg|cot|sec|csc|log|ln|exp|lim|max|min|det|"
        r"mod|arcsen|arcsin|arccos|arctan|senh|cosh|tanh)\b",
        " ", sem_conector, flags=re.IGNORECASE,
    )
    if sem_funcao != sem_conector:
        assinatura.operators.add(_FUNCAO)
    for letra in re.findall(r"[A-Za-z]", sem_funcao):
        assinatura.symbols.add(letra)

    for numero in re.findall(r"\d+", fonte_sem_grega):
        assinatura.numbers.add(numero)
    for caractere in fonte:
        if caractere in _INDICE_PARA_DIGITO:
            assinatura.numbers.add(_INDICE_PARA_DIGITO[caractere])

    if "=" in fonte:
        assinatura.operators.add(_EQUALS)
    if "≥" in fonte:
        assinatura.operators.add(_GEQ)
    if "≤" in fonte:
        assinatura.operators.add(_LEQ)
    if "≠" in fonte:
        assinatura.operators.add(_NEQ)
    if any(c in fonte for c in _SOBRESCRITOS) or "^" in fonte:
        assinatura.operators.add(_POWER)
    if any(c in fonte for c in _SUBSCRITOS) or "_" in fonte:
        assinatura.operators.add(_SUBSCRIPT)
    if "√" in fonte or r"\sqrt" in fonte:
        assinatura.operators.add(_SQRT)
    if "±" in fonte or r"\pm" in fonte:
        assinatura.operators.add(_PLUSMINUS)
    if "/" in fonte or r"\frac" in fonte:
        assinatura.operators.add(_DIVIDE)
    if "+" in fonte:
        assinatura.operators.add(_ADD)
    if re.search(r"[-−–]", fonte):
        assinatura.operators.add(_SUBTRACT)
    if re.search(r"\d\s*[A-Za-z]|[A-Za-z]\s*\(", fonte_sem_grega):
        assinatura.operators.add(_MULTIPLY)
    if "(" in fonte:
        assinatura.operators.add(_GROUP)
    return assinatura


def assinatura_da_ast(ast) -> AssinaturaSimbolica:
    from pipeline.matematica.arvore_matematica import (
        Add,
        Divide,
        Group,
        Integer,
        Multiply,
        Numero,
        PlusMinus,
        Power,
        Relation,
        Sqrt,
        Subscript,
        Subtract,
        Symbol,
        UnaryMinus,
    )

    assinatura = AssinaturaSimbolica()
    if ast is None:
        return assinatura

    _RELACAO_PARA_OPERADOR = {
        "=": _EQUALS, ">=": _GEQ, "<=": _LEQ, "!=": _NEQ, ">": _GT, "<": _LT,
    }
    from pipeline.matematica.arvore_matematica import Connector, Function

    for no in ast.percorrer():
        if isinstance(no, Symbol):
            assinatura.symbols.add(no.nome)
        elif isinstance(no, Function):
            if len(no.nome) == 1:
                assinatura.symbols.add(no.nome)
            else:
                assinatura.operators.add(_FUNCAO)
        elif isinstance(no, Integer):
            assinatura.numbers.add(str(no.valor))
        elif isinstance(no, Numero):
            assinatura.numbers.add(no.texto)
        elif isinstance(no, Power):
            assinatura.operators.add(_POWER)
        elif isinstance(no, Subscript):
            assinatura.operators.add(_SUBSCRIPT)
        elif isinstance(no, Sqrt):
            assinatura.operators.add(_SQRT)
        elif isinstance(no, PlusMinus):
            assinatura.operators.add(_PLUSMINUS)
        elif isinstance(no, Divide):
            assinatura.operators.add(_DIVIDE)
        elif isinstance(no, Add):
            assinatura.operators.add(_ADD)
        elif isinstance(no, Subtract):
            assinatura.operators.add(_SUBTRACT)
        elif isinstance(no, UnaryMinus):
            assinatura.operators.add(_NEGATE)
        elif isinstance(no, Multiply):
            assinatura.operators.add(_MULTIPLY)
        elif isinstance(no, Group):
            assinatura.operators.add(_GROUP)
        elif isinstance(no, Relation):
            assinatura.operators.add(
                _RELACAO_PARA_OPERADOR.get(no.operador, _EQUALS)
            )
    return assinatura


_REALIZACAO_NA_FALA = {
    _EQUALS: ("igual a",),
    _GEQ: ("maior ou igual",),
    _LEQ: ("menor ou igual",),
    _NEQ: ("diferente de",),
    _GT: ("maior que",),
    _LT: ("menor que",),
    _POWER: ("ao quadrado", "ao cubo", "elevado a"),
    _SQRT: ("raiz quadrada",),
    _PLUSMINUS: ("mais ou menos",),
    _DIVIDE: ("sobre", "fracao", "dividido por", "numerador"),
    _ADD: ("mais",),
    _SUBTRACT: ("menos",),
    _NEGATE: ("menos", "oposto de"),
    _MULTIPLY: ("vezes", "produto de"),
    _GROUP: ("parenteses",),
    _SUBSCRIPT: ("indice",),
    _FUNCAO: ("seno", "cosseno", "tangente", "logaritmo", "exponencial",
              "limite", "determinante", " de "),
}

_NUMERO_FALADO = {
    "0": "zero", "1": "um", "2": "dois", "3": "tres", "4": "quatro",
    "5": "cinco", "6": "seis", "7": "sete", "8": "oito", "9": "nove",
    "10": "dez", "11": "onze", "12": "doze", "13": "treze",
    "14": "quatorze", "15": "quinze", "20": "vinte", "30": "trinta",
    "100": "cem",
}
def _variaveis_faladas_sem_acento() -> dict[str, tuple[str, ...]]:
    from pipeline.matematica.vocabulario_de_fala import LETRAS_SOLETRADAS

    def _sa(texto: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", texto)
            if unicodedata.category(c) != "Mn"
        )

    return {
        letra: (_sa(nome), letra)
        for letra, nome in LETRAS_SOLETRADAS.items()
    }


_VARIAVEL_FALADA = _variaveis_faladas_sem_acento()


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def extrair_semantica_da_fala(speech_pt_br: str) -> AssinaturaSimbolica:
    fala = _sem_acento(speech_pt_br)
    assinatura = AssinaturaSimbolica()
    if not fala:
        return assinatura

    palavras = set(re.findall(r"[a-z]+", fala))

    for nome in set(_GREGAS_NOMES.values()):
        if _sem_acento(nome) in fala:
            assinatura.symbols.add(nome)

    for letra, formas in _VARIAVEL_FALADA.items():
        if any(f in palavras for f in formas):
            assinatura.symbols.add(letra)
    for letra in re.findall(r"\b([a-z])\b", fala):
        if letra not in {"a", "e", "o"}:
            assinatura.symbols.add(letra)
        elif letra == "a" and re.search(
            r"vezes a\b|de a\b|coeficiente a\b|\ba vezes\b|\ba ao\b", fala
        ):
            assinatura.symbols.add("a")

    for digito, nome in _NUMERO_FALADO.items():
        if nome in palavras:
            assinatura.numbers.add(digito)
    for numero in re.findall(r"\d+", fala):
        assinatura.numbers.add(numero)

    if "ao quadrado" in fala:
        assinatura.numbers.add("2")
    if "ao cubo" in fala:
        assinatura.numbers.add("3")

    for operador, formas in _REALIZACAO_NA_FALA.items():
        if any(_sem_acento(f) in fala for f in formas):
            assinatura.operators.add(operador)
    return assinatura


def comparar_assinaturas(
    origem: str, ast, speech_pt_br: str,
) -> dict:
    assinatura_origem = assinatura_da_origem(origem)
    assinatura_arvore = assinatura_da_ast(ast)
    assinatura_fala = extrair_semantica_da_fala(speech_pt_br)

    equivalentes = AssinaturaSimbolica(operators=set())
    if _NEGATE in assinatura_arvore.operators:
        equivalentes.operators.add(_SUBTRACT)
    if _MULTIPLY in assinatura_arvore.operators:
        equivalentes.operators.add(_MULTIPLY)
    try:
        from pipeline.matematica.arvore_matematica import Function

        if ast is not None and any(
            isinstance(n, Function) for n in ast.percorrer()
        ):
            equivalentes.operators.update({_GROUP, _MULTIPLY})
    except Exception:
        pass

    falta_na_ast = assinatura_origem - assinatura_arvore - equivalentes
    tolerado_na_fala = AssinaturaSimbolica(operators={_GROUP, _SUBSCRIPT})
    falta_na_fala = assinatura_arvore - assinatura_fala - tolerado_na_fala

    return {
        "origem": assinatura_origem.to_dict(),
        "ast": assinatura_arvore.to_dict(),
        "fala": assinatura_fala.to_dict(),
        "falta_na_ast": falta_na_ast,
        "falta_na_fala": falta_na_fala,
    }


def assinatura_estrutural(no) -> tuple:
    from pipeline.matematica.arvore_matematica import (
        Add,
        Cardinalidade,
        ConjuntoLiteral,
        ConjuntoPorPropriedade,
        Divide,
        Function,
        Group,
        Integer,
        Limite,
        Multiply,
        NegacaoLogica,
        Numero,
        OperacaoDeConjuntos,
        OperacaoLogicaBinaria,
        PlusMinus,
        Power,
        Quantificador,
        Relation,
        Sqrt,
        Subscript,
        Subtract,
        Symbol,
        UnaryMinus,
        ValorAbsoluto,
    )

    if no is None:
        return ("vazio",)
    _a = assinatura_estrutural
    if isinstance(no, Symbol):
        return ("simbolo", no.nome)
    if isinstance(no, Integer):
        return ("inteiro", no.valor)
    if isinstance(no, Numero):
        return ("numero", str(no.valor))
    if isinstance(no, Group):
        return ("grupo", _a(no.conteudo))
    if isinstance(no, Power):
        return ("potencia", _a(no.base), _a(no.expoente))
    if isinstance(no, Subscript):
        return ("subscrito", _a(no.base), _a(no.indice))
    if isinstance(no, Sqrt):
        return ("raiz",
                _a(no.indice) if no.indice is not None else 2,
                _a(no.radicando))
    if isinstance(no, Quantificador):
        return ("quantificador", no.especie, _a(no.variavel),
                _a(no.dominio), _a(no.corpo))
    if isinstance(no, OperacaoDeConjuntos):
        return ("operacao_de_conjuntos", tuple(no.operadores),
                tuple(_a(o) for o in no.operandos))
    if isinstance(no, OperacaoLogicaBinaria):
        return ("operacao_logica", no.operador,
                _a(no.esquerda), _a(no.direita))
    if isinstance(no, NegacaoLogica):
        return ("negacao", _a(no.operando))
    if isinstance(no, Limite):
        return ("limite", _a(no.variavel), _a(no.alvo), _a(no.corpo))
    if isinstance(no, ConjuntoLiteral):
        return ("conjunto_literal", tuple(_a(i) for i in no.itens))
    if isinstance(no, ConjuntoPorPropriedade):
        return ("conjunto_por_propriedade", _a(no.variavel),
                _a(no.dominio), _a(no.predicado))
    if isinstance(no, (ValorAbsoluto, Cardinalidade)):
        rotulo = ("cardinalidade" if isinstance(no, Cardinalidade)
                  else "valor_absoluto")
        return (rotulo, _a(no.expressao))
    if isinstance(no, Function):
        return ("funcao", no.nome,
                _a(no.indice) if no.indice is not None else None,
                tuple(_a(argumento) for argumento in no.argumentos))
    if isinstance(no, Relation):
        return ("relacao", tuple(no.operadores or [no.operador]),
                tuple(_a(o) for o in no.operandos))
    if isinstance(no, Add):
        return ("soma", tuple(_a(t) for t in no.termos))
    if isinstance(no, Subtract):
        return ("subtracao", _a(no.esquerda), _a(no.direita))
    if isinstance(no, Multiply):
        return ("produto", tuple(_a(f) for f in no.fatores))
    if isinstance(no, Divide):
        return ("fracao", _a(no.numerador), _a(no.denominador))
    if isinstance(no, UnaryMinus):
        return ("menos_unario", _a(no.operando))
    if isinstance(no, PlusMinus):
        return ("mais_ou_menos",
                _a(getattr(no, "esquerda", None)), _a(no.operando))
    return (type(no).__name__.lower(),
            tuple(assinatura_estrutural(f) for f in no.filhos()))


def sao_formulas_equivalentes(ast_a, ast_b) -> bool:
    if ast_a is None or ast_b is None:
        return False
    return (
        assinatura_estrutural(ast_a) == assinatura_estrutural(ast_b)
    )
