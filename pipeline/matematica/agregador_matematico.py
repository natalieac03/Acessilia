"""Etapa 1 - AGREGACAO e reconstrucao de regioes fragmentadas.

O caso que motiva este modulo: "(x - 2)(x - 3) = 0" saiu como
"(x - 2)(x" - o extrator cortou a expressao no meio. Nenhum parser
matematico consegue consertar isso depois, porque a informacao que falta
esta em OUTRA regiao. A juncao tem que acontecer ANTES da tokenizacao.

Sinais de continuacao, combinando sintaxe e geometria:

  SINTATICOS (o fragmento esta claramente incompleto)
    - parentese, colchete ou radical aberto e nao fechado
    - termina em operador binario (+, -, ×, =, ±, /)
    - igualdade sem lado direito ("x =" ou "x = ")
    - abre com operador/continuacao plausivel (")", "+", "= 0")

  GEOMETRICOS (os fragmentos pertencem ao mesmo objeto visual)
    - mesma linha visual (sobreposicao vertical dos bboxes)
    - proximidade horizontal ou linhas consecutivas proximas
    - mesmo tamanho de fonte dominante

Conservador: sem sinal SINTATICO de incompletude, nao junta. Juntar duas
frases de prosa por proximidade seria pior que o problema original.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

# Operadores que nao podem encerrar uma expressao completa.
_OPERADORES_FINAIS = ("+", "-", "*", "/", "=", "±", "×", "÷", "^", "_",
                      "<", ">", "≥", "≤", "≠", "·", "\\pm", "\\cdot")
# Aberturas que exigem fechamento.
_PARES = {"(": ")", "[": "]", "{": "}"}
# Inicios que sinalizam continuacao do fragmento anterior.
_PADRAO_CONTINUACAO = re.compile(
    r"^\s*(?:[)\]}]|[+\-*/=±×÷]|\\right|=\s*\d)"
)
_PADRAO_IGUALDADE_SEM_DIREITA = re.compile(r"[=≥≤≠]\s*$")


class RegiaoLike(Protocol):
    """O minimo que a agregacao precisa de uma regiao."""

    bbox: tuple[float, float, float, float]
    type: str
    text: str
    metadata: dict[str, Any]


class PageLayout:
    """Dados da pagina usados como referencia de escala."""

    def __init__(self, largura: float = 595.0, altura: float = 842.0):
        self.largura = largura
        self.altura = altura

    @property
    def tolerancia_vertical(self) -> float:
        """Quanto duas regioes podem distar e ainda ser "a mesma linha"."""
        return max(4.0, self.altura * 0.006)

    @property
    def tolerancia_entre_linhas(self) -> float:
        return max(14.0, self.altura * 0.022)


# --------------------------------------------------------------------------- #
# Sinais sintaticos
# --------------------------------------------------------------------------- #
def _delimitadores_abertos(texto: str) -> int:
    """Saldo de delimitadores nao fechados (positivo = falta fechar)."""
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
    """Sinais de que a expressao NAO terminou. Lista vazia = completa."""
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


# --------------------------------------------------------------------------- #
# Sinais geometricos
# --------------------------------------------------------------------------- #
def _mesma_linha_visual(a: RegiaoLike, b: RegiaoLike, layout: PageLayout) -> bool:
    """Os bboxes se sobrepoem verticalmente de forma significativa."""
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
            return True          # sem informacao, nao bloqueia
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


# --------------------------------------------------------------------------- #
# Agregacao
# --------------------------------------------------------------------------- #
_TIPOS_AGREGAVEIS = {"formula", "text", "text_clean", "text_scanned", "unknown"}


def reunir_fragmentos_matematicos(
    regioes: list[Any],
    pagina: PageLayout | None = None,
) -> list[Any]:
    """Une fragmentos quando ha continuidade visual E sintatica.

    Nao modifica as regioes recebidas: devolve uma lista nova, com as
    regioes unidas substituindo os fragmentos. Registra em
    metadata["fragmentos_unidos"] o texto de cada parte original, para
    que a evidencia bruta continue reconstituivel.

    Fail-open: qualquer falha devolve a lista original intacta.
    """
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

                # exige incompletude sintatica OU inicio de continuacao
                if not sinais_incompleto and not continua:
                    break
                sinais_geo = _adjacentes(partes[-1], candidato, layout)
                if not any(
                    s in ("mesma_linha_visual", "linhas_consecutivas")
                    for s in sinais_geo
                ):
                    break
                # Fonte muito diferente = objetos visuais distintos (um
                # titulo grande ao lado de uma formula, por exemplo).
                # Isto BLOQUEIA a juncao, nao e apenas um sinal a favor.
                if "fonte_compativel" not in sinais_geo:
                    break

                partes.append(candidato)
                sinais_totais.extend(sinais_incompleto + sinais_geo)
                if continua:
                    sinais_totais.append("inicia_como_continuacao")
                proximo_indice += 1

                # ja fechou? para de crescer
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
    """Cria uma regiao nova a partir dos fragmentos, preservando as partes."""
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
