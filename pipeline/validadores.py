from __future__ import annotations

import re
from typing import Any

from pipeline.higienizador import contem_artefatos_markdown
from pipeline.higienizador import contem_vazamento_de_prompt
from pipeline.gestor_de_verbosidade import OUTPUT_PROFILES


def validar_documento_canonico(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["Documento canônico deve ser um objeto JSON."]
    for field in ["schema_version", "id", "title", "language", "sections"]:
        if field not in document:
            errors.append(f"Campo obrigatório ausente: {field}")
    if not isinstance(document.get("sections"), list):
        errors.append("Campo sections deve ser uma lista.")
        return errors

    ids: set[str] = set()
    headings: list[int] = []
    internal_links: list[str] = []

    def walk_blocks(blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            block_id = block.get("id")
            if block_id:
                if block_id in ids:
                    errors.append(f"ID interno duplicado: {block_id}")
                ids.add(block_id)
            if block.get("type") == "heading":
                headings.append(int(block.get("level", 1)))
            if block.get("type") == "paragraph":
                text = block.get("text", "")
                if contem_vazamento_de_prompt(text):
                    errors.append(
                        f"Possivel vazamento de prompt em {block_id}"
                    )
                if contem_artefatos_markdown(text):
                    errors.append(f"Markdown indevido em {block_id}")
            if block.get("type") == "code":
                code_text = block.get("text", "")
                if _indentation_lost(code_text):
                    errors.append(
                        f"Indentacao de codigo inconsistente em {block_id}"
                    )
            if block.get("type") == "table" and not block.get("rows"):
                errors.append(f"Tabela vazia em {block_id}")
            internal_links.extend(_extract_internal_links(block))

    for section in document.get("sections", []):
        walk_blocks(section.get("blocks", []))
        _walk_sections(section.get("children", []), walk_blocks)

    if headings.count(1) > 1:
        errors.append("O documento deve ter apenas um H1 principal.")
    if headings and headings[0] != 1:
        errors.append("O documento deve começar com um H1 principal.")
    if _heading_skips_levels(headings):
        errors.append("Hierarquia de headings salta niveis indevidamente.")
    for link in internal_links:
        if link not in ids:
            errors.append(f"Link interno aponta para ID inexistente: {link}")
    return errors


def validar_perfil_de_exportacao(
    profile_name: str,
    document: dict[str, Any],
) -> list[str]:
    profile = OUTPUT_PROFILES.get(profile_name)
    if not profile:
        return [f"Perfil de exportacao desconhecido: {profile_name}"]
    allowed = set(profile["verbosity"])
    errors: list[str] = []

    def walk(blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            if block.get("verbosity", "basic") not in allowed:
                errors.append(
                    f"Bloco {block.get('id')} nao permitido no perfil "
                    f"{profile_name}"
                )
            for child in block.get("children", []) or []:
                if isinstance(child, dict):
                    walk([child])

    for section in document.get("sections", []):
        walk(section.get("blocks", []))
        _walk_sections(section.get("children", []), walk)
    return errors


def validar_texto_de_saida(text: str, profile_name: str) -> list[str]:
    errors: list[str] = []
    if contem_vazamento_de_prompt(text):
        errors.append("Possivel vazamento de prompt na saida final.")
    if profile_name != "html" and contem_artefatos_markdown(text):
        errors.append("Markdown indevido na saida final.")
    if profile_name == "txt" and re.search(
        r"\[\s*IN[IÍ]CIO DA AUDIODESCRI[CÇ][AÃ]O\s*\]",
        text,
        re.I,
    ):
        errors.append("Metadados tecnicos nao devem aparecer no TXT.")
    return errors


def auditar_documento_canonico(document: dict[str, Any]) -> dict[str, list[str]]:
    report = {"BLOCKER": [], "WARNING": []}
    
    base_errors = validar_documento_canonico(document)
    if base_errors:
        report["BLOCKER"].extend(base_errors)
    
    sections = document.get("sections", [])
    if not sections:
        report["BLOCKER"].append("Documento sem seções.")
    
    def obter_alt_da_imagem(bloco: dict[str, Any]) -> str:
        for chave in ("alt_text", "text", "alt"):
            valor = (bloco.get(chave) or "").strip()
            if valor:
                return valor
        return ""

    def check_accessibility(blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            if (
                block.get("type") == "image"
                and not block.get("decorative")
                and not obter_alt_da_imagem(block)
                and not block.get("long_description")
            ):
                report["WARNING"].append(f"Imagem {block.get('id')} sem alt-text.")
    
    for section in sections:
        check_accessibility(section.get("blocks", []))
        _walk_sections(section.get("children", []), check_accessibility)
        
    return report


def _walk_sections(sections: list[dict[str, Any]], callback) -> None:
    for section in sections:
        callback(section.get("blocks", []))
        _walk_sections(section.get("children", []), callback)


def _extract_internal_links(block: dict[str, Any]) -> list[str]:
    links: list[str] = []
    metadata = block.get("metadata", {})
    if isinstance(metadata, dict):
        for value in metadata.values():
            if isinstance(value, str) and value.startswith("#"):
                links.append(value[1:])
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.startswith("#"):
                        links.append(item[1:])
    return links


def _heading_skips_levels(levels: list[int]) -> bool:
    previous = 0
    for level in levels:
        if level > previous + 1:
            return True
        previous = level
    return False


def _indentation_lost(text: str) -> bool:
    lines = text.splitlines()
    if len(lines) <= 1:
        return False
    return not any(line.startswith((" ", "\t")) for line in lines)
