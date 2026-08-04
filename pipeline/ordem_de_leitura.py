"""Ordena as regioes na ordem correta de leitura (XY-cut).

A ordenacao ingenua (de cima para baixo, da esquerda para a direita)
funciona em coluna unica e falha em qualquer layout com cards ou
colunas lado a lado: tres cards com numero, titulo e texto saem como
"01 02 03 / TITULO TITULO TITULO / texto texto texto".

Para quem le com os olhos a diagramacao resolve; para quem ouve, o
material vira uma lista sem sentido. O XY-cut detecta as colunas e le
cada uma inteira antes de passar a seguinte.
"""

from __future__ import annotations

from typing import Any, Callable

CALHA_VERTICAL_MINIMA = 18.0

CALHA_HORIZONTAL_MINIMA = 6.0

MINIMO_PARA_CORTAR = 2

PROFUNDIDADE_MAXIMA = 12


def _sem_bbox(caixa: Any) -> bool:
    return (
        not caixa
        or len(caixa) < 4
        or any(v is None for v in caixa[:4])
    )


def _achar_calha(
    intervalos: list[tuple[float, float]], minimo: float
) -> tuple[float, float] | None:
    if len(intervalos) < 2:
        return None

    ordenados = sorted(intervalos)
    melhor_vao = 0.0
    melhor_corte = None
    limite_atual = ordenados[0][1]

    for inicio, fim in ordenados[1:]:
        vao = inicio - limite_atual
        if vao > melhor_vao:
            melhor_vao = vao
            melhor_corte = limite_atual + vao / 2
        limite_atual = max(limite_atual, fim)

    if melhor_vao >= minimo and melhor_corte is not None:
        return melhor_corte, melhor_vao
    return None


def _cortar(
    indices: list[int],
    caixas: dict[int, tuple[float, float, float, float]],
    eixo: int,
) -> tuple[list[int], list[int], float] | None:
    inicio, fim = (0, 2) if eixo == 0 else (1, 3)
    minimo = CALHA_VERTICAL_MINIMA if eixo == 0 else CALHA_HORIZONTAL_MINIMA

    intervalos = [
        (caixas[i][inicio], caixas[i][fim]) for i in indices
    ]
    achado = _achar_calha(intervalos, minimo)
    if achado is None:
        return None
    corte, vao = achado

    antes = [i for i in indices if caixas[i][fim] <= corte]
    depois = [i for i in indices if caixas[i][fim] > corte]
    if not antes or not depois:
        return None
    return antes, depois, vao


def _ordenar_recursivo(
    indices: list[int],
    caixas: dict[int, tuple[float, float, float, float]],
    profundidade: int = 0,
) -> list[int]:
    if len(indices) < MINIMO_PARA_CORTAR or profundidade >= PROFUNDIDADE_MAXIMA:
        return sorted(indices, key=lambda i: (caixas[i][1], caixas[i][0]))

    horizontal = _cortar(indices, caixas, eixo=1)
    vertical = _cortar(indices, caixas, eixo=0)

    if horizontal and vertical:
        escolhido = horizontal if horizontal[2] >= vertical[2] else vertical
    else:
        escolhido = horizontal or vertical

    if escolhido:
        primeiro, segundo, _ = escolhido
        return (
            _ordenar_recursivo(primeiro, caixas, profundidade + 1)
            + _ordenar_recursivo(segundo, caixas, profundidade + 1)
        )

    return sorted(indices, key=lambda i: (caixas[i][1], caixas[i][0]))


def ordenar_por_leitura(
    itens: list,
    obter_bbox: Callable[[Any], Any] | None = None,
) -> list:
    if not itens:
        return list(itens)

    def _bbox(item):
        if obter_bbox is not None:
            return obter_bbox(item)
        return getattr(item, "bbox", None) or (
            item.get("bbox") if isinstance(item, dict) else None
        )

    try:
        caixas: dict[int, tuple[float, float, float, float]] = {}
        sem_geometria: list[int] = []
        for i, item in enumerate(itens):
            caixa = _bbox(item)
            if _sem_bbox(caixa):
                sem_geometria.append(i)
                continue
            caixas[i] = (
                float(caixa[0]), float(caixa[1]),
                float(caixa[2]), float(caixa[3]),
            )

        ordem = _ordenar_recursivo(list(caixas), caixas)
        return [itens[i] for i in ordem] + [itens[i] for i in sem_geometria]
    except Exception:
        try:
            return sorted(
                itens,
                key=lambda r: (
                    (_bbox(r) or (0, 0, 0, 0))[1],
                    (_bbox(r) or (0, 0, 0, 0))[0],
                ),
            )
        except Exception:
            return list(itens)


def coluna_de(caixa, colunas: list[tuple[float, float]]) -> int:
    if _sem_bbox(caixa):
        return -1
    centro = (float(caixa[0]) + float(caixa[2])) / 2
    for indice, (inicio, fim) in enumerate(colunas):
        if inicio <= centro <= fim:
            return indice
    return -1


def detectar_colunas(
    itens: list, obter_bbox: Callable[[Any], Any] | None = None
) -> list[tuple[float, float]]:
    def _bbox(item):
        if obter_bbox is not None:
            return obter_bbox(item)
        return getattr(item, "bbox", None) or (
            item.get("bbox") if isinstance(item, dict) else None
        )

    try:
        intervalos = [
            (float(_bbox(i)[0]), float(_bbox(i)[2]))
            for i in itens
            if not _sem_bbox(_bbox(i))
        ]
        if not intervalos:
            return []

        faixas: list[list[float]] = []
        for inicio, fim in sorted(intervalos):
            if faixas and inicio - faixas[-1][1] < CALHA_VERTICAL_MINIMA:
                faixas[-1][1] = max(faixas[-1][1], fim)
            else:
                faixas.append([inicio, fim])
        return [(a, b) for a, b in faixas]
    except Exception:
        return []
