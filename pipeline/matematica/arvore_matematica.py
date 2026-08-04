"""Tokeniza a expressao e monta a arvore (AST) — o nucleo do sistema.

Tudo o que sai depois (fala em portugues, MathML, OMML, LaTeX) nasce
desta arvore. Nenhum renderizador volta a olhar o texto original.

O tokenizador resolve as ambiguidades que um TTS erraria sozinho:
distingue o menos unario de "-b" da subtracao de "b^2 - 4ac", insere a
multiplicacao implicita de "4ac", prende o expoente ao "b" em "b^2" e
garante que um radical nunca fique sem radicando.

Quando o parser nao entende um trecho, ele cria um no Desconhecido com
o texto original — nunca inventa nem descarta em silencio. Quem decide
o que fazer com isso e o validador.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class NoAST:

    @property
    def tipo(self) -> str:
        return type(self).__name__

    def filhos(self) -> list["NoAST"]:
        return []

    def to_dict(self) -> dict[str, Any]:
        dados: dict[str, Any] = {"tipo": self.tipo}
        for chave, valor in self.__dict__.items():
            if isinstance(valor, NoAST):
                dados[chave] = valor.to_dict()
            elif isinstance(valor, list) and valor and isinstance(valor[0], NoAST):
                dados[chave] = [v.to_dict() for v in valor]
            else:
                dados[chave] = valor
        return dados

    def percorrer(self):
        yield self
        for filho in self.filhos():
            yield from filho.percorrer()


@dataclass
class Integer(NoAST):
    valor: int


@dataclass
class Numero(NoAST):

    texto: str


@dataclass
class Symbol(NoAST):
    nome: str


@dataclass
class Group(NoAST):

    conteudo: NoAST
    estrutural: bool = False

    def filhos(self):
        return [self.conteudo]


@dataclass
class UnaryMinus(NoAST):
    operando: NoAST

    def filhos(self):
        return [self.operando]


@dataclass
class PlusMinus(NoAST):

    operando: NoAST | None = None
    esquerda: NoAST | None = None

    @property
    def binaria(self) -> bool:
        return self.esquerda is not None

    def filhos(self):
        return [n for n in (self.esquerda, self.operando) if n]


@dataclass
class Power(NoAST):
    base: NoAST
    expoente: NoAST

    def filhos(self):
        return [self.base, self.expoente]


@dataclass
class Subscript(NoAST):
    base: NoAST
    indice: NoAST

    def filhos(self):
        return [self.base, self.indice]


@dataclass
class Sqrt(NoAST):

    radicando: NoAST
    indice: NoAST | None = None

    def filhos(self):
        if self.indice is None:
            return [self.radicando]
        return [self.radicando, self.indice]

    @property
    def grau_falado(self) -> int | None:
        if isinstance(self.indice, Integer):
            return self.indice.valor
        return None


@dataclass
class Add(NoAST):
    termos: list[NoAST] = field(default_factory=list)

    def filhos(self):
        return list(self.termos)


@dataclass
class Subtract(NoAST):
    left: NoAST
    right: NoAST

    def filhos(self):
        return [self.left, self.right]


@dataclass
class Multiply(NoAST):

    fatores: list[NoAST] = field(default_factory=list)
    source_notation: str = "implicit"

    @property
    def implicita(self) -> bool:
        return self.source_notation in ("implicit", "parentheses")

    def filhos(self):
        return list(self.fatores)


@dataclass
class Divide(NoAST):
    numerador: NoAST
    denominador: NoAST

    def filhos(self):
        return [self.numerador, self.denominador]


@dataclass
class Relation(NoAST):

    operador: str
    operandos: list[NoAST] = field(default_factory=list)
    operadores: list[str] = field(default_factory=list)

    def operador_em(self, indice: int) -> str:
        if 0 <= indice < len(self.operadores):
            return self.operadores[indice]
        return self.operador

    def filhos(self):
        return list(self.operandos)


@dataclass
class Connector(NoAST):

    texto: str


@dataclass
class TextMathSequence(NoAST):
    itens: list[NoAST] = field(default_factory=list)

    def filhos(self):
        return list(self.itens)


@dataclass
class Function(NoAST):

    nome: str
    argumentos: list[NoAST] = field(default_factory=list)
    indice: NoAST | None = None

    def filhos(self):
        filhos = list(self.argumentos)
        if self.indice is not None:
            filhos.append(self.indice)
        return filhos


@dataclass
class OperacaoDeConjuntos(NoAST):

    operandos: list[NoAST] = field(default_factory=list)
    operadores: list[str] = field(default_factory=list)

    def operador_em(self, indice: int) -> str:
        if 0 <= indice < len(self.operadores):
            return self.operadores[indice]
        return self.operadores[0] if self.operadores else "∪"

    def filhos(self):
        return list(self.operandos)


@dataclass
class ConjuntoLiteral(NoAST):

    itens: list[NoAST] = field(default_factory=list)

    def filhos(self):
        return list(self.itens)


@dataclass
class Quantificador(NoAST):

    especie: str
    variavel: NoAST
    dominio: NoAST | None = None
    corpo: NoAST | None = None

    def filhos(self):
        filhos = [self.variavel]
        if self.dominio is not None:
            filhos.append(self.dominio)
        if self.corpo is not None:
            filhos.append(self.corpo)
        return filhos


@dataclass
class Limite(NoAST):

    variavel: NoAST
    alvo: NoAST
    corpo: NoAST | None = None

    def filhos(self):
        filhos = [self.variavel, self.alvo]
        if self.corpo is not None:
            filhos.append(self.corpo)
        return filhos


@dataclass
class TextoLiteral(NoAST):

    texto: str

    def filhos(self):
        return []


@dataclass
class Quantia(NoAST):

    valor: NoAST
    unidade: str

    def filhos(self):
        return [self.valor]


@dataclass
class Reticencias(NoAST):

    def filhos(self):
        return []


@dataclass
class NegacaoLogica(NoAST):

    operando: NoAST

    def filhos(self):
        return [self.operando]


@dataclass
class OperacaoLogicaBinaria(NoAST):

    operador: str
    esquerda: NoAST
    direita: NoAST

    def filhos(self):
        return [self.esquerda, self.direita]


@dataclass
class ValorAbsoluto(NoAST):

    expressao: NoAST

    def filhos(self):
        return [self.expressao]


@dataclass
class Cardinalidade(NoAST):

    expressao: NoAST

    def filhos(self):
        return [self.expressao]


@dataclass
class ConjuntoPorPropriedade(NoAST):

    variavel: NoAST
    predicado: NoAST
    dominio: NoAST | None = None

    def filhos(self):
        filhos = [self.variavel]
        if self.dominio is not None:
            filhos.append(self.dominio)
        filhos.append(self.predicado)
        return filhos


@dataclass
class Desconhecido(NoAST):

    texto: str


MathAST = NoAST


KindToken = Literal[
    "NUMBER", "IDENT", "OPERATOR", "RELATION", "PLUS_MINUS", "RADICAL",
    "SUPERSCRIPT", "SUBSCRIPT", "UNARY_MINUS", "IMPLICIT_MULTIPLICATION",
    "LPAREN", "RPAREN", "CONNECTOR", "UNKNOWN",
    "SET_OP", "QUANTIFIER", "ARROW", "LBRACE", "RBRACE", "TAL_QUE",
    "LOGIC_NOT", "LOGIC_OP", "BARRA",
]


@dataclass
class Token:
    kind: str
    value: str
    start: int = 0
    end: int = 0
    attached_to: str | None = None
    operand: str | None = None
    operands: list[str] = field(default_factory=list)
    origem: str = "texto"

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], "")}


_SOBRESCRITOS_UNICODE = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
}
_SUBSCRITOS_UNICODE = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
}
_GREGAS = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "π": "pi", "ρ": "rho",
    "σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi",
    "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "Gamma", "Δ": "Delta", "∆": "Delta", "Θ": "Theta",
    "Λ": "Lambda", "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma",
    "Υ": "Upsilon", "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega",
}
_RADICAIS = {"√": None, "∛": "3", "∜": "4"}
_RELACOES = {
    "=": "=", "≥": ">=", "≤": "<=", "≠": "!=", "<": "<", ">": ">",
    "∈": "in", "∉": "notin",
    "⊂": "subset", "⊆": "subseteq", "⊃": "supset", "⊇": "supseteq",
}

_IDENTIFICADORES_INTEIROS = {
    "sin", "sen", "cos", "tan", "tg", "cot", "sec", "csc", "log", "ln",
    "exp", "lim", "max", "min", "det", "mod", "arcsin", "arccos", "arctan",
    "senh", "cosh", "tanh", "mmc", "mdc",
}
_IDENTIFICADORES_INTEIROS |= {v.lower() for v in _GREGAS.values()}
_IDENTIFICADORES_INTEIROS |= set(_GREGAS.values())
_MULTIPLICACAO = {"·", "×", "*", "∙"}
_CONECTORES = {"e", "ou"}

_LATEX_PARA_SIMBOLO = {
    r"\pm": "±", r"\cdot": "·", r"\times": "×", r"\div": "÷",
    r"\geq": "≥", r"\leq": "≤", r"\neq": "≠", r"\sqrt": "√",
    r"\left": "", r"\right": "",
    r"\biggl": "", r"\biggr": "", r"\Biggl": "", r"\Biggr": "",
    r"\bigl": "", r"\bigr": "", r"\Bigl": "", r"\Bigr": "",
    r"\bigg": "", r"\Bigg": "", r"\big": "", r"\Big": "",
    r"\middle": "",
    r"\in": "∈", r"\notin": "∉", r"\ni": "∋",
    r"\subseteq": "⊆", r"\subset": "⊂",
    r"\supseteq": "⊇", r"\supset": "⊃",
}

for _caractere, _nome in _GREGAS.items():
    _LATEX_PARA_SIMBOLO.setdefault("\\" + _nome, _caractere)
from pipeline.matematica.registro_de_operadores import (
    kind_do_caractere as _kind_do_registro,
    latex_para_unicode as _latex_do_registro,
)

for _forma, _canonico in _latex_do_registro().items():
    _LATEX_PARA_SIMBOLO.setdefault(_forma, _canonico)
del _forma, _canonico

_LATEX_PARA_SIMBOLO.setdefault(r"\varepsilon", "ε")
_LATEX_PARA_SIMBOLO.setdefault(r"\varphi", "φ")
_LATEX_PARA_SIMBOLO.setdefault(r"\vartheta", "θ")
_LATEX_PARA_SIMBOLO.setdefault(r"\varrho", "ρ")
_LATEX_PARA_SIMBOLO.setdefault(r"\varsigma", "σ")
del _caractere, _nome

_CONJUNTOS_MATHBB = {
    "N": "ℕ", "R": "ℝ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ",
}


_FUNCOES_LATEX_ENTRADA = (
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "sin", "sen",
    "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp", "lim", "max",
    "min", "det", "gcd",
)


def _traduzir_funcoes_latex(texto: str) -> str:
    resultado = texto
    for _ in range(8):
        novo = re.sub(r"\\operatorname\s*\{([^{}]*)\}", r"\1", resultado)
        if novo == resultado:
            break
        resultado = novo
    for nome in sorted(_FUNCOES_LATEX_ENTRADA, key=len, reverse=True):
        resultado = resultado.replace(f"\\{nome}", nome)
    return resultado


def _traduzir_conjuntos_mathbb(texto: str) -> str:
    def _sub(m: "re.Match[str]") -> str:
        letra = m.group(1).strip()
        return _CONJUNTOS_MATHBB.get(letra, m.group(0))

    return re.sub(r"\\mathbb\s*\{([^{}]*)\}", _sub, texto)


_QUANTIFICADORES_E_CONJUNTOS = {
    r"\emptyset": "conjunto vazio",
    r"\varnothing": "conjunto vazio", r"\therefore": "portanto",
    r"\because": "porque",
}
_INICIO_CONECTOR = "\x03"
_FIM_CONECTOR = "\x04"


def _traduzir_quantificadores(texto: str) -> str:
    resultado = texto
    for comando, palavra in sorted(
        _QUANTIFICADORES_E_CONJUNTOS.items(), key=lambda kv: -len(kv[0])
    ):
        resultado = resultado.replace(
            comando, f"{_INICIO_CONECTOR}{palavra}{_FIM_CONECTOR}"
        )
    return resultado


def _normalizar_entrada(texto: str) -> str:
    texto = texto or ""
    texto = texto.replace("\\(", " ").replace("\\)", " ")
    texto = texto.replace("$", " ")
    texto = re.sub(
        r"\\(?:text|mathrm)\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
        lambda m: _ABRE_TEXTO + m.group(1).strip() + _FECHA_TEXTO,
        texto,
    )
    texto = re.sub(r"\\(?:ldots|dots|cdots)\b", "…", texto)
    texto = re.sub(r"\\exists\s*!", "∃!", texto)
    texto = re.sub(r"\\(?:quad|qquad)\b", " ", texto)
    texto = re.sub(r"\\[ ,;:!]", " ", texto)
    texto = re.sub(r"(?<![0-9])\.\s*$", "", texto)
    veio_de_latex = "\\" in texto
    texto = (texto or "").replace(r"\{", _ABRE_CHAVE_LITERAL)
    texto = texto.replace(r"\}", _FECHA_CHAVE_LITERAL)
    bruto = _traduzir_quantificadores(_traduzir_conjuntos_mathbb(texto or ""))
    resultado = _traduzir_funcoes_latex(_expandir_fracoes_latex(bruto))
    for comando, simbolo in sorted(
        _LATEX_PARA_SIMBOLO.items(), key=lambda kv: -len(kv[0])
    ):
        resultado = resultado.replace(comando, simbolo)
    if veio_de_latex:
        resultado = (
            resultado.replace("{", _ABRE_ESTRUTURAL)
            .replace("}", _FECHA_ESTRUTURAL)
        )
    else:
        resultado = _marcar_chaves_estruturais(resultado)
    return resultado


def _marcar_chaves_estruturais(texto: str) -> str:
    if "{" not in texto:
        return texto
    caracteres = list(texto)
    pilha: list[int] = []
    pares: list[tuple[int, int]] = []
    for indice, caractere in enumerate(caracteres):
        if caractere == "{":
            pilha.append(indice)
        elif caractere == "}" and pilha:
            pares.append((pilha.pop(), indice))
    for abre, fecha in pares:
        precedido = abre > 0 and texto[abre - 1] in "^_"
        seguido = fecha + 1 < len(texto) and texto[fecha + 1] in "^_"
        if precedido or seguido:
            caracteres[abre] = _ABRE_ESTRUTURAL
            caracteres[fecha] = _FECHA_ESTRUTURAL
    return "".join(caracteres)


_ABRE_ESTRUTURAL = "\x01"
_FECHA_ESTRUTURAL = "\x02"
_ABRE_CHAVE_LITERAL = "\x05"
_FECHA_CHAVE_LITERAL = "\x06"
_ABRE_TEXTO = "\x07"
_FECHA_TEXTO = "\x0e"


def _extrair_grupo(texto: str, inicio: int) -> tuple[str, int]:
    if inicio >= len(texto) or texto[inicio] != "{":
        return "", inicio
    profundidade = 0
    for indice in range(inicio, len(texto)):
        if texto[indice] == "{":
            profundidade += 1
        elif texto[indice] == "}":
            profundidade -= 1
            if profundidade == 0:
                return texto[inicio + 1:indice], indice + 1
    return texto[inicio + 1:], len(texto)


def _expandir_fracoes_latex(texto: str) -> str:
    resultado = texto
    for _ in range(8):
        posicao = None
        comprimento_comando = 0
        for variante in (r"\dfrac", r"\tfrac", r"\cfrac", r"\frac"):
            achado = resultado.find(variante)
            if achado >= 0 and (posicao is None or achado < posicao):
                posicao = achado
                comprimento_comando = len(variante)
        if posicao is None:
            break
        cursor = posicao + comprimento_comando
        while cursor < len(resultado) and resultado[cursor].isspace():
            cursor += 1
        numerador, cursor = _extrair_grupo(resultado, cursor)
        while cursor < len(resultado) and resultado[cursor].isspace():
            cursor += 1
        denominador, cursor = _extrair_grupo(resultado, cursor)
        if not numerador or not denominador:
            break
        resultado = (
            resultado[:posicao]
            + f"{_ABRE_ESTRUTURAL}{_ABRE_ESTRUTURAL}{numerador}"
            + f"{_FECHA_ESTRUTURAL}/{_ABRE_ESTRUTURAL}{denominador}"
            + f"{_FECHA_ESTRUTURAL}{_FECHA_ESTRUTURAL}"
            + resultado[cursor:]
        )
    return resultado


def _e_chamada_de_funcao(fonte: str, posicao: int) -> bool:
    resto = fonte[posicao:].lstrip()
    return resto.startswith("(")


_KINDS_TRANSPARENTES = ("IMPLICIT_MULTIPLICATION",)
_KINDS_ANTES_DE_UNARIO = (
    "OPERATOR", "RELATION", "LPAREN", "PLUS_MINUS", "PLUS_MINUS_BINARY",
    "UNARY_MINUS", "RADICAL", "COMMA",
)


def token_anterior_significativo(
    tokens: list[Token], indice: int
) -> Token | None:
    for posicao in range(indice - 1, -1, -1):
        if tokens[posicao].kind not in _KINDS_TRANSPARENTES:
            return tokens[posicao]
    return None


def token_seguinte_significativo(
    tokens: list[Token], indice: int
) -> Token | None:
    for posicao in range(indice + 1, len(tokens)):
        if tokens[posicao].kind not in _KINDS_TRANSPARENTES:
            return tokens[posicao]
    return None


def classificar_menos(tokens: list[Token], indice: int | None = None) -> str:
    if indice is None:
        anterior = tokens[-1] if tokens else None
    else:
        anterior = token_anterior_significativo(tokens, indice)

    if anterior is None or anterior.kind in _KINDS_ANTES_DE_UNARIO:
        return "UNARY_MINUS"
    if anterior.kind == "UNKNOWN" and anterior.value.strip() in (",", ";"):
        return "UNARY_MINUS"
    return "OPERATOR"


def _e_posicao_unaria(tokens: list[Token]) -> bool:
    return classificar_menos(tokens) == "UNARY_MINUS"


def tokenizar(texto: str, geometria=None, inicio_offset: int = 0) -> list[Token]:
    fonte = _normalizar_entrada(texto or "")
    tokens: list[Token] = []
    i = 0
    tamanho = len(fonte)

    while i < tamanho:
        caractere = fonte[i]

        if caractere.isspace():
            i += 1
            continue

        if caractere == _INICIO_CONECTOR:
            fim = fonte.find(_FIM_CONECTOR, i + 1)
            if fim < 0:
                fim = tamanho
            palavra = fonte[i + 1:fim]
            tokens.append(Token(kind="CONNECTOR", value=palavra,
                                start=inicio_offset + i,
                                end=inicio_offset + fim + 1))
            i = fim + 1
            continue

        if caractere in _SOBRESCRITOS_UNICODE:
            digitos = ""
            while i < tamanho and fonte[i] in _SOBRESCRITOS_UNICODE:
                digitos += _SOBRESCRITOS_UNICODE[fonte[i]]
                i += 1
            tokens.append(Token(
                kind="SUPERSCRIPT", value=digitos, start=i - len(digitos), end=i,
                attached_to=tokens[-1].value if tokens else None,
            ))
            continue
        if caractere in _SUBSCRITOS_UNICODE:
            digitos = ""
            while i < tamanho and fonte[i] in _SUBSCRITOS_UNICODE:
                digitos += _SUBSCRITOS_UNICODE[fonte[i]]
                i += 1
            tokens.append(Token(
                kind="SUBSCRIPT", value=digitos, start=i - len(digitos), end=i,
                attached_to=tokens[-1].value if tokens else None,
            ))
            continue

        if caractere in "^_" and tokens:
            i += 1
            if i < tamanho and fonte[i] in ("{", _ABRE_ESTRUTURAL):
                abertura = fonte[i]
                fechamento = "}" if abertura == "{" else _FECHA_ESTRUTURAL
                profundidade = 0
                fim = -1
                for k in range(i, tamanho):
                    if fonte[k] == abertura:
                        profundidade += 1
                    elif fonte[k] == fechamento:
                        profundidade -= 1
                        if profundidade == 0:
                            fim = k
                            break
                conteudo = fonte[i + 1:fim] if fim > 0 else ""
                i = fim + 1 if fim > 0 else tamanho
            else:
                comeco_do_script = i
                if i < tamanho and fonte[i].isdigit():
                    while i < tamanho and fonte[i].isdigit():
                        i += 1
                    conteudo = fonte[comeco_do_script:i]
                else:
                    conteudo = fonte[i] if i < tamanho else ""
                    i += 1
            tokens.append(Token(
                kind="SUPERSCRIPT" if caractere == "^" else "SUBSCRIPT",
                value=conteudo.strip(), attached_to=tokens[-1].value,
            ))
            continue

        if caractere.isdigit():
            comeco = i
            while i < tamanho and (fonte[i].isdigit() or
                                   (fonte[i] in ".," and i + 1 < tamanho
                                    and fonte[i + 1].isdigit())):
                i += 1
            valor = fonte[comeco:i]
            token = Token(kind="NUMBER", value=valor,
                          start=inicio_offset + comeco, end=inicio_offset + i)
            if geometria is not None and tokens:
                elevado = _digito_elevado(geometria, token.start, token.end)
                if elevado == "sobrescrito":
                    token = Token(kind="SUPERSCRIPT", value=valor,
                                  start=token.start, end=token.end,
                                  attached_to=tokens[-1].value,
                                  origem="geometria")
                elif elevado == "subscrito":
                    token = Token(kind="SUBSCRIPT", value=valor,
                                  start=token.start, end=token.end,
                                  attached_to=tokens[-1].value,
                                  origem="geometria")
            tokens.append(token)
            continue

        if (tokens and tokens[-1].kind == "NUMBER"
                and (caractere.isalpha() or caractere in "²")):
            unidade = _casar_unidade(fonte, i)
            if unidade is not None:
                canonico, consumido = unidade
                tokens.append(Token(kind="UNIT", value=canonico,
                                    start=inicio_offset + i,
                                    end=inicio_offset + i + consumido))
                i += consumido
                continue

        if caractere.isalpha() or caractere in _GREGAS:
            comeco = i
            if caractere in _GREGAS:
                nome = _GREGAS[caractere]
                i += 1
                if nome == "Delta":
                    j = i
                    while j < tamanho and fonte[j] == " ":
                        j += 1
                    if (j < tamanho and fonte[j].isalpha()
                            and fonte[j] not in _GREGAS
                            and (j + 1 >= tamanho
                                 or not fonte[j + 1].isalpha())):
                        nome = "Δ" + fonte[j]
                        i = j + 1
            else:
                while i < tamanho and fonte[i].isalpha():
                    i += 1
                nome = fonte[comeco:i]
                if (len(nome) > 1
                        and nome.lower() not in _IDENTIFICADORES_INTEIROS
                        and nome.lower() not in _CONECTORES
                        and not _e_chamada_de_funcao(fonte, i)):
                    for deslocamento, letra in enumerate(nome):
                        tokens.append(Token(
                            kind="IDENT", value=letra,
                            start=inicio_offset + comeco + deslocamento,
                            end=inicio_offset + comeco + deslocamento + 1,
                        ))
                    tokens = _marcar_multiplicacao_implicita(tokens)
                    continue
            if nome.lower() in _CONECTORES and len(nome) <= 2:
                tokens.append(Token(kind="CONNECTOR", value=nome,
                                    start=inicio_offset + comeco,
                                    end=inicio_offset + i))
            elif _e_chamada_de_funcao(fonte, i):
                tokens.append(Token(kind="FUNCTION", value=nome,
                                    start=inicio_offset + comeco,
                                    end=inicio_offset + i))
            else:
                tokens.append(Token(kind="IDENT", value=nome,
                                    start=inicio_offset + comeco,
                                    end=inicio_offset + i))
            continue

        kind_registrado = _kind_do_registro(caractere)
        if kind_registrado is not None:
            valor = caractere
            if caractere == "∃" and i + 1 < tamanho and fonte[i + 1] == "!":
                valor = "∃!"
            tokens.append(Token(kind=kind_registrado, value=valor,
                                start=inicio_offset + i,
                                end=inicio_offset + i + len(valor)))
            i += len(valor)
            continue

        if caractere == _ABRE_TEXTO:
            fim = fonte.find(_FECHA_TEXTO, i)
            conteudo = fonte[i + 1:fim] if fim > 0 else ""
            conteudo = conteudo.replace(_ABRE_ESTRUTURAL, "{").replace(
                _FECHA_ESTRUTURAL, "}"
            )
            i = (fim + 1) if fim > 0 else tamanho
            tokens.append(Token(kind="TEXT", value=conteudo,
                                start=inicio_offset + i,
                                end=inicio_offset + i))
            continue

        if caractere == "…" or fonte[i:i + 3] == "...":
            passo = 1 if caractere == "…" else 3
            tokens.append(Token(kind="ELLIPSIS", value="…",
                                start=inicio_offset + i,
                                end=inicio_offset + i + passo))
            i += passo
            continue

        if caractere in ("{", _ABRE_CHAVE_LITERAL):
            tokens.append(Token(kind="LBRACE", value="{",
                                start=inicio_offset + i,
                                end=inicio_offset + i + 1))
            i += 1
            continue
        if caractere in ("}", _FECHA_CHAVE_LITERAL):
            tokens.append(Token(kind="RBRACE", value="}",
                                start=inicio_offset + i,
                                end=inicio_offset + i + 1))
            i += 1
            continue

        if caractere == ":":
            tokens.append(Token(kind="TAL_QUE", value=":",
                                start=inicio_offset + i,
                                end=inicio_offset + i + 1))
            i += 1
            continue

        if caractere in _RADICAIS:
            fim = i + 1
            indice = _RADICAIS[caractere]
            if indice is None and fim < tamanho and fonte[fim] == "[":
                fechamento = fonte.find("]", fim)
                if fechamento != -1:
                    indice = fonte[fim + 1:fechamento].strip()
                    fim = fechamento + 1
            tokens.append(Token(kind="RADICAL", value="√",
                                operand=indice or None,
                                start=inicio_offset + i,
                                end=inicio_offset + fim))
            i = fim
            continue

        if caractere == "±":
            unario = _e_posicao_unaria(tokens)
            tokens.append(Token(
                kind="PLUS_MINUS" if unario else "PLUS_MINUS_BINARY",
                value="±", start=inicio_offset + i, end=inicio_offset + i + 1,
            ))
            i += 1
            continue

        if caractere in _RELACOES:
            tokens.append(Token(kind="RELATION", value=_RELACOES[caractere],
                                start=inicio_offset + i, end=inicio_offset + i + 1))
            i += 1
            continue

        if caractere in "-−–":
            if _e_posicao_unaria(tokens):
                tokens.append(Token(kind="UNARY_MINUS", value="-",
                                    start=inicio_offset + i,
                                    end=inicio_offset + i + 1))
            else:
                tokens.append(Token(kind="OPERATOR", value="-",
                                    start=inicio_offset + i,
                                    end=inicio_offset + i + 1))
            i += 1
            continue

        if caractere in "+/" or caractere in _MULTIPLICACAO:
            valor = "*" if caractere in _MULTIPLICACAO else caractere
            tokens.append(Token(kind="OPERATOR", value=valor,
                                start=inicio_offset + i, end=inicio_offset + i + 1))
            i += 1
            continue

        if caractere in "([{" or caractere == _ABRE_ESTRUTURAL:
            tokens.append(Token(kind="LPAREN", value=caractere,
                                start=inicio_offset + i, end=inicio_offset + i + 1))
            i += 1
            continue
        if caractere in ")]}" or caractere == _FECHA_ESTRUTURAL:
            tokens.append(Token(kind="RPAREN", value=caractere,
                                start=inicio_offset + i, end=inicio_offset + i + 1))
            i += 1
            continue

        tokens.append(Token(kind="UNKNOWN", value=caractere,
                            start=inicio_offset + i, end=inicio_offset + i + 1))
        i += 1

    return _marcar_multiplicacao_implicita(tokens)


LIMITE_DESLOCAMENTO = 0.8
RAZAO_FONTE_MAXIMA = 0.85


def mediana_tamanho_de_fonte(spans) -> float:
    tamanhos = sorted(
        s.font_size for s in (spans or []) if getattr(s, "font_size", 0)
    )
    if not tamanhos:
        return 0.0
    meio = len(tamanhos) // 2
    if len(tamanhos) % 2:
        return tamanhos[meio]
    return (tamanhos[meio - 1] + tamanhos[meio]) / 2


def associar_scripts(spans, mediana: float | None = None) -> list[dict]:
    lista = list(spans or [])
    referencia = mediana if mediana is not None else mediana_tamanho_de_fonte(lista)
    resultado: list[dict] = []
    for span in lista:
        deslocamento = getattr(span, "baseline_shift", 0.0) or 0.0
        tamanho = getattr(span, "font_size", 0.0) or 0.0
        razao = (tamanho / referencia) if referencia else 1.0
        papel = "nenhum"
        if razao < RAZAO_FONTE_MAXIMA:
            if deslocamento > LIMITE_DESLOCAMENTO:
                papel = "expoente"
            elif deslocamento < -LIMITE_DESLOCAMENTO:
                papel = "indice"
        resultado.append({"span": span, "papel": papel})
    return resultado


def _digito_elevado(geometria, inicio: int, fim: int) -> str | None:
    try:
        candidatos = [
            s for s in geometria.spans
            if s.start < fim and s.end > inicio and s.text.strip()
        ]
        if not candidatos:
            return None
        mediana = (
            geometria.font_size_dominante
            or mediana_tamanho_de_fonte(geometria.spans)
        )
        for associacao in associar_scripts(candidatos, mediana):
            if associacao["papel"] == "expoente":
                return "sobrescrito"
            if associacao["papel"] == "indice":
                return "subscrito"
    except Exception:
        pass
    return None


def pode_terminar_operando(token: Token) -> bool:
    if token.kind in ("UNKNOWN", "COMMA") and token.value.strip() in (
        ",", ";"
    ):
        return False
    return token.kind in (
        "NUMBER", "IDENT", "RPAREN", "SUPERSCRIPT", "SUBSCRIPT",
    )


def pode_iniciar_operando(token: Token) -> bool:
    return token.kind in ("NUMBER", "IDENT", "LPAREN", "RADICAL", "FUNCTION")


def inserir_multiplicacao_implicita(tokens: list[Token]) -> list[Token]:
    resultado: list[Token] = []
    for indice, token in enumerate(tokens):
        if indice > 0:
            anterior = tokens[indice - 1]
            numeros_seguidos = (anterior.kind == "NUMBER"
                                and token.kind == "NUMBER")
            aplicacao_de_funcao = anterior.kind == "FUNCTION"
            if (pode_terminar_operando(anterior)
                    and pode_iniciar_operando(token)
                    and not numeros_seguidos
                    and not aplicacao_de_funcao):
                resultado.append(Token(
                    kind="IMPLICIT_MULTIPLICATION", value="*",
                    start=anterior.end, end=token.start,
                    operands=[anterior.value, token.value],
                ))
        resultado.append(token)
    return resultado


def _marcar_multiplicacao_implicita(tokens: list[Token]) -> list[Token]:
    return inserir_multiplicacao_implicita(tokens)


class _Parser:

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.posicao = 0
        self.nao_consumidos: list[Token] = []

    def _atual(self) -> Token | None:
        return self.tokens[self.posicao] if self.posicao < len(self.tokens) else None

    def _avancar(self) -> Token | None:
        token = self._atual()
        if token:
            self.posicao += 1
        return token

    def _casa(self, *kinds: str) -> bool:
        token = self._atual()
        return bool(token and token.kind in kinds)

    def parse(self) -> NoAST:
        no = self.expressao()
        while self._atual():
            self.nao_consumidos.append(self._avancar())
        return no

    def expressao(self) -> NoAST:
        no = self._implicacao()
        while (self._casa("LOGIC_OP")
               and self._atual().value in ("⇔", "↔")):
            self._avancar()
            no = OperacaoLogicaBinaria(
                operador="se_e_somente_se", esquerda=no,
                direita=self._implicacao(),
            )
        return no

    def _implicacao(self) -> NoAST:
        no = self._disjuncao()
        if (self._casa("LOGIC_OP") and self._atual().value == "⇒") or                 self._casa("ARROW") and self._atual().value == "→":
            self._avancar()
            return OperacaoLogicaBinaria(
                operador="implica", esquerda=no,
                direita=self._implicacao(),
            )
        return no

    def _disjuncao(self) -> NoAST:
        no = self._conjuncao()
        while (self._casa("LOGIC_OP")
               and self._atual().value in ("∨", "⊕")):
            operador = ("ou_exclusivo" if self._avancar().value == "⊕"
                        else "ou_logico")
            no = OperacaoLogicaBinaria(
                operador=operador, esquerda=no,
                direita=self._conjuncao(),
            )
        return no

    def _conjuncao(self) -> NoAST:
        no = self._negacao()
        while self._casa("LOGIC_OP") and self._atual().value == "∧":
            self._avancar()
            no = OperacaoLogicaBinaria(
                operador="e_logico", esquerda=no,
                direita=self._negacao(),
            )
        return no

    def _negacao(self) -> NoAST:
        if self._casa("LOGIC_NOT"):
            self._avancar()
            return NegacaoLogica(operando=self._negacao())
        return self.relacao()

    def relacao(self) -> NoAST:
        if self._casa("QUANTIFIER"):
            return self.quantificador()
        esquerda = self.conjunto()
        if not self._casa("RELATION"):
            return esquerda
        primeiro = self._atual().value
        operandos = [esquerda]
        operadores: list[str] = []
        while self._casa("RELATION"):
            atual = self._avancar()
            operadores.append(atual.value)
            operandos.append(self.conjunto())
        return Relation(
            operador=primeiro, operandos=operandos, operadores=operadores
        )

    def quantificador(self) -> NoAST:
        from pipeline.matematica.registro_de_operadores import QUANTIFICADORES

        token = self._avancar()
        spec = QUANTIFICADORES.get(token.value)
        tipo = spec.identificador if spec else token.value
        variavel: NoAST = (
            Symbol(nome=self._avancar().value)
            if self._casa("IDENT") else Desconhecido(texto="")
        )
        dominio: NoAST | None = None
        if self._casa("RELATION") and self._atual().value == "in":
            self._avancar()
            dominio = self.conjunto()
        corpo: NoAST | None = None
        if self._e_virgula() or self._casa("TAL_QUE"):
            self._avancar()
            corpo = self.expressao()
        elif self._casa("CONNECTOR"):
            self._avancar()
            corpo = self.expressao()
        elif self._casa("QUANTIFIER"):
            corpo = self.quantificador()
        return Quantificador(
            especie=tipo, variavel=variavel, dominio=dominio, corpo=corpo,
        )

    def conjunto(self) -> NoAST:
        from pipeline.matematica.registro_de_operadores import precedencia_do_operador

        no = self._intersecao()
        operandos = [no]
        operadores: list[str] = []
        while (self._casa("SET_OP")
               and precedencia_do_operador(self._atual().value) < 45):
            operadores.append(self._avancar().value)
            operandos.append(self._intersecao())
        if not operadores:
            return no
        return OperacaoDeConjuntos(
            operandos=operandos, operadores=operadores,
        )

    def _intersecao(self) -> NoAST:
        no = self.soma()
        operandos = [no]
        operadores: list[str] = []
        while self._casa("SET_OP") and self._atual().value == "∩":
            operadores.append(self._avancar().value)
            operandos.append(self.soma())
        if not operadores:
            return no
        return OperacaoDeConjuntos(
            operandos=operandos, operadores=operadores,
        )

    def soma(self) -> NoAST:
        no = self.produto()
        while True:
            if self._casa("PLUS_MINUS_BINARY"):
                self._avancar()
                no = PlusMinus(esquerda=no, operando=self.produto())
                continue
            if self._casa("OPERATOR") and self._atual().value in ("+", "-"):
                operador = self._avancar().value
                direita = self.produto()
                if operador == "+":
                    if isinstance(no, Add):
                        no.termos.append(direita)
                    else:
                        no = Add(termos=[no, direita])
                else:
                    no = Subtract(left=no, right=direita)
                continue
            break
        return no

    def produto(self) -> NoAST:
        no = self.unario()
        while True:
            if self._casa("IMPLICIT_MULTIPLICATION"):
                self._avancar()
                direita = self.unario()
                notacao = ("parentheses"
                           if isinstance(direita, Group) or isinstance(no, Group)
                           else "implicit")
                if isinstance(no, Multiply) and no.implicita:
                    no.fatores.append(direita)
                else:
                    no = Multiply(fatores=[no, direita],
                                  source_notation=notacao)
                continue
            if self._casa("OPERATOR") and self._atual().value in ("*", "/"):
                operador = self._avancar().value
                direita = self.unario()
                if operador == "*":
                    if isinstance(no, Multiply) and not no.implicita:
                        no.fatores.append(direita)
                    else:
                        no = Multiply(fatores=[no, direita],
                                      source_notation="dot")
                else:
                    while self._casa("IMPLICIT_MULTIPLICATION"):
                        self._avancar()
                        proximo = self.unario()
                        if isinstance(direita, Multiply) and direita.implicita:
                            direita.fatores.append(proximo)
                        else:
                            direita = Multiply(
                                fatores=[direita, proximo],
                                source_notation="implicit",
                            )
                    no = Divide(numerador=no, denominador=direita)
                continue
            break
        return no

    def unario(self) -> NoAST:
        if self._casa("UNARY_MINUS"):
            self._avancar()
            return UnaryMinus(operando=self.unario())
        if self._casa("PLUS_MINUS"):
            self._avancar()
            if self._atual() is None:
                return PlusMinus()
            return PlusMinus(operando=self.unario())
        return self.potencia()

    def potencia(self) -> NoAST:
        no = self.primario()
        while self._casa("SUPERSCRIPT", "SUBSCRIPT"):
            token = self._avancar()
            expoente = _no_de_script(token.value)
            if token.kind == "SUPERSCRIPT":
                no = Power(base=no, expoente=expoente)
            else:
                no = Subscript(base=no, indice=expoente)
        return no

    def primario(self) -> NoAST:
        token = self._atual()
        if token is None:
            return Desconhecido(texto="")

        if token.kind == "NUMBER":
            self._avancar()
            numero = _no_de_valor(token.value)
            if self._casa("UNIT"):
                unidade = self._avancar().value
                return Quantia(valor=numero, unidade=unidade)
            return numero

        if token.kind == "IDENT":
            self._avancar()
            if (token.value.lower() in _FUNCOES_COM_SUBSCRITO
                    and self._casa("SUBSCRIPT")):
                return self._funcao_com_subscrito(token.value)
            if token.value.lower() in _FUNCOES_SEM_PARENTESES:
                argumento = self._argumento_sem_parenteses()
                if argumento is not None:
                    return Function(
                        nome=token.value, argumentos=[argumento],
                    )
            return Symbol(nome=token.value)

        if token.kind == "TEXT":
            self._avancar()
            return TextoLiteral(texto=token.value)

        if token.kind == "ELLIPSIS":
            self._avancar()
            return Reticencias()

        if token.kind == "LBRACE":
            self._avancar()
            if self._casa("RBRACE"):
                self._avancar()
                return ConjuntoLiteral(itens=[])
            primeiro = self.expressao()
            if self._casa("BARRA") or self._casa("TAL_QUE"):
                self._avancar()
                predicado = self.expressao()
                if self._casa("RBRACE"):
                    self._avancar()
                variavel: NoAST = primeiro
                dominio: NoAST | None = None
                if (isinstance(primeiro, Relation)
                        and primeiro.operador == "in"
                        and len(primeiro.operandos) == 2):
                    variavel = primeiro.operandos[0]
                    dominio = primeiro.operandos[1]
                return ConjuntoPorPropriedade(
                    variavel=variavel, predicado=predicado,
                    dominio=dominio,
                )
            itens = [primeiro]
            while self._e_virgula():
                self._avancar()
                itens.append(self.expressao())
            if self._casa("RBRACE"):
                self._avancar()
            return ConjuntoLiteral(itens=itens)

        if token.kind == "BARRA":
            self._avancar()
            conteudo = self.expressao()
            if self._casa("BARRA"):
                self._avancar()
            if tipo_semantico(conteudo) == "conjunto":
                return Cardinalidade(expressao=conteudo)
            return ValorAbsoluto(expressao=conteudo)

        if token.kind == "RADICAL":
            self._avancar()
            indice = _no_de_indice_de_raiz(token.operand)
            if self._atual() is None:
                return Sqrt(radicando=Desconhecido(texto=""), indice=indice)
            return Sqrt(radicando=self.unario(), indice=indice)

        if token.kind == "FUNCTION":
            self._avancar()
            argumentos: list[NoAST] = []
            if self._casa("LPAREN"):
                self._avancar()
                argumentos.extend(self._lista_separada_por_virgula())
                if self._casa("RPAREN"):
                    self._avancar()
            return Function(nome=token.value, argumentos=argumentos)

        if token.kind == "LPAREN":
            self._avancar()
            itens = self._lista_separada_por_virgula()
            if self._casa("RPAREN"):
                self._avancar()
            interno = (
                itens[0] if len(itens) == 1
                else TextMathSequence(
                    itens=_intercalar_virgulas(itens)
                )
            )
            return Group(
                conteudo=interno,
                estrutural=token.value == _ABRE_ESTRUTURAL,
            )

        if token.kind == "CONNECTOR":
            self._avancar()
            return Connector(texto=token.value)

        self._avancar()
        return Desconhecido(texto=token.value)

    def _argumento_sem_parenteses(self) -> NoAST | None:
        posicao = self.posicao
        if self._casa("IMPLICIT_MULTIPLICATION"):
            self._avancar()
        if self._atual() is not None and self._atual().kind in (
            "NUMBER", "IDENT", "LPAREN", "RADICAL",
        ):
            return self.unario()
        self.posicao = posicao
        return None

    def _funcao_com_subscrito(self, nome: str) -> NoAST:
        script = self._avancar()
        if nome.lower() == "lim":
            return self._limite(script.value)
        indice = _no_de_script(script.value)
        if self._casa("IMPLICIT_MULTIPLICATION"):
            self._avancar()
        argumento: NoAST
        if self._casa("LPAREN"):
            self._avancar()
            itens = self._lista_separada_por_virgula()
            if self._casa("RPAREN"):
                self._avancar()
            argumento = itens[0] if len(itens) == 1 else TextMathSequence(
                itens=_intercalar_virgulas(itens)
            )
        elif self._atual() is not None and self._atual().kind in (
            "NUMBER", "IDENT", "LPAREN", "RADICAL", "UNARY_MINUS",
        ):
            argumento = self.unario()
        else:
            argumento = Desconhecido(texto="")
        return Function(
            nome=nome, argumentos=[argumento], indice=indice,
        )

    def _limite(self, conteudo_do_subscrito: str) -> NoAST:
        variavel: NoAST = Desconhecido(texto=conteudo_do_subscrito)
        alvo: NoAST = Desconhecido(texto="")
        partes = re.split(r"[→↦]", conteudo_do_subscrito or "", maxsplit=1)
        if len(partes) == 2:
            variavel = _no_de_script(partes[0])
            alvo = _no_de_script(partes[1])
        if self._casa("IMPLICIT_MULTIPLICATION"):
            self._avancar()
        corpo: NoAST | None = None
        if self._atual() is not None and self._atual().kind in (
            "NUMBER", "IDENT", "LPAREN", "RADICAL", "UNARY_MINUS",
        ):
            corpo = self.unario()
        return Limite(variavel=variavel, alvo=alvo, corpo=corpo)

    def _e_virgula(self) -> bool:
        atual = self._atual()
        return (
            atual is not None
            and atual.kind in ("UNKNOWN", "COMMA")
            and atual.value.strip() in (",", ";")
        )

    def _lista_separada_por_virgula(self) -> list[NoAST]:
        itens = [self.expressao()]
        while self._e_virgula():
            self._avancar()
            if self._casa("RPAREN") or self._atual() is None:
                break
            itens.append(self.expressao())
        return itens


_FUNCOES_COM_SUBSCRITO = {"log", "lim", "max", "min"}

def _casar_unidade(fonte: str, posicao: int):
    from pipeline.matematica.vocabulario_de_fala import UNIDADES_POR_TAMANHO

    trecho = fonte[posicao:]
    for canonico in UNIDADES_POR_TAMANHO:
        formas = [canonico]
        if canonico.endswith("²"):
            base = canonico[:-1]
            formas += [
                base + "^{2}", base + "^2",
                base + "^" + _ABRE_ESTRUTURAL + "2" + _FECHA_ESTRUTURAL,
            ]
        for forma in formas:
            if not trecho.startswith(forma):
                continue
            fim = posicao + len(forma)
            if fim < len(fonte) and (fonte[fim].isalnum()
                                     or fonte[fim] in "À-ÿ/^_"):
                continue
            return canonico, len(forma)
    return None


_FUNCOES_SEM_PARENTESES = {
    "log", "ln", "sen", "sin", "cos", "tan", "tg", "sec", "csc",
    "cossec", "cot", "cotg", "exp",
}


_CONJUNTOS_NUMERICOS = {"ℕ", "ℝ", "ℤ", "ℚ", "ℂ"}


def tipo_semantico(no: NoAST) -> str:
    if isinstance(no, (ConjuntoLiteral, ConjuntoPorPropriedade,
                       OperacaoDeConjuntos)):
        return "conjunto"
    if isinstance(no, (Quantificador, NegacaoLogica,
                       OperacaoLogicaBinaria)):
        return "proposicao"
    if isinstance(no, Symbol) and no.nome in _CONJUNTOS_NUMERICOS:
        return "conjunto"
    if isinstance(no, Group):
        return tipo_semantico(no.conteudo)
    if isinstance(no, (Integer, Numero, Divide)):
        return "escalar"
    return "desconhecido"


def _no_de_script(valor: str) -> NoAST:
    limpo = (valor or "").strip()
    if not limpo:
        return Desconhecido(texto="")
    simples = _no_de_valor(limpo)
    if not isinstance(simples, Desconhecido):
        return simples
    try:
        resultado = construir_ast(limpo)
    except Exception:
        return Desconhecido(texto=limpo)
    if resultado.nao_consumidos:
        return Desconhecido(texto=limpo)
    return resultado.ast


def _no_de_indice_de_raiz(texto: str | None) -> NoAST | None:
    if not texto:
        return None
    limpo = texto.strip()
    if not limpo:
        return None
    if limpo.isdigit():
        return Integer(valor=int(limpo))
    if limpo.isalpha() and len(limpo) == 1:
        return Symbol(nome=limpo)
    try:
        return construir_ast(limpo).ast
    except Exception:
        return Desconhecido(texto=limpo)


_FOLHAS = (Integer, Numero, Symbol)


def desembrulhar_grupos_redundantes(no: NoAST) -> NoAST:
    if isinstance(no, Group) and getattr(no, "estrutural", False):
        return desembrulhar_grupos_redundantes(no.conteudo)
    if isinstance(no, Group) and isinstance(no.conteudo, _FOLHAS):
        return no.conteudo
    for chave, valor in list(no.__dict__.items()):
        if isinstance(valor, NoAST):
            setattr(no, chave, desembrulhar_grupos_redundantes(valor))
        elif isinstance(valor, list) and valor and isinstance(valor[0], NoAST):
            setattr(no, chave,
                    [desembrulhar_grupos_redundantes(v) for v in valor])
    return no


def _no_de_valor(valor: str) -> NoAST:
    texto = (valor or "").strip()
    if not texto:
        return Desconhecido(texto="")
    if re.fullmatch(r"\d+", texto):
        return Integer(valor=int(texto))
    if re.fullmatch(r"\d+[.,]\d+", texto):
        return Numero(texto=texto)
    if re.fullmatch(r"[A-Za-z]+", texto):
        return Symbol(nome=texto)
    return Desconhecido(texto=texto)


@dataclass
class ResultadoParse:

    ast: NoAST
    tokens: list[Token] = field(default_factory=list)
    nao_consumidos: list[Token] = field(default_factory=list)

    @property
    def completa(self) -> bool:
        if self.nao_consumidos:
            return False
        return not any(isinstance(n, Desconhecido) for n in self.ast.percorrer())


def construir_ast(
    texto: str, geometria=None, inicio_offset: int = 0
) -> ResultadoParse:
    tokens = tokenizar(texto, geometria, inicio_offset)
    if not tokens:
        return ResultadoParse(ast=Desconhecido(texto=texto or ""), tokens=[])

    primeiro_significativo = next(
        (t for t in tokens if t.kind != "IMPLICIT_MULTIPLICATION"), None
    )
    from pipeline.matematica.vocabulario_de_fala import UNIDADES_FALADAS

    for token in tokens:
        if token.kind != "TEXT":
            continue
        conteudo = token.value.strip()
        if conteudo.lower() in ("e", "ou", ",", ";"):
            token.kind = "CONNECTOR"
            token.value = conteudo.lower()
        elif conteudo.replace("^{2}", "\u00b2").replace(
                "^2", "\u00b2") in UNIDADES_FALADAS:
            conteudo = conteudo.replace("^{2}", "\u00b2").replace(
                "^2", "\u00b2")
            token.kind = "UNIT"
            token.value = conteudo
    comeca_estruturado = primeiro_significativo is not None and (
        primeiro_significativo.kind in ("QUANTIFIER", "LBRACE")
    )
    if not comeca_estruturado and (
        any(t.kind == "CONNECTOR" for t in tokens)
        or _virgulas_de_enumeracao(tokens)
    ):
        return _parse_sequencia(tokens)

    parser = _Parser(tokens)
    try:
        ast = parser.parse()
    except Exception:
        return ResultadoParse(
            ast=Desconhecido(texto=texto or ""), tokens=tokens,
            nao_consumidos=list(tokens),
        )
    return ResultadoParse(
        ast=desembrulhar_grupos_redundantes(ast), tokens=tokens,
        nao_consumidos=parser.nao_consumidos,
    )


def _intercalar_virgulas(itens: list[NoAST]) -> list[NoAST]:
    saida: list[NoAST] = []
    for indice, item in enumerate(itens):
        if indice:
            saida.append(Connector(texto=","))
        saida.append(item)
    return saida


def _virgulas_de_enumeracao(tokens: list[Token]) -> set[int]:
    indices: set[int] = set()
    profundidade = 0
    for indice, token in enumerate(tokens):
        if token.kind in ("LPAREN", "LBRACE"):
            profundidade += 1
        elif token.kind in ("RPAREN", "RBRACE"):
            profundidade = max(0, profundidade - 1)
        elif (
            profundidade == 0
            and token.kind in ("UNKNOWN", "COMMA")
            and token.value.strip() in (",", ";")
        ):
            indices.add(indice)
    return indices


def _parse_sequencia(tokens: list[Token]) -> ResultadoParse:
    itens: list[NoAST] = []
    nao_consumidos: list[Token] = []
    bloco: list[Token] = []
    separadoras = _virgulas_de_enumeracao(tokens)

    def _fechar_bloco():
        if not bloco:
            return
        parser = _Parser(list(bloco))
        itens.append(parser.parse())
        nao_consumidos.extend(parser.nao_consumidos)
        bloco.clear()

    for indice, token in enumerate(tokens):
        if indice in separadoras:
            _fechar_bloco()
            itens.append(Connector(texto=","))
            continue
        if token.kind == "CONNECTOR":
            _fechar_bloco()
            itens.append(Connector(texto=token.value))
            continue
        if token.kind == "IMPLICIT_MULTIPLICATION" and not bloco:
            continue
        bloco.append(token)
    _fechar_bloco()

    return ResultadoParse(
        ast=TextMathSequence(itens=itens), tokens=tokens,
        nao_consumidos=nao_consumidos,
    )
