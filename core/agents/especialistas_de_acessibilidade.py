"""
POR QUE NAO HA ESPECIALISTA DE MathML AQUI, e nao deve haver: MathML,
LaTeX, OMML e fala sao TODOS derivados da mesma arvore semantica pela
camada matematica. Um agente que escrevesse MathML reintroduziria a
divergencia entre representacoes - o defeito que a refatoracao eliminou -
e permitiria marcacao alucinada, que o leitor de tela nao tem como
detectar. A geracao de LaTeX a partir da IMAGEM ja e feita pelo
especialista de formula; dali para frente e tudo deterministico.

DETERMINISTICO PRIMEIRO. A sintese de grafico e inteiramente calculada a
partir dos dados: maximo, minimo e tendencia sao contas, e uma conta nao
alucina um valor. A camada de IA e opcional e cuida apenas da parte que e
de fato linguistica - condensar uma descricao longa numa identificacao
curta que ainda faca sentido.
"""

from __future__ import annotations

import os
import re
from typing import Any

from core.utils.logger import logger


_MAX_ALT = 140


_MIN_PARA_DIVIDIR = 200


_LINHAS_PARA_RESUMIR = 10

_TIPOLOGIAS = (
    "fotografia", "ilustracao", "ilustração", "diagrama", "grafico",
    "gráfico", "esquema", "mapa", "logotipo", "captura de tela",
    "tirinha", "cartaz", "infografico", "infográfico", "organograma",
)


def _ia_ligada() -> bool:
    return os.getenv(
        "USAR_ESPECIALISTAS_ACESSIBILIDADE", "false"
    ).strip().lower() == "true"


def _frases(texto: str) -> list[str]:
    partes = re.split(r"(?<=[.!?])\s+", (texto or "").strip())
    return [p.strip() for p in partes if p.strip()]



def _tipologia_de(texto: str) -> str:
    """A primeira palavra do texto, quando ela e uma tipologia conhecida.

    As regras de ouro do IBC mandam abrir pela tipologia ("Diagrama de
    blocos."), entao ela costuma estar na primeira frase - e e justamente
    o que o alt curto precisa preservar: ela permite ao usuario ativar o
    esquema mental certo antes de decidir se abre a descricao longa.
    """
    primeira = (_frases(texto) or [""])[0].lower()
    for tipologia in _TIPOLOGIAS:
        if primeira.startswith(tipologia):
            return primeira.rstrip(".:")
    return ""


def _primeira_oracao(frase: str, limite: int) -> str:
    """A maior oracao COMPLETA que cabe no limite, ou "".

    Corta em fronteira sintatica (virgula, ponto e virgula, travessao),
    nunca no meio de um sintagma. Devolve "" quando nenhuma fronteira
    cabe - e melhor tentar outro template do que entregar frase quebrada.
    """
    frase = frase.strip().rstrip(".!?")
    if len(frase) <= limite:
        return frase

    # Fronteiras sintaticas, da mais forte para a mais fraca.
    for separador in (";", " — ", " - ", ","):
        pedaco = frase[:limite]
        if separador in pedaco:
            candidato = pedaco.rsplit(separador, 1)[0].strip()
            # Nao pode terminar em palavra funcional pendente.
            if candidato and not _termina_pendente(candidato):
                return candidato
    return ""


# Palavras que nunca podem encerrar um alt: deixam a frase suspensa.
_PALAVRAS_PENDENTES = {
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "com", "sem", "por", "para", "a", "o", "as", "os", "um", "uma",
    "e", "ou", "que", "se", "ao", "aos", "à", "às", "entre", "sobre",
}


def _termina_pendente(texto: str) -> bool:
    ultima = texto.rstrip(".,;: ").split()[-1].lower() if texto.split() else ""
    return ultima in _PALAVRAS_PENDENTES


def dividir_alt_e_descricao_longa(texto: str) -> tuple[str, str]:

    limpo = " ".join((texto or "").split())
    if len(limpo) < _MIN_PARA_DIVIDIR:
        return "", ""

    frases = _frases(limpo)
    if not frases:
        return "", ""

    tipologia = _tipologia_de(limpo)
    alt = _montar_alt_curto(frases, tipologia)
    return alt, limpo


def _montar_alt_curto(frases: list[str], tipologia: str) -> str:
    """Candidatos em ordem de preferencia; o primeiro completo vence."""
    primeira = frases[0].strip()
    segunda = frases[1].strip() if len(frases) > 1 else ""

    candidatos: list[str] = []


    so_tipologia = len(primeira.rstrip(".")) < 25 and segunda
    if so_tipologia:
        base = primeira.rstrip(".")
        espaco = _MAX_ALT - len(base) - 5
        oracao_segunda = (
            segunda if len(segunda) <= espaco
            else _primeira_oracao(segunda, espaco)
        )
        if oracao_segunda:

            if _aceita_emenda_com_de(oracao_segunda):
                candidatos.append(
                    f"{base} de {_minuscula_inicial(oracao_segunda)}"
                )
            candidatos.append(f"{base}. {oracao_segunda}")


    if len(primeira) <= _MAX_ALT:
        if len(primeira) < 40 and segunda:
            juntas = f"{primeira} {segunda}"
            if len(juntas) <= _MAX_ALT:
                candidatos.append(juntas)
        if not so_tipologia:
            candidatos.append(primeira)


    oracao = _primeira_oracao(primeira, _MAX_ALT)
    if oracao:
        if tipologia and not oracao.lower().startswith(tipologia.lower()):
            com_tipo = f"{tipologia}: {oracao}"
            if len(com_tipo) <= _MAX_ALT:
                candidatos.append(com_tipo)
        candidatos.append(oracao)


    if so_tipologia:
        candidatos.append(primeira)
    if tipologia:
        candidatos.append(f"{tipologia} descrita em detalhe a seguir")


    nucleo = _nucleo_nominal(primeira)
    if nucleo:
        candidatos.append(f"{nucleo}. Descricao detalhada a seguir")

    candidatos.append("Conteudo visual informativo")

    for candidato in candidatos:
        candidato = " ".join(candidato.split()).strip().rstrip(",;: ")
        if not candidato or _termina_pendente(candidato):
            continue
        if len(candidato) > _MAX_ALT:
            continue
        if not candidato.endswith((".", "!", "?")):
            candidato += "."
        return candidato

    return "Conteudo visual informativo."


# Palavras que, iniciando a oracao, impedem a emenda com "de".
_INICIOS_QUE_RECUSAM_DE = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas",
    "ao", "aos", "à", "às", "no", "na", "nos", "nas",
    "de", "do", "da", "dos", "das", "em", "com", "por", "para",
    "que", "se", "e", "ou", "este", "esta", "esse", "essa",
}


def _nucleo_nominal(frase: str, limite: int = 90) -> str:
    """As primeiras palavras ate um limite, encerradas em substantivo.

    Nao e corte mecanico: para na ultima palavra que NAO deixa a frase
    suspensa, e nunca acrescenta reticencias.
    """
    palavras = frase.strip().rstrip(".!?").split()
    acumulado: list[str] = []
    for palavra in palavras:
        provisorio = " ".join(acumulado + [palavra])
        if len(provisorio) > limite:
            break
        acumulado.append(palavra)
    while acumulado and acumulado[-1].lower() in _PALAVRAS_PENDENTES:
        acumulado.pop()
    resultado = " ".join(acumulado).rstrip(",;:")
    return resultado if len(resultado.split()) >= 3 else ""


def _aceita_emenda_com_de(oracao: str) -> bool:
    """"Diagrama de blocos de A camada..." e portugues quebrado."""
    palavras = oracao.split()
    if not palavras:
        return False
    return palavras[0].lower() not in _INICIOS_QUE_RECUSAM_DE


def _minuscula_inicial(texto: str) -> str:
    """"Várias flores..." -> "várias flores..." para emendar apos "de"."""
    if not texto:
        return texto
    # Nao rebaixa nome proprio nem sigla.
    primeira_palavra = texto.split()[0]
    if primeira_palavra.isupper() or (
        len(primeira_palavra) > 1 and primeira_palavra[1:].islower()
        and primeira_palavra not in _PALAVRAS_COMUNS_CAPITALIZADAS
    ):
        pass
    return texto[0].lower() + texto[1:]


# Palavras que iniciam frase por convencao, nao por serem nome proprio.
_PALAVRAS_COMUNS_CAPITALIZADAS = {
    "Várias", "Vários", "Uma", "Um", "Duas", "Dois", "Diversas",
    "Diversos", "Muitas", "Muitos", "Ao", "No", "Na", "Em", "Com",
}


_INSTRUCOES_ALT = """\
Voce recebe a descricao completa de uma imagem de material didatico.

Devolva APENAS uma identificacao curta dela, com no maximo 140
caracteres, que permita ao estudante decidir se quer ouvir a descricao
completa.

Comece pela tipologia (Fotografia, Diagrama, Grafico, Mapa, Esquema...).
NAO explique o conteudo. NAO acrescente nada que nao esteja na descricao
recebida. NAO escreva "imagem de" nem "figura de".

Responda so a identificacao, sem aspas e sem comentarios.
"""


def refinar_alt_com_ia(alt: str, descricao_longa: str) -> str:
    """Condensa o alt curto. Fail-open: devolve o alt deterministico.

    E a unica parte deste modulo que e de fato tarefa linguistica -
    escolher o que cabe em 140 caracteres. O guarda-corpo e o mesmo do
    agente acessivel: se a saida crescer, sumir ou trouxer termo que nao
    estava na descricao, ela e descartada.
    """
    if not _ia_ligada() or not alt or not descricao_longa:
        return alt
    try:
        from agno.agent import Agent

        from core.agents.conferidor_de_formulas import _construir_modelo_texto

        agente = Agent(
            name="alt-curto",
            model=_construir_modelo_texto(),
            description="Condensa a identificacao curta de uma imagem",
            instructions=_INSTRUCOES_ALT,
            markdown=False,
        )
        candidato = (agente.run(descricao_longa).content or "").strip()
        candidato = candidato.strip('"').strip()
        if not candidato or len(candidato) > _MAX_ALT:
            return alt
        # Nao pode introduzir termo de conteudo ausente da descricao:
        # seria inferencia, nao condensacao.
        origem = descricao_longa.lower()
        for palavra in re.findall(r"\b[a-zA-ZÀ-ú]{5,}\b", candidato.lower()):
            if palavra not in origem:
                logger.warning(
                    "Alt curto trouxe termo ausente da descricao ({!r}); "
                    "mantendo a versao deterministica", palavra,
                )
                return alt
        return candidato
    except Exception as erro:
        logger.warning("Especialista de alt indisponivel ({}); seguindo", erro)
        return alt


# --------------------------------------------------------------------------- #
# TAB-005 - caption e resumo de leitura
# --------------------------------------------------------------------------- #
def _e_numero(valor: str) -> bool:
    limpo = re.sub(r"[^\d,.\-]", "", str(valor or "")).replace(",", ".")
    if not limpo or limpo in ("-", ".", "-."):
        return False
    try:
        float(limpo)
        return True
    except ValueError:
        return False


def _como_numero(valor: str) -> float | None:
    limpo = re.sub(r"[^\d,.\-]", "", str(valor or "")).replace(",", ".")
    try:
        return float(limpo)
    except (ValueError, TypeError):
        return None


def resumir_tabela(rows: list, contexto: str = "") -> str:
    """Resumo de leitura de uma tabela. Deterministico, a partir da grade.

    O resumo antecipa o modelo mental ANTES da navegacao celula a celula
    (DAISY KB). Sem ele, o estudante descobre a estrutura da tabela
    tateando - e so entende o formato depois de ja ter passado por
    metade dos dados.

    Devolve "" para tabela curta: ali o proprio cabecalho basta.
    """
    if not rows or len(rows) <= _LINHAS_PARA_RESUMIR:
        return ""

    cabecalhos = [str(c).strip() for c in rows[0]]
    dados = rows[1:]
    if not cabecalhos:
        return ""

    rotulo_da_linha = cabecalhos[0] or "identificador"
    demais = [c for c in cabecalhos[1:] if c]

    partes = [
        f"Tabela de {len(dados)} linhas e {len(cabecalhos)} colunas.",
        f"Cada linha e identificada por {rotulo_da_linha}.",
    ]
    if demais:
        partes.append(
            "As demais colunas trazem " + ", ".join(demais) + "."
        )
    partes.append(
        f"Cada celula cruza o {rotulo_da_linha.lower()} da linha com o "
        "titulo da coluna."
    )
    return " ".join(partes)



ORDENS_COM_SEQUENCIA = ("temporal", "ordinal", "continuous")

# Cabecalhos que denunciam um eixo X ordenado. Deliberadamente curto e
# explicito: um falso positivo aqui reintroduz o defeito.
_PISTAS_TEMPORAIS = (
    "ano", "anos", "mes", "mês", "meses", "data", "datas", "dia", "dias",
    "hora", "horas", "periodo", "período", "trimestre", "semestre",
    "decada", "década", "year", "month", "date", "time", "day", "quarter",
)
_PISTAS_CONTINUAS = (
    "idade", "distancia", "distância", "temperatura", "altura", "peso",
    "profundidade", "comprimento", "tempo", "age", "distance", "length",
    "depth", "height", "weight", "dose", "concentracao", "concentração",
)
_PISTAS_ORDINAIS = (
    "faixa", "faixas", "nivel", "níveis", "nivel", "serie", "série",
    "grau", "graus", "etapa", "etapas", "fase", "fases", "classe",
    "level", "grade", "stage", "rank", "range",
)


def detectar_ordem_do_eixo_x(rows: list) -> str:
    """Deduz a semantica do eixo X pelo cabecalho e pelos rotulos.

    Devolve `nominal` sempre que nao houver EVIDENCIA de ordenacao. Nao e
    timidez: afirmar tendencia sobre categorias nominais e inventar um
    fato, enquanto deixar de afirma-la sobre uma serie temporal apenas
    omite uma leitura que os dados ainda permitem fazer. Os dois erros
    nao tem o mesmo custo.
    """
    if not rows or len(rows) < 2:
        return "nominal"

    cabecalho = str(rows[0][0]).strip().lower() if rows[0] else ""
    if any(p in cabecalho for p in _PISTAS_TEMPORAIS):
        return "temporal"
    if any(p in cabecalho for p in _PISTAS_CONTINUAS):
        return "continuous"
    if any(p in cabecalho for p in _PISTAS_ORDINAIS):
        return "ordinal"

    # Rotulos todos numericos (anos, faixas etarias) indicam ordenacao.
    rotulos = [str(l[0]).strip() for l in rows[1:] if l]
    if len(rotulos) >= 3 and all(_e_numero(r) for r in rotulos):
        numeros = [_como_numero(r) for r in rotulos]
        if all(n is not None for n in numeros):
            crescente = all(
                b >= a for a, b in zip(numeros, numeros[1:])
            )
            if crescente:
                # 1900-2100 sao anos; o resto e grandeza continua.
                if all(1900 <= n <= 2100 for n in numeros):
                    return "temporal"
                return "continuous"
    return "nominal"


def sintetizar_grafico(
    rows: list, contexto: str = "", ordem_x: str | None = None
) -> str:
    """Padrao principal de um grafico, CALCULADO a partir dos dados.

    Deterministico de proposito. A sintese de um grafico e onde a
    alucinacao seria mais dificil de detectar: um maximo errado se
    parece exatamente com um maximo certo, e o estudante nao tem como
    conferir. Maximo, minimo e tendencia sao contas - e uma conta nao
    inventa valor.

    `ordem_x` define se a SEQUENCIA dos dados tem significado. Quando
    omitido, e deduzido dos cabecalhos e rotulos; na ausencia de
    evidencia, assume `nominal` e nenhuma tendencia e afirmada.

    Devolve "" quando nao ha coluna numerica: sem numero nao ha padrao a
    calcular, e chutar seria pior que calar.
    """
    if not rows or len(rows) < 3:
        return ""

    if ordem_x is None:
        ordem_x = detectar_ordem_do_eixo_x(rows)

    cabecalhos = [str(c).strip() for c in rows[0]]
    dados = rows[1:]

    # Escolhe a primeira coluna majoritariamente numerica.
    coluna_valor = None
    for indice in range(1, len(cabecalhos)):
        numericos = sum(
            1 for linha in dados
            if indice < len(linha) and _e_numero(linha[indice])
        )
        if numericos >= max(2, len(dados) // 2):
            coluna_valor = indice
            break
    if coluna_valor is None:
        return ""

    pares: list[tuple[str, float]] = []
    for linha in dados:
        if coluna_valor >= len(linha):
            continue
        valor = _como_numero(linha[coluna_valor])
        if valor is None:
            continue
        rotulo = str(linha[0]).strip() if linha else ""
        pares.append((rotulo, valor))
    if len(pares) < 2:
        return ""

    nome = cabecalhos[coluna_valor] or "valor"
    maximo = max(pares, key=lambda p: p[1])
    minimo = min(pares, key=lambda p: p[1])

    partes = [
        f"Maior {nome.lower()}: {maximo[0]} ({_formatar(maximo[1])}).",
        f"Menor: {minimo[0]} ({_formatar(minimo[1])}).",
    ]

    if ordem_x in ORDENS_COM_SEQUENCIA:
        partes.extend(_tendencia_ordenada([v for _, v in pares]))
    else:
        partes.extend(_comparacao_categorica(pares))
    return " ".join(partes)


def _tendencia_ordenada(valores: list[float]) -> list[str]:
    """Leitura sequencial - so para eixos em que a ordem significa algo."""
    if all(b >= a for a, b in zip(valores, valores[1:])):
        return ["A serie cresce do inicio ao fim."]
    if all(b <= a for a, b in zip(valores, valores[1:])):
        return ["A serie decresce do inicio ao fim."]
    subidas = sum(1 for a, b in zip(valores, valores[1:]) if b > a)
    descidas = sum(1 for a, b in zip(valores, valores[1:]) if b < a)
    return [
        f"A serie oscila, com {subidas} aumento(s) e "
        f"{descidas} queda(s) entre pontos consecutivos."
    ]


def _comparacao_categorica(pares: list[tuple[str, float]]) -> list[str]:
    """Leitura por COMPARACAO - a que faz sentido em eixo nominal.

    Em vez de uma tendencia inexistente, entrega o que o estudante de
    fato precisa: quem esta proximo de quem, e qual a distancia entre os
    extremos. Sao as perguntas que um vidente responde olhando as alturas
    relativas das barras.
    """
    if len(pares) < 3:
        return []

    ordenados = sorted(pares, key=lambda p: p[1], reverse=True)
    partes: list[str] = []


    topo = ordenados[0][1]
    proximos = [
        rotulo for rotulo, valor in ordenados[1:]
        if topo > 0 and abs(valor - topo) / topo <= 0.15
    ]
    if proximos:
        lista = ", ".join(proximos[:3])
        partes.append(
            f"{lista} {'apresentam' if len(proximos) > 1 else 'apresenta'} "
            f"valores proximos do maior."
        )

    menor = ordenados[-1][1]
    if menor > 0 and topo / menor >= 2:
        partes.append(
            f"O maior valor e cerca de {topo / menor:.0f} vezes o menor."
        )
    return partes


def _formatar(valor: float) -> str:
    if valor == int(valor):
        return str(int(valor))
    return f"{valor:.2f}".replace(".", ",")


# --------------------------------------------------------------------------- #
# Aplicacao aos blocos canonicos
# --------------------------------------------------------------------------- #
def _localizar_se_preciso(bloco: dict[str, Any]) -> dict[str, Any]:
    """Aplica a camada de localizacao a tabelas (falha 4).

    Roda ANTES da sintese: o resumo precisa ser calculado sobre os
    rotulos ja em portugues, senao ele proprio sai hibrido - foi assim
    que "Maior density (gram/cm3): Platinum" foi parar no TXT.
    """
    if bloco.get("type") not in ("table", "chart"):
        return bloco
    try:
        from pipeline.localizacao import localizar_bloco

        return localizar_bloco(bloco)
    except Exception:
        return bloco


def enriquecer_bloco(bloco: dict[str, Any]) -> dict[str, Any]:
    """Preenche alt_text/long_description/summary conforme o tipo.

    Chamado pelo analisador de estrutura, sobre o bloco ja montado.
    Nunca sobrescreve campo que ja veio preenchido, e nunca levanta: o
    enriquecimento e um acrescimo, e um acrescimo que falha nao pode
    custar o bloco.
    """
    if not isinstance(bloco, dict):
        return bloco
    try:
        tipo = bloco.get("type")

        if tipo == "image" and not bloco.get("decorative"):
            if not bloco.get("long_description"):
                alt, longa = dividir_alt_e_descricao_longa(
                    bloco.get("text", "")
                )
                if alt and longa:
                    bloco["alt_text"] = bloco.get("alt_text") or (
                        refinar_alt_com_ia(alt, longa)
                    )
                    bloco["long_description"] = longa

        elif tipo == "table":

            bloco.update(_localizar_se_preciso(bloco))
            linhas = bloco.get("rows") or []
            metadata = bloco.get("metadata") or {}
            if not bloco.get("summary"):
                if metadata.get("source_visual_type") == "chart":
                    sintese = sintetizar_grafico(linhas)
                    if sintese:
                        bloco["summary"] = sintese
                else:
                    resumo = resumir_tabela(linhas)
                    if resumo:
                        bloco["summary"] = resumo
    except Exception as erro:
        logger.warning("Enriquecimento de acessibilidade falhou ({})", erro)
    return bloco
