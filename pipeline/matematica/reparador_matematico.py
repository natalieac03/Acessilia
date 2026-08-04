"""REPARADOR DE CONTEXTO MATEMATICO - o caso "x2".

O extrator entrega "x2 - 5x + 6 = 0". A informacao de que o 2 estava
elevado ficou no PDF, nao no texto. Reconstruir isso exige decidir entre
quatro leituras legitimas:

    Power(x, 2)      -> x²        expoente
    Subscript(x, 2)  -> x₂        indice
    Multiply(x, 2)   -> x vezes 2 produto
    Symbol("x2")     -> x2        uma variavel chamada x2

E O QUE ESTE MODULO NAO FAZ: `texto.replace("x2", "x²")`. Isso quebraria
"O ponto x2 foi calculado", "A variavel x2 armazena o resultado" e
"vetor[x2]" - casos em que x2 e mesmo o nome da variavel. Tambem nao
entrega o paragrafo a um modelo para reescrever livremente: ele
corrigiria o expoente e, no caminho, mudaria uma palavra ou um sinal.

A correcao e LOCALIZADA e por EVIDENCIA ACUMULADA, com pesos explicitos:

    posicao do glifo (visual)           0.45   <- prioritaria
    formula equivalente proxima         0.20
    tema da secao                       0.15
    coeficientes conferem               0.10
    grafico compativel                  0.05
    operador de equacao presente        0.05

A visual pesa mais porque vem da fonte, nao de inferencia. Quando ela
falta (OCR sem geometria), as demais somam no maximo 0.55 - abaixo do
limiar de correcao automatica. Ou seja: sem evidencia visual, o sistema
propoe e um humano decide. E o comportamento correto: preferir a
pendencia ao chute.
"""

from __future__ import annotations

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

# Limiares de decisao.
LIMIAR_CORRECAO_AUTOMATICA = 0.90   # aplica a correcao
# 0.50 e proposital: o contexto sozinho (secao + formula proxima +
# coeficientes) soma 0.55 sem nenhuma evidencia visual. Isso e evidencia
# real, so nao conclusiva - o caso exato de "propor e deixar o humano
# decidir". Um limiar mais alto silenciaria justamente essa faixa.
LIMIAR_PENDENCIA = 0.50             # registra MATH-OCR-SCRIPT-001
LIMIAR_MATEMATICA = 0.6             # ativa a analise (etapa 1)

# Geometria (mesmos criterios da secao 6.3).
LIMIAR_SUPERIOR = 0.8
LIMIAR_INFERIOR = 0.8
PROPORCAO_FONTE = 0.9

# letra seguida de digito, sem nada colado em volta
_PADRAO_LETRA_DIGITO = re.compile(r"(?<!\w)([a-zA-Z])([0-9]+)(?!\w)")

# ATENCAO: "¹²³" vivem em Latin-1 (U+00B9, U+00B2, U+00B3), FORA do bloco
# de sobrescritos (U+2070+). A classe [⁰-⁹] nao os alcanca - e justamente
# ¹²³ sao os expoentes mais comuns em material didatico. Por isso os
# conjuntos aqui sao explicitos.
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


# --------------------------------------------------------------------------- #
# Etapa 1 - deteccao da sequencia suspeita
# --------------------------------------------------------------------------- #
@dataclass
class ScriptCandidate:
    """Uma sequencia "letra + digito" que pode ser script perdido."""

    base: str
    digit: str
    raw: str
    start: int
    end: int

    @property
    def como_identificador(self) -> str:
        return f"{self.base}{self.digit}"


# Sinais de que a regiao e matematica (o portao da etapa 1).
_PALAVRAS_MATEMATICAS = (
    "equacao", "equacoes", "funcao", "funcoes", "resolver", "coeficiente",
    "coeficientes", "raiz", "raizes", "formula", "expressao", "grau",
    "discriminante", "polinomio", "termo", "calcular", "calculo",
    "substituir", "fatorar", "grafico", "parabola", "derivada", "integral",
)
# Sinais de que a regiao NAO e matematica - contextos em que "x2" e mesmo
# um nome de variavel.
_PALAVRAS_DE_CODIGO = (
    "variavel", "vetor", "matriz", "array", "indice do array", "ponteiro",
    "funcao def", "retorna", "atribui", "armazena", "parametro",
    "coluna", "campo", "registro", "coordenada", "ponto",
)


def calcular_probabilidade_matematica(
    texto: str, contexto: Any = None
) -> float:
    """Quao matematica e esta regiao? (0 a 1)

    E o portao da etapa 1: sem 0.6, a analise de script perdido nem
    comeca. Combina os sinais que o plano lista, e SUBTRAI quando o texto
    tem marcas de codigo ou de prosa descritiva - "a variavel x2 armazena"
    nao pode abrir a porta para virar expoente.
    """
    if not texto:
        return 0.0
    limpo = _sem_acento(texto)
    pontos = 0.0

    if re.search(r"[=≥≤≠]", texto):
        pontos += 0.35          # o sinal mais forte que existe
    if re.search(r"[+\-−±×÷/]", texto):
        pontos += 0.15
    if re.search(r"\d", texto) and re.search(r"[A-Za-z]", texto):
        pontos += 0.10
    # DENSIDADE SIMBOLICA: uma equacao nua ("x2 - 5x + 6 = 0") nao tem
    # nenhuma palavra matematica, mas e quase toda simbolo. Sem este
    # sinal ela ficava logo abaixo do limiar - e o portao nem abria para o
    # caso central do plano.
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

    # penalidade: marcas de codigo ou de prosa sobre uma variavel
    if any(p in limpo for p in _PALAVRAS_DE_CODIGO):
        pontos -= 0.35
    if re.search(r"\[[^\]]*\]|\(\)|;\s*$|def\s|=\s*\w+\(", texto):
        pontos -= 0.25
    # proporcao de prosa: muitas palavras longas indicam texto comum
    palavras = re.findall(r"[A-Za-z]{4,}", texto)
    if len(palavras) >= 4:
        pontos -= 0.15

    return max(0.0, min(1.0, pontos))


def detectar_script_perdido(
    texto: str, contexto: Any = None,
) -> list[ScriptCandidate]:
    """Etapa 1 - marca "letra + digito" em regiao matematica.

    Fora de contexto matematico nao devolve nada: e o que impede
    "vetor[x2]" de entrar na analise.
    """
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


# --------------------------------------------------------------------------- #
# Etapa 2 - as quatro interpretacoes
# --------------------------------------------------------------------------- #
@dataclass
class MathHypothesis:
    ast: NoAST
    label: str
    score: float = 0.0
    evidencias: list[str] = field(default_factory=list)

    @property
    def texto_corrigido(self) -> str:
        """Como o trecho ficaria sob esta hipotese."""
        from pipeline.matematica.serializacao_matematica import para_latex

        return para_latex(self.ast)


def gerar_interpretacoes_script(base: str, digit: str) -> list[MathHypothesis]:
    """Etapa 2 - as quatro leituras possiveis, sem escolher nenhuma."""
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


# --------------------------------------------------------------------------- #
# Etapa 3 - evidencias
# --------------------------------------------------------------------------- #
@dataclass
class Glyph:
    """Um caractere com posicao e tamanho - o que o texto plano perde."""

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
    """superscript | subscript | baseline.

    Compara a baseline e o tamanho da fonte. Exigir as duas condicoes
    evita tratar uma linha levemente desalinhada como expoente.
    """
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
    """O que o DOCUMENTO sabe e a regiao nao.

    E a diferenca entre "adivinhar" e "conferir": a mesma equacao aparece
    de novo mais abaixo com o expoente preservado, e os coeficientes
    declarados batem com a leitura quadratica.
    """

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
    """As evidencias reunidas para um candidato."""

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
    """Remove espacos e ACHATA scripts, para comparar leituras."""
    texto = formula or ""
    for indice, digito in enumerate("0123456789"):
        texto = texto.replace(SOBRESCRITOS[indice], digito)
        texto = texto.replace(SUBSCRITOS[indice], digito)
    texto = re.sub(r"[\^_]\{?(\w+)\}?", r"\1", texto)
    return re.sub(r"\s+", "", texto).lower()


def comparar_formulas_aproximadas(formula_a: str, formula_b: str) -> float:
    """Similaridade de tokens depois de achatar os scripts (0 a 1)."""
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
    """As duas grafias sao iguais SE ignorarmos expoentes e indices?

    Se sim, e a mesma expressao com um script perdido de um lado - e a
    ocorrencia que tem o script e a referencia.
    """
    if _normalizar_para_comparacao(texto_a) != _normalizar_para_comparacao(texto_b):
        return False
    return bool(_PADRAO_QUALQUER_SCRIPT.search(texto_a)) != bool(
        _PADRAO_QUALQUER_SCRIPT.search(texto_b)
    )


def _formula_equivalente_usa(
    bruto: str, formulas: list[str], marca: str,
) -> tuple[bool, str]:
    """Ha formula proxima equivalente que usa expoente (ou indice)?"""
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
    """Os coeficientes declarados batem com a leitura quadratica?

    "a = 1, b = -5, c = 6" corresponde a x^2 - 5x + 6. Nao corresponde
    naturalmente a uma variavel chamada x2.
    """
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
    """A expressao em volta do candidato, sem a prosa da frase.

    "Exemplo: resolver x2 - 5x + 6 = 0." tem similaridade baixa com
    "x² - 5x + 6 = 0" por causa das palavras. Comparar formula com
    PARAGRAFO subestima a semelhanca e desliga a evidencia mais util.
    """
    try:
        from pipeline.matematica.matematica_inline import detectar_candidatos_matematicos

        for encontrado in detectar_candidatos_matematicos(texto):
            if encontrado.start <= candidato.start < encontrado.end:
                return encontrado.source_text
    except Exception:
        pass
    # sem detector, recorta uma janela em volta do candidato
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
    """Reune todas as evidencias disponiveis para um candidato."""
    documento = documento or DocumentContext()
    evidencia = MathEvidence(
        section_topic=documento.section_topic or documento.section_title,
        contains_equation_operator=bool(re.search(r"[=≥≤≠]", texto_da_regiao)),
        graph_is_parabola=documento.describes_parabola,
        probabilidade_matematica=calcular_probabilidade_matematica(
            texto_da_regiao, contexto
        ),
    )

    # --- 1. posicao do glifo (evidencia PRIORITARIA) ---
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

    # --- 2. formula equivalente proxima ---
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

    # --- 3. tema da secao ---
    if documento.tema_e_segundo_grau:
        evidencia.detalhes.append(
            f"a secao trata de equacao do segundo grau: "
            f"{documento.section_title or documento.section_topic}"
        )

    # --- 4. coeficientes declarados ---
    confere, declarado = _coeficientes_conferem(
        trecho, documento.declared_coefficients
    )
    evidencia.coefficients_match_quadratic = confere
    if confere:
        evidencia.detalhes.append(
            f"os coeficientes {declarado} confirmam a leitura quadratica"
        )

    # --- 5. grafico ---
    if documento.describes_parabola:
        evidencia.detalhes.append(
            "a funcao associada e representada por uma parabola"
        )

    # --- 6. contexto de codigo (evidencia CONTRA o script) ---
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
    """Encontra os glifos da base e do digito e compara."""
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
    """Usa a TextGeometry da etapa 0 quando nao ha glifos por caractere."""
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


# --------------------------------------------------------------------------- #
# Pontuacao
# --------------------------------------------------------------------------- #
def pontuar_hipotese(hipotese: MathHypothesis, evidence: MathEvidence) -> float:
    """Pontua uma hipotese contra as evidencias (0 a 1).

    Os pesos de "expoente" sao os do plano. Os das outras hipoteses foram
    construidos em espelho, com uma assimetria deliberada: "identificador"
    ganha peso quando NAO ha evidencia de script, porque e a leitura
    conservadora - manter o que o texto diz. Assim, na duvida, o sistema
    nao inventa um expoente.
    """
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
            # A visual e PRIORITARIA: um digito comprovadamente na linha
            # de base CONTRADIZ o expoente. Sem esta penalidade, as
            # evidencias de contexto (secao, coeficientes, formula
            # proxima) somavam 0.55 e venciam a propria imagem.
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
        # indice e comum em listas de solucoes e sequencias
        if "solucoes" in _sem_acento(evidence.section_topic) or "sequencia" in \
                _sem_acento(evidence.section_topic):
            _somar(0.15, "a secao fala de solucoes ou sequencias indexadas")

    elif hipotese.label == "multiplicacao":
        # produto explicito e raro nesta forma: exige baseline E ausencia
        # de qualquer indicio de script
        if evidence.glyph_position == "baseline":
            _somar(0.25, "o digito esta na mesma linha de base")
        if evidence.contains_equation_operator:
            _somar(0.05, "ha operador de equacao no trecho")
        if not (evidence.nearby_equivalent_formula_uses_power
                or evidence.nearby_equivalent_formula_uses_subscript):
            _somar(0.10, "nenhuma formula proxima usa script")

    else:  # identificador
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
            # sem evidencia visual, manter o texto e o conservador
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


# --------------------------------------------------------------------------- #
# O reparador
# --------------------------------------------------------------------------- #
@dataclass
class ResultadoDoReparo:
    """A decisao, com tudo que a sustenta."""

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
    """Decide o que "x2" significa NESTE trecho, com evidencia registrada."""

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
        # Empate ou pontuacao baixa: fica com o identificador (o texto
        # como esta) e vira pendencia. Nunca se escolhe um script por
        # desempate arbitrario.
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
        """Repara todos os candidatos de um trecho. LOCALIZADO.

        Devolve (texto_reparado, resultados). Substitui de tras para a
        frente, para nao invalidar os offsets dos candidatos seguintes -
        e por isso que a correcao e por posicao, nunca por replace global.
        """
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

    # ------------------------------------------------------------------ #
    @staticmethod
    def _grafia(hipotese: MathHypothesis, candidato: ScriptCandidate) -> str:
        """A grafia Unicode da hipotese escolhida."""
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


# --------------------------------------------------------------------------- #
# Reparo por ocorrencia confirmada (indice de formulas repetidas)
# --------------------------------------------------------------------------- #
def encontrar_equivalentes(
    texto: str, formulas_documento: list, limite: float = 0.75,
) -> list:
    """Nos do documento cuja grafia e equivalente ao texto dado."""
    equivalentes = []
    for no in formulas_documento or []:
        origem = getattr(no, "source_text", None) or str(no)
        if comparar_formulas_aproximadas(texto, origem) >= limite:
            equivalentes.append(no)
    return equivalentes


def reparar_por_ocorrencia_confirmada(
    texto: str, formulas_documento: list, confianca_minima: float = 0.95,
) -> dict | None:
    """Usa uma ocorrencia CONFIRMADA como referencia para reparar.

    E a evidencia mais forte que o proprio documento oferece: a mesma
    equacao aparece de novo, com o script preservado e alta confianca. Se
    a unica diferenca entre as duas grafias for o script, a que tem o
    script e a correta.
    """
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


# --------------------------------------------------------------------------- #
# MATH-OCR-SCRIPT-001
# --------------------------------------------------------------------------- #
def revisar_scripts_perdidos(
    texto: str,
    glifos: list[Glyph] | None = None,
    geometria=None,
    documento: DocumentContext | None = None,
    contexto=None,
    formulas_documento: list | None = None,
) -> tuple[str, list]:
    """Revisao completa: repara o que da, e reporta o que nao da.

    Returns:
        (texto_reparado, issues). Confianca >= 0.90 aplica a correcao;
        entre 0.65 e 0.90 gera MATH-OCR-SCRIPT-001 com needs_review;
        abaixo disso o texto fica como esta - o silencio aqui e a decisao
        de nao mexer no que provavelmente ja esta certo.
    """
    from pipeline.matematica.cobertura_matematica import ValidationIssue

    issues: list = []

    # 1. a evidencia mais forte primeiro: ocorrencia confirmada
    if formulas_documento:
        confirmada = reparar_por_ocorrencia_confirmada(
            texto, formulas_documento
        )
        if confirmada:
            issues.append(ValidationIssue(
                check="revisar_scripts_perdidos", severity="INFO",
                code="MATH-OCR-SCRIPT-001",
                message=(
                    "script recuperado por ocorrencia confirmada: "
                    f"{confirmada['referencia']}"
                ),
                how_to_fix="nenhuma acao necessaria",
                evidencia=confirmada["reason"],
            ))
            return confirmada["texto_reparado"], issues

    # 2. decisao por evidencia acumulada
    reparado, resultados = reparador_padrao.reparar_texto(
        texto, glifos, geometria, documento, contexto
    )
    for resultado in resultados:
        if resultado.aplicar_automaticamente:
            issues.append(ValidationIssue(
                check="revisar_scripts_perdidos", severity="INFO",
                code="MATH-OCR-SCRIPT-001",
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
                code="MATH-OCR-SCRIPT-001",
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
    """O pacote que o critico precisa - nao apenas {"text": ...}.

    Texto plano nao carrega posicao: "x2" nao diz se o 2 estava elevado.
    Sem glifos, recorte e vizinhanca, o critico nao tem como decidir - e
    decidir sem evidencia e exatamente o que este modulo evita.
    """
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
