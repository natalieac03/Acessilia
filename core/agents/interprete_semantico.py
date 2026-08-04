"""
Dois componentes com responsabilidades distintas, como o plano separa:

  1. INTERPRETE SEMANTICO - entende a formula, constroi a estrutura e
     resolve ambiguidades de OCR. Devolve uma arvore validavel.
  2. PLANEJADOR DE LEITURA - transforma a arvore em fala acessivel, nos
     tres niveis, e produz a explicacao pedagogica SEPARADA.

Onde entra no pipeline: depois da reconstrucao da formula e do parser
deterministico, antes da geracao de TXT/MP3/MathML/DOCX.

A regra de acionamento (que controla custo e alucinacao): o parser
deterministico vem primeiro; o agente so e chamado quando a confianca
dele fica abaixo de 0.95. Formula limpa nunca paga uma chamada de modelo.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from pipeline.matematica.arvore_matematica import (
    Add,
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
    Subscript,
    Subtract,
    Symbol,
    TextMathSequence,
    UnaryMinus,
    construir_ast,
)

# Confianca do parser deterministico a partir da qual o agente NAO e
# chamado. Abaixo dela, ha ambiguidade que so o contexto resolve.
LIMIAR_DISPENSA_AGENTE = 0.95


# --------------------------------------------------------------------------- #
# Contexto unificado
# --------------------------------------------------------------------------- #
@dataclass
class ContextoMatematico:
    """Todas as evidencias que cercam uma expressao.

    Unifica o que estava espalhado: RegionContext (tipo de regiao, celula)
    e DocumentContext (secao, formulas proximas, coeficientes). O agente
    precisa das duas coisas ao mesmo tempo - a expressao nao se interpreta
    sem saber onde ela esta.
    """

    texto_anterior: str = ""
    texto_posterior: str = ""
    titulo_secao: str | None = None
    tipo_regiao: str = "text"
    conteudo_linha_tabela: list[str] = field(default_factory=list)
    formulas_proximas: list[str] = field(default_factory=list)
    tema_documento: str | None = None
    cabecalho_coluna: str | None = None
    coeficientes_declarados: dict[str, str] = field(default_factory=dict)
    descreve_parabola: bool = False
    recorte_visual: str | None = None

    @property
    def e_celula(self) -> bool:
        return self.tipo_regiao in ("table", "cell")

    def para_region_context(self):
        """Adapta para o RegionContext que o detector consome."""
        from pipeline.matematica.evidencia_matematica import RegionContext

        vizinho = " ".join(filter(None, [
            self.texto_anterior, self.texto_posterior,
            self.cabecalho_coluna or "",
            *self.conteudo_linha_tabela,
        ]))
        return RegionContext(
            tipo_regiao=self.tipo_regiao, e_celula=self.e_celula,
            texto_vizinho=vizinho.strip(),
        )

    def para_document_context(self):
        """Adapta para o DocumentContext que o reparador consome."""
        from pipeline.matematica.reparador_matematico import DocumentContext

        return DocumentContext(
            section_title=self.titulo_secao or "",
            section_topic=self.tema_documento or "",
            nearby_formulas=list(self.formulas_proximas),
            declared_coefficients=dict(self.coeficientes_declarados),
            describes_parabola=self.descreve_parabola,
        )

    def resumir(self) -> str:
        """Resumo legivel, para o prompt e para o relatorio."""
        partes = []
        if self.titulo_secao:
            partes.append(f"secao: {self.titulo_secao}")
        if self.tema_documento:
            partes.append(f"tema: {self.tema_documento}")
        if self.texto_anterior:
            partes.append(f"antes: ...{self.texto_anterior[-60:]}")
        if self.texto_posterior:
            partes.append(f"depois: {self.texto_posterior[:60]}...")
        if self.cabecalho_coluna:
            partes.append(f"coluna: {self.cabecalho_coluna}")
        if self.conteudo_linha_tabela:
            partes.append("linha: " + " | ".join(self.conteudo_linha_tabela[:3]))
        if self.formulas_proximas:
            partes.append("proximas: " + ", ".join(self.formulas_proximas[:3]))
        return "; ".join(partes)


def construir_contexto_matematico(
    texto_anterior: str = "",
    texto_posterior: str = "",
    titulo_secao: str | None = None,
    tipo_regiao: str = "text",
    conteudo_linha_tabela: list[str] | None = None,
    formulas_proximas: list[str] | None = None,
    tema_documento: str | None = None,
    **extras: Any,
) -> ContextoMatematico:
    """Reune as evidencias usadas para interpretar a expressao."""
    return ContextoMatematico(
        texto_anterior=texto_anterior or "",
        texto_posterior=texto_posterior or "",
        titulo_secao=titulo_secao,
        tipo_regiao=tipo_regiao or "text",
        conteudo_linha_tabela=list(conteudo_linha_tabela or []),
        formulas_proximas=list(formulas_proximas or []),
        tema_documento=tema_documento,
        cabecalho_coluna=extras.get("cabecalho_coluna"),
        coeficientes_declarados=dict(extras.get("coeficientes_declarados") or {}),
        descreve_parabola=bool(extras.get("descreve_parabola")),
        recorte_visual=extras.get("recorte_visual"),
    )


# --------------------------------------------------------------------------- #
# Saida do agente
# --------------------------------------------------------------------------- #
class ResultadoSemanticoMatematico(BaseModel):
    """A interpretacao completa, com as tres leituras separadas."""

    formula_original: str
    formula_reparada: str = ""

    arvore_semantica: dict = Field(default_factory=dict)

    latex: str = ""
    mathml: str = ""
    omml: str = ""

    # AS TRES LEITURAS, geradas juntas. O renderer escolhe; nao e preciso
    # reprocessar para trocar de modo.
    fala_curta: str = ""
    fala_estrutural: str = ""
    # COMPLEMENTAR, nunca substituta da leitura estrutural.
    explicacao_pedagogica: str | None = None

    evidencias: list[str] = Field(default_factory=list)
    ambiguidades_encontradas: list[str] = Field(default_factory=list)
    alternativas_rejeitadas: list[str] = Field(default_factory=list)
    problemas: list[dict] = Field(default_factory=list)

    confianca: float = Field(default=0.0, ge=0, le=1)
    precisa_revisao_humana: bool = True
    usou_agente_de_ia: bool = False

    @property
    def leitura_formula(self) -> str:
        """Alias do plano: a transcricao (nao a explicacao)."""
        return self.fala_estrutural

    @property
    def nota_pedagogica(self) -> str:
        """Alias do plano: a explicacao (nao a transcricao)."""
        return self.explicacao_pedagogica or ""

    def para_math_node(self):
        """Converte para o MathNode que os renderers consomem."""
        from pipeline.matematica.nos_matematicos import MathNode

        return MathNode(
            source_text=self.formula_reparada or self.formula_original,
            ast=self.arvore_semantica,
            latex=self.latex, mathml=self.mathml, omml=self.omml,
            speech_pt_br=self.fala_estrutural,
            confidence=self.confianca,
            uncertainties=list(self.ambiguidades_encontradas),
            validation_issues=list(self.problemas),
            review_status=("needs_review" if self.precisa_revisao_humana
                           else "reviewed"),
        )


# --------------------------------------------------------------------------- #
# 1. INTERPRETE SEMANTICO
# --------------------------------------------------------------------------- #
@dataclass
class HipoteseMatematica:
    ast: NoAST
    label: str
    score: float = 0.0
    justificativas: list[str] = field(default_factory=list)
    # Tokens que o parser deixou de fora ficam FORA da arvore - inspecionar
    # apenas os nos nao os enxerga. Esta lista viaja com a hipotese para
    # que a pontuacao possa considera-los.
    tokens_descartados: list[str] = field(default_factory=list)
    parse_completo: bool = True


def gerar_hipoteses_de_interpretacao(
    formula_extraida: str, tokens: list | None = None,
) -> list[HipoteseMatematica]:
    """Alternativas possiveis para os trechos ambiguos da formula.

    A primeira hipotese e sempre a leitura do parser deterministico. As
    demais vem dos trechos ambiguos - hoje o caso "x2", que pode ser
    potencia, subscrito, multiplicacao ou identificador.
    """
    from pipeline.matematica.reparador_matematico import (
        detectar_script_perdido,
        gerar_interpretacoes_script,
    )

    parse = construir_ast(formula_extraida)
    hipoteses = [HipoteseMatematica(
        ast=parse.ast, label="parser_deterministico",
        tokens_descartados=[t.value for t in parse.nao_consumidos],
        parse_completo=parse.completa,
    )]
    for candidato in detectar_script_perdido(formula_extraida):
        for alternativa in gerar_interpretacoes_script(
            candidato.base, candidato.digit
        ):
            hipoteses.append(HipoteseMatematica(
                ast=alternativa.ast,
                label=f"{candidato.raw}:{alternativa.label}",
            ))
    return hipoteses


def pontuar_hipotese_com_contexto(
    hipotese: HipoteseMatematica,
    contexto: ContextoMatematico,
    evidencia_visual=None,
) -> float:
    """Confianca da hipotese, com contexto, geometria e consistencia."""
    from pipeline.matematica.reparador_matematico import (
        MathHypothesis,
        coletar_evidencias,
        detectar_script_perdido,
        pontuar_hipotese,
    )

    if hipotese.label == "parser_deterministico":
        # A confianca do parser depende de DUAS coisas: nenhum no
        # Desconhecido DENTRO da arvore e nenhum token descartado FORA
        # dela. Checar so a arvore deixava "x @ y" passar com 0.95, porque
        # o "@" e o "y" nunca entraram nela.
        tem_lacuna = any(
            n.tipo == "Desconhecido" for n in hipotese.ast.percorrer()
        )
        sobrou = bool(hipotese.tokens_descartados) or not hipotese.parse_completo
        if tem_lacuna or sobrou:
            hipotese.score = 0.5
            motivos = []
            if tem_lacuna:
                motivos.append("arvore com trecho nao interpretado")
            if hipotese.tokens_descartados:
                motivos.append(
                    "tokens descartados pelo parser: "
                    + " ".join(hipotese.tokens_descartados[:6])
                )
            hipotese.justificativas = motivos
        else:
            hipotese.score = 0.95
            hipotese.justificativas = [
                "o parser deterministico explicou a expressao inteira"
            ]
        return hipotese.score

    bruto, _, rotulo = hipotese.label.partition(":")
    candidatos = detectar_script_perdido(bruto or "") or []
    if not candidatos:
        hipotese.score = 0.0
        return 0.0

    evidencia = coletar_evidencias(
        candidatos[0], bruto,
        glifos=getattr(evidencia_visual, "glifos", None),
        geometria=getattr(evidencia_visual, "geometria", None),
        documento=contexto.para_document_context(),
        contexto=contexto.para_region_context(),
    )
    ponte = MathHypothesis(ast=hipotese.ast, label=rotulo)
    hipotese.score = pontuar_hipotese(ponte, evidencia)
    hipotese.justificativas = list(ponte.evidencias)
    return hipotese.score


@dataclass
class EvidenciaVisual:
    """O que o recorte da imagem oferece."""

    glifos: list = field(default_factory=list)
    geometria: Any = None
    recorte: str | None = None


class InterpreteSemanticoMatematico:
    """Componente 1 - entende a formula e resolve ambiguidades."""

    def interpretar(
        self,
        formula_extraida: str,
        contexto: ContextoMatematico | None = None,
        evidencia_visual: EvidenciaVisual | None = None,
        arvore_inicial: NoAST | None = None,
    ) -> tuple[NoAST, str, dict]:
        """Devolve (arvore, formula_reparada, relatorio).

        O relatorio traz evidencias, ambiguidades e alternativas
        rejeitadas - o que permite auditar a escolha depois.
        """
        contexto = contexto or ContextoMatematico()
        relatorio: dict[str, list[str]] = {
            "evidencias": [], "ambiguidades": [], "rejeitadas": [],
        }

        # 1. reparo de OCR por evidencia acumulada
        from pipeline.matematica.reparador_matematico import revisar_scripts_perdidos

        reparada, issues = revisar_scripts_perdidos(
            formula_extraida,
            glifos=(evidencia_visual.glifos if evidencia_visual else None),
            geometria=(evidencia_visual.geometria if evidencia_visual else None),
            documento=contexto.para_document_context(),
            contexto=contexto.para_region_context(),
        )
        for issue in issues:
            if issue.severity == "INFO":
                relatorio["evidencias"].append(issue.message)
            else:
                relatorio["ambiguidades"].append(issue.message)
            if issue.evidencia:
                relatorio["evidencias"].append(issue.evidencia)

        # 2. hipoteses e pontuacao
        hipoteses = gerar_hipoteses_de_interpretacao(reparada)
        for hipotese in hipoteses:
            pontuar_hipotese_com_contexto(hipotese, contexto, evidencia_visual)
        escolhida = max(hipoteses, key=lambda h: h.score)
        for hipotese in hipoteses:
            if hipotese is not escolhida and hipotese.score > 0:
                relatorio["rejeitadas"].append(
                    f"{hipotese.label} (score {hipotese.score:.2f})"
                )
        relatorio["evidencias"].extend(escolhida.justificativas)

        # 3. contexto explicito como evidencia registrada
        if contexto.resumir():
            relatorio["evidencias"].append(f"contexto: {contexto.resumir()}")

        arvore = arvore_inicial if arvore_inicial is not None else escolhida.ast
        return arvore, reparada, relatorio


# --------------------------------------------------------------------------- #
# 2. PLANEJADOR DE LEITURA
# --------------------------------------------------------------------------- #
Modo = Literal["curta", "estrutural", "pedagogica"]


def gerar_leitura_matematica(
    arvore: NoAST, modo: str = "estrutural", idioma: str = "pt-BR",
):
    """Gera a leitura no modo pedido. Devolve o SpeechPlan."""
    from pipeline.matematica.fala_matematica import gerar_fala_matematica

    equivalencia = {"curta": "conciso", "estrutural": "estrutural",
                    "pedagogica": "pedagogico"}
    return gerar_fala_matematica(
        arvore, locale=idioma, modo=equivalencia.get(modo, modo)
    )


# Notas didaticas de formulas reconhecidas. Nao e "o modelo explicando":
# e um catalogo pequeno e conferido, indexado pelo hash canonico da
# arvore. Fora dele, a explicacao e apenas estrutural - o sistema nao
# inventa significado pedagogico que nao conhece.
_NOTAS_CONHECIDAS = {
    "bhaskara": "A fórmula fornece as possíveis raízes de uma equação do "
                "segundo grau.",
    "discriminante": "O discriminante indica quantas raízes reais a equação "
                     "possui.",
    "forma_geral": "É a forma geral da equação do segundo grau, com os "
                   "coeficientes a, b e c.",
}


def _identificar_formula_conhecida(arvore: NoAST) -> str | None:
    """Reconhece formulas do catalogo pela ESTRUTURA, nao pela grafia."""
    try:
        tipos = [n.tipo for n in arvore.percorrer()]
        simbolos = {n.nome for n in arvore.percorrer()
                    if isinstance(n, Symbol)}

        if (isinstance(arvore, Relation) and "Divide" in tipos
                and "Sqrt" in tipos and "PlusMinus" in tipos):
            return "bhaskara"
        if (isinstance(arvore, Relation) and "Subtract" in tipos
                and "Power" in tipos and {"a", "b", "c"} <= simbolos):
            return "discriminante"
        if (isinstance(arvore, Relation) and "Add" in tipos
                and "Power" in tipos and {"a", "b", "c"} <= simbolos):
            return "forma_geral"
    except Exception:
        pass
    return None


def descrever_estrutura(arvore: NoAST) -> str:
    """Narrativa da ESTRUTURA - a explicacao pedagogica de 3o nivel.

    Diferente da leitura estrutural: aquela transcreve a expressao; esta
    descreve como ela e montada. "O numerador contem o oposto de b,
    seguido do operador mais ou menos e da raiz quadrada de delta."
    """
    from pipeline.matematica.fala_matematica import gerar_fala_matematica

    def _falar(no: NoAST, modo: str = "estrutural") -> str:
        return gerar_fala_matematica(no, modo=modo).texto

    try:
        if isinstance(arvore, Relation) and len(arvore.operandos) == 2:
            esquerda, direita = arvore.operandos
            alvo = _falar(esquerda)
            if isinstance(direita, Divide):
                numerador = _descrever_parte(direita.numerador)
                denominador = _descrever_parte(direita.denominador)
                return (
                    f"A fórmula calcula {alvo} por meio de uma fração. "
                    f"O numerador contém {numerador}. "
                    f"O denominador é {denominador}."
                )
            if isinstance(direita, Sqrt):
                return (f"A fórmula calcula {alvo} pela raiz quadrada de "
                        f"{_falar(direita.radicando)}.")
            # Sem estrutura notavel do lado direito, uma "explicacao" seria
            # a leitura reescrita. Melhor nao produzir nada.
            if type(direita).__name__ in ("Symbol", "Integer", "Numero"):
                return ""
            return (f"A fórmula relaciona {alvo} com "
                    f"{_descrever_parte(direita)}.")
        if isinstance(arvore, Divide):
            return (f"É uma fração. O numerador contém "
                    f"{_descrever_parte(arvore.numerador)}. O denominador é "
                    f"{_descrever_parte(arvore.denominador)}.")
        if isinstance(arvore, Sqrt):
            return (f"É a raiz quadrada de "
                    f"{_falar(arvore.radicando)}.")
        return f"A expressão é {_descrever_parte(arvore)}."
    except Exception:
        return ""


# "de" + artigo definido vira contracao em portugues. Sem isto a
# explicacao sai como "e de a raiz quadrada", que soa errado no TTS.
_CONTRACOES = (("de a ", "da "), ("de o ", "do "), ("de as ", "das "),
               ("de os ", "dos "))


def _contrair(texto: str) -> str:
    resultado = texto
    for antes, depois in _CONTRACOES:
        resultado = resultado.replace(antes, depois)
    return resultado


# "vezes" e feminino: 2 -> "duas", 1 -> "uma". A tabela normativa da
# secao 7 pede "dois vezes a" na LEITURA (transcricao); aqui, na
# EXPLICACAO em prosa, a concordancia correta e "duas vezes".
_MULTIPLICADOR_FEMININO = {"um": "uma", "dois": "duas"}


def _descrever_parte(no: NoAST) -> str:
    """Descreve um trecho nomeando as operacoes, nao apenas lendo."""
    from pipeline.matematica.fala_matematica import gerar_fala_matematica

    def _falar(interno: NoAST, modo: str = "estrutural") -> str:
        return gerar_fala_matematica(interno, modo=modo).texto

    if isinstance(no, Group):
        return _descrever_parte(no.conteudo)
    if isinstance(no, PlusMinus) and no.binaria:
        return _contrair(
            f"{_descrever_parte(no.esquerda)}, seguido do operador mais "
            f"ou menos e de {_descrever_parte(no.operando)}"
        )
    if isinstance(no, UnaryMinus):
        return f"o oposto de {_falar(no.operando)}"
    if isinstance(no, Sqrt):
        return f"a raiz quadrada de {_falar(no.radicando)}"
    if isinstance(no, Multiply):
        partes = [_falar(f) for f in no.fatores]
        if len(partes) == 2 and isinstance(no.fatores[0], (Integer, Numero)):
            multiplicador = _MULTIPLICADOR_FEMININO.get(partes[0], partes[0])
            return f"{multiplicador} vezes o coeficiente {partes[1]}"
        return " vezes ".join(partes)
    if isinstance(no, Power):
        return f"{_falar(no.base)} elevado a {_falar(no.expoente)}"
    if isinstance(no, Subtract):
        return (f"a diferença entre {_falar(no.left)} e "
                f"{_falar(no.right)}")
    if isinstance(no, Add):
        return "a soma de " + ", ".join(_falar(t) for t in no.termos)
    return _falar(no)


def _e_tautologica(explicacao: str, leitura: str) -> bool:
    """A explicacao apenas repete a leitura com outras palavras?

    "A expressao e xis um e xis dois" nao explica nada - e a leitura com
    um prefixo. Melhor devolver None: uma explicacao redundante gasta o
    tempo do aluno e ensina a ignorar o campo.
    """
    import re

    def _nucleo(texto: str) -> str:
        limpo = re.sub(
            r"^(a expressao e|a formula relaciona|e a|e uma|e o)\s+", "",
            texto.strip().lower().rstrip("."),
        )
        return re.sub(r"[^\w]", "", limpo)

    from pipeline.matematica.reparador_matematico import _sem_acento

    return _nucleo(_sem_acento(explicacao)) == _nucleo(_sem_acento(leitura))


def gerar_explicacao_pedagogica(
    arvore: NoAST, leitura_estrutural: str = "",
) -> str | None:
    """A explicacao COMPLEMENTAR: o que a formula faz, e como e montada.

    Duas camadas: a nota do catalogo (o que a formula serve para calcular)
    e a narrativa da estrutura. Sem catalogo, so a narrativa - o sistema
    nao atribui significado didatico a uma expressao que nao reconhece.

    Devolve None quando a narrativa apenas repetiria a leitura.
    """
    conhecida = _identificar_formula_conhecida(arvore)
    estrutura = _contrair(descrever_estrutura(arvore))

    if conhecida:
        nota = _NOTAS_CONHECIDAS[conhecida]
        return f"{nota} {estrutura}".strip() if estrutura else nota
    if not estrutura:
        return None
    if leitura_estrutural and _e_tautologica(estrutura, leitura_estrutural):
        return None
    return estrutura


class PlanejadorDeLeituraMatematica:
    """Componente 2 - transforma a arvore em leituras acessiveis."""

    def planejar(
        self, arvore: NoAST, idioma: str = "pt-BR",
    ) -> dict[str, str]:
        """As tres leituras de uma vez, mais a explicacao separada."""
        curta = gerar_leitura_matematica(arvore, "curta", idioma)
        estrutural = gerar_leitura_matematica(arvore, "estrutural", idioma)
        return {
            "fala_curta": curta.texto,
            "fala_estrutural": estrutural.texto,
            "explicacao_pedagogica": gerar_explicacao_pedagogica(
                arvore, estrutural.texto
            ) or "",
            "avisos": curta.avisos + estrutural.avisos,
        }


# --------------------------------------------------------------------------- #
# Critico especifico
# --------------------------------------------------------------------------- #
def conferir_fala_com_formula(arvore: NoAST, fala: str) -> list[dict]:
    """Confere se operadores, operandos, indices, expoentes e
    agrupamentos aparecem na leitura."""
    from pipeline.matematica.cobertura_matematica import validar_cobertura_da_fala

    problemas = validar_cobertura_da_fala("", arvore, fala)
    return [p.to_dict() for p in problemas]


def validar_adaptacao_semantica(
    resultado: ResultadoSemanticoMatematico,
) -> list[dict]:
    """As quatro conferencias especificas do plano.

    Cada uma pergunta: a estrutura existe na arvore? Entao ela aparece na
    fala? Nao basta a arvore estar certa - o aluno ouve a fala.
    """
    from pipeline.matematica.cobertura_matematica import ValidationIssue

    problemas: list[ValidationIssue] = []
    try:
        arvore = _arvore_do_dicionario(resultado.arvore_semantica)
    except Exception:
        return [ValidationIssue(
            check="validar_adaptacao_semantica", severity="ERROR",
            code="MATH-SPEECH-001",
            message="nao foi possivel reconstruir a arvore para conferencia",
        ).to_dict()]

    if arvore is None:
        return []
    fala = (resultado.fala_estrutural or "").lower()
    tipos = {n.tipo for n in arvore.percorrer()}

    def _reprovar(mensagem: str, codigo: str = "MATH-SPEECH-001",
                  severidade: str = "BLOCKER"):
        problemas.append(ValidationIssue(
            check="validar_adaptacao_semantica", severity=severidade,
            code=codigo, message=mensagem,
            how_to_fix="regerar a leitura a partir da arvore",
            evidencia=fala[:100],
        ))

    if {"Subtract"} & tipos and "menos" not in fala:
        _reprovar("Sinal de subtracao ausente na fala.", "MATH-SIGN-001")
    if "UnaryMinus" in tipos and "menos" not in fala and "oposto" not in fala:
        _reprovar("Menos unario ausente na fala.", "MATH-SIGN-001")

    if "Sqrt" in tipos:
        if "raiz" not in fala:
            _reprovar("Radical ausente na fala.", "MATH-ROOT-001")
        else:
            for raiz in (n for n in arvore.percorrer() if isinstance(n, Sqrt)):
                if not _radicando_foi_falado(raiz, fala):
                    _reprovar("Radicando ausente na fala.", "MATH-ROOT-001")
                    break

    if "Subscript" in tipos and not _indices_aparecem_na_fala(arvore, fala):
        _reprovar("Subscrito ausente na fala.", "MATH-SUB-001", "ERROR")

    if "Power" in tipos and not any(
        p in fala for p in ("quadrado", "cubo", "elevado")
    ):
        _reprovar("Expoente ausente na fala.", "MATH-POW-001")

    if "Divide" in tipos:
        if "numerador" not in fala and "sobre" not in fala:
            _reprovar("Numerador nao foi identificado.", "MATH-FRAC-001")
        elif "numerador" in fala and "denominador" not in fala:
            _reprovar("Denominador nao foi identificado.", "MATH-FRAC-001")

    if "Group" in tipos and "parênteses" not in fala and "parenteses" not in fala:
        # agrupamento sem realizacao e aviso, nao bloqueio: em expressao
        # simples o grupo pode ser transparente
        _reprovar("Agrupamento nao anunciado na fala.", "MATH-BOUND-001",
                  "WARNING")

    return [p.to_dict() for p in problemas]


def _radicando_foi_falado(raiz: Sqrt, fala: str) -> bool:
    from pipeline.matematica.fala_matematica import gerar_fala_matematica

    esperado = gerar_fala_matematica(raiz.radicando, modo="conciso").texto
    if not esperado:
        return False
    # basta a primeira palavra significativa aparecer
    primeira = esperado.split(",")[0].split()[0] if esperado.split() else ""
    return bool(primeira) and primeira.lower() in fala


def _indices_aparecem_na_fala(arvore: NoAST, fala: str) -> bool:
    from pipeline.matematica.fala_matematica import gerar_fala_matematica

    for indice in (n for n in arvore.percorrer()
                   if isinstance(n, Subscript)):
        falado = gerar_fala_matematica(indice.indice, modo="conciso").texto
        if falado and falado.lower() not in fala:
            return False
    return True


def _arvore_do_dicionario(dados: dict) -> NoAST | None:
    """Reconstroi a AST a partir do dicionario serializado."""
    if not dados or not isinstance(dados, dict):
        return None
    import pipeline.matematica.arvore_matematica as modulo

    tipo = dados.get("tipo")
    classe = getattr(modulo, tipo, None) if tipo else None
    if classe is None:
        return None
    argumentos: dict[str, Any] = {}
    for chave, valor in dados.items():
        if chave == "tipo":
            continue
        if isinstance(valor, dict) and "tipo" in valor:
            argumentos[chave] = _arvore_do_dicionario(valor)
        elif isinstance(valor, list):
            argumentos[chave] = [
                _arvore_do_dicionario(v) if isinstance(v, dict) and "tipo" in v
                else v for v in valor
            ]
        else:
            argumentos[chave] = valor
    try:
        return classe(**argumentos)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# O agente completo
# --------------------------------------------------------------------------- #
class AgenteSemanticoMatematico:
    """Interprete + planejador, com o portao de acionamento do plano."""

    def __init__(self):
        self.interprete = InterpreteSemanticoMatematico()
        self.planejador = PlanejadorDeLeituraMatematica()

    def interpretar_formula_semanticamente(
        self,
        formula_extraida: str,
        imagem_formula: EvidenciaVisual | None = None,
        contexto: ContextoMatematico | None = None,
        arvore_inicial: NoAST | None = None,
    ) -> ResultadoSemanticoMatematico:
        """Interpreta, resolve ambiguidades e devolve arvore validavel."""
        from pipeline.matematica.serializacao_matematica import gerar_latex, gerar_mathml, gerar_omml

        contexto = contexto or ContextoMatematico()
        arvore, reparada, relatorio = self.interprete.interpretar(
            formula_extraida, contexto, imagem_formula, arvore_inicial
        )
        # tokens que sobraram do parser sao conteudo perdido: registram-se
        # como ambiguidade, nunca em silencio
        parse_final = construir_ast(reparada)
        if parse_final.nao_consumidos:
            relatorio["ambiguidades"].append(
                "o parser deixou de fora: "
                + " ".join(t.value for t in parse_final.nao_consumidos[:6])
            )
        leituras = self.planejador.planejar(arvore)

        latex = gerar_latex(arvore)
        resultado = ResultadoSemanticoMatematico(
            formula_original=formula_extraida,
            formula_reparada=reparada,
            arvore_semantica=arvore.to_dict(),
            latex=latex,
            mathml=gerar_mathml(arvore, latex),
            omml=gerar_omml(arvore),
            fala_curta=leituras["fala_curta"],
            fala_estrutural=leituras["fala_estrutural"],
            explicacao_pedagogica=leituras["explicacao_pedagogica"] or None,
            evidencias=relatorio["evidencias"],
            ambiguidades_encontradas=(
                relatorio["ambiguidades"] + leituras["avisos"]
            ),
            alternativas_rejeitadas=relatorio["rejeitadas"],
        )

        problemas = validar_adaptacao_semantica(resultado)
        resultado.problemas = problemas
        bloqueia = any(p.get("severity") == "BLOCKER" for p in problemas)
        resultado.confianca = (
            0.3 if bloqueia else
            0.6 if resultado.ambiguidades_encontradas else 0.95
        )
        resultado.precisa_revisao_humana = bool(
            bloqueia or resultado.ambiguidades_encontradas
        )
        return resultado


agente_semantico = AgenteSemanticoMatematico()


def interpretar_formula_semanticamente(
    formula_extraida: str,
    imagem_formula: EvidenciaVisual | None = None,
    contexto: ContextoMatematico | None = None,
    arvore_inicial: NoAST | None = None,
) -> ResultadoSemanticoMatematico:
    """Interpreta a formula, resolve ambiguidades e devolve uma arvore
    matematica validavel."""
    return agente_semantico.interpretar_formula_semanticamente(
        formula_extraida, imagem_formula, contexto, arvore_inicial
    )


# --------------------------------------------------------------------------- #
# Orquestracao: deterministico primeiro
# --------------------------------------------------------------------------- #
def processar_formula_acessivel(
    evidencia, contexto: ContextoMatematico | None = None,
):
    """Fluxo do plano: parser deterministico primeiro, agente depois.

    Se a arvore deterministica explica a expressao inteira (confianca
    >= 0.95), o agente NAO e chamado. E o que mantem o custo baixo: a
    maioria das formulas de um material e limpa.
    """
    from pipeline.matematica.evidencia_matematica import SourceEvidence

    contexto = contexto or ContextoMatematico()
    if isinstance(evidencia, str):
        texto = evidencia
        geometria = None
        recorte = None
    else:
        texto = getattr(evidencia, "raw_text", "")
        geometria = getattr(evidencia, "geometry", None)
        recorte = getattr(evidencia, "image_crop_path", None)

    parse = construir_ast(texto, geometria)
    confianca_deterministica = 0.95 if parse.completa else 0.5

    if confianca_deterministica >= LIMIAR_DISPENSA_AGENTE:
        resultado = agente_semantico.interpretar_formula_semanticamente(
            texto, None, contexto, arvore_inicial=parse.ast
        )
        resultado.usou_agente_de_ia = False
        return resultado.para_math_node()

    visual = EvidenciaVisual(geometria=geometria, recorte=recorte)
    resultado = agente_semantico.interpretar_formula_semanticamente(
        texto, visual, contexto
    )
    resultado.usou_agente_de_ia = True
    return resultado.para_math_node()


# --------------------------------------------------------------------------- #
# Atalhos nomeados do plano
# --------------------------------------------------------------------------- #
def adaptar_formula_dentro_do_paragrafo(
    paragrafo: str, segmentos: list | None = None,
    contexto: ContextoMatematico | None = None,
):
    """Substitui SOMENTE os trechos matematicos por MathNode.

    O texto ao redor e preservado integralmente - a invariante e
    verificada, e a violacao devolve o paragrafo como texto puro.
    """
    from pipeline.matematica.matematica_inline import segmentar_bloco_misto
    from pipeline.matematica.nos_matematicos import MixedParagraph, TextNode

    contexto = contexto or ContextoMatematico()
    resultado = segmentar_bloco_misto(paragrafo) if segmentos is None else None
    lista = segmentos if segmentos is not None else resultado.segments
    if resultado is not None and not resultado.aceita:
        return MixedParagraph(children=[TextNode(source_text=paragrafo)])

    filhos: list = []
    for segmento in lista:
        tipo = getattr(segmento, "type", "text")
        texto = getattr(segmento, "source_text", "")
        if tipo == "text":
            filhos.append(TextNode(source_text=texto))
            continue
        contexto_local = ContextoMatematico(
            **{**contexto.__dict__,
               "texto_anterior": paragrafo[:getattr(segmento, "start", 0)],
               "texto_posterior": paragrafo[getattr(segmento, "end", 0):]}
        )
        filhos.append(processar_formula_acessivel(texto, contexto_local))

    paragrafo_misto = MixedParagraph(children=filhos)
    if paragrafo_misto.source_text != paragrafo:
        return MixedParagraph(children=[TextNode(source_text=paragrafo)])
    return paragrafo_misto


def adaptar_matematica_da_celula(
    texto_celula: str,
    cabecalho_coluna: str = "",
    outras_celulas_da_linha: list[str] | None = None,
    contexto_documento: ContextoMatematico | None = None,
):
    """Usa as outras celulas da LINHA para resolver ambiguidades."""
    from pipeline.matematica.evidencia_matematica import RegionContext
    from pipeline.matematica.matematica_inline import (
        detectar_candidatos_matematicos,
        segmentar_bloco_misto,
    )
    from pipeline.matematica.nos_matematicos import MixedTableCell, TextNode

    base = contexto_documento or ContextoMatematico()
    contexto = ContextoMatematico(
        **{**base.__dict__, "tipo_regiao": "table",
           "cabecalho_coluna": cabecalho_coluna,
           "conteudo_linha_tabela": list(outras_celulas_da_linha or [])}
    )

    candidatos = detectar_candidatos_matematicos(
        texto_celula, None, contexto.para_region_context()
    )
    segmentacao = segmentar_bloco_misto(texto_celula, candidatos)
    filhos: list = []
    if segmentacao.aceita:
        for segmento in segmentacao.segments:
            if segmento.type == "text":
                filhos.append(TextNode(source_text=segmento.source_text))
            else:
                filhos.append(processar_formula_acessivel(
                    segmento.source_text, contexto
                ))
    else:
        filhos = [TextNode(source_text=texto_celula)]

    celula = MixedTableCell(
        row=0, column=0,
        headers=[cabecalho_coluna] if cabecalho_coluna else [],
        children=filhos,
    )
    if celula.source_text != texto_celula:
        return MixedTableCell(
            row=0, column=0,
            headers=[cabecalho_coluna] if cabecalho_coluna else [],
            children=[TextNode(source_text=texto_celula)],
        )
    return celula
