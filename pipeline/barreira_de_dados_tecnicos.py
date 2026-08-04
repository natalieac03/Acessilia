"""Impede que dado tecnico chegue ao material do estudante.

Metadado de pipeline, eco de contexto e dump de estrutura nao sao
conteudo da aula. Um caso instrutivo: o HTML embutia um dump do
documento canonico dentro de um elemento com aria-hidden.

O aria-hidden esconde da arvore de acessibilidade, e por isso parece
resolver — o leitor de tela nao anuncia. Mas o texto continua no DOM:
a busca do navegador acha, o Ctrl+F acha, copiar e colar leva junto.
Esconder da API de acessibilidade nao e remover.
"""

from __future__ import annotations

import re
from typing import Any

_TERMOS_INTERNOS = (
    "tipo da regiao", "tipo da região", "tipo_regiao",
    "review_status", "reviewstatus",
    "source_text", "source_hash", "block_id", "region_id",
    "validation_issues", "confidence", "confianca do critico",
    "bounding box", "bbox",
    "metadata", "metadados tecnicos", "metadados técnicos",
    "canonical_document", "documento canonico", "documento canônico",
    "asset_id", "asset_path",
    "acessilia_generated", "publicationdecision",
    "needs_review", "text_clean", "text_scanned", "embedded_image",
)

PERFIL_DEBUG = "developer_debug"

_PADRAO_TERMOS = re.compile(
    "|".join(re.escape(t) for t in _TERMOS_INTERNOS), re.IGNORECASE
)

_PADRAO_ECO = re.compile(
    r"^\s*(?:<<<TEXTO|TEXTO>>>|\[tipo d[ao] regi[aã]o[^\]]*\]|"
    r"contexto \(n[aã]o faz parte do texto\)[^\n]*)\s*",
    re.IGNORECASE | re.MULTILINE,
)


def encontrar_termos_internos(texto: str) -> list[str]:
    if not texto:
        return []
    return sorted({m.group(0).lower() for m in _PADRAO_TERMOS.finditer(texto)})


def limpar_eco_de_contexto(texto: str) -> str:
    if not texto:
        return texto
    limpo = _PADRAO_ECO.sub("", texto)
    return limpo.strip()


def texto_seguro_para_estudante(
    texto: str, original: str | None = None
) -> tuple[str, list[str]]:
    limpo = limpar_eco_de_contexto(texto or "")
    encontrados = encontrar_termos_internos(limpo)
    if encontrados and original and not encontrar_termos_internos(original):
        return original, encontrados
    return limpo, encontrados


_CHAVES_TECNICAS = (
    "accessibilityAudit", "acessilia", "publicationDecision",
    "revisao_textual", "trilha", "metadata",
)

_CHAVES_TECNICAS_DE_BLOCO = (
    "validation_issues", "review_status", "source_text", "uncertainties",
    "confidence", "source_hash", "review_events",
)


def documento_para_estudante(
    documento: dict[str, Any], perfil: str = ""
) -> dict[str, Any]:
    if perfil == PERFIL_DEBUG:
        return documento

    limpo = {
        chave: valor for chave, valor in documento.items()
        if chave not in _CHAVES_TECNICAS
    }
    if "sections" in documento:
        limpo["sections"] = [
            _secao_limpa(secao) for secao in documento.get("sections") or []
        ]
    if "blocks" in documento:
        limpo["blocks"] = [
            _bloco_limpo(bloco) for bloco in documento.get("blocks") or []
        ]
    return limpo


def _secao_limpa(secao: dict[str, Any]) -> dict[str, Any]:
    nova = dict(secao)
    nova["blocks"] = [_bloco_limpo(b) for b in secao.get("blocks") or []]
    nova["children"] = [_secao_limpa(c) for c in secao.get("children") or []]
    return nova


def _bloco_limpo(bloco: dict[str, Any]) -> dict[str, Any]:
    novo = {
        chave: valor for chave, valor in bloco.items()
        if chave not in _CHAVES_TECNICAS_DE_BLOCO
    }
    metadata = bloco.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("asset_path"):
        novo.setdefault("asset_path", metadata["asset_path"])
    novo.pop("metadata", None)
    return novo
