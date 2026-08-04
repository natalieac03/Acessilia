"""Verifica o documento inteiro: repeticao, ordem, imagem perdida.

O critico visual compara uma descricao com UM recorte e nao ve o
documento. Por isso uma descricao pode corresponder ao recorte ERRADO
e ainda receber confianca alta: ela e fiel ao que viu, so que viu a
regiao trocada.

Estes verificadores olham o conjunto e sao deterministicos — contam e
medem, em vez de perguntar a um modelo se a saida ficou boa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

LIMIAR_REPETICAO = 0.90

RAZAO_EXPANSAO_SUSPEITA = 4.0

_MARCAS_DE_LAYOUT = (
    "primeira linha", "segunda linha", "canto superior", "canto inferior",
    "a esquerda da tela", "no topo da imagem", "letra maiuscula",
    "sinal de igual", "parentese de abertura", "parêntese de abertura",
)


@dataclass
class ProblemaDeCoerencia:
    check: str
    severity: str
    message: str
    block_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check, "severity": self.severity,
            "message": self.message, "block_ids": list(self.block_ids),
        }


def _blocos(documento: dict[str, Any]):
    def _secao(secao):
        for bloco in secao.get("blocks", []) or []:
            yield bloco
        for filha in secao.get("children", []) or []:
            yield from _secao(filha)

    for secao in documento.get("sections", []) or []:
        yield from _secao(secao)
    for bloco in documento.get("blocks", []) or []:
        yield bloco


def _texto(bloco: dict[str, Any]) -> str:
    if bloco.get("type") in ("table", "math", "list", "code"):
        return ""
    return str(bloco.get("text") or "")


def _normalizar(texto: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", texto.lower()).strip()


def detectar_repeticao(documento: dict[str, Any]) -> list[ProblemaDeCoerencia]:
    problemas: list[ProblemaDeCoerencia] = []
    anteriores: list[tuple[str, str]] = []

    for bloco in _blocos(documento):
        texto = _normalizar(_texto(bloco))
        if len(texto) < 40:
            continue
        bloco_id = str(bloco.get("id") or "")
        for id_anterior, texto_anterior in anteriores[-3:]:
            razao = SequenceMatcher(None, texto, texto_anterior).ratio()
            if razao >= LIMIAR_REPETICAO:
                problemas.append(ProblemaDeCoerencia(
                    check="repeticao", severity="WARNING",
                    message=(
                        f"Dois blocos repetem o mesmo conteudo "
                        f"({razao:.0%} de similaridade)."
                    ),
                    block_ids=[id_anterior, bloco_id],
                ))
                break
        anteriores.append((bloco_id, texto))
    return problemas


def detectar_narracao_de_layout(
    documento: dict[str, Any],
) -> list[ProblemaDeCoerencia]:
    problemas = []
    for bloco in _blocos(documento):
        texto = _texto(bloco).lower()
        if not texto:
            continue
        marcas = [m for m in _MARCAS_DE_LAYOUT if m in texto]
        if len(marcas) >= 2:
            problemas.append(ProblemaDeCoerencia(
                check="narracao_de_layout", severity="WARNING",
                message=(
                    "A descricao narra a posicao dos elementos em vez de "
                    f"ler o conteudo ({', '.join(marcas[:3])})."
                ),
                block_ids=[str(bloco.get("id") or "")],
            ))
    return problemas


def detectar_ordem_quebrada(
    documento: dict[str, Any],
) -> list[ProblemaDeCoerencia]:
    problemas = []
    ultima_pagina = 0
    for bloco in _blocos(documento):
        pagina = bloco.get("page_number") or (
            bloco.get("metadata", {}) or {}
        ).get("page_number")
        if not isinstance(pagina, int):
            continue
        if pagina < ultima_pagina:
            problemas.append(ProblemaDeCoerencia(
                check="ordem_de_leitura", severity="ERROR",
                message=(
                    f"Bloco da pagina {pagina} aparece depois de conteudo "
                    f"da pagina {ultima_pagina}."
                ),
                block_ids=[str(bloco.get("id") or "")],
            ))
        ultima_pagina = max(ultima_pagina, pagina)
    return problemas


def detectar_perda_de_imagem(
    documento: dict[str, Any],
) -> list[ProblemaDeCoerencia]:
    problemas = []
    for bloco in _blocos(documento):
        if bloco.get("type") != "image" or bloco.get("decorative"):
            continue
        tem_descricao = any(
            str(bloco.get(campo) or "").strip()
            for campo in ("alt_text", "long_description", "text")
        )
        if not tem_descricao:
            problemas.append(ProblemaDeCoerencia(
                check="imagem_perdida", severity="ERROR",
                message=(
                    "Imagem nao decorativa sem nenhuma descricao: "
                    "o conteudo visual se perdeu."
                ),
                block_ids=[str(bloco.get("id") or "")],
            ))
    return problemas


def razao_de_expansao(documento: dict[str, Any]) -> float:
    saida = sum(len(_texto(b).split()) for b in _blocos(documento))
    origem = 0
    for bloco in _blocos(documento):
        metadata = bloco.get("metadata") or {}
        origem += len(str(metadata.get("origem") or "").split())
    if origem <= 0:
        return 0.0
    return round(saida / origem, 2)


def verificar_coerencia_global(
    documento: dict[str, Any],
) -> dict[str, Any]:
    problemas: list[ProblemaDeCoerencia] = []
    for verificador in (
        detectar_repeticao,
        detectar_narracao_de_layout,
        detectar_ordem_quebrada,
        detectar_perda_de_imagem,
    ):
        try:
            problemas.extend(verificador(documento))
        except Exception:
            continue

    razao = razao_de_expansao(documento)
    if razao and razao > RAZAO_EXPANSAO_SUSPEITA:
        problemas.append(ProblemaDeCoerencia(
            check="expansao_suspeita", severity="WARNING",
            message=(
                f"A saida tem {razao}x mais palavras que a origem - "
                "possivel repeticao ou texto inventado."
            ),
        ))

    erros = [p for p in problemas if p.severity == "ERROR"]
    return {
        "issues": [p.to_dict() for p in problemas],
        "counts": {
            "ERROR": len(erros),
            "WARNING": len(problemas) - len(erros),
        },
        "output_expansion_ratio": razao,
        "coerente": not erros,
    }
