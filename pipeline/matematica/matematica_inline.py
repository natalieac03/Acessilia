"""Separa um bloco misto em segmentos de texto e de formula.

Corrige o erro mais estrutural que o projeto ja teve: o pipeline
classificava o BLOCO INTEIRO como um tipo so. Um paragrafo de material
didatico costuma ser misto ("A funcao e f(x) = x^2 - 5x + 6. As raizes
aparecem no grafico..."), e classificar tudo de uma vez produzia dois
erros opostos — ou a formula saia achatada como texto, ou a frase em
portugues ao redor era descartada.

Duas garantias, ambas testadas: a concatenacao dos segmentos reproduz
o texto original caractere por caractere, e o detector so abre um
segmento de formula com sinal matematico forte. Prosa comum nunca vira
formula por engano.
"""

from __future__ import annotations

import re
import unicodedata

_SIMBOLOS_FORTES = "=±√∆Δ≥≤≠∑∫∞≈·×÷"
_SOBRESCRITOS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUBSCRITOS = "₀₁₂₃₄₅₆₇₈₉"

_PADRAO_FUNCAO = re.compile(r"^[A-Za-z]\s?\([A-Za-z0-9]+\)")
_PADRAO_COEFICIENTE = re.compile(r"^(?:\d+[A-Za-z]{1,3}|[A-Za-z]{1,3}\d+)$")
_PADRAO_NUMERO = re.compile(r"^[+\-]?\d+(?:[.,]\d+)?$")
_OPERADORES = {"+", "-", "*", "/", "=", "±", "<", ">", "≥", "≤", "≠", "·",
               "×", "÷", "^", "_"}

_PALAVRAS_FUNCIONAIS = {
    "a", "o", "e", "é", "à", "as", "os", "da", "do", "de", "na", "no",
    "em", "um", "uma", "se", "ao", "ou", "eh", "ha", "há", "ja", "já",
    "la", "lá", "me", "te", "se", "nos", "vos", "por", "com", "sem",
}

_CONECTORES_MATEMATICOS = {"e", "ou", ","}


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _tem_sinal_forte(token: str) -> bool:
    if any(s in token for s in _SIMBOLOS_FORTES):
        return True
    if any(s in token for s in _SOBRESCRITOS + _SUBSCRITOS):
        return True
    if re.search(r"[A-Za-z0-9][\^_][A-Za-z0-9{]", token):
        return True
    return False


def _classificar_token(token: str) -> str:
    limpo = token.strip("()[]{}.,;:!?\"'“”")
    if not limpo:
        return "FRACO" if token.strip(".,;:!?") else "NEUTRO"

    if len(limpo) > 1 and limpo[0] in "+-−–±":
        nucleo = limpo[1:].strip()
        if nucleo and (
            _PADRAO_NUMERO.match(nucleo)
            or _PADRAO_COEFICIENTE.match(nucleo)
            or (len(nucleo) <= 2 and nucleo.isalpha())
        ):
            return "FRACO"

    if _tem_sinal_forte(token):
        return "FORTE"
    if limpo in _OPERADORES or token in _OPERADORES:
        return "FRACO"
    if _PADRAO_NUMERO.match(limpo):
        return "FRACO"
    if _PADRAO_FUNCAO.match(token.strip(".,;:")):
        return "FORTE"
    if _PADRAO_COEFICIENTE.match(limpo):
        return "FRACO"

    minusculo = _sem_acento(limpo.lower())
    if minusculo in _CONECTORES_MATEMATICOS:
        return "NEUTRO"
    if minusculo in _PALAVRAS_FUNCIONAIS:
        return "PROSA"
    if len(limpo) == 1 and limpo.isalpha():
        return "FRACO"
    if len(limpo) == 2 and limpo.isalpha() and minusculo not in _PALAVRAS_FUNCIONAIS:
        return "FRACO"
    if any(c in limpo for c in "()[]{}"):
        nucleo = re.sub(r"[()\[\]{}]", "", limpo)
        if nucleo and nucleo != limpo:
            if _PADRAO_NUMERO.match(nucleo) or _PADRAO_COEFICIENTE.match(nucleo):
                return "FRACO"
            if len(nucleo) <= 2 and nucleo.isalpha():
                return "FRACO"
    return "PROSA"


def _aparar_pontuacao_final(texto: str) -> tuple[str, str]:
    sobra = ""
    while texto and texto[-1] in ".,;:":
        sobra = texto[-1] + sobra
        texto = texto[:-1]
    return texto, sobra


def segmentar_matematica(texto: str, celula: bool = False) -> list[dict]:
    if not texto or not texto.strip():
        return [{"tipo": "text", "conteudo": texto}] if texto else []

    tokens = [(m.group(0), m.start(), m.end())
              for m in re.finditer(r"\S+", texto)]
    if not tokens:
        return [{"tipo": "text", "conteudo": texto}]

    classes = [_classificar_token(t[0]) for t in tokens]

    corridas: list[tuple[int, int]] = []
    inicio = None
    for indice, classe in enumerate(classes):
        if classe == "PROSA":
            if inicio is not None:
                corridas.append((inicio, indice - 1))
                inicio = None
        else:
            if inicio is None:
                inicio = indice
    if inicio is not None:
        corridas.append((inicio, len(classes) - 1))

    intervalos: list[tuple[int, int]] = []
    for ini, fim in corridas:
        while ini <= fim and classes[ini] == "NEUTRO":
            ini += 1
        while fim >= ini and classes[fim] == "NEUTRO":
            fim -= 1
        if ini > fim:
            continue
        faixa = range(ini, fim + 1)
        tem_forte = any(classes[k] == "FORTE" for k in faixa)
        celula_inteira = (
            celula and ini == 0 and fim == len(classes) - 1
            and any(classes[k] in ("FORTE", "FRACO") for k in faixa)
        )
        if tem_forte or celula_inteira:
            intervalos.append((ini, fim))

    if not intervalos:
        return [{"tipo": "text", "conteudo": texto}]

    segmentos: list[dict] = []
    cursor = 0
    for ini, fim in intervalos:
        ini_char = tokens[ini][1]
        fim_char = tokens[fim][2]
        bruto = texto[ini_char:fim_char]
        nucleo, sobra = _aparar_pontuacao_final(bruto)
        if not nucleo:
            continue
        if ini_char > cursor:
            segmentos.append({"tipo": "text", "conteudo": texto[cursor:ini_char]})
        segmentos.append({"tipo": "math", "conteudo": nucleo})
        cursor = ini_char + len(nucleo)
        if sobra:
            pass
    if cursor < len(texto):
        segmentos.append({"tipo": "text", "conteudo": texto[cursor:]})

    return [s for s in segmentos if s["conteudo"]]


def tem_matematica_inline(texto: str) -> bool:
    return any(s["tipo"] == "math" for s in segmentar_matematica(texto))


def extrair_expressoes(texto: str) -> list[str]:
    return [s["conteudo"] for s in segmentar_matematica(texto)
            if s["tipo"] == "math"]


_LETRAS_GREGAS = "αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ∆"
_RELACIONAIS = "=≥≤≠<>"


def _sinais_do_token(token: str) -> list[str]:
    sinais: list[str] = []
    if any(c in token for c in _RELACIONAIS):
        sinais.append("forte:operador_relacional")
    if "±" in token:
        sinais.append("forte:mais_ou_menos")
    if "√" in token:
        sinais.append("forte:radical")
    if any(c in token for c in _LETRAS_GREGAS):
        sinais.append("forte:letra_grega")
    if any(c in token for c in _SOBRESCRITOS):
        sinais.append("forte:expoente_unicode")
    if any(c in token for c in _SUBSCRITOS):
        sinais.append("forte:indice_unicode")
    if any(c in token for c in "∑∫∞≈"):
        sinais.append("forte:operador_avancado")
    if re.search(r"[A-Za-z0-9][\^_][A-Za-z0-9{]", token):
        sinais.append("forte:indice_ascii")
    if _PADRAO_FUNCAO.match(token.strip(".,;:")):
        sinais.append("forte:notacao_funcao")

    limpo = token.strip("()[]{}.,;:!?\"'“”")
    if _PADRAO_NUMERO.match(limpo):
        sinais.append("fraco:numero")
    if _PADRAO_COEFICIENTE.match(limpo):
        sinais.append("fraco:coeficiente")
    if limpo in _OPERADORES or token in _OPERADORES:
        sinais.append("fraco:operador_aritmetico")
    if len(limpo) == 1 and limpo.isalpha():
        sinais.append("fraco:variavel")
    if any(c in token for c in "()[]"):
        sinais.append("fraco:parenteses")
    return sinais


def detectar_candidatos_matematicos(
    texto: str,
    geometria=None,
    contexto=None,
) -> list:
    from pipeline.matematica.evidencia_matematica import MathCandidate

    if not texto or not texto.strip():
        return []

    e_celula = bool(getattr(contexto, "e_celula", False))
    e_cabecalho = bool(getattr(contexto, "e_cabecalho", False))
    if e_cabecalho:
        return []

    tokens = [(m.group(0), m.start(), m.end())
              for m in re.finditer(r"\S+", texto)]
    if not tokens:
        return []

    classes = [_classificar_token(t[0]) for t in tokens]
    sinais_por_token = [_sinais_do_token(t[0]) for t in tokens]

    if geometria is not None:
        for indice, (_, inicio, fim) in enumerate(tokens):
            try:
                deslocados = geometria.deslocamentos_em(inicio, fim)
            except Exception:
                deslocados = []
            for span in deslocados:
                if not span.text.strip():
                    continue
                nome = ("forte:sobrescrito_geometrico"
                        if span.parece_sobrescrito
                        else "forte:subscrito_geometrico")
                if nome not in sinais_por_token[indice]:
                    sinais_por_token[indice].append(nome)
                classes[indice] = "FORTE"

    corridas: list[tuple[int, int]] = []
    inicio_corrida = None
    for indice, classe in enumerate(classes):
        if classe == "PROSA":
            if inicio_corrida is not None:
                corridas.append((inicio_corrida, indice - 1))
                inicio_corrida = None
        else:
            if inicio_corrida is None:
                inicio_corrida = indice
    if inicio_corrida is not None:
        corridas.append((inicio_corrida, len(classes) - 1))

    candidatos = []
    for ini, fim in corridas:
        while ini <= fim and classes[ini] == "NEUTRO":
            ini += 1
        while fim >= ini and classes[fim] == "NEUTRO":
            fim -= 1
        if ini > fim:
            continue

        faixa = range(ini, fim + 1)
        sinais = sorted({s for k in faixa for s in sinais_por_token[k]})
        tem_forte = any(classes[k] == "FORTE" for k in faixa)
        cobre_tudo = ini == 0 and fim == len(classes) - 1
        tem_algum = any(classes[k] in ("FORTE", "FRACO") for k in faixa)

        aceito = tem_forte or (e_celula and cobre_tudo and tem_algum)
        if not aceito:
            continue
        if e_celula and cobre_tudo and not tem_forte:
            sinais.append("contexto:celula_integralmente_matematica")

        inicio_char, fim_char = tokens[ini][1], tokens[fim][2]
        bruto = texto[inicio_char:fim_char]
        nucleo, _ = _aparar_pontuacao_final(bruto)
        if not nucleo:
            continue

        fortes = sum(1 for s in sinais if s.startswith("forte:"))
        candidatos.append(
            MathCandidate(
                start=inicio_char,
                end=inicio_char + len(nucleo),
                source_text=nucleo,
                signals=sinais,
                score=round(min(1.0, 0.45 + 0.18 * fortes), 2),
            )
        )
    return candidatos


def segmentar_bloco_misto(texto: str, candidatos: list | None = None):
    from pipeline.matematica.evidencia_matematica import InlineSegment, ResultadoSegmentacao

    if texto is None:
        return ResultadoSegmentacao(segments=[], aceita=True)

    if candidatos is None:
        candidatos = detectar_candidatos_matematicos(texto)

    ordenados = sorted(
        (c for c in candidatos if c.end > c.start), key=lambda c: (c.start, c.end)
    )
    fundidos: list = []
    for candidato in ordenados:
        if fundidos and candidato.start < fundidos[-1].end:
            anterior = fundidos[-1]
            if candidato.end > anterior.end:
                anterior.end = candidato.end
                anterior.source_text = texto[anterior.start:anterior.end]
                anterior.signals = sorted(set(anterior.signals + candidato.signals))
            continue
        fundidos.append(candidato.model_copy())

    segmentos: list[InlineSegment] = []
    cursor = 0
    for candidato in fundidos:
        inicio = max(cursor, candidato.start)
        if inicio >= candidato.end:
            continue
        if inicio > cursor:
            segmentos.append(InlineSegment(
                type="text", start=cursor, end=inicio,
                source_text=texto[cursor:inicio],
            ))
        segmentos.append(InlineSegment(
            type="math_candidate", start=inicio, end=candidato.end,
            source_text=texto[inicio:candidato.end],
            bbox=candidato.bbox, signals=candidato.signals,
        ))
        cursor = candidato.end
    if cursor < len(texto):
        segmentos.append(InlineSegment(
            type="text", start=cursor, end=len(texto),
            source_text=texto[cursor:],
        ))
    if not segmentos and texto:
        segmentos.append(InlineSegment(
            type="text", start=0, end=len(texto), source_text=texto,
        ))

    resultado = ResultadoSegmentacao(segments=segmentos)
    reconstruido = resultado.reconstruir()
    if reconstruido != texto:
        return ResultadoSegmentacao(
            segments=[InlineSegment(
                type="text", start=0, end=len(texto), source_text=texto,
            )],
            aceita=False,
            motivo_rejeicao=(
                "a concatenacao dos segmentos nao reproduziu o texto de "
                f"origem ({len(texto)} -> {len(reconstruido)} caracteres); "
                "bloco tratado como texto puro"
            ),
        )
    return resultado
