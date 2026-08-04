"""A mesma arvore virando LaTeX, MathML e OMML.

Tres formatos gerados num lugar so. Quando cada renderizador montava o
seu, eles divergiam — o TXT dizia uma coisa e o HTML outra sobre a
mesma formula.

O MathML sai com a anotacao LaTeX dentro do <semantics>, que e o que a
linha braille le, e com Invisible Times (U+2062) na multiplicacao
implicita: visualmente "4ac" nao muda, mas a marcacao passa a afirmar
que ali existe multiplicacao em vez de deixar cada leitor de tela
adivinhar. O OMML e o que faz o Word abrir a equacao como equacao
editavel, nao como imagem colada.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from pipeline.matematica.arvore_matematica import (
    Add,
    Connector,
    Desconhecido,
    Divide,
    Function,
    Group,
    Integer,
    Multiply,
    NoAST,
    Numero,
    PlusMinus,
    Power,
    Relation,
    Sqrt,
    Cardinalidade,
    ConjuntoLiteral,
    ConjuntoPorPropriedade,
    Limite,
    NegacaoLogica,
    OperacaoDeConjuntos,
    OperacaoLogicaBinaria,
    Quantia,
    Quantificador,
    Reticencias,
    TextoLiteral,
    ValorAbsoluto,
    Subscript,
    Subtract,
    Symbol,
    TextMathSequence,
    UnaryMinus,
)

_GREGAS_LATEX = {
    "Delta": r"\Delta", "delta": r"\delta", "pi": r"\pi",
    "alpha": r"\alpha", "beta": r"\beta", "gamma": r"\gamma",
    "theta": r"\theta", "lambda": r"\lambda", "mu": r"\mu",
    "sigma": r"\sigma", "omega": r"\omega", "Sigma": r"\Sigma",
    "Omega": r"\Omega", "Phi": r"\Phi",
    "ℕ": r"\mathbb{N}", "ℝ": r"\mathbb{R}", "ℤ": r"\mathbb{Z}",
    "ℚ": r"\mathbb{Q}", "ℂ": r"\mathbb{C}",
}
_GREGAS_UNICODE = {
    "Delta": "Δ", "delta": "δ", "pi": "π", "alpha": "α", "beta": "β",
    "gamma": "γ", "theta": "θ", "lambda": "λ", "mu": "μ", "sigma": "σ",
    "omega": "ω", "Sigma": "Σ", "Omega": "Ω", "Phi": "Φ",
    "ℕ": "ℕ", "ℝ": "ℝ", "ℤ": "ℤ", "ℚ": "ℚ", "ℂ": "ℂ",
}
_RELACAO_LATEX = {
    "=": "=", ">=": r"\geq", "<=": r"\leq", "!=": r"\neq",
    "<": "<", ">": ">",
    "in": r"\in", "notin": r"\notin",
    "subset": r"\subset", "subseteq": r"\subseteq",
    "supset": r"\supset", "supseteq": r"\supseteq",
}
_RELACAO_UNICODE = {
    "=": "=", ">=": "≥", "<=": "≤", "!=": "≠", "<": "<", ">": ">",
    "in": "∈", "notin": "∉",
    "subset": "⊂", "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇",
}
_FUNCOES_LATEX = {"sen": r"\operatorname{sen}", "sin": r"\sin",
                  "cos": r"\cos", "tan": r"\tan", "log": r"\log",
                  "ln": r"\ln", "exp": r"\exp", "lim": r"\lim"}


def para_latex(no: NoAST) -> str:
    try:
        return _latex(no)
    except Exception:
        return ""


def _termina_em_digito(texto: str) -> bool:
    return bool(texto) and texto[-1].isdigit()


def _comeca_com_digito(texto: str) -> bool:
    return bool(texto) and texto[0].isdigit()


def _justapor(fatores: list, serializar, operador_explicito: str) -> str:
    partes = [serializar(f) for f in fatores]
    if not partes:
        return ""
    resultado = partes[0]
    for parte in partes[1:]:
        if _termina_em_digito(resultado) and _comeca_com_digito(parte):
            resultado += operador_explicito + parte
        else:
            resultado += parte
    return resultado


def _latex(no: NoAST) -> str:
    if isinstance(no, Integer):
        return str(no.valor)
    if isinstance(no, Numero):
        return no.texto
    if isinstance(no, Symbol):
        if len(no.nome) == 2 and no.nome.startswith("Δ"):
            return rf"\Delta {no.nome[1]}"
        _MATHBB = {"ℕ": r"\mathbb{N}", "ℝ": r"\mathbb{R}",
                   "ℤ": r"\mathbb{Z}", "ℚ": r"\mathbb{Q}",
                   "ℂ": r"\mathbb{C}"}
        if no.nome in _MATHBB:
            return _MATHBB[no.nome]
        return _GREGAS_LATEX.get(no.nome, no.nome)
    if isinstance(no, Connector):
        return rf"\text{{ {no.texto} }}"
    if isinstance(no, Desconhecido):
        return no.texto
    if isinstance(no, Group):
        return rf"\left({_latex(no.conteudo)}\right)"
    if isinstance(no, UnaryMinus):
        return f"-{_latex(no.operando)}"
    if isinstance(no, PlusMinus):
        if no.binaria:
            return rf"{_latex(no.esquerda)} \pm {_latex(no.operando)}"
        return rf"\pm {_latex(no.operando)}"
    if isinstance(no, Power):
        return f"{{{_latex(no.base)}}}^{{{_latex(no.expoente)}}}"
    if isinstance(no, Subscript):
        return f"{{{_latex(no.base)}}}_{{{_latex(no.indice)}}}"
    if isinstance(no, Sqrt):
        if no.indice is not None:
            return rf"\sqrt[{_latex(no.indice)}]{{{_latex(no.radicando)}}}"
        return rf"\sqrt{{{_latex(no.radicando)}}}"
    if isinstance(no, OperacaoDeConjuntos):
        from pipeline.matematica.registro_de_operadores import latex_do_operador

        partes = [_latex(no.operandos[0])] if no.operandos else []
        for indice, operando in enumerate(no.operandos[1:]):
            comando = latex_do_operador(no.operador_em(indice))
            partes.append(f" {comando} {_latex(operando)}")
        return "".join(partes)
    if isinstance(no, ConjuntoLiteral):
        return r"\{" + ", ".join(_latex(i) for i in no.itens) + r"\}"
    if isinstance(no, Quantificador):
        from pipeline.matematica.registro_de_operadores import QUANTIFICADORES

        comando = next(
            (spec.formas_latex[0] for spec in QUANTIFICADORES.values()
             if spec.identificador == no.especie), "",
        )
        resultado = f"{comando} {_latex(no.variavel)}"
        if no.dominio is not None:
            resultado += rf" \in {_latex(no.dominio)}"
        if no.corpo is not None:
            separador = ", " if no.especie == "para_todo" else ": "
            resultado += separador + _latex(no.corpo)
        return resultado
    if isinstance(no, TextoLiteral):
        return rf"\text{{{no.texto}}}"
    if isinstance(no, Quantia):
        unidade = no.unidade.replace("\u00b2", "^{2}")
        return rf"{_latex(no.valor)}\ \mathrm{{{unidade}}}"
    if isinstance(no, Reticencias):
        return r"\ldots"
    if isinstance(no, NegacaoLogica):
        return rf"\neg {_latex(no.operando)}"
    if isinstance(no, OperacaoLogicaBinaria):
        _COMANDOS_LOGICOS = {
            "e_logico": r"\land", "ou_logico": r"\lor",
            "ou_exclusivo": r"\oplus", "implica": r"\to",
            "se_e_somente_se": r"\Leftrightarrow",
        }
        comando = _COMANDOS_LOGICOS.get(no.operador, no.operador)
        return f"{_latex(no.esquerda)} {comando} {_latex(no.direita)}"
    if isinstance(no, (ValorAbsoluto, Cardinalidade)):
        return rf"\left|{_latex(no.expressao)}\right|"
    if isinstance(no, ConjuntoPorPropriedade):
        cabeca = _latex(no.variavel)
        if no.dominio is not None:
            cabeca += rf" \in {_latex(no.dominio)}"
        return (r"\{" + cabeca + r" \mid "
                + _latex(no.predicado) + r"\}")
    if isinstance(no, Limite):
        cabeca = (rf"\lim_{{{_latex(no.variavel)} \to {_latex(no.alvo)}}}")
        if no.corpo is None:
            return cabeca
        return f"{cabeca} {_latex(no.corpo)}"
    if isinstance(no, Add):
        return " + ".join(_latex(t) for t in no.termos)
    if isinstance(no, Subtract):
        return f"{_latex(no.left)} - {_latex(no.right)}"
    if isinstance(no, Multiply):
        if no.implicita:
            return _justapor(no.fatores, _latex, r" \cdot ")
        return r" \cdot ".join(_latex(f) for f in no.fatores)
    if isinstance(no, Divide):
        return rf"\frac{{{_latex(no.numerador)}}}{{{_latex(no.denominador)}}}"
    if isinstance(no, Function):
        nome = _FUNCOES_LATEX.get(no.nome.lower(), rf"\operatorname{{{no.nome}}}")
        if no.indice is not None:
            nome = f"{nome}_{{{_latex(no.indice)}}}"
        args = ", ".join(_latex(a) for a in no.argumentos)
        return f"{nome}\\left({args}\\right)" if args else nome
    if isinstance(no, Relation):
        partes = [_latex(o) for o in no.operandos]
        saida = partes[0] if partes else ""
        for indice, parte in enumerate(partes[1:]):
            simbolo = no.operador_em(indice)
            saida += f" {_RELACAO_LATEX.get(simbolo, simbolo)} {parte}"
        return saida
    if isinstance(no, TextMathSequence):
        return " ".join(_latex(i) for i in no.itens)
    return ""


def para_mathml(
    no: NoAST, latex_anotacao: str | None = None, display: str = "inline"
) -> str:
    try:
        corpo = _mathml(no)
    except Exception:
        return ""
    if not corpo:
        return ""
    anotacao = ""
    tex = latex_anotacao if latex_anotacao is not None else para_latex(no)
    if tex:
        anotacao = (
            '<annotation encoding="application/x-tex">'
            f"{escape(tex)}</annotation>"
        )
    return (
        f'<math xmlns="http://www.w3.org/1998/Math/MathML" '
        f'xml:lang="pt-BR" display="{display}">'
        f"<semantics><mrow>{corpo}</mrow>{anotacao}</semantics></math>"
    )


def _mrow(conteudo: str) -> str:
    return f"<mrow>{conteudo}</mrow>"


def _mathml(no: NoAST) -> str:
    if isinstance(no, Integer):
        return f"<mn>{no.valor}</mn>"
    if isinstance(no, Numero):
        return f"<mn>{escape(no.texto)}</mn>"
    if isinstance(no, Symbol):
        nome = _GREGAS_UNICODE.get(no.nome, no.nome)
        return f"<mi>{escape(nome)}</mi>"
    if isinstance(no, Connector):
        return f"<mtext> {escape(no.texto)} </mtext>"
    if isinstance(no, Desconhecido):
        return f"<mtext>{escape(no.texto)}</mtext>" if no.texto else ""
    if isinstance(no, Group):
        return _mrow(
            '<mo stretchy="false">(</mo>'
            f"{_mathml(no.conteudo)}"
            '<mo stretchy="false">)</mo>'
        )
    if isinstance(no, UnaryMinus):
        return _mrow(f"<mo>&#x2212;</mo>{_mathml(no.operando)}")
    if isinstance(no, PlusMinus):
        if no.binaria:
            return _mrow(
                f"{_mathml(no.esquerda)}<mo>&#x00B1;</mo>"
                f"{_mathml(no.operando)}"
            )
        return _mrow(f"<mo>&#x00B1;</mo>{_mathml(no.operando)}")
    if isinstance(no, Power):
        return f"<msup>{_mathml(no.base)}{_mathml(no.expoente)}</msup>"
    if isinstance(no, Subscript):
        return f"<msub>{_mathml(no.base)}{_mathml(no.indice)}</msub>"
    if isinstance(no, Sqrt):
        if no.indice is not None:
            return (f"<mroot>{_mathml(no.radicando)}"
                    f"{_mathml(no.indice)}</mroot>")
        return f"<msqrt>{_mathml(no.radicando)}</msqrt>"
    if isinstance(no, OperacaoDeConjuntos):
        partes = [_mathml(no.operandos[0])] if no.operandos else []
        for indice, operando in enumerate(no.operandos[1:]):
            partes.append(f"<mo>{no.operador_em(indice)}</mo>")
            partes.append(_mathml(operando))
        return _mrow("".join(partes))
    if isinstance(no, ConjuntoLiteral):
        interno = "<mo>,</mo>".join(_mathml(i) for i in no.itens)
        return _mrow(f"<mo>{{</mo>{interno}<mo>}}</mo>")
    if isinstance(no, Quantificador):
        from pipeline.matematica.registro_de_operadores import QUANTIFICADORES

        simbolo = next(
            (spec.forma_unicode for spec in QUANTIFICADORES.values()
             if spec.identificador == no.especie), "",
        )
        partes = [f"<mo>{simbolo}</mo>", _mathml(no.variavel)]
        if no.dominio is not None:
            partes.append("<mo>&#x2208;</mo>")
            partes.append(_mathml(no.dominio))
        if no.corpo is not None:
            separador = "," if no.especie == "para_todo" else ":"
            partes.append(f"<mo>{separador}</mo>")
            partes.append(_mathml(no.corpo))
        return _mrow("".join(partes))
    if isinstance(no, TextoLiteral):
        return f"<mtext>{escape(no.texto)}</mtext>"
    if isinstance(no, Quantia):
        return _mrow(
            f"{_mathml(no.valor)}<mo>&#x2062;</mo>"
            f'<mi mathvariant="normal">{escape(no.unidade)}</mi>'
        )
    if isinstance(no, Reticencias):
        return "<mo>\u2026</mo>"
    if isinstance(no, NegacaoLogica):
        return _mrow(f"<mo>\u00ac</mo>{_mathml(no.operando)}")
    if isinstance(no, OperacaoLogicaBinaria):
        _SIMBOLOS_LOGICOS = {
            "e_logico": "\u2227", "ou_logico": "\u2228",
            "ou_exclusivo": "\u2295", "implica": "\u2192",
            "se_e_somente_se": "\u21d4",
        }
        simbolo = _SIMBOLOS_LOGICOS.get(no.operador, no.operador)
        return _mrow(
            f"{_mathml(no.esquerda)}<mo>{simbolo}</mo>"
            f"{_mathml(no.direita)}"
        )
    if isinstance(no, (ValorAbsoluto, Cardinalidade)):
        return _mrow(
            f'<mo stretchy="false">|</mo>{_mathml(no.expressao)}'
            f'<mo stretchy="false">|</mo>'
        )
    if isinstance(no, ConjuntoPorPropriedade):
        partes = [f"<mo>{{</mo>", _mathml(no.variavel)]
        if no.dominio is not None:
            partes.append("<mo>&#x2208;</mo>")
            partes.append(_mathml(no.dominio))
        partes.append("<mo>|</mo>")
        partes.append(_mathml(no.predicado))
        partes.append("<mo>}</mo>")
        return _mrow("".join(partes))
    if isinstance(no, Limite):
        subscrito = _mrow(
            f"{_mathml(no.variavel)}<mo>&#x2192;</mo>{_mathml(no.alvo)}"
        )
        cabeca = f"<munder><mo>lim</mo>{subscrito}</munder>"
        if no.corpo is None:
            return cabeca
        return _mrow(cabeca + _mathml(no.corpo))
    if isinstance(no, Add):
        partes = f"<mo>+</mo>".join(_mathml(t) for t in no.termos)
        return _mrow(partes)
    if isinstance(no, Subtract):
        return _mrow(
            f"{_mathml(no.left)}<mo>&#x2212;</mo>{_mathml(no.right)}"
        )
    if isinstance(no, Multiply):
        if not no.implicita:
            return _mrow("<mo>&#x22C5;</mo>".join(
                _mathml(f) for f in no.fatores
            ))
        partes = [_mathml(f) for f in no.fatores]
        numericos = [
            isinstance(f, (Integer, Numero)) for f in no.fatores
        ]
        montado = partes[0] if partes else ""
        for indice in range(1, len(partes)):
            if numericos[indice - 1] and numericos[indice]:
                montado += "<mo>&#x22C5;</mo>"
            else:
                montado += "<mo>&#x2062;</mo>"
            montado += partes[indice]
        return _mrow(montado)
    if isinstance(no, Divide):
        return (
            f"<mfrac>{_envolver(no.numerador)}"
            f"{_envolver(no.denominador)}</mfrac>"
        )
    if isinstance(no, Function):
        args = "".join(_mathml(a) for a in no.argumentos)
        interno = (
            '<mo stretchy="false">(</mo>' + args + '<mo stretchy="false">)</mo>'
            if args else ""
        )
        nome = f"<mi>{escape(no.nome)}</mi>"
        if no.indice is not None:
            nome = f"<msub>{nome}{_mathml(no.indice)}</msub>"
        return _mrow(
            f"{nome}<mo>&#x2061;</mo>{interno}"
        )
    if isinstance(no, Relation):
        partes = [_mathml(o) for o in no.operandos]
        saida = partes[0] if partes else ""
        for indice, parte in enumerate(partes[1:]):
            simbolo = _RELACAO_UNICODE.get(
                no.operador_em(indice), no.operador_em(indice)
            )
            saida += f"<mo>{escape(simbolo)}</mo>{parte}"
        return _mrow(saida)
    if isinstance(no, TextMathSequence):
        return "".join(_mathml(i) for i in no.itens)
    return ""


def _envolver(no: NoAST) -> str:
    conteudo = _mathml(no)
    if conteudo.startswith("<mrow>") or conteudo.startswith((
        "<mn>", "<mi>", "<msup>", "<msub>", "<msqrt>", "<mfrac>",
    )):
        return conteudo
    return _mrow(conteudo)


def para_texto_linear(no: NoAST) -> str:
    from pipeline.matematica.fala_matematica import gerar_fala_matematica

    return gerar_fala_matematica(no, modo="conciso").texto


_NS_OMML = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def gerar_omml(no: NoAST, envolver: bool = True) -> str:
    try:
        corpo = _omml(no)
    except Exception:
        return ""
    if not corpo:
        return ""
    if not envolver:
        return corpo
    return f'<m:oMath xmlns:m="{_NS_OMML}">{corpo}</m:oMath>'


def _texto_omml(conteudo: str, italico: bool = False) -> str:
    propriedades = (
        "<m:rPr><m:sty m:val=\"i\"/></m:rPr>" if italico else ""
    )
    return f"<m:r>{propriedades}<m:t>{escape(conteudo)}</m:t></m:r>"


def _omml(no: NoAST) -> str:
    if isinstance(no, Integer):
        return _texto_omml(str(no.valor))
    if isinstance(no, Numero):
        return _texto_omml(no.texto)
    if isinstance(no, Symbol):
        nome = _GREGAS_UNICODE.get(no.nome, no.nome)
        return _texto_omml(nome, italico=len(nome) <= 2)
    if isinstance(no, Connector):
        return _texto_omml(f" {no.texto} ")
    if isinstance(no, Desconhecido):
        return _texto_omml(no.texto) if no.texto else ""
    if isinstance(no, Group):
        return (
            "<m:d><m:dPr><m:begChr m:val=\"(\"/><m:endChr m:val=\")\"/>"
            "</m:dPr><m:e>" + _omml(no.conteudo) + "</m:e></m:d>"
        )
    if isinstance(no, UnaryMinus):
        return _texto_omml("\u2212") + _omml(no.operando)
    if isinstance(no, PlusMinus):
        if no.binaria:
            return _omml(no.esquerda) + _texto_omml("\u00B1") + _omml(no.operando)
        return _texto_omml("\u00B1") + _omml(no.operando)
    if isinstance(no, Power):
        return (
            "<m:sSup><m:e>" + _omml(no.base) + "</m:e><m:sup>"
            + _omml(no.expoente) + "</m:sup></m:sSup>"
        )
    if isinstance(no, Subscript):
        return (
            "<m:sSub><m:e>" + _omml(no.base) + "</m:e><m:sub>"
            + _omml(no.indice) + "</m:sub></m:sSub>"
        )
    if isinstance(no, OperacaoDeConjuntos):
        partes = [_omml(no.operandos[0])] if no.operandos else []
        for indice, operando in enumerate(no.operandos[1:]):
            partes.append(_texto_omml(no.operador_em(indice)))
            partes.append(_omml(operando))
        return "".join(partes)
    if isinstance(no, ConjuntoLiteral):
        interno = _texto_omml(", ").join(_omml(i) for i in no.itens)
        return _texto_omml("{") + interno + _texto_omml("}")
    if isinstance(no, Quantificador):
        from pipeline.matematica.registro_de_operadores import QUANTIFICADORES

        simbolo = next(
            (spec.forma_unicode for spec in QUANTIFICADORES.values()
             if spec.identificador == no.especie), "",
        )
        partes = [_texto_omml(simbolo), _omml(no.variavel)]
        if no.dominio is not None:
            partes.append(_texto_omml("\u2208"))
            partes.append(_omml(no.dominio))
        if no.corpo is not None:
            partes.append(_texto_omml(
                ", " if no.especie == "para_todo" else ": "
            ))
            partes.append(_omml(no.corpo))
        return "".join(partes)
    if isinstance(no, TextoLiteral):
        return _texto_omml(no.texto)
    if isinstance(no, Quantia):
        return _omml(no.valor) + _texto_omml(" " + no.unidade)
    if isinstance(no, Reticencias):
        return _texto_omml("\u2026")
    if isinstance(no, NegacaoLogica):
        return _texto_omml("\u00ac") + _omml(no.operando)
    if isinstance(no, OperacaoLogicaBinaria):
        _SIMBOLOS_LOGICOS = {
            "e_logico": "\u2227", "ou_logico": "\u2228",
            "ou_exclusivo": "\u2295", "implica": "\u2192",
            "se_e_somente_se": "\u21d4",
        }
        return (_omml(no.esquerda)
                + _texto_omml(f" {_SIMBOLOS_LOGICOS.get(no.operador, '')} ")
                + _omml(no.direita))
    if isinstance(no, (ValorAbsoluto, Cardinalidade)):
        return _texto_omml("|") + _omml(no.expressao) + _texto_omml("|")
    if isinstance(no, ConjuntoPorPropriedade):
        partes = [_texto_omml("{"), _omml(no.variavel)]
        if no.dominio is not None:
            partes.append(_texto_omml(" \u2208 "))
            partes.append(_omml(no.dominio))
        partes.append(_texto_omml(" | "))
        partes.append(_omml(no.predicado))
        partes.append(_texto_omml("}"))
        return "".join(partes)
    if isinstance(no, Limite):
        cabeca = (
            "<m:limLow><m:e><m:r><m:t>lim</m:t></m:r></m:e><m:lim>"
            + _omml(no.variavel) + _texto_omml("\u2192") + _omml(no.alvo)
            + "</m:lim></m:limLow>"
        )
        if no.corpo is None:
            return cabeca
        return cabeca + _omml(no.corpo)
    if isinstance(no, Sqrt):
        if no.indice is not None:
            return (
                "<m:rad><m:radPr><m:degHide m:val=\"0\"/></m:radPr>"
                "<m:deg>" + _omml(no.indice) + "</m:deg>"
                "<m:e>" + _omml(no.radicando) + "</m:e></m:rad>"
            )
        return (
            "<m:rad><m:radPr><m:degHide m:val=\"1\"/></m:radPr><m:deg/>"
            "<m:e>" + _omml(no.radicando) + "</m:e></m:rad>"
        )
    if isinstance(no, Add):
        return _texto_omml("+").join(_omml(t) for t in no.termos)
    if isinstance(no, Subtract):
        return _omml(no.left) + _texto_omml("\u2212") + _omml(no.right)
    if isinstance(no, Multiply):
        if not no.implicita:
            return _texto_omml("\u22C5").join(_omml(f) for f in no.fatores)
        partes = [_omml(f) for f in no.fatores]
        numericos = [isinstance(f, (Integer, Numero)) for f in no.fatores]
        montado = partes[0] if partes else ""
        for indice in range(1, len(partes)):
            if numericos[indice - 1] and numericos[indice]:
                montado += _texto_omml("\u22C5")
            montado += partes[indice]
        return montado
    if isinstance(no, Divide):
        return (
            "<m:f><m:num>" + _omml(no.numerador) + "</m:num><m:den>"
            + _omml(no.denominador) + "</m:den></m:f>"
        )
    if isinstance(no, Function):
        argumentos = "".join(_omml(a) for a in no.argumentos)
        interno = (
            "<m:d><m:dPr><m:begChr m:val=\"(\"/><m:endChr m:val=\")\"/>"
            "</m:dPr><m:e>" + argumentos + "</m:e></m:d>"
            if argumentos else ""
        )
        return "<m:func><m:fName>" + _texto_omml(no.nome) + \
            "</m:fName><m:e>" + interno + "</m:e></m:func>"
    if isinstance(no, Relation):
        partes = [_omml(o) for o in no.operandos]
        saida = partes[0] if partes else ""
        for indice, parte in enumerate(partes[1:]):
            simbolo = _RELACAO_UNICODE.get(
                no.operador_em(indice), no.operador_em(indice)
            )
            saida += _texto_omml(simbolo) + parte
        return saida
    if isinstance(no, TextMathSequence):
        return "".join(_omml(i) for i in no.itens)
    return ""


gerar_latex = para_latex
gerar_mathml = para_mathml


def adicionar_ids_de_navegacao(mathml: str, math_id: str) -> str:
    if not mathml or not math_id:
        return mathml
    import re as _re

    contador = {"n": 0}

    def _com_id(casado: "_re.Match[str]") -> str:
        contador["n"] += 1
        tag = casado.group(1)
        return f'<{tag} id="{math_id}-no{contador["n"]}">'

    return _re.sub(r"<(mfrac|msqrt|msup|msub|mroot)>", _com_id, mathml)
