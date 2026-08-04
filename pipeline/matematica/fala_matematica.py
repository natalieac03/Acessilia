"""Percorre a arvore e gera a fala em portugues.

E a saida que alimenta o TXT e, por consequencia, o audio. Precisa
soar como alguem lendo a formula em voz alta, nao como quem soletra
simbolo por simbolo.

Dois modos derivam da MESMA arvore: o estrutural anuncia as fronteiras
("uma fracao. No numerador: ... Fim da fracao") porque em expressao
longa o ouvinte se perde sem saber onde cada parte termina; o conciso
le corrido ("menos b sobre dois a"). Expressao simples nao recebe os
marcadores nos dois modos — seria ruido.

Nunca levanta excecao: em caso de falha devolve o plano com a lacuna
marcada, e o validador barra na frente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

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

Modo = Literal["conciso", "estrutural", "pedagogico"]

_MARCA_PAUSA = "\u2062"
PAUSA_CURTA = 100
PAUSA_MEDIA = 150
PAUSA_LONGA = 250


def _pausa(ms: int) -> str:
    return f"{_MARCA_PAUSA}{ms}{_MARCA_PAUSA}"


_LIMITE_EXPRESSAO_LONGA = 4


@dataclass
class SpeechPlan:

    texto: str
    modo: str = "estrutural"
    locale: str = "pt-BR"
    tem_lacuna: bool = False
    avisos: list[str] = field(default_factory=list)
    texto_com_pausas: str = ""
    nos_falados: set[int] = field(default_factory=set)

    def __str__(self) -> str:
        return self.texto

    @property
    def ssml(self) -> str:
        return gerar_ssml(self)

    @property
    def tem_simbolo_cru(self) -> bool:
        return any(c in self.texto for c in _SIMBOLOS_PROIBIDOS_NA_FALA)


from pipeline.matematica.vocabulario_de_fala import (
    FUNCOES_FALADAS as _FUNCOES_FALADAS,
    GREGAS_FALADAS as _GREGAS_FALADAS,
    RELACOES_FALADAS as _RELACOES_FALADAS,
    SIMBOLOS_PROIBIDOS_NA_FALA as _SIMBOLOS_PROIBIDOS_NA_FALA,
    LETRAS_SOLETRADAS as _LETRAS_SOLETRADAS,
    falar_letra as _falar_letra,
    numero_por_extenso as _numero_em_palavras,
)


_PADRAO_NUMERO_CRU = re.compile(r"^(-)?(\d+)([.,](\d+))?$")


def _falar_numero_cru(texto: str) -> str | None:
    casado = _PADRAO_NUMERO_CRU.match(texto)
    if not casado:
        return None
    sinal, inteiro, _, decimal = casado.groups()
    fala = _numero_em_palavras(int(inteiro))
    if decimal:
        fala = f"{fala} vírgula {_numero_em_palavras(int(decimal))}"
    return f"menos {fala}" if sinal else fala


def _e_folha(no: NoAST) -> bool:
    return isinstance(no, (Integer, Numero, Symbol))


class _Planejador:
    def __init__(self, modo: Modo, soletrar: bool,
                 indice_tecnico: bool = False):
        self.modo = modo
        self.soletrar = soletrar
        self.indice_tecnico = indice_tecnico
        self.tem_lacuna = False
        self.avisos: list[str] = []
        self.nos_falados: set[int] = set()

    def simbolo(self, nome: str) -> str:
        if len(nome) == 2 and nome.startswith("Δ"):
            return f"delta {self.simbolo(nome[1])}"
        if nome in _GREGAS_FALADAS:
            return _GREGAS_FALADAS[nome]
        minusculo = nome.lower()
        if minusculo in _GREGAS_FALADAS and minusculo == nome:
            return _GREGAS_FALADAS[minusculo]
        if self.soletrar:
            return _falar_letra(nome)
        return nome

    def falar(self, no: NoAST) -> str:
        metodo = getattr(self, f"_{type(no).__name__.lower()}", None)
        if metodo is None:
            self.tem_lacuna = True
            self.avisos.append(f"no sem regra de fala: {no.tipo}")
            return ""
        falado = metodo(no)
        if falado and falado.strip():
            self.nos_falados.add(id(no))
        return falado

    def _integer(self, no: Integer) -> str:
        return _numero_em_palavras(no.valor)

    def _numero(self, no: Numero) -> str:
        if "," in no.texto:
            inteiro, decimal = no.texto.split(",", 1)
        elif "." in no.texto:
            inteiro, decimal = no.texto.split(".", 1)
        else:
            return no.texto
        try:
            return (f"{_numero_em_palavras(int(inteiro))} vírgula "
                    f"{_numero_em_palavras(int(decimal))}")
        except ValueError:
            return no.texto

    def _symbol(self, no: Symbol) -> str:
        return self.simbolo(no.nome)

    def _connector(self, no: Connector) -> str:
        return no.texto

    def _desconhecido(self, no: Desconhecido) -> str:
        self.tem_lacuna = True
        texto = (no.texto or "").strip()
        if not texto:
            self.avisos.append("trecho ausente na expressao")
            return ""
        self.avisos.append(f"trecho nao interpretado na fala: {texto!r}")
        recuperado = _falar_numero_cru(texto)
        return recuperado if recuperado is not None else texto

    def _unaryminus(self, no: UnaryMinus) -> str:
        interno = self.falar(no.operando)
        if self.modo == "pedagogico":
            return f"o oposto de {interno}"
        return f"menos {interno}"

    def _plusminus(self, no: PlusMinus) -> str:
        if no.binaria:
            return (f"{self.falar(no.esquerda)}, mais ou menos, "
                    f"{self.falar(no.operando)}")
        if no.operando is None:
            return "mais ou menos"
        return f"mais ou menos {self.falar(no.operando)}"

    _RAIZES_NOMEADAS = {2: "raiz quadrada", 3: "raiz cúbica"}

    def _nome_da_raiz(self, no: Sqrt) -> str:
        if no.indice is None:
            return "raiz quadrada"
        grau = no.grau_falado
        if grau in self._RAIZES_NOMEADAS:
            self.realizado(no.indice)
            return self._RAIZES_NOMEADAS[grau]
        indice = self.falar(no.indice)
        if not indice.strip():
            self.tem_lacuna = True
            self.avisos.append("radical com indice nao interpretado")
            return "raiz"
        return f"raiz de índice {indice}"

    def _sqrt(self, no: Sqrt) -> str:
        nome = self._nome_da_raiz(no)
        radicando = self.falar(no.radicando)
        if not radicando.strip():
            self.tem_lacuna = True
            self.avisos.append("radical sem radicando na fala")
            return nome
        if not _e_folha(no.radicando) or no.grau_falado not in (None, 2, 3):
            return (f"{nome} de{_pausa(PAUSA_CURTA)} {radicando}"
                    f"{_pausa(PAUSA_CURTA)} fim da raiz")
        return f"{nome} de {radicando}"

    def _group(self, no: Group) -> str:
        interno = self.falar(no.conteudo)
        if _e_folha(no.conteudo) or self.modo == "conciso":
            return interno
        return f"abre parênteses, {interno}, fecha parênteses"

    def realizado(self, no: NoAST) -> None:
        self.nos_falados.add(id(no))

    def _power(self, no: Power) -> str:
        base = self.falar(no.base)
        if isinstance(no.expoente, Integer):
            if no.expoente.valor == 2:
                self.realizado(no.expoente)
                return f"{base} ao quadrado"
            if no.expoente.valor == 3:
                self.realizado(no.expoente)
                return f"{base} ao cubo"
        return f"{base} elevado a {self.falar(no.expoente)}"

    def _subscript(self, no: Subscript) -> str:
        base, indice = self.falar(no.base), self.falar(no.indice)
        if self.indice_tecnico:
            return f"{base} índice {indice}"
        return f"{base} {indice}"

    def _add(self, no: Add) -> str:
        return ", mais ".join(self.falar(t) for t in no.termos)

    def _subtract(self, no: Subtract) -> str:
        return f"{self.falar(no.left)} menos {self.falar(no.right)}"

    def _multiply(self, no: Multiply) -> str:
        partes = [self.falar(f) for f in no.fatores]
        if self.modo == "conciso" and no.implicita:
            return " ".join(partes)
        if no.source_notation == "parentheses" and any(
            isinstance(f, Group) for f in no.fatores
        ):
            return ", vezes, ".join(partes)
        if self.modo == "pedagogico" and len(partes) == 2:
            primeiro, segundo = no.fatores
            if isinstance(primeiro, (Integer, Numero)) and isinstance(
                segundo, Symbol
            ):
                return (f"o produto de {partes[0]} pelo coeficiente "
                        f"{partes[1]}")
        return " vezes ".join(partes)

    def _divide(self, no: Divide) -> str:
        numerador = self.falar(no.numerador)
        denominador = self.falar(no.denominador)
        simples = _e_folha(no.numerador) and _e_folha(no.denominador)
        if self.modo == "conciso" or simples:
            return f"{numerador} sobre {denominador}"
        return (f"uma fração.{_pausa(PAUSA_CURTA)} "
                f"No numerador: {numerador}."
                f"{_pausa(PAUSA_MEDIA)} "
                f"No denominador: {denominador}."
                f"{_pausa(PAUSA_CURTA)} Fim da fração")

    def _function(self, no: Function) -> str:
        nome = _FUNCOES_FALADAS.get(no.nome.lower(), self.simbolo(no.nome))
        if not no.argumentos:
            return nome
        argumentos = ", ".join(self.falar(a) for a in no.argumentos)
        if no.indice is None:
            return f"{nome} de {argumentos}"
        indice = self.falar(no.indice)
        if no.nome.lower() == "log":
            return f"logaritmo de {argumentos} na base {indice}"
        return f"{nome} de {argumentos}, com índice {indice}"

    def _operacaodeconjuntos(self, no: OperacaoDeConjuntos) -> str:
        from pipeline.matematica.registro_de_operadores import fala_do_operador

        partes = [self.falar(o) for o in no.operandos]
        pedacos = [partes[0]] if partes else []
        for indice, parte in enumerate(partes[1:]):
            ligacao = fala_do_operador(no.operador_em(indice))
            pedacos.append(f" {ligacao} {parte}")
        return "".join(pedacos)

    def _conjuntoliteral(self, no: ConjuntoLiteral) -> str:
        if not no.itens:
            return "conjunto vazio"
        partes = []
        for item in no.itens:
            if isinstance(item, Reticencias):
                partes.append("e assim por diante")
            else:
                partes.append(self.falar(item))
        itens = ", ".join(partes)
        return f"abre chaves, {itens}, fecha chaves"

    def _quantificador(self, no: Quantificador) -> str:
        from pipeline.matematica.registro_de_operadores import (
            CONECTOR_DE_CORPO,
            QUANTIFICADORES,
        )

        abertura = next(
            (spec.fala for spec in QUANTIFICADORES.values()
             if spec.identificador == no.especie), no.especie,
        )
        if no.especie == "existe":
            abertura = "existe pelo menos um"
        fala = f"{abertura} {self.falar(no.variavel)}"
        if no.dominio is not None:
            fala += f" pertencente {self._dominio_falado(no.dominio)}"
        if no.corpo is not None:
            conector = CONECTOR_DE_CORPO.get(no.especie, ",")
            if conector == ",":
                fala += f",{_pausa(PAUSA_CURTA)} {self.falar(no.corpo)}"
            else:
                fala += (f"{_pausa(PAUSA_CURTA)} {conector} "
                         f"{self.falar(no.corpo)}")
        else:
            self.tem_lacuna = True
            self.avisos.append("quantificador sem corpo")
        return fala

    _CONJUNTOS_POR_EXTENSO = {
        "naturais": "ao conjunto dos números naturais",
        "reais": "ao conjunto dos números reais",
        "inteiros": "ao conjunto dos números inteiros",
        "racionais": "ao conjunto dos números racionais",
        "complexos": "ao conjunto dos números complexos",
    }

    def _dominio_falado(self, dominio) -> str:
        falado = self.falar(dominio)
        if falado in self._CONJUNTOS_POR_EXTENSO:
            return self._CONJUNTOS_POR_EXTENSO[falado]
        from pipeline.matematica.arvore_matematica import Symbol as _Sym

        if isinstance(dominio, _Sym) and len(dominio.nome) == 1 \
                and dominio.nome.isupper():
            return f"ao conjunto {falado}"
        return f"a {falado}"

    def _textoliteral(self, no: TextoLiteral) -> str:
        return (no.texto or "").strip()

    def _quantia(self, no: Quantia) -> str:
        from pipeline.matematica.vocabulario_de_fala import unidade_por_extenso

        valor_falado = self.falar(no.valor)
        valor_numerico = getattr(no.valor, "valor", None)
        return f"{valor_falado} {unidade_por_extenso(no.unidade, valor_numerico)}"

    def _reticencias(self, no: Reticencias) -> str:
        return "reticências"

    def _negacaologica(self, no: NegacaoLogica) -> str:
        interno = self.falar(no.operando)
        if _e_folha(no.operando):
            return f"não {interno}"
        return f"não é verdade que {interno}"

    def _operacaologicabinaria(self, no: OperacaoLogicaBinaria) -> str:
        esquerda = self.falar(no.esquerda)
        direita = self.falar(no.direita)
        if no.operador == "implica":
            return f"se {esquerda}, então {direita}"
        if no.operador == "se_e_somente_se":
            return f"{esquerda} se, e somente se, {direita}"
        ligacao = {"e_logico": "e", "ou_logico": "ou",
                   "ou_exclusivo": "ou exclusivo"}.get(
            no.operador, no.operador)
        return f"{esquerda} {ligacao} {direita}"

    def _valorabsoluto(self, no: ValorAbsoluto) -> str:
        return f"valor absoluto de {self.falar(no.expressao)}"

    def _cardinalidade(self, no: Cardinalidade) -> str:
        return f"cardinalidade de {self.falar(no.expressao)}"

    def _conjuntoporpropriedade(self, no: ConjuntoPorPropriedade) -> str:
        variavel = self.falar(no.variavel)
        predicado = self.falar(no.predicado)
        if no.dominio is not None:
            dominio = self._dominio_falado(no.dominio)
            return (f"conjunto dos {variavel} pertencentes {dominio}"
                    f" tal que {predicado}")
        return f"conjunto dos {variavel} tal que {predicado}"

    def _limite(self, no: Limite) -> str:
        variavel = self.falar(no.variavel)
        alvo = self.falar(no.alvo)
        if no.corpo is None:
            self.tem_lacuna = True
            self.avisos.append("limite sem expressao")
            return f"limite quando {variavel} tende a {alvo}"
        corpo = self.falar(no.corpo)
        if _e_folha(no.corpo):
            return f"limite de {corpo} quando {variavel} tende a {alvo}"
        return (f"limite, quando {variavel} tende a {alvo},"
                f"{_pausa(PAUSA_CURTA)} de: {corpo}")

    def _relation(self, no: Relation) -> str:
        partes = [self.falar(o) for o in no.operandos]
        longa = any(
            len(list(o.percorrer())) > _LIMITE_EXPRESSAO_LONGA
            for o in no.operandos
        )
        pedacos = [partes[0]] if partes else []
        for indice, parte in enumerate(partes[1:]):
            simbolo = no.operador_em(indice)
            ligacao = _RELACOES_FALADAS.get(simbolo, simbolo)
            if longa:
                separador = (
                    f"{_pausa(PAUSA_CURTA)} {ligacao}{_pausa(PAUSA_CURTA)} "
                )
            else:
                separador = f" {ligacao} "
            pedacos.append(separador + parte)
        return "".join(pedacos)

    def _textmathsequence(self, no: TextMathSequence) -> str:
        partes: list[str] = []
        for item in no.itens:
            falado = self.falar(item)
            if falado:
                partes.append(falado)
        return " ".join(partes)


def _limpar(texto: str) -> str:
    resultado = re.sub(r"[ \t]{2,}", " ", texto).strip()
    resultado = re.sub(r"\s+,", ",", resultado)
    resultado = re.sub(r",\s*,", ",", resultado)
    resultado = re.sub(r",\s*;", ";", resultado)
    resultado = resultado.strip(" ,")
    return resultado


def _remover_marcas(texto: str) -> str:
    return _limpar(re.sub(
        f"{_MARCA_PAUSA}\\d+{_MARCA_PAUSA}", " ", texto
    ))


def gerar_ssml(plano: "SpeechPlan") -> str:
    from xml.sax.saxutils import escape

    fonte = plano.texto_com_pausas or plano.texto
    partes: list[str] = []
    cursor = 0
    for encontro in re.finditer(f"{_MARCA_PAUSA}(\\d+){_MARCA_PAUSA}", fonte):
        trecho = fonte[cursor:encontro.start()].strip()
        if trecho:
            partes.append(escape(trecho))
        partes.append(f'<break time="{encontro.group(1)}ms"/>')
        cursor = encontro.end()
    resto = fonte[cursor:].strip()
    if resto:
        partes.append(escape(resto))
    corpo = "\n  ".join(partes)
    return f"<speak>\n  {corpo}\n</speak>"


def gerar_fala_matematica(
    ast: NoAST,
    locale: str = "pt-BR",
    modo: Modo = "estrutural",
    soletrar_variaveis: bool = True,
    indice_tecnico: bool = False,
) -> SpeechPlan:
    if ast is None:
        return SpeechPlan(texto="", modo=modo, locale=locale, tem_lacuna=True,
                          avisos=["AST ausente"])
    planejador = _Planejador(modo, soletrar_variaveis, indice_tecnico)
    try:
        bruto = planejador.falar(ast)
    except Exception as erro:
        return SpeechPlan(
            texto="", modo=modo, locale=locale, tem_lacuna=True,
            avisos=[f"falha ao planejar a fala: {type(erro).__name__}: {erro}"],
        )
    plano = SpeechPlan(
        texto=_remover_marcas(bruto), modo=modo, locale=locale,
        tem_lacuna=planejador.tem_lacuna, avisos=list(planejador.avisos),
        texto_com_pausas=_limpar(bruto),
        nos_falados=set(planejador.nos_falados),
    )
    if plano.tem_simbolo_cru:
        plano.tem_lacuna = True
        plano.avisos.append(
            "a fala contem simbolo cru que o TTS leria de forma "
            "imprevisivel"
        )
    return plano


def falar_expressao(
    texto: str, geometria=None, modo: Modo = "estrutural",
    soletrar_variaveis: bool = True, indice_tecnico: bool = False,
) -> SpeechPlan:
    from pipeline.matematica.arvore_matematica import construir_ast

    resultado = construir_ast(texto, geometria)
    plano = gerar_fala_matematica(
        resultado.ast, modo=modo, soletrar_variaveis=soletrar_variaveis,
        indice_tecnico=indice_tecnico,
    )
    if resultado.nao_consumidos:
        plano.tem_lacuna = True
        plano.avisos.append(
            "tokens nao consumidos pelo parser: "
            + " ".join(t.value for t in resultado.nao_consumidos)
        )
    return plano


falar = gerar_fala_matematica
planejar_fala = gerar_fala_matematica
