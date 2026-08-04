"""Resolve as fronteiras de uma expressao incompleta."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PARES = {"(": ")", "[": "]", "{": "}"}
_OPERADORES_BINARIOS = ("+", "-", "*", "/", "·", "×", "÷", "±")
_RELACOES = ("=", "≥", "≤", "≠", "<", ">")
_MAX_VIZINHOS = 3


@dataclass
class BoundaryReport:

    parenteses_balanceados: bool = True
    colchetes_balanceados: bool = True
    radical_tem_operando: bool = True
    operadores_tem_operandos: bool = True
    igualdade_completa: bool = True
    termina_em_fragmento_invalido: bool = False
    detalhes: list[str] = field(default_factory=list)

    @property
    def plausivel(self) -> bool:
        return (
            self.parenteses_balanceados
            and self.colchetes_balanceados
            and self.radical_tem_operando
            and self.operadores_tem_operandos
            and self.igualdade_completa
            and not self.termina_em_fragmento_invalido
        )

    def to_dict(self) -> dict:
        return {**self.__dict__, "plausivel": self.plausivel}


def _saldo(texto: str, abre: str, fecha: str) -> int:
    return texto.count(abre) - texto.count(fecha)


def validar_fronteira_expressao(texto: str) -> BoundaryReport:
    relatorio = BoundaryReport()
    limpo = (texto or "").strip()
    if not limpo:
        relatorio.termina_em_fragmento_invalido = True
        relatorio.detalhes.append("expressao vazia")
        return relatorio

    if _saldo(limpo, "(", ")") != 0:
        relatorio.parenteses_balanceados = False
        relatorio.detalhes.append(
            f"parenteses desbalanceados (saldo {_saldo(limpo, '(', ')')})"
        )
    if _saldo(limpo, "[", "]") != 0 or _saldo(limpo, "{", "}") != 0:
        relatorio.colchetes_balanceados = False
        relatorio.detalhes.append("colchetes ou chaves desbalanceados")

    for ocorrencia in re.finditer(r"√|\\sqrt", limpo):
        resto = limpo[ocorrencia.end():].strip()
        if not resto or resto[0] in ")]}" or resto.startswith(_RELACOES):
            relatorio.radical_tem_operando = False
            relatorio.detalhes.append("radical sem radicando")
            break

    if limpo.endswith(_OPERADORES_BINARIOS):
        relatorio.operadores_tem_operandos = False
        relatorio.detalhes.append("termina em operador binario")
    if limpo.endswith(_RELACOES):
        relatorio.igualdade_completa = False
        relatorio.detalhes.append("relacao sem lado direito")

    for relacao in _RELACOES:
        if relacao in limpo:
            partes = [p.strip() for p in limpo.split(relacao)]
            if any(not p for p in partes):
                relatorio.igualdade_completa = False
                relatorio.detalhes.append(
                    f"relacao '{relacao}' com um dos lados vazio"
                )
            break

    if limpo.endswith(("\\", "^", "_")):
        relatorio.termina_em_fragmento_invalido = True
        relatorio.detalhes.append("termina em marcador incompleto")

    return relatorio


def expandir_fronteira(candidato, vizinhos: list, max_vizinhos: int = _MAX_VIZINHOS):
    relatorio = validar_fronteira_expressao(candidato.source_text)
    if relatorio.plausivel:
        return candidato

    expandido = candidato.model_copy(deep=True)
    sinais = list(expandido.signals)
    usados = 0

    for vizinho in vizinhos[:max_vizinhos]:
        texto_vizinho = (
            vizinho if isinstance(vizinho, str)
            else (getattr(vizinho, "text", "") or "")
        ).strip()
        if not texto_vizinho:
            continue

        expandido.source_text = f"{expandido.source_text} {texto_vizinho}".strip()
        expandido.end = expandido.start + len(expandido.source_text)
        usados += 1
        if validar_fronteira_expressao(expandido.source_text).plausivel:
            sinais.append(f"fronteira:expandida_com_{usados}_vizinho(s)")
            expandido.signals = sorted(set(sinais))
            return expandido

    final = validar_fronteira_expressao(expandido.source_text)
    if final.plausivel:
        sinais.append(f"fronteira:expandida_com_{usados}_vizinho(s)")
    else:
        sinais.append("fronteira:incompleta_apos_expansao")
        sinais.extend(f"fronteira:{d}" for d in final.detalhes[:3])
    expandido.signals = sorted(set(sinais))
    return expandido


class NeedsReview(Exception):

    def __init__(self, mensagem: str, texto_parcial: str = "",
                 detalhes: list[str] | None = None):
        super().__init__(mensagem)
        self.texto_parcial = texto_parcial
        self.detalhes = detalhes or []


def expressao_completa(texto: str) -> bool:
    return validar_fronteira_expressao(texto).plausivel


def fragmento_e_continuacao_plausivel(texto: str, fragmento) -> bool:
    from pipeline.matematica.agrupador_matematico import (
        fragmento_incompleto,
        inicia_como_continuacao,
    )

    conteudo = (
        fragmento if isinstance(fragmento, str)
        else (getattr(fragmento, "text", "") or "")
    )
    if not conteudo.strip():
        return False
    return bool(fragmento_incompleto(texto)) or inicia_como_continuacao(conteudo)


def completar_expressao(
    candidato, proximos_fragmentos: list, max_fragmentos: int = _MAX_VIZINHOS,
) -> str:
    texto = (
        candidato if isinstance(candidato, str)
        else (getattr(candidato, "source_text", None)
              or getattr(candidato, "text", "") or "")
    )
    usados = 0
    for fragmento in proximos_fragmentos[:max_fragmentos]:
        if expressao_completa(texto):
            break
        if not fragmento_e_continuacao_plausivel(texto, fragmento):
            continue
        conteudo = (
            fragmento if isinstance(fragmento, str)
            else (getattr(fragmento, "text", "") or "")
        )
        texto = f"{texto} {conteudo.strip()}".strip()
        usados += 1

    if not expressao_completa(texto):
        relatorio = validar_fronteira_expressao(texto)
        raise NeedsReview(
            "Fronteira matematica incompleta apos reunir "
            f"{usados} fragmento(s)",
            texto_parcial=texto,
            detalhes=relatorio.detalhes,
        )
    return texto
