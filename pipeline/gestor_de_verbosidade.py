"""Perfis de saida e filtro de blocos por verbosidade."""

from __future__ import annotations

from copy import deepcopy

OUTPUT_PROFILES = {
    "html": {
        "verbosity": ["basic", "detailed", "technical"],
        "interactive": True,
        "collapsible": True,
        "include_audit": False,
        "developer_debug": False,
    },
    "developer_debug": {
        "verbosity": ["basic", "detailed", "technical"],
        "interactive": True,
        "collapsible": True,
        "include_audit": True,
        "developer_debug": True,
    },
    "pdf": {
        "verbosity": ["basic", "detailed"],
        "interactive": False,
        "collapsible": False,
        "include_audit": False,
    },
    "docx": {
        "verbosity": ["basic", "detailed"],
        "interactive": False,
        "collapsible": False,
        "include_audit": False,
    },
    "txt": {
        "verbosity": ["basic"],
        "interactive": False,
        "collapsible": False,
        "include_audit": False,
    },
}

MODE_TO_VERBOSITY = {
    "normal": "detailed",
    "medio": "detailed",
    "detalhado": "technical",
    "baixo": "basic",
    "ocr": "detailed",
}


def normalizar_perfil(profile_name: str) -> dict:
    return deepcopy(OUTPUT_PROFILES.get(profile_name, OUTPUT_PROFILES["txt"]))


def verbosity_for_mode(mode: str) -> str:
    return MODE_TO_VERBOSITY.get(mode, "detailed")


def filtrar_blocos_por_perfil(
    blocks: list[dict],
    profile_name: str,
) -> list[dict]:
    allowed = set(normalizar_perfil(profile_name)["verbosity"])
    return [block for block in blocks if block.get("verbosity", "basic") in allowed]
