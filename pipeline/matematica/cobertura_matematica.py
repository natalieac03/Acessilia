"""Os validadores — o portao que decide se a formula pode sair.

Comparam o que entrou com o que a arvore entendeu: operador que sumiu,
expoente que virou multiplicacao, raiz sem radicando, passo de uma
cadeia de igualdade suprimido, simbolo cru sobrando na fala, palavra
em ingles na saida pt-BR, MathML invalido ou com atributo duplicado,
texto de titulo que vazou para dentro do no matematico.

Cada verificacao nasceu de um erro que apareceu de verdade em
material processado. A politica e deliberada: bloquear demais e melhor
que publicar errado, porque formula errada com cara de certa e o pior
resultado possivel — o aluno cego nao tem como desconfiar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.matematica.arvore_matematica import (
    Desconhecido,
    Divide,
    Group,
    Multiply,
    NoAST,
    PlusMinus,
    Power,
    Relation,
    Sqrt,
    Subscript,
    Subtract,
    UnaryMinus,
)

_SOBRESCRITOS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUBSCRITOS = "₀₁₂₃₄₅₆₇₈₉"


@dataclass
class ValidationIssue:

    check: str
    severity: str
    message: str
    how_to_fix: str = ""
    evidencia: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class RelatorioCobertura:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def bloqueia_publicacao(self) -> bool:
        return any(i.severity == "BLOCKER" for i in self.issues)

    @property
    def aprovada(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {
            "issues": [i.to_dict() for i in self.issues],
            "bloqueia_publicacao": self.bloqueia_publicacao,
            "aprovada": self.aprovada,
        }


def _nos(ast: NoAST, tipo) -> list:
    if ast is None:
        return []
    return [n for n in ast.percorrer() if isinstance(n, tipo)]


def _texto_de_origem(evidence, fallback: str = "") -> str:
    if evidence is None:
        return fallback
    if isinstance(evidence, str):
        return evidence
    return getattr(evidence, "raw_text", "") or fallback


def _fala(speech) -> str:
    if speech is None:
        return ""
    if isinstance(speech, str):
        return speech.lower()
    return (getattr(speech, "texto", "") or "").lower()


def validar_menos(origem: str, ast: NoAST, fala: str) -> list[ValidationIssue]:
    quantos = len(re.findall(r"[-−–]", origem))
    if not quantos:
        return []
    nos = len(_nos(ast, UnaryMinus)) + len(_nos(ast, Subtract))
    nos += len([n for n in _nos(ast, PlusMinus)])
    if nos == 0:
        return [ValidationIssue(
            check="validar_menos", severity="BLOCKER",
            message=(f"a origem tem {quantos} sinal(is) de menos, mas a AST "
                     "nao tem nenhum no de subtracao ou menos unario"),
            how_to_fix="reprocessar a expressao; o sinal foi descartado",
            evidencia=origem[:80],
        )]
    if fala and "menos" not in fala:
        return [ValidationIssue(
            check="validar_menos", severity="ERROR",
            message="a AST tem menos, mas a fala nao diz 'menos'",
            how_to_fix="regerar a fala a partir da AST",
            evidencia=fala[:80],
        )]
    return []


def validar_expoentes(origem: str, ast: NoAST, fala: str,
                      evidence=None) -> list[ValidationIssue]:
    quantos = sum(1 for c in origem if c in _SOBRESCRITOS)
    quantos += len(re.findall(r"\^", origem))
    if evidence is not None and not isinstance(evidence, str):
        quantos += len(getattr(evidence, "superscript_candidates", []) or [])
    if not quantos:
        return []
    potencias = _nos(ast, Power)
    from pipeline.matematica.arvore_matematica import Quantia as _Qt

    realizadas = len(potencias) + sum(
        1 for q in _nos(ast, _Qt) if "²" in q.unidade
    )
    if not realizadas:
        return [ValidationIssue(
            check="validar_expoentes", severity="BLOCKER",
            message=(f"a origem indica {quantos} expoente(s), mas a AST nao "
                     "tem nenhum no Power"),
            how_to_fix=("verificar a geometria: o expoente pode ter sido "
                        "achatado pelo extrator"),
            evidencia=origem[:80],
        )]
    if fala and not any(p in fala for p in ("quadrado", "cubo", "elevado")):
        return [ValidationIssue(
            check="validar_expoentes", severity="ERROR",
            message="ha potencia na AST, mas a fala nao a realiza",
            how_to_fix="regerar a fala a partir da AST",
            evidencia=fala[:80],
        )]
    return []


def validar_subscritos(origem: str, ast: NoAST, fala: str,
                       evidence=None) -> list[ValidationIssue]:
    quantos = sum(1 for c in origem if c in _SUBSCRITOS)
    quantos += len(re.findall(r"_", origem))
    if evidence is not None and not isinstance(evidence, str):
        quantos += len(getattr(evidence, "subscript_candidates", []) or [])
    if not quantos:
        return []
    from pipeline.matematica.arvore_matematica import Function as _Fn, Limite as _Lim

    realizados = len(_nos(ast, Subscript))
    realizados += sum(1 for f in _nos(ast, _Fn) if f.indice is not None)
    realizados += len(_nos(ast, _Lim))
    if not realizados:
        return [ValidationIssue(
            check="validar_subscritos", severity="BLOCKER",
            message=(f"a origem indica {quantos} indice(s), mas a AST nao tem "
                     "nenhum no Subscript"),
            how_to_fix="reprocessar; o indice foi perdido na extracao",
            evidencia=origem[:80],
        )]
    return []


_LETRAS_QUE_SAO_PALAVRAS = {"a", "e", "o", "à", "é"}
_SIMBOLOS_PROIBIDOS_NO_TXT = set("0123456789+=^_*/\\<>{}[]|%")


_INGLES_PROIBIDO = {
    "sub", "squared", "cubed", "cap", "over", "equals", "square",
    "root", "superscript", "subscript", "divided", "fraction",
    "times", "plus", "minus", "equal",
}


def validar_mathml_valido(mathml: str) -> list[ValidationIssue]:
    if not mathml:
        return []
    import re as _re
    import xml.etree.ElementTree as _ET

    issues: list[ValidationIssue] = []
    try:
        _ET.fromstring(mathml)
    except _ET.ParseError as erro:
        issues.append(ValidationIssue(
            check="validar_mathml_valido", severity="BLOCKER",
            message=f"MathML nao e XML valido: {erro}",
            how_to_fix=("nenhuma etapa pode INJETAR atributos por "
                        "string em um <math> pronto; atributos nascem "
                        "na serializacao"),
            evidencia=mathml[:80],
        ))
        return issues
    ids = _re.findall(r'\bid="([^"]+)"', mathml)
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        issues.append(ValidationIssue(
            check="validar_mathml_valido", severity="BLOCKER",
            message="ids repetidos no MathML: " + ", ".join(repetidos),
            how_to_fix="ids de navegacao devem ser unicos por formula",
            evidencia=mathml[:80],
        ))
    return issues


def validar_idioma_da_fala(fala: str) -> list[ValidationIssue]:
    if not fala:
        return []
    palavras = set(re.findall(r"[a-z]+", fala.lower()))
    inglesas = sorted(palavras & _INGLES_PROIBIDO)
    if not inglesas:
        return []
    return [ValidationIssue(
        check="validar_idioma_da_fala", severity="BLOCKER",
        message=("a fala contem palavra inglesa: "
                 + ", ".join(inglesas)),
        how_to_fix=("a leitura deve nascer em portugues do planejador; "
                    "nunca traduzir depois uma frase inglesa"),
        evidencia=fala[:80],
    )]


def validar_texto_incorporado(ast: NoAST) -> list[ValidationIssue]:
    from pipeline.matematica.arvore_matematica import Symbol as _Sym

    for no in ast.percorrer():
        if not isinstance(no, Multiply):
            continue
        seguidas = 0
        for fator in no.fatores:
            if (isinstance(fator, _Sym) and len(fator.nome) == 1
                    and fator.nome.isalpha()):
                seguidas += 1
                if seguidas >= 5:
                    return [ValidationIssue(
                        check="validar_texto_incorporado",
                        severity="BLOCKER",
                        message=("sequencia de letras soltas parece "
                                 "TEXTO incorporado a formula "
                                 "(titulo ou legenda vazou para o no "
                                 "matematico)"),
                        how_to_fix=("revisar o recorte da regiao: o "
                                    "texto vizinho entrou na formula"),
                        evidencia="".join(
                            f.nome for f in no.fatores
                            if isinstance(f, _Sym)
                        )[:40],
                    )]
            else:
                seguidas = 0
    return []


def validar_fala_por_extenso(fala: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not fala:
        return issues
    encontrados = sorted({c for c in fala
                          if c in _SIMBOLOS_PROIBIDOS_NO_TXT})
    if encontrados:
        issues.append(ValidationIssue(
            check="validar_fala_por_extenso", severity="BLOCKER",
            message=("a fala contem simbolo cru em vez de palavras: "
                     + " ".join(repr(c) for c in encontrados)),
            how_to_fix="todo numero e operador deve sair por extenso "
                       "do planejador de fala",
            evidencia=fala[:80],
        ))
    return issues


def validar_estruturas_semanticas(ast: NoAST) -> list[ValidationIssue]:
    from pipeline.matematica.arvore_matematica import (
        Desconhecido as _Desc,
        Function as _Fn,
        Limite as _Lim,
        Power as _Pow,
        Quantificador as _Quant,
        Subscript as _Sub,
    )

    issues: list[ValidationIssue] = []

    def _vazio(no) -> bool:
        return no is None or (
            isinstance(no, _Desc) and not (no.texto or "").strip()
        )

    for no in ast.percorrer():
        if isinstance(no, _Quant) and no.corpo is None:
            issues.append(ValidationIssue(
                check="validar_estruturas_semanticas", severity="BLOCKER",
                message=("quantificador sem corpo: a afirmacao logica "
                         "esta incompleta"),
                how_to_fix="verificar se o predicado ficou fora do recorte",
                evidencia=no.especie,
            ))
        if isinstance(no, _Lim):
            if _vazio(no.corpo) or _vazio(no.variavel) or _vazio(no.alvo):
                issues.append(ValidationIssue(
                    check="validar_estruturas_semanticas",
                    severity="BLOCKER",
                    message=("limite sem variavel, alvo ou expressao"),
                    how_to_fix="reprocessar o recorte do limite",
                    evidencia="lim",
                ))
        if isinstance(no, _Fn) and no.indice is not None:
            if not no.argumentos or all(_vazio(a) for a in no.argumentos):
                issues.append(ValidationIssue(
                    check="validar_estruturas_semanticas",
                    severity="BLOCKER",
                    message=(f"{no.nome} com indice mas sem argumento"),
                    how_to_fix="verificar se o argumento ficou fora do "
                               "recorte",
                    evidencia=no.nome,
                ))
        if isinstance(no, (_Pow, _Sub)):
            filho = (no.expoente if isinstance(no, _Pow) else no.indice)
            if isinstance(filho, _Desc) and (filho.texto or "").strip():
                issues.append(ValidationIssue(
                    check="validar_estruturas_semanticas",
                    severity="BLOCKER",
                    message=("sobrescrito/subscrito com conteudo nao "
                             f"analisado: {filho.texto[:30]!r}"),
                    how_to_fix="analisar o marcador recursivamente",
                    evidencia=filho.texto[:40],
                ))
    return issues


def validar_radicandos(ast: NoAST, fala: str) -> list[ValidationIssue]:
    issues = []
    for raiz in _nos(ast, Sqrt):
        vazio = isinstance(raiz.radicando, Desconhecido) and not (
            raiz.radicando.texto or ""
        ).strip()
        if vazio:
            issues.append(ValidationIssue(
                check="validar_radicandos", severity="BLOCKER",
                message="radical sem radicando na AST",
                how_to_fix=("expandir a fronteira da expressao: o radicando "
                            "provavelmente ficou em outro fragmento"),
            ))
    if _nos(ast, Sqrt) and fala:
        if re.search(r"raiz quadrada( de)?\s*$", fala):
            issues.append(ValidationIssue(
                check="validar_radicandos", severity="BLOCKER",
                message="a fala termina em 'raiz quadrada de' sem radicando",
                how_to_fix="regerar a fala a partir da AST completa",
                evidencia=fala[-60:],
            ))
    return issues


def _tem_coeficiente_colado(origem: str, tokens: list | None) -> bool:
    if tokens:
        from pipeline.matematica.arvore_matematica import (
            _FUNCOES_COM_SUBSCRITO,
            _FUNCOES_SEM_PARENTESES,
        )

        anterior = None
        anterior_token = None
        for token in tokens:
            kind = getattr(token, "kind", "")
            if kind == "IMPLICIT_MULTIPLICATION":
                if (anterior == "IDENT" and anterior_token is not None
                        and str(getattr(anterior_token, "value", "")
                                ).lower() in _FUNCOES_SEM_PARENTESES):
                    anterior = kind
                    continue
                if (anterior == "SUBSCRIPT" and anterior_token is not None
                        and str(getattr(anterior_token, "attached_to", "")
                                ).lower() in _FUNCOES_COM_SUBSCRITO):
                    anterior = kind
                    continue
                return True
            if anterior == "NUMBER" and kind in ("IDENT", "FUNCTION"):
                return True
            if kind not in ("IMPLICIT_MULTIPLICATION",):
                anterior = kind
                anterior_token = token
        return False
    sem_comandos = re.sub(r"\\[A-Za-z]+", " ", origem or "")
    return bool(re.search(r"\d\s*[A-Za-z]|[A-Za-z]\s*\d", sem_comandos))


def validar_multiplicacao_implicita(origem: str, ast: NoAST,
                                    fala: str,
                                    tokens: list | None = None,
                                    ) -> list[ValidationIssue]:
    issues = []
    implicitas = [m for m in _nos(ast, Multiply) if m.implicita]
    tem_colado = _tem_coeficiente_colado(origem, tokens)
    if tem_colado and not implicitas and not _nos(ast, Power) \
            and not _nos(ast, Subscript):
        issues.append(ValidationIssue(
            check="validar_multiplicacao_implicita", severity="ERROR",
            message=("a origem tem coeficiente colado (ex.: '2a') mas a AST "
                     "nao registra multiplicacao implicita"),
            how_to_fix="verificar a tokenizacao do coeficiente",
            evidencia=origem[:80],
        ))
    if fala:
        fala_sem_unidades = fala.replace("por segundo", " ")
        for ordinal in ("segunda", "segundo", "terceira", "terceiro",
                        "primeira", "primeiro"):
            if ordinal in fala_sem_unidades:
                issues.append(ValidationIssue(
                    check="validar_multiplicacao_implicita",
                    severity="BLOCKER",
                    message=(f"a fala contem o ordinal '{ordinal}': o TTS "
                             "interpretou um coeficiente como palavra"),
                    how_to_fix=("a fala precisa vir do planejador (Etapa 8), "
                                "nunca do texto bruto"),
                    evidencia=fala[:80],
                ))
                break
    return issues


def validar_parenteses(origem: str, ast: NoAST,
                       mathml: str = "") -> list[ValidationIssue]:
    issues = []
    saldo = origem.count("(") - origem.count(")")
    if saldo != 0:
        issues.append(ValidationIssue(
            check="validar_parenteses", severity="BLOCKER",
            message=f"parenteses desbalanceados na origem (saldo {saldo})",
            how_to_fix=("reunir os fragmentos adjacentes antes de tokenizar "
                        "(Etapa 1/4)"),
            evidencia=origem[:80],
        ))
        return issues
    grupos_origem = origem.count("(")
    grupos_ast = len(_nos(ast, Group))
    if grupos_origem and grupos_ast == 0 and "(" in origem:
        from pipeline.matematica.arvore_matematica import Function

        if not _nos(ast, Function):
            issues.append(ValidationIssue(
                check="validar_parenteses", severity="WARNING",
                message=("a origem tem parenteses, mas a AST nao registra "
                         "nenhum agrupamento"),
                how_to_fix="conferir se o agrupamento altera a leitura",
                evidencia=origem[:80],
            ))
    return issues


def validar_cadeia_de_igualdade(origem: str, ast: NoAST,
                                fala: str) -> list[ValidationIssue]:
    relacoes_origem = len(re.findall(r"=", origem))
    if relacoes_origem < 2:
        return []
    cadeias = _nos(ast, Relation)
    passos_ast = sum(
        max(0, len(c.operandos) - 1) for c in cadeias
    )
    if passos_ast < relacoes_origem:
        return [ValidationIssue(
            check="validar_cadeia_de_igualdade", severity="BLOCKER",
            message=(f"a origem tem {relacoes_origem} igualdades e a AST "
                     f"apenas {passos_ast}: um passo do calculo foi suprimido"),
            how_to_fix=("transcrever a cadeia inteira; passos intermediarios "
                        "sao conteudo pedagogico"),
            evidencia=origem[:80],
        )]
    if fala:
        ditos = fala.count("igual")
        if ditos < relacoes_origem:
            return [ValidationIssue(
                check="validar_cadeia_de_igualdade", severity="ERROR",
                message=(f"a fala realiza {ditos} de {relacoes_origem} "
                         "igualdades da cadeia"),
                how_to_fix="regerar a fala a partir da AST",
                evidencia=fala[:100],
            )]
    return []


_IGNORAVEIS = {"left", "right", "frac", "sqrt", "cdot", "operatorname",
               "text", "pm", "displaystyle", "mathrm"}


def _termos_da_origem(origem: str, tokens: list | None) -> tuple[set, set]:
    if tokens:
        numeros = {
            t.value for t in tokens
            if getattr(t, "kind", "") == "NUMBER"
        }
        variaveis = {
            t.value for t in tokens
            if getattr(t, "kind", "") in ("IDENT", "FUNCTION")
        }
        return numeros, variaveis

    sem_comandos = re.sub(r"\\[A-Za-z]+", " ", origem or "")
    numeros = set(re.findall(r"\d+", re.sub(r"[⁰-⁹₀-₉]", "", sem_comandos)))
    variaveis = set(re.findall(r"[A-Za-z]", sem_comandos))
    return numeros, variaveis


def validar_termos_preservados(origem: str, ast: NoAST,
                               latex: str = "",
                               tokens: list | None = None,
                               ) -> list[ValidationIssue]:
    from pipeline.matematica.arvore_matematica import Connector, Integer, Numero, Symbol

    numeros_origem, variaveis_origem = _termos_da_origem(origem, tokens)
    numeros_ast = {str(n.valor) for n in _nos(ast, Integer)}
    numeros_ast |= {n.texto for n in _nos(ast, Numero)}
    variaveis_ast = {s.nome for s in _nos(ast, Symbol)}
    variaveis_ast |= {c for s in _nos(ast, Symbol) for c in s.nome}
    for conector in _nos(ast, Connector):
        variaveis_ast |= set(conector.texto)
    from pipeline.matematica.arvore_matematica import Function

    for funcao in _nos(ast, Function):
        variaveis_ast |= set(funcao.nome)
        variaveis_ast.add(funcao.nome)
    from pipeline.matematica.arvore_matematica import Limite as _Lim

    if _nos(ast, _Lim):
        variaveis_ast.add("lim")

    faltando_numeros = {n for n in numeros_origem if n not in numeros_ast}
    faltando_variaveis = {
        v for v in variaveis_origem
        if v not in variaveis_ast and v.lower() not in {
            x.lower() for x in variaveis_ast
        }
    }
    issues = []
    if faltando_numeros:
        issues.append(ValidationIssue(
            check="validar_termos_preservados", severity="BLOCKER",
            message=("numeros da origem ausentes na AST: "
                     + ", ".join(sorted(faltando_numeros))),
            how_to_fix="reprocessar a expressao sem simplificar",
            evidencia=origem[:80],
        ))
    if faltando_variaveis:
        issues.append(ValidationIssue(
            check="validar_termos_preservados", severity="ERROR",
            message=("variaveis da origem ausentes na AST: "
                     + ", ".join(sorted(faltando_variaveis))),
            how_to_fix="conferir a tokenizacao dos identificadores",
            evidencia=origem[:80],
        ))
    return issues


def validar_cobertura_simbolica(
    evidence=None,
    ast: NoAST | None = None,
    speech=None,
    latex: str = "",
    mathml: str = "",
    origem: str = "",
    nao_consumidos: list | None = None,
    tokens: list | None = None,
    plano_de_fala=None,
) -> RelatorioCobertura:
    texto = _texto_de_origem(evidence, origem) or origem
    fala = _fala(speech)
    issues: list[ValidationIssue] = []

    verificacoes = (
        lambda: validar_menos(texto, ast, fala),
        lambda: validar_expoentes(texto, ast, fala, evidence),
        lambda: validar_subscritos(texto, ast, fala, evidence),
        lambda: validar_radicandos(ast, fala),
        lambda: validar_estruturas_semanticas(ast),
        lambda: validar_fala_por_extenso(fala),
        lambda: validar_idioma_da_fala(fala),
        lambda: validar_texto_incorporado(ast),
        lambda: validar_multiplicacao_implicita(texto, ast, fala, tokens),
        lambda: validar_parenteses(texto, ast, mathml),
        lambda: validar_mathml_valido(mathml),
        lambda: validar_cadeia_de_igualdade(texto, ast, fala),
        lambda: validar_termos_preservados(texto, ast, latex, tokens),
    )
    for verificacao in verificacoes:
        try:
            issues.extend(verificacao() or [])
        except Exception as erro:
            issues.append(ValidationIssue(
                check="interno", severity="INFO",
                message=f"verificacao falhou: {type(erro).__name__}: {erro}",
            ))

    if ast is not None:
        lacunas = [
            n for n in _nos(ast, Desconhecido) if (n.texto or "").strip()
        ]
        if lacunas:
            issues.append(ValidationIssue(
                check="ast_com_lacuna", severity="BLOCKER",
                message=("a AST tem trecho(s) nao interpretado(s): "
                         + ", ".join(repr(n.texto) for n in lacunas[:3])),
                how_to_fix=("resolver com contexto (Etapa 7) ou enviar para "
                            "revisao humana"),
            ))
    if nao_consumidos:
        descartados = [
            getattr(t, "value", str(t)) for t in nao_consumidos
        ]
        issues.append(ValidationIssue(
            check="tokens_descartados", severity="BLOCKER",
            message=("o parser deixou de fora "
                     f"{len(descartados)} token(s) da origem: "
                     + " ".join(descartados[:6])),
            how_to_fix=("a expressao tem notacao que o parser nao cobre; "
                        "resolver com contexto (Etapa 7) ou revisao humana"),
            evidencia=texto[:80],
        ))
    if speech is not None and getattr(speech, "tem_lacuna", False):
        issues.append(ValidationIssue(
            check="fala_com_lacuna", severity="ERROR",
            message="a fala planejada registrou lacuna",
            how_to_fix="ver os avisos do SpeechPlan",
            evidencia="; ".join(getattr(speech, "avisos", [])[:2]),
        ))
    return RelatorioCobertura(issues=issues)


def auditar_expressao(texto: str, geometria=None, modo: str = "estrutural") -> dict:
    from pipeline.matematica.arvore_matematica import construir_ast
    from pipeline.matematica.serializacao_matematica import para_latex, para_mathml
    from pipeline.matematica.fala_matematica import gerar_fala_matematica

    resultado = construir_ast(texto, geometria)
    latex = para_latex(resultado.ast)
    mathml = para_mathml(resultado.ast, latex)
    fala = gerar_fala_matematica(resultado.ast, modo=modo)
    cobertura = validar_cobertura_simbolica(
        evidence=texto, ast=resultado.ast, speech=fala,
        latex=latex, mathml=mathml,
        nao_consumidos=resultado.nao_consumidos,
    )
    return {
        "origem": texto,
        "ast": resultado.ast.to_dict(),
        "latex": latex,
        "mathml": mathml,
        "fala": fala.texto,
        "parse_completo": resultado.completa,
        "cobertura": cobertura.to_dict(),
        "publicavel": not cobertura.bloqueia_publicacao,
    }


_ESTRUTURAS = (
    (Divide, r"\frac", ("<mfrac>",), "fracao"),
    (Sqrt, r"\sqrt", ("<msqrt>", "<mroot>"), "radical"),
    (Power, "^", ("<msup>",), "potencia"),
    (Subscript, "_", ("<msub>",), "indice"),
)


def validar_serializacoes(
    ast: NoAST | None, latex: str = "", mathml: str = "", omml: str = "",
) -> list[ValidationIssue]:
    if ast is None:
        return [ValidationIssue(
            check="validar_serializacoes", severity="BLOCKER",
            message="AST ausente: nada a serializar",
        )]

    issues: list[ValidationIssue] = []
    for tipo, marca_latex, marcas_mathml, nome in _ESTRUTURAS:
        quantos = len(_nos(ast, tipo))
        if not quantos:
            continue
        if latex and marca_latex not in latex:
            issues.append(ValidationIssue(
                check="validar_serializacoes", severity="ERROR",
                message=(f"a AST tem {quantos} {nome}(s) mas o LaTeX nao "
                         f"traz '{marca_latex}'"),
                how_to_fix="regerar o LaTeX a partir da AST",
                evidencia=latex[:80],
            ))
        if mathml and not any(m in mathml for m in marcas_mathml):
            issues.append(ValidationIssue(
                check="validar_serializacoes", severity="BLOCKER",
                message=(f"a AST tem {quantos} {nome}(s) mas o MathML nao "
                         f"traz {' nem '.join(marcas_mathml)}"),
                how_to_fix=("regerar o MathML a partir da AST; sem a "
                            "estrutura o leitor de tela nao navega"),
                evidencia=mathml[:100],
            ))

    if omml:
        if _nos(ast, Divide) and "<m:f" not in omml:
            issues.append(ValidationIssue(
                check="validar_serializacoes", severity="ERROR",
                message="a AST tem fracao mas o OMML nao traz <m:f>",
                how_to_fix="regerar o OMML a partir da AST",
            ))
        if _nos(ast, Sqrt) and "<m:rad" not in omml:
            issues.append(ValidationIssue(
                check="validar_serializacoes", severity="ERROR",
                message="a AST tem radical mas o OMML nao traz <m:rad>",
                how_to_fix="regerar o OMML a partir da AST",
            ))

    if mathml and "<mo>/</mo>" in mathml:
        issues.append(ValidationIssue(
            check="validar_serializacoes", severity="BLOCKER",
            message="o MathML traz <mo>/</mo> em vez de <mfrac>",
            how_to_fix="a divisao deve virar fracao estrutural",
        ))
    return issues


def _normalizar_chave(texto: str) -> str:
    return re.sub(r"\s+", "", (texto or "").lower())


def comparar_formulas_repetidas(documento) -> list[ValidationIssue]:
    ocorrencias: dict[str, list[dict]] = {}

    def _registrar(origem: str, latex: str, fala: str, mathml: str = ""):
        chave = _normalizar_chave(origem)
        if not chave:
            return
        ocorrencias.setdefault(chave, []).append({
            "origem": origem, "latex": (latex or "").strip(),
            "fala": (fala or "").strip(), "mathml": (mathml or "").strip(),
        })

    try:
        if isinstance(documento, dict):
            for secao in documento.get("sections", []) or []:
                _varrer_secao(secao, _registrar)
        else:
            for item in documento or []:
                if hasattr(item, "nos_matematicos"):
                    for no in item.nos_matematicos():
                        _registrar(no.source_text, no.latex, no.speech_pt_br,
                                   no.mathml)
                elif hasattr(item, "source_text"):
                    _registrar(
                        item.source_text, getattr(item, "latex", ""),
                        getattr(item, "speech_pt_br", ""),
                        getattr(item, "mathml", ""),
                    )
    except Exception as erro:
        return [ValidationIssue(
            check="comparar_formulas_repetidas", severity="INFO",
            message=f"comparacao falhou: {type(erro).__name__}: {erro}",
        )]

    issues: list[ValidationIssue] = []
    for chave, lista in sorted(ocorrencias.items()):
        if len(lista) < 2:
            continue
        latex_distintos = {o["latex"] for o in lista if o["latex"]}
        falas_distintas = {o["fala"] for o in lista if o["fala"]}
        if len(latex_distintos) > 1:
            issues.append(ValidationIssue(
                check="comparar_formulas_repetidas", severity="BLOCKER",
                message=(f"a expressao {lista[0]['origem']!r} aparece "
                         f"{len(lista)}x com {len(latex_distintos)} LaTeX "
                         "diferentes"),
                how_to_fix=("uma das leituras esta errada; conferir as duas "
                            "contra a imagem e unificar"),
                evidencia=" | ".join(sorted(latex_distintos)[:2]),
            ))
        elif len(falas_distintas) > 1:
            issues.append(ValidationIssue(
                check="comparar_formulas_repetidas", severity="ERROR",
                message=(f"a expressao {lista[0]['origem']!r} aparece "
                         f"{len(lista)}x com falas diferentes"),
                how_to_fix="unificar a fala (o modo pode variar por secao)",
                evidencia=" | ".join(sorted(falas_distintas)[:2]),
            ))
    return issues


def _varrer_secao(secao: dict, registrar) -> None:
    for bloco in secao.get("blocks", []) or []:
        if bloco.get("type") == "math":
            registrar(
                (bloco.get("metadata") or {}).get("origem")
                or bloco.get("source_text") or bloco.get("text", ""),
                bloco.get("latex", ""), bloco.get("speech_pt_br")
                or bloco.get("text", ""), bloco.get("mathml", ""),
            )
        for filho in bloco.get("children", []) or []:
            if isinstance(filho, dict) and filho.get("type") == "math":
                registrar(
                    filho.get("source_text", ""), filho.get("latex", ""),
                    filho.get("speech_pt_br", ""), filho.get("mathml", ""),
                )
    for filha in secao.get("children", []) or []:
        _varrer_secao(filha, registrar)


def aplicar_portao_de_publicacao(relatorio) -> dict:
    issues: list[dict] = []
    if hasattr(relatorio, "issues"):
        origem = relatorio.issues
    else:
        origem = relatorio or []
    for item in origem:
        if isinstance(item, ValidationIssue):
            issues.append(item.to_dict())
        elif isinstance(item, dict):
            issues.append(item)

    contagem = {"BLOCKER": 0, "ERROR": 0, "WARNING": 0, "INFO": 0}
    for issue in issues:
        severidade = str(issue.get("severity", "INFO")).upper()
        if severidade in contagem:
            contagem[severidade] += 1

    bloqueadores = [i for i in issues
                    if str(i.get("severity", "")).upper() == "BLOCKER"]
    if bloqueadores:
        decisao, status = False, "blocked"
    elif contagem["ERROR"]:
        decisao, status = False, "needs_review"
    elif contagem["WARNING"]:
        decisao, status = True, "publicavel_com_avisos"
    else:
        decisao, status = True, "aprovado"

    return {
        "publicar_como_final": decisao,
        "status": status,
        "contagem": contagem,
        "bloqueadores": [i.get("message", "") for i in bloqueadores],
        "gerar_rascunho": not decisao,
        "review_status_sugerido": (
            "needs_review" if not decisao else "reviewed"
        ),
    }


def analisar_mathml(mathml: str):
    from xml.etree import ElementTree

    from pipeline.matematica.arvore_matematica import (
        Add,
        Desconhecido,
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

    _GREGA_PARA_NOME = {
        "\u0394": "Delta", "\u03b4": "delta", "\u03c0": "pi",
        "\u03b1": "alpha", "\u03b2": "beta", "\u03b8": "theta",
        "\u03c3": "sigma", "\u03c9": "omega", "\u03a3": "Sigma",
    }
    _RELACOES = {"=": "=", "\u2265": ">=", "\u2264": "<=", "\u2260": "!=",
                 ">": ">", "<": "<"}

    def _tag(elemento) -> str:
        return elemento.tag.split("}")[-1]

    def _texto(elemento) -> str:
        return (elemento.text or "").strip()

    def _converter(elemento):
        nome = _tag(elemento)
        filhos = [f for f in elemento if _tag(f) != "annotation"]

        if nome == "math":
            return _sequencia(filhos)
        if nome == "semantics":
            return _sequencia(filhos)
        if nome == "mrow":
            return _sequencia(filhos)
        if nome == "mn":
            bruto = _texto(elemento)
            if bruto.isdigit():
                return Integer(valor=int(bruto))
            return Numero(texto=bruto)
        if nome == "mi":
            bruto = _texto(elemento)
            return Symbol(nome=_GREGA_PARA_NOME.get(bruto, bruto))
        if nome == "mtext":
            return Desconhecido(texto=_texto(elemento))
        if nome == "mfrac" and len(filhos) >= 2:
            return Divide(numerador=_converter(filhos[0]),
                          denominador=_converter(filhos[1]))
        if nome == "msqrt":
            return Sqrt(radicando=_sequencia(filhos))
        if nome == "msup" and len(filhos) >= 2:
            return Power(base=_converter(filhos[0]),
                         expoente=_converter(filhos[1]))
        if nome == "msub" and len(filhos) >= 2:
            return Subscript(base=_converter(filhos[0]),
                             indice=_converter(filhos[1]))
        if nome == "mo":
            return Desconhecido(texto=_texto(elemento))
        return _sequencia(filhos) if filhos else Desconhecido(texto="")

    def _sequencia(elementos):
        pecas = []
        for elemento in elementos:
            nome = _tag(elemento)
            if nome == "annotation":
                continue
            if nome == "mo":
                pecas.append(("op", _texto(elemento)))
            else:
                pecas.append(("no", _converter(elemento)))

        pecas = _agrupar_parenteses(pecas)

        operadores_relacionais = [
            i for i, (tipo, valor) in enumerate(pecas)
            if tipo == "op" and valor in _RELACOES
        ]
        if operadores_relacionais:
            simbolo = pecas[operadores_relacionais[0]][1]
            operandos, atual = [], []
            for tipo, valor in pecas:
                if tipo == "op" and valor in _RELACOES:
                    operandos.append(_reduzir(atual))
                    atual = []
                else:
                    atual.append((tipo, valor))
            operandos.append(_reduzir(atual))
            return Relation(operador=_RELACOES[simbolo], operandos=operandos)
        return _reduzir(pecas)

    def _agrupar_parenteses(pecas):
        resultado, pilha = [], []
        for tipo, valor in pecas:
            if tipo == "op" and valor in ("(",):
                pilha.append(len(resultado))
                continue
            if tipo == "op" and valor in (")",) and pilha:
                inicio = pilha.pop()
                interno = resultado[inicio:]
                del resultado[inicio:]
                resultado.append(("no", Group(conteudo=_reduzir(interno))))
                continue
            resultado.append((tipo, valor))
        return resultado

    def _reduzir(pecas):
        if not pecas:
            return Desconhecido(texto="")
        nos_e_ops = [p for p in pecas]
        if nos_e_ops[0][0] == "op" and nos_e_ops[0][1] in ("\u2212", "-"):
            resto = _reduzir(nos_e_ops[1:])
            return UnaryMinus(operando=resto)
        if nos_e_ops[0][0] == "op" and nos_e_ops[0][1] == "\u00b1":
            return PlusMinus(operando=_reduzir(nos_e_ops[1:]))

        atual = nos_e_ops[0][1] if nos_e_ops[0][0] == "no" else \
            Desconhecido(texto=str(nos_e_ops[0][1]))
        indice = 1
        while indice < len(nos_e_ops):
            tipo, valor = nos_e_ops[indice]
            if tipo != "op":
                atual = Multiply(fatores=[atual, valor],
                                 source_notation="implicit")
                indice += 1
                continue
            direita_pecas = nos_e_ops[indice + 1:]
            if valor in ("+",):
                atual = Add(termos=[atual, _reduzir(direita_pecas)])
                break
            if valor in ("\u2212", "-"):
                atual = Subtract(left=atual, right=_reduzir(direita_pecas))
                break
            if valor in ("\u00b1",):
                atual = PlusMinus(esquerda=atual,
                                  operando=_reduzir(direita_pecas))
                break
            if valor in ("\u22c5", "*", "\u00d7"):
                atual = Multiply(fatores=[atual, _reduzir(direita_pecas)],
                                 source_notation="dot")
                break
            if valor in ("\u2061",):
                indice += 1
                continue
            indice += 1
        return atual

    try:
        raiz = ElementTree.fromstring(mathml)
    except Exception:
        return None
    try:
        return _converter(raiz)
    except Exception:
        return None


def canonizar_para_comparacao(ast) -> dict:
    from pipeline.matematica.nos_matematicos import remover_espacos_e_estilo

    if ast is None:
        return {}
    return remover_espacos_e_estilo(ast)


def comparar_latex_e_mathml(
    latex: str, mathml: str,
) -> list[ValidationIssue]:
    if not latex or not mathml:
        return []
    from pipeline.matematica.arvore_matematica import construir_ast
    from pipeline.matematica.problemas_matematicos import assinatura_da_ast

    ast_latex = construir_ast(latex).ast
    ast_mathml = analisar_mathml(mathml)
    if ast_mathml is None:
        return [ValidationIssue(
            check="comparar_latex_e_mathml", severity="BLOCKER",
            message="o MathML gerado nao pode ser reparseado",
            how_to_fix="regerar o MathML a partir da AST",
            evidencia=mathml[:80],
        )]

    assinatura_l = assinatura_da_ast(ast_latex)
    assinatura_m = assinatura_da_ast(ast_mathml)

    from pipeline.matematica.arvore_matematica import Function as _Fn
    from pipeline.matematica.problemas_matematicos import AssinaturaSimbolica

    equivalencia = AssinaturaSimbolica()
    for lado in (ast_latex, ast_mathml):
        if lado is None:
            continue
        for no in lado.percorrer():
            if isinstance(no, _Fn) and no.indice is not None:
                equivalencia.symbols.add(no.nome)
                equivalencia.operators.update(
                    {"subscript", "group", "multiply"}
                )
            elif isinstance(no, _Fn):
                equivalencia.symbols.add(no.nome)
                equivalencia.operators.update({"multiply", "group"})
        from pipeline.matematica.arvore_matematica import Quantia as _Qt

        for no in lado.percorrer():
            if isinstance(no, _Qt):
                for letra in no.unidade:
                    if letra.isalpha():
                        equivalencia.symbols.add(letra)
                equivalencia.symbols.add(no.unidade)
                equivalencia.operators.update(
                    {"multiply", "divide", "power", "group"}
                )
    faltando_no_mathml = assinatura_l - assinatura_m - equivalencia
    faltando_no_latex = assinatura_m - assinatura_l - equivalencia

    issues: list[ValidationIssue] = []
    if faltando_no_mathml.symbols or faltando_no_mathml.numbers:
        issues.append(ValidationIssue(
            check="comparar_latex_e_mathml", severity="BLOCKER",
            message=("LaTeX e MathML representam expressoes diferentes; "
                     f"ausente no MathML: {faltando_no_mathml.descrever()}"),
            how_to_fix="ambos devem ser derivados da MESMA AST",
            evidencia=latex[:80],
        ))
    if faltando_no_latex.symbols or faltando_no_latex.numbers:
        issues.append(ValidationIssue(
            check="comparar_latex_e_mathml", severity="BLOCKER",
            message=("LaTeX e MathML representam expressoes diferentes; "
                     f"ausente no LaTeX: {faltando_no_latex.descrever()}"),
            how_to_fix="ambos devem ser derivados da MESMA AST",
            evidencia=mathml[:80],
        ))
    return issues


def _nos_nao_falados(ast, plano) -> list:
    falados = getattr(plano, "nos_falados", None)
    if not falados:
        return []
    return [
        no for no in ast.percorrer()
        if id(no) not in falados
        and (no.filhos() or getattr(no, "texto", "")
             or getattr(no, "nome", "") or getattr(no, "valor", None)
             is not None)
    ]


def _descrever_nos(nos: list) -> str:
    from pipeline.matematica.arvore_matematica import Integer, Numero, Symbol

    partes = []
    for no in nos[:6]:
        if isinstance(no, (Integer, Numero)):
            partes.append(str(getattr(no, "valor", getattr(no, "texto", ""))))
        elif isinstance(no, Symbol):
            partes.append(no.nome)
        else:
            partes.append(type(no).__name__)
    return ", ".join(partes)


def validar_cobertura_da_fala(
    origem: str, ast, speech_pt_br: str, plano=None,
) -> list[ValidationIssue]:
    from pipeline.matematica.problemas_matematicos import comparar_assinaturas

    if not speech_pt_br:
        return []

    if ast is not None and getattr(plano, "nos_falados", None):
        ausentes = _nos_nao_falados(ast, plano)
        if not ausentes:
            return []
        return [ValidationIssue(
            check="validar_cobertura_da_fala", severity="BLOCKER",
            message=("a fala nao realizou parte da arvore: "
                     + _descrever_nos(ausentes)),
            how_to_fix="regerar a fala a partir da AST (Etapa 8)",
            evidencia=speech_pt_br[:100],
        )]
    comparacao = comparar_assinaturas(origem, ast, speech_pt_br)
    faltando = comparacao["falta_na_fala"]
    if not faltando:
        return []
    return [ValidationIssue(
        check="validar_cobertura_da_fala", severity="BLOCKER",
        message=("a fala nao cobre parte da expressao: "
                 + faltando.descrever()),
        how_to_fix="regerar a fala a partir da AST (Etapa 8)",
        evidencia=speech_pt_br[:100],
    )]


def validar_produto_de_grupos(origem: str, ast) -> list[ValidationIssue]:
    from pipeline.matematica.arvore_matematica import Group, Multiply, Relation

    issues: list[ValidationIssue] = []
    texto = origem or ""

    if texto.count("(") != texto.count(")"):
        issues.append(ValidationIssue(
            check="validar_produto_de_grupos", severity="BLOCKER",
            message="pares de parenteses incompletos na origem",
            how_to_fix="reunir os fragmentos antes de tokenizar",
            evidencia=texto[:80],
        ))
        return issues

    produtos = [
        n for n in (ast.percorrer() if ast else [])
        if isinstance(n, Multiply)
        and sum(1 for f in n.fatores if isinstance(f, Group)) >= 2
    ]
    grupos_na_origem = texto.count("(")

    if grupos_na_origem >= 2 and not produtos:
        grupos_na_ast = [n for n in (ast.percorrer() if ast else [])
                         if isinstance(n, Group)]
        if len(grupos_na_ast) >= 2:
            issues.append(ValidationIssue(
                check="validar_produto_de_grupos", severity="BLOCKER",
                message=("ha dois grupos na origem mas nenhuma multiplicacao "
                         "entre eles na AST"),
                how_to_fix="inserir a multiplicacao implicita entre os grupos",
                evidencia=texto[:80],
            ))

    if "=" in texto:
        from pipeline.matematica.arvore_matematica import Desconhecido

        def _lado_vazio(no) -> bool:
            return isinstance(no, Desconhecido) and not (no.texto or "").strip()

        relacoes = [n for n in (ast.percorrer() if ast else [])
                    if isinstance(n, Relation)]
        if not relacoes:
            issues.append(ValidationIssue(
                check="validar_produto_de_grupos", severity="BLOCKER",
                message="a origem tem igualdade mas a AST nao tem relacao",
                how_to_fix="reprocessar; o lado direito pode ter se perdido",
                evidencia=texto[:80],
            ))
        elif any(len(r.operandos) < 2 or any(_lado_vazio(o) for o in r.operandos)
                 for r in relacoes):
            issues.append(ValidationIssue(
                check="validar_produto_de_grupos", severity="BLOCKER",
                message="relacao com um dos lados ausente na AST",
                how_to_fix="o lado direito da igualdade e obrigatorio",
                evidencia=texto[:80],
            ))

    from pipeline.matematica.fronteira_matematica import validar_fronteira_expressao

    fronteira = validar_fronteira_expressao(texto)
    if not fronteira.plausivel:
        issues.append(ValidationIssue(
            check="validar_produto_de_grupos", severity="BLOCKER",
            message=("fronteira implausivel: "
                     + "; ".join(fronteira.detalhes[:2])),
            how_to_fix="a expressao provavelmente continua no fragmento seguinte",
            evidencia=texto[-40:],
        ))

    from pipeline.matematica.problemas_matematicos import comparar_assinaturas

    faltando = comparar_assinaturas(texto, ast, "")["falta_na_ast"]
    if faltando:
        issues.append(ValidationIssue(
            check="validar_produto_de_grupos", severity="BLOCKER",
            message=("a AST nao contem todos os termos da origem: "
                     + faltando.descrever()),
            how_to_fix="reprocessar sem simplificar",
            evidencia=texto[:80],
        ))
    return issues
