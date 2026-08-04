"""As palavras: numeros, unidades, letras gregas e nomes de funcoes.

Separado do planejador de fala de proposito — acrescentar uma unidade
nova ou corrigir o nome de um simbolo se resolve aqui, sem abrir a
logica que percorre a arvore.

Numeros e unidades saem sempre por extenso, com concordancia ("um
metro" x "cinco metros"). O dicionario LETRAS_SOLETRADAS esta vazio
hoje (cada letra fala como ela mesma) mas continua existindo: e o
interruptor para voltar a soletrar qualquer letra em todo o sistema.
"""

from __future__ import annotations

_UNIDADES = (
    "zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete",
    "oito", "nove", "dez", "onze", "doze", "treze", "quatorze", "quinze",
    "dezesseis", "dezessete", "dezoito", "dezenove",
)

_DEZENAS = (
    "", "", "vinte", "trinta", "quarenta", "cinquenta",
    "sessenta", "setenta", "oitenta", "noventa",
)

_CENTENAS = (
    "", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos",
    "seiscentos", "setecentos", "oitocentos", "novecentos",
)

_ESCALAS = (
    ("", ""),
    ("mil", "mil"),
    ("milhão", "milhões"),
    ("bilhão", "bilhões"),
    ("trilhão", "trilhões"),
    ("quatrilhão", "quatrilhões"),
    ("quintilhão", "quintilhões"),
)

LIMITE_EXTENSO = 1000 ** len(_ESCALAS)


def _ate_999(valor: int) -> str:
    if valor < 20:
        return _UNIDADES[valor]
    if valor < 100:
        dezena, unidade = divmod(valor, 10)
        if unidade == 0:
            return _DEZENAS[dezena]
        return f"{_DEZENAS[dezena]} e {_UNIDADES[unidade]}"
    if valor == 100:
        return "cem"
    centena, resto = divmod(valor, 100)
    if resto == 0:
        return _CENTENAS[centena]
    return f"{_CENTENAS[centena]} e {_ate_999(resto)}"


def _grupos_de_tres(valor: int) -> list[int]:
    grupos = []
    while valor:
        valor, grupo = divmod(valor, 1000)
        grupos.append(grupo)
    return grupos


def numero_por_extenso(valor: int) -> str:
    if valor < 0:
        return f"menos {numero_por_extenso(-valor)}"
    if valor == 0:
        return "zero"
    if valor >= LIMITE_EXTENSO:
        return str(valor)

    grupos = _grupos_de_tres(valor)
    partes: list[str] = []
    for indice in range(len(grupos) - 1, -1, -1):
        grupo = grupos[indice]
        if grupo == 0:
            continue
        singular, plural = _ESCALAS[indice]
        if indice == 1:
            nome = "mil" if grupo == 1 else f"{_ate_999(grupo)} mil"
        elif indice == 0:
            nome = _ate_999(grupo)
        else:
            escala = singular if grupo == 1 else plural
            nome = f"{_ate_999(grupo)} {escala}"
        partes.append(nome)

    if len(partes) == 1:
        return partes[0]

    ultimo_grupo = next((g for g in grupos if g), 0)
    if ultimo_grupo < 100 or ultimo_grupo % 100 == 0:
        return f"{_juntar(partes[:-1])} e {partes[-1]}"
    return _juntar(partes)


def _juntar(partes: list[str]) -> str:
    if len(partes) <= 1:
        return "".join(partes)
    if len(partes) == 2:
        return " ".join(partes)
    return ", ".join(partes)


GREGAS_FALADAS = {
    "alpha": "alfa", "beta": "beta", "gamma": "gama", "delta": "delta",
    "epsilon": "épsilon", "zeta": "zeta", "eta": "eta", "theta": "teta",
    "iota": "iota", "kappa": "capa", "lambda": "lambda", "mu": "mi",
    "nu": "ni", "xi": "csi", "pi": "pi", "rho": "rô",
    "sigma": "sigma", "tau": "tau", "upsilon": "úpsilon", "phi": "fi",
    "chi": "qui", "psi": "psi", "omega": "ômega",
    "Delta": "delta",
    "Gamma": "gama maiúsculo", "Theta": "teta maiúsculo",
    "Lambda": "lambda maiúsculo", "Xi": "csi maiúsculo",
    "Pi": "pi maiúsculo", "Sigma": "sigma maiúsculo",
    "Upsilon": "úpsilon maiúsculo", "Phi": "fi maiúsculo",
    "Psi": "psi maiúsculo", "Omega": "ômega maiúsculo",
    "ℕ": "naturais", "ℝ": "reais", "ℤ": "inteiros",
    "ℚ": "racionais", "ℂ": "complexos",
}

LETRAS_SOLETRADAS: dict[str, str] = {}


def falar_letra(letra: str) -> str:
    if not letra:
        return letra
    return LETRAS_SOLETRADAS.get(letra.lower(), letra)


FUNCOES_FALADAS = {
    "sen": "seno", "sin": "seno", "cos": "cosseno", "tan": "tangente",
    "tg": "tangente", "log": "logaritmo", "ln": "logaritmo natural",
    "exp": "exponencial", "lim": "limite", "det": "determinante",
    "max": "máximo", "min": "mínimo",
    "cot": "cotangente", "cotg": "cotangente",
    "sec": "secante", "csc": "cossecante", "cossec": "cossecante",
    "arcsin": "arco seno", "arccos": "arco cosseno",
    "arctan": "arco tangente",
    "senh": "seno hiperbólico", "cosh": "cosseno hiperbólico",
    "tanh": "tangente hiperbólica", "coth": "cotangente hiperbólica",
    "sech": "secante hiperbólica", "csch": "cossecante hiperbólica",
    "mod": "módulo", "mmc": "mínimo múltiplo comum",
    "mdc": "máximo divisor comum",
    "arcsen": "arco seno", "arctg": "arco tangente",
    "sup": "supremo", "inf": "ínfimo",
}

RELACOES_FALADAS = {
    "=": "é igual a", ">=": "maior ou igual a", "<=": "menor ou igual a",
    "!=": "diferente de", "<": "menor que", ">": "maior que",
    "in": "pertence a", "notin": "não pertence a",
    "subset": "está contido em", "subseteq": "está contido ou é igual a",
    "supset": "contém", "supseteq": "contém ou é igual a",
}

SIMBOLOS_PROIBIDOS_NA_FALA = (
    "²³¹⁰⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉√±≥≤≠∑∫ΔδπαβθλσωΩΣΦ^_\\"
)


def numero_por_extenso_feminino(valor: int) -> str:
    import re as _re

    falado = numero_por_extenso(valor)
    falado = _re.sub(r"\bum\b", "uma", falado)
    return _re.sub(r"\bdois\b", "duas", falado)


def texto_com_numeros_por_extenso(texto: str) -> str:
    import re as _re

    if not texto:
        return texto

    def _um_numero(m: "_re.Match[str]") -> str:
        bruto = m.group(0)
        inteiro = bruto.replace(".", "")
        if "," in inteiro:
            parte_inteira, _, parte_decimal = inteiro.partition(",")
            try:
                falado = numero_por_extenso(int(parte_inteira))
            except (TypeError, ValueError):
                return bruto
            decimais = " ".join(
                numero_por_extenso(int(d)) for d in parte_decimal
                if d.isdigit()
            )
            return f"{falado} vírgula {decimais}"
        try:
            return numero_por_extenso(int(inteiro))
        except (TypeError, ValueError):
            return bruto

    convertido = _re.sub(
        r"\d+(?:\.\d{3})*(?:,\d+)?", _um_numero, texto
    )
    return convertido.replace("%", " por cento").replace("  ", " ")


UNIDADES_FALADAS = {
    "m/s²": ("metro por segundo ao quadrado",
             "metros por segundo ao quadrado"),
    "m/s": ("metro por segundo", "metros por segundo"),
    "km/h": ("quilômetro por hora", "quilômetros por hora"),
    "km": ("quilômetro", "quilômetros"),
    "cm": ("centímetro", "centímetros"),
    "mm": ("milímetro", "milímetros"),
    "kg": ("quilograma", "quilogramas"),
    "g": ("grama", "gramas"),
    "m": ("metro", "metros"),
    "s": ("segundo", "segundos"),
    "h": ("hora", "horas"),
    "min": ("minuto", "minutos"),
    "N": ("newton", "newtons"),
    "J": ("joule", "joules"),
    "W": ("watt", "watts"),
    "Hz": ("hertz", "hertz"),
    "Pa": ("pascal", "pascals"),
}

UNIDADES_POR_TAMANHO = sorted(
    UNIDADES_FALADAS, key=len, reverse=True,
)


def unidade_por_extenso(unidade: str, valor: float | int | None) -> str:
    singular, plural = UNIDADES_FALADAS.get(unidade, (unidade, unidade))
    if valor is None:
        return plural
    try:
        return singular if abs(float(valor)) == 1 else plural
    except (TypeError, ValueError):
        return plural


def texto_por_extenso_com_unidades(texto: str) -> str:
    import re as _re

    if not texto:
        return texto
    alternativas = "|".join(
        _re.escape(u) for u in UNIDADES_POR_TAMANHO
    )
    padrao = _re.compile(
        r"(\d+(?:\.\d{3})*(?:,\d+)?)\s*(" + alternativas
        + r")(?![\wÀ-ÿ/])"
    )

    def _troca(m: "_re.Match[str]") -> str:
        bruto = m.group(1).replace(".", "")
        try:
            if "," in bruto:
                inteiro = int(bruto.split(",")[0])
                numero = texto_com_numeros_por_extenso(m.group(1))
            else:
                inteiro = int(bruto)
                numero = numero_por_extenso(inteiro)
        except (TypeError, ValueError):
            return m.group(0)
        return f"{numero} {unidade_por_extenso(m.group(2), inteiro)}"

    convertido = padrao.sub(_troca, texto)
    return texto_com_numeros_por_extenso(convertido)
