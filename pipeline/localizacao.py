"""Trata idioma de origem diferente do idioma de saida.

Um grafico em ingles gerava saida hibrida dentro de um documento
declarado pt-BR: estrutura em portugues, conteudo em ingles, decimal
ora com virgula ora com ponto — e o sintetizador lendo palavras
inglesas com fonetica portuguesa.

O defeito nao era de leitura, era de modelo de dados: existia um unico
campo de idioma, fixo, e nenhuma etapa de traducao entre extrair e
renderizar.
"""

from __future__ import annotations

import re
from typing import Any

IDIOMA_PADRAO_DE_SAIDA = "pt-BR"

_MARCADORES = {
    "pt": (
        "de", "da", "do", "para", "com", "por", "uma", "que", "nao", "não",
        "e", "ou", "em", "os", "as", "dos", "das", "ao", "pelo", "pela",
    ),
    "en": (
        "the", "of", "and", "for", "with", "from", "this", "that", "are",
        "is", "by", "to", "in", "on", "at", "as", "per",
    ),
    "es": (
        "el", "la", "los", "las", "del", "por", "para", "con", "una",
        "que", "es", "son", "y", "o", "en",
    ),
}

_ACENTOS_LATINOS = set("áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ")


def detectar_idioma(texto: str) -> str:
    if not texto or len(texto.strip()) < 12:
        return ""

    palavras = re.findall(r"[a-zà-ÿ]+", texto.lower())
    if len(palavras) < 3:
        return ""

    pontos = {
        idioma: sum(1 for p in palavras if p in marcadores)
        for idioma, marcadores in _MARCADORES.items()
    }
    if any(c in _ACENTOS_LATINOS for c in texto):
        pontos["pt"] += 2

    vencedor = max(pontos, key=lambda k: pontos[k])
    if pontos[vencedor] == 0:
        return ""
    segundos = sorted(pontos.values(), reverse=True)
    if len(segundos) > 1 and segundos[0] == segundos[1]:
        return ""
    return vencedor


def detectar_idioma_de_tabela(rows: list[list[Any]]) -> str:
    if not rows:
        return ""

    celulas = [
        str(c).strip().lower().strip(" .:")
        for linha in rows for c in linha
        if str(c).strip()
    ]
    textuais = [
        c for c in celulas if not re.fullmatch(r"-?[\d.,\s%]+", c)
    ]
    if not textuais:
        return ""

    dicionario = {**GLOSSARIO_GERAL_PT_BR, **GLOSSARIO_QUIMICA_PT_BR}
    traduziveis = 0
    ja_em_portugues = 0
    equivalentes_pt = {v.lower() for v in dicionario.values()}

    for celula in textuais:
        nucleo = re.sub(r"\s*\([^)]*\)\s*$", "", celula).strip()
        if nucleo in dicionario:
            traduziveis += 1
        elif nucleo in equivalentes_pt:
            ja_em_portugues += 1

    if traduziveis and traduziveis > ja_em_portugues:
        return "en"
    if ja_em_portugues:
        return "pt-BR"

    return detectar_idioma(" ".join(textuais))


def e_portugues(codigo: str) -> bool:
    return (codigo or "").lower().startswith("pt")


GLOSSARIO_QUIMICA_PT_BR = {
    "aluminum": "Alumínio", "aluminium": "Alumínio",
    "antimony": "Antimônio", "arsenic": "Arsênio", "barium": "Bário",
    "beryllium": "Berílio", "bismuth": "Bismuto", "boron": "Boro",
    "cadmium": "Cádmio", "calcium": "Cálcio", "carbon": "Carbono",
    "chromium": "Cromo", "cobalt": "Cobalto", "copper": "Cobre",
    "gold": "Ouro", "iron": "Ferro", "lead": "Chumbo",
    "lithium": "Lítio", "magnesium": "Magnésio", "manganese": "Manganês",
    "mercury": "Mercúrio", "molybdenum": "Molibdênio",
    "nickel": "Níquel", "niobium": "Nióbio", "osmium": "Ósmio",
    "palladium": "Paládio", "platinum": "Platina",
    "potassium": "Potássio", "rhodium": "Ródio", "silver": "Prata",
    "sodium": "Sódio", "tantalum": "Tântalo", "tin": "Estanho",
    "titanium": "Titânio", "tungsten": "Tungstênio",
    "uranium": "Urânio", "vanadium": "Vanádio", "zinc": "Zinco",
    "zirconium": "Zircônio",
}

GLOSSARIO_GERAL_PT_BR = {
    "density": "Densidade", "metal": "Metal", "metals": "Metais",
    "element": "Elemento", "elements": "Elementos",
    "value": "Valor", "values": "Valores", "name": "Nome",
    "year": "Ano", "years": "Anos", "month": "Mês", "months": "Meses",
    "total": "Total", "average": "Média", "mean": "Média",
    "percentage": "Percentual", "percent": "Percentual",
    "temperature": "Temperatura", "weight": "Peso", "mass": "Massa",
    "volume": "Volume", "length": "Comprimento", "area": "Área",
    "country": "País", "countries": "Países", "population": "População",
    "category": "Categoria", "type": "Tipo", "quantity": "Quantidade",
}

_GLOSSARIOS = {
    "quimica": {**GLOSSARIO_GERAL_PT_BR, **GLOSSARIO_QUIMICA_PT_BR},
    "geral": GLOSSARIO_GERAL_PT_BR,
}


_UNIDADES = (
    (r"\bgram/cm3\b", "g/cm³"), (r"\bg/cm3\b", "g/cm³"),
    (r"\bgrams?\s*per\s*cubic\s*centimet(?:er|re)\b", "g/cm³"),
    (r"\bkg/m3\b", "kg/m³"), (r"\bm/s2\b", "m/s²"),
    (r"\bcm2\b", "cm²"), (r"\bm2\b", "m²"), (r"\bkm2\b", "km²"),
    (r"\bdegrees?\s*celsius\b", "°C"), (r"\bcelsius\b", "°C"),
)


def normalizar_unidade(texto: str) -> str:
    resultado = texto or ""
    for padrao, substituto in _UNIDADES:
        resultado = re.sub(padrao, substituto, resultado, flags=re.IGNORECASE)
    return resultado


def normalizar_numero(texto: str) -> str:
    limpo = (texto or "").strip()
    if re.fullmatch(r"-?\d+\.\d+", limpo):
        return limpo.replace(".", ",")
    return texto


def traduzir_termo(
    termo: str, dominio: str = "quimica"
) -> tuple[str, bool]:
    bruto = (termo or "").strip()
    if not bruto:
        return termo, True

    glossario = _GLOSSARIOS.get(dominio, GLOSSARIO_GERAL_PT_BR)

    if re.fullmatch(r"-?[\d.,\s]+", bruto):
        return normalizar_numero(bruto), True

    correspondencia = re.match(r"^([^(]+)\(([^)]*)\)\s*$", bruto)
    if correspondencia:
        nucleo, unidade = correspondencia.groups()
        traduzido, ok = traduzir_termo(nucleo.strip(), dominio)
        return f"{traduzido} ({normalizar_unidade(unidade.strip())})", ok

    chave = bruto.lower().strip(" .:")
    if chave in glossario:
        return glossario[chave], True

    normalizado = normalizar_unidade(bruto)
    if normalizado != bruto:
        return normalizado, True

    return bruto, False


def localizar_tabela(
    rows: list[list[Any]],
    destino: str = IDIOMA_PADRAO_DE_SAIDA,
    origem: str = "",
    dominio: str = "quimica",
) -> dict[str, Any]:
    if not rows:
        return {
            "source_rows": [], "rows": [], "cell_languages": [],
            "source_language": origem, "language": destino,
        }

    if not origem:
        origem = detectar_idioma_de_tabela(rows)

    if e_portugues(origem) or not origem:
        localizadas = [
            [normalizar_numero(str(c)) for c in linha] for linha in rows
        ]
        return {
            "source_rows": [list(linha) for linha in rows],
            "rows": localizadas,
            "cell_languages": [[destino] * len(linha) for linha in rows],
            "source_language": origem or destino,
            "language": destino,
            "localization": {"strategy": "numbers_only"},
        }

    localizadas: list[list[str]] = []
    idiomas: list[list[str]] = []
    for linha in rows:
        nova_linha: list[str] = []
        idiomas_da_linha: list[str] = []
        for celula in linha:
            traduzido, ok = traduzir_termo(str(celula), dominio)
            nova_linha.append(traduzido)
            idiomas_da_linha.append(destino if ok else origem)
        localizadas.append(nova_linha)
        idiomas.append(idiomas_da_linha)

    return {
        "source_rows": [list(linha) for linha in rows],
        "rows": localizadas,
        "cell_languages": idiomas,
        "source_language": origem,
        "language": destino,
        "localization": {
            "strategy": "translated_labels",
            "glossary": f"{dominio}-{destino}-v1",
        },
    }


def localizar_bloco(
    bloco: dict[str, Any], destino: str = IDIOMA_PADRAO_DE_SAIDA
) -> dict[str, Any]:
    if bloco.get("type") not in ("table", "chart"):
        return bloco
    if bloco.get("source_rows"):
        return bloco
    rows = bloco.get("rows") or []
    if not rows:
        return bloco

    pacote = localizar_tabela(rows, destino=destino)
    novo = dict(bloco)
    novo.update(pacote)
    return novo


_CODIGO_COMPLETO = {"en": "en-US", "es": "es-ES", "fr": "fr-FR",
                    "de": "de-DE", "it": "it-IT"}


def codigo_bcp47(codigo: str) -> str:
    curto = (codigo or "").lower()
    if "-" in curto:
        return codigo
    return _CODIGO_COMPLETO.get(curto, codigo)


def precisa_marcar(idioma_da_celula: str, idioma_do_documento: str) -> bool:
    if not idioma_da_celula or not idioma_do_documento:
        return False
    return idioma_da_celula.split("-")[0] != idioma_do_documento.split("-")[0]
