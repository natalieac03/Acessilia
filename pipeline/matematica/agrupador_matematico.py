"""Reune fragmentos de formula que o extrator entregou quebrados.

Fracoes e radicais chegam despedacados: o numerador e um bloco, a
barra e outro, o denominador e um terceiro. E expressoes inteiras vem
cortadas no meio ("(x - 2)(x" numa regiao, "- 3) = 0" na seguinte).

A juncao precisa acontecer ANTES da tokenizacao, com a pagina ainda
aberta — nenhum parser reconstroi o que foi descartado antes de chegar
a arvore, porque a informacao que falta esta em outra regiao.

O criterio e geometrico e sintatico (alinhamento na pagina mais
fragmento sintaticamente incompleto), nunca semantico: nenhum modelo
decide o que se junta com o que.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


import re
from typing import Any, Protocol

DISTANCIA_VERTICAL_MAXIMA = 40.0

SOBREPOSICAO_HORIZONTAL_MINIMA = 0.30

_ABERTURAS = ("(", "[", "{", "\\frac", "\\sqrt", "√")
_FECHAMENTOS = (")", "]", "}")
_OPERADORES_PENDENTES = ("+", "-", "=", "±", "×", "·", "/", "^", "_", "<", ">")
_SIMBOLOS_MATEMATICOS = (
    "=", "±", "√", "∫", "∑", "≤", "≥", "≠", "∞", "π", "Δ", "²", "³",
)


@dataclass
class GrupoMatematico:

    indices: list[int] = field(default_factory=list)
    texto: str = ""
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    sinais: list[str] = field(default_factory=list)

    @property
    def fragmentado(self) -> bool:
        return len(self.indices) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "indices": list(self.indices), "texto": self.texto,
            "bbox": list(self.bbox), "sinais": list(self.sinais),
            "fragmentado": self.fragmentado,
        }


def _bbox(regiao) -> tuple[float, float, float, float]:
    try:
        return tuple(float(v) for v in getattr(regiao, "bbox", (0, 0, 0, 0)))
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0, 0.0)


def _texto(regiao) -> str:
    return str(getattr(regiao, "text", "") or "").strip()


def sinais_de_formula(texto: str) -> list[str]:
    achados = []
    if any(s in texto for s in _SIMBOLOS_MATEMATICOS):
        achados.append("simbolo_matematico")
    if any(texto.rstrip().endswith(op) for op in _OPERADORES_PENDENTES):
        achados.append("termina_em_operador")
    if texto.count("(") != texto.count(")"):
        achados.append("parenteses_desbalanceados")
    if any(texto.lstrip().startswith(f) for f in _FECHAMENTOS):
        achados.append("comeca_por_fechamento")
    if any(a in texto for a in _ABERTURAS):
        achados.append("abertura")
    return achados


def fragmento_incompleto(texto: str) -> bool:
    if not texto:
        return False
    sinais = sinais_de_formula(texto)
    return any(
        s in sinais for s in (
            "termina_em_operador", "parenteses_desbalanceados",
            "comeca_por_fechamento",
        )
    )


def _sobreposicao_horizontal(a, b) -> float:
    x0 = max(a[0], b[0])
    x1 = min(a[2], b[2])
    if x1 <= x0:
        return 0.0
    largura_menor = min(a[2] - a[0], b[2] - b[0])
    if largura_menor <= 0:
        return 0.0
    return (x1 - x0) / largura_menor


def _distancia_vertical(a, b) -> float:
    if a[3] <= b[1]:
        return b[1] - a[3]
    if b[3] <= a[1]:
        return a[1] - b[3]
    return 0.0


def _adjacente_horizontal(a, b, folga: float = 20.0) -> bool:
    faixa_vertical = min(a[3], b[3]) - max(a[1], b[1])
    if faixa_vertical <= -folga:
        return False
    gap = max(b[0] - a[2], a[0] - b[2])
    return gap <= folga


def fronteira_visual_coerente(regiao_a, regiao_b) -> bool:
    a, b = _bbox(regiao_a), _bbox(regiao_b)
    if _distancia_vertical(a, b) > DISTANCIA_VERTICAL_MAXIMA:
        return False
    return _sobreposicao_horizontal(a, b) >= SOBREPOSICAO_HORIZONTAL_MINIMA


def construir_grafo_de_proximidade(regioes: list) -> dict[int, set[int]]:
    grafo: dict[int, set[int]] = {i: set() for i in range(len(regioes))}
    for i, regiao in enumerate(regioes):
        texto_i = _texto(regiao)
        if not texto_i or not sinais_de_formula(texto_i):
            continue
        for j in range(i + 1, len(regioes)):
            texto_j = _texto(regioes[j])
            if not texto_j or not sinais_de_formula(texto_j):
                continue
            if not (
                fragmento_incompleto(texto_i) or fragmento_incompleto(texto_j)
            ):
                continue
            if fronteira_visual_coerente(regiao, regioes[j]):
                grafo[i].add(j)
                grafo[j].add(i)
    return grafo


def componentes_conexos(grafo: dict[int, set[int]]) -> list[list[int]]:
    visitados: set[int] = set()
    componentes: list[list[int]] = []
    for inicio in sorted(grafo):
        if inicio in visitados:
            continue
        pilha = [inicio]
        componente: list[int] = []
        while pilha:
            atual = pilha.pop()
            if atual in visitados:
                continue
            visitados.add(atual)
            componente.append(atual)
            pilha.extend(grafo.get(atual, set()) - visitados)
        componentes.append(sorted(componente))
    return componentes


def _proporcao_de_prosa(texto: str) -> float:
    tokens = texto.split()
    if not tokens:
        return 0.0
    prosa = sum(1 for t in tokens if t.isalpha() and len(t) >= 4)
    return prosa / len(tokens)


def fragmento_isolado(texto: str) -> bool:
    limpo = (texto or "").strip()
    if not limpo or len(limpo) > 14:
        return False
    if _proporcao_de_prosa(limpo) > 0:
        return False
    if any(rel in limpo for rel in ("=", "<", ">", "≤", "≥", "≠")):
        return False
    return any(s in limpo for s in _SIMBOLOS_MATEMATICOS)


def incompleto_no_fim(texto: str) -> bool:
    if not texto:
        return False
    if any(texto.rstrip().endswith(op) for op in _OPERADORES_PENDENTES):
        return True
    if texto.rstrip().endswith(("√", "\\sqrt")):
        return True
    return texto.count("(") > texto.count(")")


def incompleto_no_inicio(texto: str) -> bool:
    if not texto:
        return False
    if any(texto.lstrip().startswith(f) for f in _FECHAMENTOS):
        return True
    return texto.count(")") > texto.count("(")


def expressao_fechada(texto: str) -> bool:
    return not incompleto_no_fim(texto) and not incompleto_no_inicio(texto)


def agrupar_blocos_matematicos(regioes: list) -> list[GrupoMatematico]:
    if not regioes:
        return []

    grupos: list[GrupoMatematico] = []
    consumidos: set[int] = set()

    for i, regiao in enumerate(regioes):
        if i in consumidos:
            continue
        texto = _texto(regiao)
        if not texto:
            continue
        if not sinais_de_formula(texto) and not fragmento_isolado(texto):
            continue

        indices = [i]
        acumulado = texto

        j = i + 1
        while j < len(regioes):
            proximo = _texto(regioes[j])
            if not proximo:
                j += 1
                continue
            aberto = not expressao_fechada(acumulado)
            complementa = aberto and (
                incompleto_no_fim(acumulado) or incompleto_no_inicio(proximo)
            )
            if not (complementa or fragmento_isolado(proximo)):
                break
            if _proporcao_de_prosa(proximo) >= 0.4:
                break
            coerente = fronteira_visual_coerente(
                regioes[indices[-1]], regioes[j]
            ) or (
                (fragmento_isolado(proximo) or fragmento_isolado(acumulado))
                and _adjacente_horizontal(
                    _bbox(regioes[indices[-1]]), _bbox(regioes[j])
                )
            )
            if not coerente:
                break
            indices.append(j)
            acumulado = f"{acumulado} {proximo}".strip()
            j += 1

        if len(indices) > 1:
            consumidos.update(indices)

        if not sinais_de_formula(acumulado):
            continue

        caixas = [_bbox(regioes[k]) for k in indices]
        grupos.append(GrupoMatematico(
            indices=indices,
            texto=acumulado,
            bbox=(
                min(c[0] for c in caixas), min(c[1] for c in caixas),
                max(c[2] for c in caixas), max(c[3] for c in caixas),
            ),
            sinais=sinais_de_formula(acumulado),
        ))
    return grupos


def montar_evidencia_do_grupo(grupo: GrupoMatematico, regioes: list):
    try:
        from pipeline.matematica.evidencia_matematica import SourceEvidence
    except Exception:
        return None

    fragmentos = [
        _texto(regioes[i]) for i in grupo.indices if _texto(regioes[i])
    ]
    try:
        return SourceEvidence(
            raw_text=grupo.texto,
            lines=fragmentos,
            extraction_engine="agrupador_matematico",
        )
    except Exception:
        return None


def fundir_fragmentos_em_regioes(regioes: list, page_num: int) -> list:
    regioes = fundir_bandas_de_display(regioes, page_num)
    grupos = [g for g in agrupar_blocos_matematicos(regioes) if g.fragmentado]
    if not grupos:
        return list(regioes)

    consumidos: set[int] = set()
    for grupo in grupos:
        consumidos.update(grupo.indices)

    try:
        from core.extrator_de_regioes import Region
    except Exception:
        return list(regioes)

    novas = [r for i, r in enumerate(regioes) if i not in consumidos]
    for grupo in grupos:
        novas.append(Region(
            bbox=grupo.bbox,
            type="formula",
            text=grupo.texto,
            image_bytes=None,
            confidence=0.7,
            page_num=page_num,
            metadata={
                "agrupado": True,
                "fragmentos": len(grupo.indices),
                "sinais": list(grupo.sinais),
                "textos_originais": [
                    str(getattr(regioes[i], "text", "") or "")
                    for i in grupo.indices
                ],
            },
        ))
    novas.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
    return novas


VAO_VERTICAL_DA_BANDA = 30.0

LACUNA_HORIZONTAL_MAXIMA_NA_LINHA = 60.0

_PADRAO_FRAGMENTO_NUMERICO = None


def _membro_de_banda(texto: str) -> bool:
    global _PADRAO_FRAGMENTO_NUMERICO
    import re as _re

    if _PADRAO_FRAGMENTO_NUMERICO is None:
        _PADRAO_FRAGMENTO_NUMERICO = _re.compile(
            r"^[\d\s\.,;:·×+\-−±*/()a-zA-Z√∆α-ω²³]{1,12}$"
        )

    limpo = (texto or "").strip()
    if not limpo:
        return False
    if _proporcao_de_prosa(limpo) > 0:
        return False
    if sinais_de_formula(limpo) or fragmento_isolado(limpo):
        return True
    if _PADRAO_FRAGMENTO_NUMERICO.fullmatch(limpo):
        tem_ancora = any(c.isdigit() for c in limpo) or any(
            s in limpo for s in _SIMBOLOS_MATEMATICOS
        ) or len(limpo.replace(" ", "").replace(".", "")) <= 1
        return tem_ancora
    return False


def _vao_vertical(a, b) -> float:
    return max(0.0, max(b[1] - a[3], a[1] - b[3]))


def _lacuna_horizontal(a, b) -> float:
    return max(0.0, max(b[0] - a[2], a[0] - b[2]))


def _pecas_conectadas(a, b) -> bool:
    return (
        _vao_vertical(a, b) <= VAO_VERTICAL_DA_BANDA
        and _lacuna_horizontal(a, b) <= LACUNA_HORIZONTAL_MAXIMA_NA_LINHA
    )


def _componentes_conectados(banda: list[int], regioes: list) -> list[list[int]]:
    if len(banda) <= 1:
        return [banda]

    restantes = list(banda)
    componentes: list[list[int]] = []
    while restantes:
        semente = restantes.pop(0)
        componente = [semente]
        mudou = True
        while mudou:
            mudou = False
            for candidato in list(restantes):
                if any(
                    _pecas_conectadas(
                        _bbox(regioes[candidato]), _bbox(regioes[membro])
                    )
                    for membro in componente
                ):
                    restantes.remove(candidato)
                    componente.append(candidato)
                    mudou = True
        componentes.append(sorted(componente))
    return componentes


def fundir_bandas_de_display(regioes: list, page_num: int) -> list:
    if not regioes:
        return list(regioes)

    try:
        from core.extrator_de_regioes import Region
    except Exception:
        return list(regioes)

    ordenadas = sorted(
        range(len(regioes)),
        key=lambda i: (_bbox(regioes[i])[1], _bbox(regioes[i])[0]),
    )

    bandas_brutas: list[list[int]] = []
    atual: list[int] = []
    for indice in ordenadas:
        texto = _texto(regioes[indice])
        if _membro_de_banda(texto):
            if atual and _vao_vertical(
                _bbox(regioes[atual[-1]]), _bbox(regioes[indice])
            ) > VAO_VERTICAL_DA_BANDA:
                bandas_brutas.append(atual)
                atual = []
            atual.append(indice)
        else:
            if atual:
                bandas_brutas.append(atual)
                atual = []
    if atual:
        bandas_brutas.append(atual)

    bandas: list[list[int]] = []
    for banda in bandas_brutas:
        bandas.extend(_componentes_conectados(banda, regioes))

    consumidos: set[int] = set()
    novas_regioes: list = []
    for banda in bandas:
        if len(banda) < 2:
            continue
        textos = [_texto(regioes[i]) for i in banda]
        combinado = " ".join(t for t in textos if t).strip()
        if not any(s in combinado for s in ("=", "√", "±")):
            continue
        def _autossuficiente(t: str) -> bool:
            t = t.strip()
            if not (expressao_fechada(t) and "=" in t):
                return False
            return bool(t) and not t[0].isdigit()

        if all(_autossuficiente(t) for t in textos if t.strip()):
            continue
        caixas = [_bbox(regioes[i]) for i in banda]
        consumidos.update(banda)
        novas_regioes.append(Region(
            bbox=(
                min(c[0] for c in caixas), min(c[1] for c in caixas),
                max(c[2] for c in caixas), max(c[3] for c in caixas),
            ),
            type="formula",
            text=combinado,
            image_bytes=None,
            confidence=0.7,
            page_num=page_num,
            metadata={
                "agrupado": True,
                "banda_de_display": True,
                "fragmentos": len(banda),
                "textos_originais": textos,
            },
        ))

    if not consumidos:
        return list(regioes)

    resultado = [r for i, r in enumerate(regioes) if i not in consumidos]
    resultado.extend(novas_regioes)
    resultado.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
    return resultado


_OPERADORES_FINAIS = ("+", "-", "*", "/", "=", "±", "×", "÷", "^", "_",
                      "<", ">", "≥", "≤", "≠", "·", "\\pm", "\\cdot")
_PARES = {"(": ")", "[": "]", "{": "}"}
_PADRAO_CONTINUACAO = re.compile(
    r"^\s*(?:[)\]}]|[+\-*/=±×÷]|\\right|=\s*\d)"
)
_PADRAO_IGUALDADE_SEM_DIREITA = re.compile(r"[=≥≤≠]\s*$")


class RegiaoLike(Protocol):

    bbox: tuple[float, float, float, float]
    type: str
    text: str
    metadata: dict[str, Any]


class PageLayout:

    def __init__(self, largura: float = 595.0, altura: float = 842.0):
        self.largura = largura
        self.altura = altura

    @property
    def tolerancia_vertical(self) -> float:
        return max(4.0, self.altura * 0.006)

    @property
    def tolerancia_entre_linhas(self) -> float:
        return max(14.0, self.altura * 0.022)


def _delimitadores_abertos(texto: str) -> int:
    saldo = 0
    for caractere in texto:
        if caractere in _PARES:
            saldo += 1
        elif caractere in _PARES.values():
            saldo -= 1
    return saldo


def _radical_sem_radicando(texto: str) -> bool:
    limpo = texto.rstrip()
    return limpo.endswith("√") or limpo.endswith("\\sqrt")


def fragmento_incompleto(texto: str) -> list[str]:
    sinais: list[str] = []
    limpo = (texto or "").rstrip()
    if not limpo:
        return sinais
    if _delimitadores_abertos(limpo) > 0:
        sinais.append("delimitador_aberto")
    if limpo.endswith(_OPERADORES_FINAIS):
        sinais.append("termina_em_operador")
    if _PADRAO_IGUALDADE_SEM_DIREITA.search(limpo):
        sinais.append("igualdade_sem_lado_direito")
    if _radical_sem_radicando(limpo):
        sinais.append("radical_sem_radicando")
    return sinais


def inicia_como_continuacao(texto: str) -> bool:
    return bool(_PADRAO_CONTINUACAO.match(texto or ""))


def _mesma_linha_visual(a: RegiaoLike, b: RegiaoLike, layout: PageLayout) -> bool:
    try:
        topo = max(a.bbox[1], b.bbox[1])
        base = min(a.bbox[3], b.bbox[3])
        sobreposicao = base - topo
        altura_menor = min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1])
        if altura_menor <= 0:
            return False
        return sobreposicao > altura_menor * 0.5
    except Exception:
        return False


def _linhas_consecutivas(a: RegiaoLike, b: RegiaoLike, layout: PageLayout) -> bool:
    try:
        return 0 <= (b.bbox[1] - a.bbox[3]) <= layout.tolerancia_entre_linhas
    except Exception:
        return False


def _fontes_compativeis(a: RegiaoLike, b: RegiaoLike) -> bool:
    try:
        fa = float((a.metadata or {}).get("avg_font_size") or 0)
        fb = float((b.metadata or {}).get("avg_font_size") or 0)
        if not fa or not fb:
            return True
        return abs(fa - fb) <= max(1.0, 0.15 * max(fa, fb))
    except Exception:
        return True


def _adjacentes(a: RegiaoLike, b: RegiaoLike, layout: PageLayout) -> list[str]:
    sinais = []
    if _mesma_linha_visual(a, b, layout):
        sinais.append("mesma_linha_visual")
    elif _linhas_consecutivas(a, b, layout):
        sinais.append("linhas_consecutivas")
    if _fontes_compativeis(a, b):
        sinais.append("fonte_compativel")
    return sinais


_TIPOS_AGREGAVEIS = {"formula", "text", "text_clean", "text_scanned", "unknown"}


def reunir_fragmentos_matematicos(
    regioes: list[Any],
    pagina: PageLayout | None = None,
) -> list[Any]:
    if not regioes or len(regioes) < 2:
        return list(regioes or [])

    layout = pagina or PageLayout()
    try:
        resultado: list[Any] = []
        indice = 0
        while indice < len(regioes):
            atual = regioes[indice]
            if getattr(atual, "type", "") not in _TIPOS_AGREGAVEIS:
                resultado.append(atual)
                indice += 1
                continue

            partes = [atual]
            sinais_totais: list[str] = []
            proximo_indice = indice + 1

            while proximo_indice < len(regioes):
                acumulado = " ".join(
                    (getattr(p, "text", "") or "") for p in partes
                ).strip()
                sinais_incompleto = fragmento_incompleto(acumulado)
                candidato = regioes[proximo_indice]

                if getattr(candidato, "type", "") not in _TIPOS_AGREGAVEIS:
                    break
                texto_candidato = getattr(candidato, "text", "") or ""
                continua = inicia_como_continuacao(texto_candidato)

                if not sinais_incompleto and not continua:
                    break
                sinais_geo = _adjacentes(partes[-1], candidato, layout)
                if not any(
                    s in ("mesma_linha_visual", "linhas_consecutivas")
                    for s in sinais_geo
                ):
                    break
                if "fonte_compativel" not in sinais_geo:
                    break

                partes.append(candidato)
                sinais_totais.extend(sinais_incompleto + sinais_geo)
                if continua:
                    sinais_totais.append("inicia_como_continuacao")
                proximo_indice += 1

                novo_acumulado = " ".join(
                    (getattr(p, "text", "") or "") for p in partes
                ).strip()
                if not fragmento_incompleto(novo_acumulado):
                    break

            if len(partes) == 1:
                resultado.append(atual)
                indice += 1
                continue

            resultado.append(_unir(partes, sinais_totais))
            indice = proximo_indice
        return resultado
    except Exception:
        return list(regioes)


def _unir(partes: list[Any], sinais: list[str]) -> Any:
    from copy import copy

    base = copy(partes[0])
    textos = [(getattr(p, "text", "") or "").strip() for p in partes]
    base.text = " ".join(t for t in textos if t)

    caixas = [getattr(p, "bbox", None) for p in partes if getattr(p, "bbox", None)]
    if caixas:
        base.bbox = (
            min(c[0] for c in caixas), min(c[1] for c in caixas),
            max(c[2] for c in caixas), max(c[3] for c in caixas),
        )

    metadados = dict(getattr(base, "metadata", {}) or {})
    metadados["fragmentos_unidos"] = textos
    metadados["sinais_de_juncao"] = sorted(set(sinais))
    base.metadata = metadados
    return base
