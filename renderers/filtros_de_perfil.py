"""Decide quais blocos entram em cada formato de saida."""

from __future__ import annotations

from copy import deepcopy

from pipeline.gestor_de_verbosidade import filtrar_blocos_por_perfil


def aplicar_filtro_de_perfil(blocks: list[dict], profile_name: str) -> list[dict]:
    return filtrar_blocos_por_perfil(blocks, profile_name)


def _filter_sections(sections: list[dict], profile_name: str) -> list[dict]:
    result: list[dict] = []
    for section in sections:
        new_section = deepcopy(section)
        new_section["blocks"] = filtrar_blocos_por_perfil(
            section.get("blocks", []), profile_name
        )
        new_section["children"] = _filter_sections(
            section.get("children", []), profile_name
        )
        result.append(new_section)
    return result
