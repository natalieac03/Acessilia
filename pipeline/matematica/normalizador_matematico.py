"""Normaliza e repara a expressao antes de montar a arvore.

Duas responsabilidades. A normalizacao converte a matematica "como
aparece" na matematica "como significa": barra de divisao vira fracao
de verdade (senao o leitor de tela nao consegue entrar no numerador),
e a base de um expoente passa a ser o grupo inteiro, nao o parentese
solto.

O reparo trata o caso "x2", em que a informacao de que o 2 estava
elevado ficou no PDF e nao no texto. Reconstruir isso exige escolher
entre expoente, indice, produto e nome de variavel — e a escolha e
feita por evidencia (geometria do span, contexto, ocorrencias
equivalentes no mesmo material), com pontuacao por hipotese. O que
este modulo nunca faz e substituir "x2" por "x²" as cegas: isso
quebraria "a variavel x2 armazena o resultado".
"""

from __future__ import annotations

import re


import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from pipeline.matematica.arvore_matematica import (
    Integer,
    Multiply,
    NoAST,
    Power,
    Subscript,
    Symbol,
)

_MAPA_SIMBOLOS = {
    "±": r"\pm ", "√": r"\sqrt ", "≥": r"\geq ", "≤": r"\leq ",
    "≠": r"\neq ", "×": r"\times ", "÷": r"\div ", "·": r"\cdot ",
    "∑": r"\sum ", "∫": r"\int ", "∞": r"\infty ", "≈": r"\approx ",
    "Δ": r"\Delta ", "∆": r"\Delta ", "δ": r"\delta ", "π": r"\pi ",
    "α": r"\alpha ", "β": r"\beta ", "θ": r"\theta ", "µ": r"\mu ",
}
_SOBRESCRITOS = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
                 "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
_SUBSCRITOS = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
               "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9"}


def _converter_indices_unicode(texto: str) -> str:
    def _troca(mapa: dict, marcador: str, alvo: str) -> str:
        padrao = re.compile(f"[{''.join(mapa)}]+")
        return padrao.sub(
            lambda m: marcador + "{" + "".join(mapa[c] for c in m.group(0)) + "}",
            alvo,
        )
    texto = _troca(_SOBRESCRITOS, "^", texto)
    texto = _troca(_SUBSCRITOS, "_", texto)
    return texto


def _converter_simbolos(texto: str) -> str:
    for simbolo, comando in _MAPA_SIMBOLOS.items():
        texto = texto.replace(simbolo, comando)
    texto = re.sub(r"\\sqrt\s+\\([a-zA-Z]+)", r"\\sqrt{\\\1}", texto)
    texto = re.sub(r"\\sqrt\s+([A-Za-z0-9]+)", r"\\sqrt{\1}", texto)
    return texto


def recuperar_expoentes_achatados(texto: str) -> str:
    return re.sub(
        r"(?<![\d^_{])(?<![A-Za-z]{3})([A-Za-z])\s+(\d)(?=\s*(?:[+\-=*/)\]]|$))",
        r"\1^{\2}",
        texto,
    )


def _fim_do_grupo_a_esquerda(texto: str, pos_fecha: int) -> int:
    profundidade = 0
    for i in range(pos_fecha, -1, -1):
        if texto[i] == ")":
            profundidade += 1
        elif texto[i] == "(":
            profundidade -= 1
            if profundidade == 0:
                return i
    return -1


def _fim_do_grupo_a_direita(texto: str, pos_abre: int) -> int:
    profundidade = 0
    for i in range(pos_abre, len(texto)):
        if texto[i] == "(":
            profundidade += 1
        elif texto[i] == ")":
            profundidade -= 1
            if profundidade == 0:
                return i
    return -1


def converter_barra_em_fracao(latex: str) -> str:
    if "/" not in latex:
        return latex

    resultado = latex
    protecao = 0
    while "/" in resultado and protecao < 12:
        protecao += 1
        pos = None
        for m in re.finditer(r"/", resultado):
            pos = m.start()
            break
        if pos is None:
            break

        esquerda = resultado[:pos].rstrip()
        if not esquerda:
            break
        if esquerda.endswith(")"):
            abre = _fim_do_grupo_a_esquerda(esquerda, len(esquerda) - 1)
            if abre < 0:
                break
            numerador = esquerda[abre + 1:-1].strip()
            antes = esquerda[:abre]
        else:
            m = re.search(r"([A-Za-z0-9\\{}\^_\.]+)$", esquerda)
            if not m:
                break
            numerador = m.group(1)
            antes = esquerda[:m.start(1)]

        direita = resultado[pos + 1:].lstrip()
        if not direita:
            break
        if direita.startswith("("):
            fecha = _fim_do_grupo_a_direita(direita, 0)
            if fecha < 0:
                break
            denominador = direita[1:fecha].strip()
            depois = direita[fecha + 1:]
        else:
            m = re.match(r"([A-Za-z0-9\\{}\^_\.]+)", direita)
            if not m:
                break
            denominador = m.group(1)
            depois = direita[m.end(1):]

        if not numerador or not denominador:
            break
        resultado = f"{antes}\\frac{{{numerador}}}{{{denominador}}}{depois}"

    return resultado


def agrupar_base_de_expoente(latex: str) -> str:
    resultado = latex
    for _ in range(8):
        alterou = False
        for m in re.finditer(r"\)\s*\^", resultado):
            fecha = m.start()
            if fecha > 0 and resultado[fecha - 1] == "}":
                continue
            abre = _fim_do_grupo_a_esquerda(resultado, fecha)
            if abre < 0:
                continue
            if resultado[max(0, abre - 5):abre].endswith("\\left"):
                continue
            interior = resultado[abre + 1:fecha]
            resultado = (
                resultado[:abre] + r"\left(" + interior + r"\right)"
                + resultado[fecha + 1:]
            )
            alterou = True
            break
        if not alterou:
            break
    return resultado


def normalizar_latex(latex: str) -> str:
    if not latex or not latex.strip():
        return latex
    try:
        texto = latex.strip()
        texto = _converter_simbolos(texto)
        texto = _converter_indices_unicode(texto)
        texto = recuperar_expoentes_achatados(texto)
        texto = converter_barra_em_fracao(texto)
        texto = agrupar_base_de_expoente(texto)
        return re.sub(r"\s{2,}", " ", texto).strip()
    except Exception:
        return latex


def normalizar_expressao_bruta(expressao: str) -> str:
    return normalizar_latex(expressao)


LIMIAR_CORRECAO_AUTOMATICA = 0.90
LIMIAR_PENDENCIA = 0.50
LIMIAR_MATEMATICA = 0.6

LIMIAR_SUPERIOR = 0.8
LIMIAR_INFERIOR = 0.8
PROPORCAO_FONTE = 0.9

_PADRAO_LETRA_DIGITO = re.compile(r"(?<!\w)([a-zA-Z])([0-9]+)(?!\w)")

SOBRESCRITOS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
SUBSCRITOS = "₀₁₂₃₄₅₆₇₈₉"
_PADRAO_SOBRESCRITO = re.compile(f"[{SOBRESCRITOS}]|\\^")
_PADRAO_SUBSCRITO = re.compile(f"[{SUBSCRITOS}]|_")
_PADRAO_QUALQUER_SCRIPT = re.compile(f"[{SOBRESCRITOS}{SUBSCRITOS}]|[\\^_]")


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


@dataclass
class ScriptCandidate:

    base: str
    digit: str
    raw: str
    start: int
    end: int

    @property
    def como_identificador(self) -> str:
        return f"{self.base}{self.digit}"


_PALAVRAS_MATEMATICAS = (
    "equacao", "equacoes", "funcao", "funcoes", "resolver", "coeficiente",
    "coeficientes", "raiz", "raizes", "formula", "expressao", "grau",
    "discriminante", "polinomio", "termo", "calcular", "calculo",
    "substituir", "fatorar", "grafico", "parabola", "derivada", "integral",
)
_PALAVRAS_DE_CODIGO = (
    "variavel", "vetor", "matriz", "array", "indice do array", "ponteiro",
    "funcao def", "retorna", "atribui", "armazena", "parametro",
    "coluna", "campo", "registro", "coordenada", "ponto",
)


def calcular_probabilidade_matematica(
    texto: str, contexto: Any = None
) -> float:
    if not texto:
        return 0.0
    limpo = _sem_acento(texto)
    pontos = 0.0

    if re.search(r"[=≥≤≠]", texto):
        pontos += 0.35
    if re.search(r"[+\-−±×÷/]", texto):
        pontos += 0.15
    if re.search(r"\d", texto) and re.search(r"[A-Za-z]", texto):
        pontos += 0.10
    tokens = re.findall(r"\S+", texto)
    palavras_longas = re.findall(r"[A-Za-zÀ-ÿ]{4,}", texto)
    if tokens and len(palavras_longas) / len(tokens) < 0.25:
        pontos += 0.15
    if any(p in limpo for p in _PALAVRAS_MATEMATICAS):
        pontos += 0.25
    if any(c in texto for c in "²³√±ΔΣ∫∑"):
        pontos += 0.20

    if contexto is not None:
        if getattr(contexto, "tipo_regiao", "") == "formula":
            pontos += 0.30
        vizinho = _sem_acento(getattr(contexto, "texto_vizinho", ""))
        if any(p in vizinho for p in _PALAVRAS_MATEMATICAS):
            pontos += 0.15

    if any(p in limpo for p in _PALAVRAS_DE_CODIGO):
        pontos -= 0.35
    if re.search(r"\[[^\]]*\]|\(\)|;\s*$|def\s|=\s*\w+\(", texto):
        pontos -= 0.25
    palavras = re.findall(r"[A-Za-z]{4,}", texto)
    if len(palavras) >= 4:
        pontos -= 0.15

    return max(0.0, min(1.0, pontos))


def detectar_script_perdido(
    texto: str, contexto: Any = None,
) -> list[ScriptCandidate]:
    probabilidade = getattr(contexto, "probabilidade_matematica", None)
    if probabilidade is None:
        probabilidade = calcular_probabilidade_matematica(texto, contexto)
    if probabilidade < LIMIAR_MATEMATICA:
        return []

    candidatos: list[ScriptCandidate] = []
    for encontro in _PADRAO_LETRA_DIGITO.finditer(texto or ""):
        candidatos.append(ScriptCandidate(
            base=encontro.group(1), digit=encontro.group(2),
            raw=encontro.group(0), start=encontro.start(),
            end=encontro.end(),
        ))
    return candidatos


@dataclass
class MathHypothesis:
    ast: NoAST
    label: str
    score: float = 0.0
    evidencias: list[str] = field(default_factory=list)

    @property
    def texto_corrigido(self) -> str:
        from pipeline.matematica.serializacao_matematica import para_latex

        return para_latex(self.ast)


def gerar_interpretacoes_script(base: str, digit: str) -> list[MathHypothesis]:
    valor = Integer(valor=int(digit)) if digit.isdigit() else Symbol(nome=digit)
    return [
        MathHypothesis(ast=Power(base=Symbol(nome=base), expoente=valor),
                       label="expoente"),
        MathHypothesis(ast=Subscript(base=Symbol(nome=base), indice=valor),
                       label="subscrito"),
        MathHypothesis(
            ast=Multiply(fatores=[Symbol(nome=base), valor],
                         source_notation="implicit"),
            label="multiplicacao",
        ),
        MathHypothesis(ast=Symbol(nome=f"{base}{digit}"),
                       label="identificador"),
    ]


@dataclass
class Glyph:

    char: str
    bbox: tuple[float, float, float, float]
    font_size: float = 0.0

    @property
    def baseline_y(self) -> float:
        return self.bbox[3]

    def to_dict(self) -> dict:
        return {"char": self.char, "bbox": list(self.bbox),
                "font_size": self.font_size}


def classificar_posicao_do_digito(base_glyph: Glyph, digit_glyph: Glyph) -> str:
    try:
        deslocamento = base_glyph.baseline_y - digit_glyph.baseline_y
        proporcao = (
            digit_glyph.font_size / base_glyph.font_size
            if base_glyph.font_size else 1.0
        )
        if deslocamento > LIMIAR_SUPERIOR and proporcao < PROPORCAO_FONTE:
            return "superscript"
        if deslocamento < -LIMIAR_INFERIOR and proporcao < PROPORCAO_FONTE:
            return "subscript"
        return "baseline"
    except Exception:
        return "desconhecido"


@dataclass
class DocumentContext:

    section_title: str = ""
    section_topic: str = ""
    nearby_formulas: list[str] = field(default_factory=list)
    declared_coefficients: dict[str, str] = field(default_factory=dict)
    describes_parabola: bool = False

    @property
    def tema_e_segundo_grau(self) -> bool:
        alvo = _sem_acento(f"{self.section_topic} {self.section_title}")
        return any(p in alvo for p in (
            "segundo grau", "quadratica", "bhaskara", "equacao do 2",
            "equacao_segundo_grau",
        ))


@dataclass
class MathEvidence:

    glyph_position: str = "desconhecido"
    section_topic: str = ""
    nearby_equivalent_formula_uses_power: bool = False
    nearby_equivalent_formula_uses_subscript: bool = False
    coefficients_match_quadratic: bool = False
    graph_is_parabola: bool = False
    contains_equation_operator: bool = False
    contexto_de_codigo: bool = False
    probabilidade_matematica: float = 0.0
    detalhes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _normalizar_para_comparacao(formula: str) -> str:
    texto = formula or ""
    for indice, digito in enumerate("0123456789"):
        texto = texto.replace(SOBRESCRITOS[indice], digito)
        texto = texto.replace(SUBSCRITOS[indice], digito)
    texto = re.sub(r"[\^_]\{?(\w+)\}?", r"\1", texto)
    return re.sub(r"\s+", "", texto).lower()


def comparar_formulas_aproximadas(formula_a: str, formula_b: str) -> float:
    a = _normalizar_para_comparacao(formula_a)
    b = _normalizar_para_comparacao(formula_b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    tokens_a = set(re.findall(r"\d+|[A-Za-z]+|[^\w\s]", a))
    tokens_b = set(re.findall(r"\d+|[A-Za-z]+|[^\w\s]", b))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def diferenca_apenas_em_scripts(texto_a: str, texto_b: str) -> bool:
    if _normalizar_para_comparacao(texto_a) != _normalizar_para_comparacao(texto_b):
        return False
    return bool(_PADRAO_QUALQUER_SCRIPT.search(texto_a)) != bool(
        _PADRAO_QUALQUER_SCRIPT.search(texto_b)
    )


def _formula_equivalente_usa(
    bruto: str, formulas: list[str], marca: str,
) -> tuple[bool, str]:
    padrao = (_PADRAO_SOBRESCRITO if marca == "power"
              else _PADRAO_SUBSCRITO)
    for formula in formulas or []:
        if comparar_formulas_aproximadas(bruto, formula) < 0.75:
            continue
        if padrao.search(formula):
            return True, formula
    return False, ""


def _coeficientes_conferem(
    bruto: str, coeficientes: dict[str, str],
) -> tuple[bool, str]:
    if not coeficientes:
        return False, ""
    try:
        b = str(coeficientes.get("b", "")).replace("−", "-").strip()
        c = str(coeficientes.get("c", "")).strip()
        numeros = re.findall(r"-?\d+", bruto)
        if b and c and b.lstrip("-") in numeros and c in numeros:
            declarado = ", ".join(f"{k} = {v}" for k, v in
                                  sorted(coeficientes.items()))
            return True, declarado
    except Exception:
        pass
    return False, ""


def _trecho_matematico(texto: str, candidato: ScriptCandidate) -> str:
    try:
        from pipeline.matematica.matematica_inline import detectar_candidatos_matematicos

        for encontrado in detectar_candidatos_matematicos(texto):
            if encontrado.start <= candidato.start < encontrado.end:
                return encontrado.source_text
    except Exception:
        pass
    inicio = max(0, candidato.start - 40)
    return texto[inicio:candidato.end + 40].strip()


def coletar_evidencias(
    candidato: ScriptCandidate,
    texto_da_regiao: str,
    glifos: list[Glyph] | None = None,
    geometria=None,
    documento: DocumentContext | None = None,
    contexto=None,
) -> MathEvidence:
    documento = documento or DocumentContext()
    evidencia = MathEvidence(
        section_topic=documento.section_topic or documento.section_title,
        contains_equation_operator=bool(re.search(r"[=≥≤≠]", texto_da_regiao)),
        graph_is_parabola=documento.describes_parabola,
        probabilidade_matematica=calcular_probabilidade_matematica(
            texto_da_regiao, contexto
        ),
    )

    posicao = "desconhecido"
    if glifos:
        posicao = _posicao_por_glifos(candidato, glifos)
    elif geometria is not None:
        posicao = _posicao_por_geometria(candidato, geometria)
    evidencia.glyph_position = posicao
    if posicao == "superscript":
        evidencia.detalhes.append(
            f"o digito {candidato.digit} aparece acima da linha de base"
        )
    elif posicao == "subscript":
        evidencia.detalhes.append(
            f"o digito {candidato.digit} aparece abaixo da linha de base"
        )
    elif posicao == "baseline":
        evidencia.detalhes.append(
            f"o digito {candidato.digit} esta na linha de base"
        )

    trecho = _trecho_matematico(texto_da_regiao, candidato)
    usa_power, qual = _formula_equivalente_usa(
        trecho, documento.nearby_formulas, "power"
    )
    evidencia.nearby_equivalent_formula_uses_power = usa_power
    if usa_power:
        evidencia.detalhes.append(
            f"a mesma expressao aparece proxima com expoente: {qual}"
        )
    usa_sub, qual_sub = _formula_equivalente_usa(
        trecho, documento.nearby_formulas, "subscript"
    )
    evidencia.nearby_equivalent_formula_uses_subscript = usa_sub
    if usa_sub:
        evidencia.detalhes.append(
            f"a mesma expressao aparece proxima com indice: {qual_sub}"
        )

    if documento.tema_e_segundo_grau:
        evidencia.detalhes.append(
            f"a secao trata de equacao do segundo grau: "
            f"{documento.section_title or documento.section_topic}"
        )

    confere, declarado = _coeficientes_conferem(
        trecho, documento.declared_coefficients
    )
    evidencia.coefficients_match_quadratic = confere
    if confere:
        evidencia.detalhes.append(
            f"os coeficientes {declarado} confirmam a leitura quadratica"
        )

    if documento.describes_parabola:
        evidencia.detalhes.append(
            "a funcao associada e representada por uma parabola"
        )

    limpo = _sem_acento(texto_da_regiao)
    if any(p in limpo for p in _PALAVRAS_DE_CODIGO) or re.search(
        r"\[[^\]]*\]", texto_da_regiao
    ):
        evidencia.contexto_de_codigo = True
        evidencia.detalhes.append(
            "o texto tem marcas de codigo ou descreve uma variavel"
        )
    return evidencia


def _posicao_por_glifos(candidato: ScriptCandidate,
                        glifos: list[Glyph]) -> str:
    base = digito = None
    for indice, glifo in enumerate(glifos):
        if glifo.char == candidato.base and indice + 1 < len(glifos):
            seguinte = glifos[indice + 1]
            if seguinte.char == candidato.digit[0]:
                base, digito = glifo, seguinte
                break
    if base is None or digito is None:
        return "desconhecido"
    return classificar_posicao_do_digito(base, digito)


def _posicao_por_geometria(candidato: ScriptCandidate, geometria) -> str:
    try:
        deslocados = geometria.deslocamentos_em(candidato.start, candidato.end)
        for span in deslocados:
            if not span.text.strip():
                continue
            if span.parece_sobrescrito:
                return "superscript"
            if span.parece_subscrito:
                return "subscript"
        if geometria.span_em(candidato.start) is not None:
            return "baseline"
    except Exception:
        pass
    return "desconhecido"


def pontuar_hipotese(hipotese: MathHypothesis, evidence: MathEvidence) -> float:
    pontos = 0.0
    justificativas: list[str] = []

    def _somar(valor: float, motivo: str):
        nonlocal pontos
        pontos += valor
        justificativas.append(motivo)

    if hipotese.label == "expoente":
        if evidence.glyph_position == "superscript":
            _somar(0.45, "o digito esta acima da linha de base")
        elif evidence.glyph_position == "baseline":
            _somar(-0.35, "o digito NAO esta elevado - contradiz expoente")
        if evidence.section_topic and _sem_acento(
            evidence.section_topic
        ) and _tema_quadratico(evidence.section_topic):
            _somar(0.15, "a secao trata de equacao do segundo grau")
        if evidence.nearby_equivalent_formula_uses_power:
            _somar(0.20, "formula equivalente proxima usa expoente")
        if evidence.coefficients_match_quadratic:
            _somar(0.10, "os coeficientes conferem com a leitura quadratica")
        if evidence.graph_is_parabola:
            _somar(0.05, "o grafico e uma parabola")
        if evidence.contains_equation_operator:
            _somar(0.05, "ha operador de equacao no trecho")

    elif hipotese.label == "subscrito":
        if evidence.glyph_position == "subscript":
            _somar(0.45, "o digito esta abaixo da linha de base")
        elif evidence.glyph_position == "baseline":
            _somar(-0.35, "o digito NAO esta rebaixado - contradiz indice")
        if evidence.nearby_equivalent_formula_uses_subscript:
            _somar(0.20, "formula equivalente proxima usa indice")
        if evidence.contains_equation_operator:
            _somar(0.05, "ha operador de equacao no trecho")
        if "solucoes" in _sem_acento(evidence.section_topic) or "sequencia" in \
                _sem_acento(evidence.section_topic):
            _somar(0.15, "a secao fala de solucoes ou sequencias indexadas")

    elif hipotese.label == "multiplicacao":
        if evidence.glyph_position == "baseline":
            _somar(0.25, "o digito esta na mesma linha de base")
        if evidence.contains_equation_operator:
            _somar(0.05, "ha operador de equacao no trecho")
        if not (evidence.nearby_equivalent_formula_uses_power
                or evidence.nearby_equivalent_formula_uses_subscript):
            _somar(0.10, "nenhuma formula proxima usa script")

    else:
        if evidence.glyph_position == "baseline":
            _somar(0.40, "o digito esta na mesma linha de base")
        if evidence.contexto_de_codigo:
            _somar(0.30, "o texto descreve uma variavel ou tem marcas de codigo")
        if evidence.probabilidade_matematica < LIMIAR_MATEMATICA:
            _somar(0.20, "o trecho tem pouca caracteristica matematica")
        if not (evidence.nearby_equivalent_formula_uses_power
                or evidence.nearby_equivalent_formula_uses_subscript):
            _somar(0.15, "nenhuma formula proxima usa script")
        if evidence.glyph_position == "desconhecido":
            _somar(0.25, "nao ha evidencia visual de deslocamento")

    hipotese.evidencias = justificativas
    hipotese.score = max(0.0, min(pontos, 1.0))
    return hipotese.score


def _tema_quadratico(tema: str) -> bool:
    alvo = _sem_acento(tema)
    return any(p in alvo for p in (
        "segundo grau", "quadratica", "bhaskara", "equacao do 2",
        "equacao_segundo_grau",
    ))


@dataclass
class ResultadoDoReparo:

    candidato: ScriptCandidate
    escolhida: MathHypothesis
    hipoteses: list[MathHypothesis]
    evidencia: MathEvidence
    confidence: float
    aplicar_automaticamente: bool
    gerar_pendencia: bool
    texto_reparado: str = ""

    def to_dict(self) -> dict:
        return {
            "raw": self.candidato.raw,
            "chosen": self.escolhida.label,
            "ast": self.escolhida.ast.to_dict(),
            "confidence": round(self.confidence, 2),
            "evidence": list(self.evidencia.detalhes),
            "justificativas": list(self.escolhida.evidencias),
            "alternativas": [
                {"label": h.label, "score": round(h.score, 2)}
                for h in self.hipoteses if h is not self.escolhida
            ],
            "aplicar_automaticamente": self.aplicar_automaticamente,
            "gerar_pendencia": self.gerar_pendencia,
        }


class ReparadorDeContextoMatematico:

    def resolver(
        self,
        candidato: ScriptCandidate,
        texto_da_regiao: str,
        glifos: list[Glyph] | None = None,
        geometria=None,
        documento: DocumentContext | None = None,
        contexto=None,
    ) -> ResultadoDoReparo:
        evidencia = coletar_evidencias(
            candidato, texto_da_regiao, glifos, geometria, documento, contexto
        )
        hipoteses = gerar_interpretacoes_script(
            candidato.base, candidato.digit
        )
        for hipotese in hipoteses:
            pontuar_hipotese(hipotese, evidencia)

        escolhida = max(hipoteses, key=lambda h: h.score)
        if escolhida.score <= 0.0:
            escolhida = next(h for h in hipoteses if h.label == "identificador")

        return ResultadoDoReparo(
            candidato=candidato, escolhida=escolhida, hipoteses=hipoteses,
            evidencia=evidencia, confidence=escolhida.score,
            aplicar_automaticamente=(
                escolhida.score >= LIMIAR_CORRECAO_AUTOMATICA
                and escolhida.label != "identificador"
            ),
            gerar_pendencia=(
                LIMIAR_PENDENCIA <= escolhida.score < LIMIAR_CORRECAO_AUTOMATICA
                and escolhida.label != "identificador"
            ),
            texto_reparado=self._aplicar_no_texto(
                texto_da_regiao, candidato, escolhida
            ),
        )

    def reparar_texto(
        self,
        texto: str,
        glifos: list[Glyph] | None = None,
        geometria=None,
        documento: DocumentContext | None = None,
        contexto=None,
    ) -> tuple[str, list[ResultadoDoReparo]]:
        candidatos = detectar_script_perdido(texto, contexto)
        if not candidatos:
            return texto, []

        resultados = [
            self.resolver(c, texto, glifos, geometria, documento, contexto)
            for c in candidatos
        ]
        reparado = texto
        for resultado in sorted(resultados,
                                key=lambda r: r.candidato.start, reverse=True):
            if not resultado.aplicar_automaticamente:
                continue
            substituto = self._grafia(resultado.escolhida, resultado.candidato)
            inicio, fim = resultado.candidato.start, resultado.candidato.end
            reparado = reparado[:inicio] + substituto + reparado[fim:]
        return reparado, resultados

    @staticmethod
    def _grafia(hipotese: MathHypothesis, candidato: ScriptCandidate) -> str:
        if hipotese.label == "expoente":
            tabela = str.maketrans("0123456789", SOBRESCRITOS)
            return candidato.base + candidato.digit.translate(tabela)
        if hipotese.label == "subscrito":
            tabela = str.maketrans("0123456789", SUBSCRITOS)
            return candidato.base + candidato.digit.translate(tabela)
        if hipotese.label == "multiplicacao":
            return f"{candidato.base} · {candidato.digit}"
        return candidato.raw

    def _aplicar_no_texto(
        self, texto: str, candidato: ScriptCandidate,
        hipotese: MathHypothesis,
    ) -> str:
        substituto = self._grafia(hipotese, candidato)
        return texto[:candidato.start] + substituto + texto[candidato.end:]


reparador_padrao = ReparadorDeContextoMatematico()


def encontrar_equivalentes(
    texto: str, formulas_documento: list, limite: float = 0.75,
) -> list:
    equivalentes = []
    for no in formulas_documento or []:
        origem = getattr(no, "source_text", None) or str(no)
        if comparar_formulas_aproximadas(texto, origem) >= limite:
            equivalentes.append(no)
    return equivalentes


def reparar_por_ocorrencia_confirmada(
    texto: str, formulas_documento: list, confianca_minima: float = 0.95,
) -> dict | None:
    for no in encontrar_equivalentes(texto, formulas_documento):
        origem = getattr(no, "source_text", "") or ""
        confianca = float(getattr(no, "confidence", 0.0) or 0.0)
        status = getattr(no, "review_status", "")
        if confianca < confianca_minima and status not in ("reviewed",
                                                           "approved"):
            continue
        if not diferenca_apenas_em_scripts(texto, origem):
            continue
        return {
            "texto_reparado": origem,
            "ast": getattr(no, "ast", {}),
            "reason": "Formula equivalente confirmada em outra regiao",
            "referencia": origem,
            "confidence": max(confianca, 0.95),
        }
    return None


def revisar_scripts_perdidos(
    texto: str,
    glifos: list[Glyph] | None = None,
    geometria=None,
    documento: DocumentContext | None = None,
    contexto=None,
    formulas_documento: list | None = None,
) -> tuple[str, list]:
    from pipeline.matematica.cobertura_matematica import ValidationIssue

    issues: list = []

    if formulas_documento:
        confirmada = reparar_por_ocorrencia_confirmada(
            texto, formulas_documento
        )
        if confirmada:
            issues.append(ValidationIssue(
                check="revisar_scripts_perdidos", severity="INFO",
                message=(
                    "script recuperado por ocorrencia confirmada: "
                    f"{confirmada['referencia']}"
                ),
                how_to_fix="nenhuma acao necessaria",
                evidencia=confirmada["reason"],
            ))
            return confirmada["texto_reparado"], issues

    reparado, resultados = reparador_padrao.reparar_texto(
        texto, glifos, geometria, documento, contexto
    )
    for resultado in resultados:
        if resultado.aplicar_automaticamente:
            issues.append(ValidationIssue(
                check="revisar_scripts_perdidos", severity="INFO",
                message=(
                    f"{resultado.candidato.raw!r} interpretado como "
                    f"{resultado.escolhida.label} "
                    f"(confianca {resultado.confidence:.2f})"
                ),
                how_to_fix="conferir a decisao no relatorio de evidencias",
                evidencia="; ".join(resultado.evidencia.detalhes[:3]),
            ))
        elif resultado.gerar_pendencia:
            issues.append(ValidationIssue(
                check="revisar_scripts_perdidos", severity="ERROR",
                message=(
                    "Possivel expoente ou subscrito perdido em "
                    f"{resultado.candidato.raw!r}: melhor hipotese e "
                    f"{resultado.escolhida.label} com confianca "
                    f"{resultado.confidence:.2f}"
                ),
                how_to_fix=(
                    "confirmar contra a imagem; sem evidencia visual o "
                    "sistema nao aplica a correcao sozinho"
                ),
                evidencia="; ".join(resultado.evidencia.detalhes[:3]),
            ))
    return reparado, issues


def montar_payload_para_o_critico(
    texto: str,
    glifos: list[Glyph] | None = None,
    antes: str = "",
    depois: str = "",
    documento: DocumentContext | None = None,
    image_crop: str | None = None,
) -> dict:
    documento = documento or DocumentContext()
    return {
        "raw_text": texto,
        "image_crop": image_crop,
        "glyphs": [g.to_dict() for g in (glifos or [])],
        "before": antes,
        "after": depois,
        "section": documento.section_title or documento.section_topic,
        "nearby_formulas": list(documento.nearby_formulas),
        "declared_coefficients": dict(documento.declared_coefficients),
        "probabilidade_matematica": round(
            calcular_probabilidade_matematica(texto), 2
        ),
    }
