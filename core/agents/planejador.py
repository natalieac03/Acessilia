"""Faz a primeira leitura da pagina e classifica as regioes.

Antes de processar qualquer coisa, monta um plano do que existe na
pagina: quantas regioes de cada tipo, quais precisam de visao
computacional, qual a ordem de leitura.

A classificacao e deterministica por padrao. O refinamento por IA
existe mas fica desligado — a heuristica ja acerta os casos comuns, e
uma chamada de modelo por pagina custaria tempo sem ganho claro.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from core.utils.logger import logger

_DISTANCIA_VIZINHA = 90.0

_SOBREPOSICAO_MINIMA = 0.25

_MAX_CARACTERES_LEGENDA = 220

_PREFIXOS_DE_LEGENDA = (
    "figura", "fig.", "grafico", "gráfico", "tabela", "quadro",
    "imagem", "ilustracao", "ilustração", "fonte:", "mapa",
)


@dataclass
class ItemDoPlano:

    indice: int
    tipo: str
    papel: str = "conteudo"
    precisa_visao: bool = False
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    resumo: str = ""
    vizinhos: list[int] = field(default_factory=list)
    relacionado_a: int | None = None
    avisos: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "indice": self.indice, "tipo": self.tipo, "papel": self.papel,
            "precisa_visao": self.precisa_visao, "bbox": list(self.bbox),
            "resumo": self.resumo, "vizinhos": list(self.vizinhos),
            "relacionado_a": self.relacionado_a, "avisos": list(self.avisos),
        }


@dataclass
class PlanoDaPagina:

    pagina: int
    itens: list[ItemDoPlano] = field(default_factory=list)
    inventario: dict[str, int] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    sugestoes_da_ia: list[dict] = field(default_factory=list)

    def item(self, indice: int) -> ItemDoPlano | None:
        for item in self.itens:
            if item.indice == indice:
                return item
        return None

    def textos_vizinhos(self, indice: int, regioes: list) -> list[str]:
        item = self.item(indice)
        if item is None:
            return []
        textos: list[str] = []
        for vizinho in item.vizinhos:
            if 0 <= vizinho < len(regioes):
                try:
                    texto = str(
                        getattr(regioes[vizinho], "text", "") or ""
                    ).strip()
                except Exception:
                    continue
                if texto:
                    textos.append(texto)
        return textos

    @property
    def resumo_legivel(self) -> str:
        if not self.inventario:
            return "pagina vazia"
        partes = [
            f"{quantidade} {nome}" for nome, quantidade
            in sorted(self.inventario.items(), key=lambda kv: -kv[1])
        ]
        return ", ".join(partes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pagina": self.pagina,
            "inventario": dict(self.inventario),
            "itens": [i.to_dict() for i in self.itens],
            "avisos": list(self.avisos),
            "sugestoes_da_ia": list(self.sugestoes_da_ia),
        }


def _distancia_vertical(a, b) -> float:
    caixa_a, caixa_b = a.bbox, b.bbox
    if caixa_b[3] < caixa_a[1]:
        return caixa_a[1] - caixa_b[3]
    if caixa_b[1] > caixa_a[3]:
        return caixa_b[1] - caixa_a[3]
    return 0.0


def _sobreposicao_horizontal(a, b) -> float:
    ax0, _, ax1, _ = a.bbox
    bx0, _, bx1, _ = b.bbox
    largura = min(ax1, bx1) - max(ax0, bx0)
    if largura <= 0:
        return 0.0
    menor = min(ax1 - ax0, bx1 - bx0) or 1.0
    return largura / menor


def _ordem_de_leitura(regioes: list) -> list[int]:
    return sorted(
        range(len(regioes)),
        key=lambda i: (round(regioes[i].bbox[1], 1), regioes[i].bbox[0]),
    )


def _parece_legenda(texto: str) -> bool:
    limpo = (texto or "").strip()
    if not limpo or len(limpo) > _MAX_CARACTERES_LEGENDA:
        return False
    minusculo = limpo.lower()
    return any(minusculo.startswith(p) for p in _PREFIXOS_DE_LEGENDA)


def _parece_titulo(texto: str) -> bool:
    limpo = (texto or "").strip()
    if not limpo or len(limpo) > 90:
        return False
    if limpo.endswith((".", ";", "!", "?")):
        return False
    return limpo == limpo.upper() and any(c.isalpha() for c in limpo)


def planejar_pagina(regioes: list, pagina: int = 0) -> PlanoDaPagina:
    plano = PlanoDaPagina(pagina=pagina)
    if not regioes:
        return plano

    try:
        from core.classificador_de_regioes import (
            classificar_regiao,
            reclassificar_para_formula,
            regiao_precisa_de_visao,
        )
    except Exception as erro:
        logger.warning("Planejador sem classificador ({}); plano vazio", erro)
        return plano

    ordem = _ordem_de_leitura(regioes)
    if ordem != list(range(len(regioes))):
        plano.avisos.append(
            "a ordem do extrator difere da ordem de leitura da pagina"
        )

    for indice, regiao in enumerate(regioes):
        try:
            texto = str(getattr(regiao, "text", "") or "")
        except Exception:
            texto = ""
        try:
            tipo = classificar_regiao(regiao)
            tipo = reclassificar_para_formula(tipo, texto)
            precisa = regiao_precisa_de_visao(tipo)
        except Exception:
            tipo, precisa = "unknown", True

        papel = "conteudo"
        if _parece_legenda(texto):
            papel = "legenda"
        elif _parece_titulo(texto):
            papel = "titulo"

        plano.itens.append(
            ItemDoPlano(
                indice=indice, tipo=tipo, papel=papel,
                precisa_visao=precisa,
                bbox=tuple(getattr(regiao, "bbox", (0, 0, 0, 0))),
                resumo=" ".join(texto.split())[:120],
            )
        )

    for item in plano.itens:
        alvo = regioes[item.indice]
        vizinhos: list[tuple[float, int]] = []
        for outro in plano.itens:
            if outro.indice == item.indice:
                continue
            candidata = regioes[outro.indice]
            distancia = _distancia_vertical(alvo, candidata)
            if distancia > _DISTANCIA_VIZINHA:
                continue
            if _sobreposicao_horizontal(alvo, candidata) < _SOBREPOSICAO_MINIMA:
                continue
            vizinhos.append((distancia, outro.indice))
        vizinhos.sort()
        item.vizinhos = [indice for _, indice in vizinhos[:4]]

    _ligar_legendas(plano, regioes)
    _detectar_formula_partida(plano, regioes)
    _detectar_sequencia_de_formulas(plano)

    for item in plano.itens:
        chave = item.papel if item.papel != "conteudo" else item.tipo
        plano.inventario[chave] = plano.inventario.get(chave, 0) + 1

    return plano


def _ligar_legendas(plano: PlanoDaPagina, regioes: list) -> None:
    alvos = {"embedded_image", "table", "formula"}
    for item in plano.itens:
        if item.papel != "legenda":
            continue
        melhor, menor = None, float("inf")
        for vizinho in item.vizinhos:
            candidato = plano.item(vizinho)
            if candidato is None or candidato.tipo not in alvos:
                continue
            distancia = _distancia_vertical(
                regioes[item.indice], regioes[vizinho]
            )
            if distancia < menor:
                melhor, menor = vizinho, distancia
        if melhor is not None:
            item.relacionado_a = melhor
            alvo = plano.item(melhor)
            if alvo is not None:
                alvo.avisos.append(f"tem legenda na regiao {item.indice}")


def _detectar_formula_partida(plano: PlanoDaPagina, regioes: list) -> None:
    try:
        from pipeline.matematica.fronteira_matematica import validar_fronteira_expressao
    except Exception:
        return

    for item in plano.itens:
        if item.tipo != "formula":
            continue
        try:
            texto = str(getattr(regioes[item.indice], "text", "") or "").strip()
        except Exception:
            continue
        if not texto:
            continue
        try:
            fronteira = validar_fronteira_expressao(texto)
        except Exception:
            continue
        if fronteira.plausivel:
            continue
        item.avisos.append(
            "expressao nao fecha; candidata a continuar na regiao vizinha"
        )
        item.papel = "continuacao" if item.papel == "conteudo" else item.papel
        plano.avisos.append(
            f"formula possivelmente partida na regiao {item.indice}"
        )


def _detectar_sequencia_de_formulas(plano: PlanoDaPagina) -> None:
    consecutivas: list[int] = []
    for item in sorted(plano.itens, key=lambda i: i.bbox[1]):
        if item.tipo == "formula":
            consecutivas.append(item.indice)
            continue
        if len(consecutivas) > 1:
            plano.avisos.append(
                "sequencia de formulas nas regioes "
                + ", ".join(str(i) for i in consecutivas)
                + " (provavel derivacao em passos)"
            )
        consecutivas = []
    if len(consecutivas) > 1:
        plano.avisos.append(
            "sequencia de formulas nas regioes "
            + ", ".join(str(i) for i in consecutivas)
            + " (provavel derivacao em passos)"
        )


_INSTRUCOES_PLANEJADOR = """\
Voce recebe o INVENTARIO estrutural de uma pagina de material didatico:
uma lista de regioes com tipo, posicao e um resumo do texto.

Sua tarefa e apontar RELACOES que a analise geometrica pode ter perdido:
uma legenda que pertence a outra figura, uma formula que continua na
regiao seguinte, um titulo de tabela solto, regioes na ordem errada.

Voce NAO descreve conteudo. Voce NAO explica materia. Voce NAO
reclassifica regiao - apenas aponta relacoes suspeitas.

Responda uma relacao por linha, no formato:
REGIAO <n> -> <papel> (motivo curto)

Se nada parecer fora do lugar, responda exatamente: NADA
"""


def _planejador_ia_ligado() -> bool:
    return os.getenv("USAR_PLANEJADOR_IA", "false").strip().lower() == "true"


def refinar_plano_com_ia(plano: PlanoDaPagina) -> PlanoDaPagina:
    if not _planejador_ia_ligado() or not plano.itens:
        return plano

    inventario = "\n".join(
        f"REGIAO {i.indice}: tipo={i.tipo}, papel={i.papel}, "
        f"topo={i.bbox[1]:.0f}, texto={i.resumo!r}"
        for i in plano.itens
    )
    try:
        from agno.agent import Agent

        from core.agents.conferidor_de_formulas import _construir_modelo_texto

        agente = Agent(
            name="planejador",
            model=_construir_modelo_texto(),
            description="Aponta relacoes estruturais entre regioes da pagina",
            instructions=_INSTRUCOES_PLANEJADOR,
            markdown=False,
        )
        resposta = agente.run(inventario)
        conteudo = (resposta.content or "").strip()
        if not conteudo or conteudo.upper() == "NADA":
            return plano
        for linha in conteudo.splitlines():
            linha = linha.strip()
            if linha.upper().startswith("REGIAO"):
                plano.sugestoes_da_ia.append({"sugestao": linha})
        logger.info(
            "Planejador (IA): {} sugestao(oes) anotada(s)",
            len(plano.sugestoes_da_ia),
        )
    except Exception as erro:
        logger.warning("Planejador (IA) indisponivel ({}); plano mantido", erro)
    return plano


def planejar(regioes: list, pagina: int = 0) -> PlanoDaPagina:
    plano = planejar_pagina(regioes, pagina)
    if plano.itens:
        logger.info("[pag {}] Plano: {}", pagina, plano.resumo_legivel)
        for aviso in plano.avisos:
            logger.info("[pag {}] Plano: {}", pagina, aviso)
    return refinar_plano_com_ia(plano)
