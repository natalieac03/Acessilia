"""Normalizacao do `reasoning_effort` enviado ao provedor."""

from __future__ import annotations

_VALIDOS = frozenset({
    "minimal", "low", "medium", "high", "xhigh", "max",
})

_DESLIGADO = frozenset({
    "", "off", "none", "false", "no", "nao", "não", "0", "desligado",
})

_LIGADO_GENERICO = frozenset({
    "on", "true", "yes", "sim", "1", "ligado", "ativo",
})

_PADRAO_GENERICO = "medium"


def normalizar_esforco(valor: str | None, origem: str = "") -> str | None:
    texto = (valor or "").strip().lower()

    if texto in _DESLIGADO:
        return None
    if texto in _VALIDOS:
        return texto
    if texto in _LIGADO_GENERICO:
        return _PADRAO_GENERICO

    _avisar(
        f"{origem or 'REASONING'}='{valor}' nao e um esforco valido "
        f"(aceitos: {', '.join(sorted(_VALIDOS))}, ou off). "
        f"Seguindo SEM raciocinio estendido nesta etapa."
    )
    return None


def aplicar_esforco(
    parametros: dict, variavel: str, padrao: str = "off"
) -> dict:
    import os

    esforco = normalizar_esforco(os.getenv(variavel, padrao), variavel)
    if esforco:
        parametros["reasoning_effort"] = esforco
    return parametros


def _avisar(mensagem: str) -> None:
    try:
        from core.utils.logger import logger

        logger.warning(mensagem)
    except Exception:
        import sys

        print(f"AVISO: {mensagem}", file=sys.stderr)
