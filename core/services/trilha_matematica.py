"""Secao 13 - OBSERVABILIDADE da camada matematica."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

ETAPAS = ("evidencia", "detector", "fronteira", "tokenizer", "parser",
          "contexto", "speech", "serializacao", "validator", "publicacao")


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class TrilhaDaExpressao:

    region_id: str
    source_text: str
    events: list[dict[str, Any]] = field(default_factory=list)
    review_status: str = "draft"
    criado_em: str = field(default_factory=_agora)

    def registrar(self, stage: str, **dados: Any) -> "TrilhaDaExpressao":
        try:
            evento: dict[str, Any] = {"stage": stage}
            evento.update({k: v for k, v in dados.items() if v is not None})
            self.events.append(evento)
        except Exception:
            pass
        return self

    def evento_de(self, stage: str) -> dict | None:
        for evento in self.events:
            if evento.get("stage") == stage:
                return evento
        return None

    @property
    def etapas_percorridas(self) -> list[str]:
        return [e.get("stage", "") for e in self.events]

    @property
    def etapa_da_perda(self) -> str | None:
        for evento in self.events:
            if evento.get("perdeu"):
                return evento.get("stage")
            if evento.get("issues"):
                return evento.get("stage")
        return None

    def to_dict(self) -> dict:
        return {
            "region_id": self.region_id,
            "source_text": self.source_text,
            "events": self.events,
            "review_status": self.review_status,
            "criado_em": self.criado_em,
        }


_trilhas: dict[str, TrilhaDaExpressao] = {}
_trava = threading.Lock()


def abrir_trilha(region_id: str, source_text: str) -> TrilhaDaExpressao:
    try:
        trilha = TrilhaDaExpressao(region_id=region_id, source_text=source_text)
        with _trava:
            _trilhas[region_id] = trilha
        return trilha
    except Exception:
        return TrilhaDaExpressao(region_id=region_id or "?", source_text="")


def obter_trilha(region_id: str) -> TrilhaDaExpressao | None:
    with _trava:
        return _trilhas.get(region_id)


def listar_trilhas() -> list[TrilhaDaExpressao]:
    with _trava:
        return list(_trilhas.values())


def limpar_trilhas() -> None:
    with _trava:
        _trilhas.clear()


def exportar_trilhas() -> list[dict]:
    return [t.to_dict() for t in listar_trilhas()]


def gravar_trilhas(caminho) -> bool:
    from pathlib import Path

    try:
        destino = Path(caminho)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(exportar_trilhas(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def rastrear_expressao(
    region_id: str,
    source_text: str,
    geometria=None,
    contexto=None,
    modo_fala: str = "estrutural",
) -> TrilhaDaExpressao:
    trilha = abrir_trilha(region_id, source_text)

    try:
        from pipeline.matematica.matematica_inline import detectar_candidatos_matematicos

        candidatos = detectar_candidatos_matematicos(
            source_text, geometria, contexto
        )
        trilha.registrar(
            "detector",
            result="math_candidate" if candidatos else "text",
            candidatos=len(candidatos),
            sinais=sorted({s for c in candidatos for s in c.signals})[:6] or None,
        )
    except Exception as erro:
        trilha.registrar("detector", erro=str(erro))

    try:
        from pipeline.matematica.fronteira_matematica import validar_fronteira_expressao

        fronteira = validar_fronteira_expressao(source_text)
        trilha.registrar(
            "fronteira", plausivel=fronteira.plausivel,
            detalhes=fronteira.detalhes or None,
            perdeu=not fronteira.plausivel or None,
        )
    except Exception as erro:
        trilha.registrar("fronteira", erro=str(erro))

    try:
        from pipeline.matematica.arvore_matematica import tokenizar

        tokens = tokenizar(source_text, geometria)
        trilha.registrar(
            "tokenizer",
            tokens=[t.value for t in tokens],
            kinds=[t.kind for t in tokens],
            por_geometria=sum(1 for t in tokens if t.origem == "geometria") or None,
        )
    except Exception as erro:
        trilha.registrar("tokenizer", erro=str(erro))

    resultado = None
    try:
        from pipeline.matematica.arvore_matematica import construir_ast
        from pipeline.matematica.nos_matematicos import indexar_formula

        resultado = construir_ast(source_text, geometria)
        trilha.registrar(
            "parser",
            ast_hash=indexar_formula(resultado.ast),
            ast_tipo=resultado.ast.tipo,
            completa=resultado.completa,
            descartados=[t.value for t in resultado.nao_consumidos] or None,
            perdeu=bool(resultado.nao_consumidos) or None,
        )
    except Exception as erro:
        trilha.registrar("parser", erro=str(erro))

    if resultado is None:
        trilha.review_status = "needs_review"
        return trilha

    try:
        from core.agents.resolvedor_de_contexto_matematico import avaliar_ambiguidades

        ambiguidades = avaliar_ambiguidades(
            source_text, resultado.ast, geometria, contexto,
            nao_consumidos=resultado.nao_consumidos,
        )
        if ambiguidades:
            trilha.registrar(
                "contexto", acionado=True,
                ambiguidades=[a.tipo for a in ambiguidades],
            )
    except Exception as erro:
        trilha.registrar("contexto", erro=str(erro))

    fala = None
    try:
        from pipeline.matematica.fala_matematica import gerar_fala_matematica

        fala = gerar_fala_matematica(resultado.ast, modo=modo_fala)
        trilha.registrar(
            "speech", text=fala.texto, modo=fala.modo,
            avisos=fala.avisos or None, perdeu=fala.tem_lacuna or None,
        )
    except Exception as erro:
        trilha.registrar("speech", erro=str(erro))

    latex = mathml = ""
    try:
        from pipeline.matematica.serializacao_matematica import gerar_latex, gerar_mathml, gerar_omml

        latex = gerar_latex(resultado.ast)
        mathml = gerar_mathml(resultado.ast, latex)
        omml = gerar_omml(resultado.ast)
        trilha.registrar(
            "serializacao", latex=latex,
            mathml_nos=sorted({
                marca for marca in ("mfrac", "msup", "msub", "msqrt", "mrow")
                if f"<{marca}>" in mathml
            }) or None,
            omml_ok=bool(omml) or None,
        )
    except Exception as erro:
        trilha.registrar("serializacao", erro=str(erro))

    try:
        from pipeline.matematica.cobertura_matematica import (
            comparar_latex_e_mathml,
            validar_cobertura_simbolica,
        )

        relatorio = validar_cobertura_simbolica(
            evidence=source_text, ast=resultado.ast, speech=fala,
            latex=latex, mathml=mathml,
            nao_consumidos=resultado.nao_consumidos,
        )
        issues = [i.to_dict() for i in relatorio.issues]
        issues += [i.to_dict() for i in comparar_latex_e_mathml(latex, mathml)]
        trilha.registrar("validator", issues=issues or None,
                         checks=sorted({
                             i["check"] for i in issues if i.get("check")
                         }) or None)
        bloqueia = any(i.get("severity") == "BLOCKER" for i in issues)
    except Exception as erro:
        trilha.registrar("validator", erro=str(erro))
        bloqueia = True

    trilha.review_status = "needs_review" if (
        bloqueia or not resultado.completa
    ) else "reviewed"
    trilha.registrar(
        "publicacao", review_status=trilha.review_status,
        publicavel=not bloqueia,
    )
    return trilha


def calcular_metricas(trilhas: list[TrilhaDaExpressao] | None = None) -> dict:
    lista = trilhas if trilhas is not None else listar_trilhas()
    total = len(lista)

    def _taxa(quantos: int, base: int | None = None) -> dict:
        divisor = base if base is not None else total
        fracao = (quantos / divisor) if divisor else 0.0
        return {"quantidade": quantos, "base": divisor,
                "taxa": round(fracao, 4), "percentual": round(fracao * 100, 1)}

    candidatos = 0
    parse_ok = 0
    contexto_acionado = 0
    perda_de_simbolo = 0
    fronteira_reparada = 0
    falha_de_fala = 0
    regressao_de_renderer = 0
    revisao_humana = 0
    hashes: dict[str, set[str]] = {}

    for trilha in lista:
        detector = trilha.evento_de("detector") or {}
        candidatos += int(detector.get("candidatos") or 0)

        parser = trilha.evento_de("parser") or {}
        if parser.get("completa"):
            parse_ok += 1

        if (trilha.evento_de("contexto") or {}).get("acionado"):
            contexto_acionado += 1

        fronteira = trilha.evento_de("fronteira") or {}
        if fronteira.get("plausivel") is False:
            fronteira_reparada += 1

        checks = set((trilha.evento_de("validator") or {}).get("checks") or [])
        if checks & {"validar_menos", "validar_expoentes",
                     "validar_subscritos", "validar_radicandos",
                     "validar_multiplicacao_implicita",
                     "validar_cadeia_de_igualdade",
                     "validar_termos_preservados"}:
            perda_de_simbolo += 1
        if checks & {"fala_com_lacuna", "validar_cobertura_da_fala"}:
            falha_de_fala += 1
        if checks & {"validar_derivacao_unica", "validar_tabela",
                     "validar_serializacoes"}:
            regressao_de_renderer += 1

        if trilha.review_status in ("draft", "needs_review"):
            revisao_humana += 1

        chave = parser.get("ast_hash")
        if chave:
            fala = (trilha.evento_de("speech") or {}).get("text", "")
            hashes.setdefault(chave, set()).add(fala)

    conflitos = sum(1 for falas in hashes.values() if len(falas) > 1)

    return {
        "expressoes_rastreadas": total,
        "math_candidates_total": candidatos,
        "math_parse_success_rate": _taxa(parse_ok),
        "context_resolver_call_rate": _taxa(contexto_acionado),
        "symbol_loss_rate": _taxa(perda_de_simbolo),
        "boundary_repair_rate": _taxa(fronteira_reparada),
        "speech_validation_failure_rate": _taxa(falha_de_fala),
        "renderer_regression_rate": _taxa(regressao_de_renderer),
        "human_review_rate": _taxa(revisao_humana),
        "formula_consistency_conflicts": conflitos,
    }


def resumo_para_depuracao(region_id: str) -> dict | None:
    trilha = obter_trilha(region_id)
    if trilha is None:
        return None

    evidencia = trilha.evento_de("evidencia") or {}
    detector = trilha.evento_de("detector") or {}
    tokenizer = trilha.evento_de("tokenizer") or {}
    parser = trilha.evento_de("parser") or {}
    speech = trilha.evento_de("speech") or {}
    serializacao = trilha.evento_de("serializacao") or {}
    validator = trilha.evento_de("validator") or {}

    return {
        "region_id": trilha.region_id,
        "source_text": trilha.source_text,
        "recorte": evidencia.get("image_crop_path"),
        "linhas_brutas": evidencia.get("raw_lines"),
        "spans_detectados": detector.get("candidatos"),
        "sinais": detector.get("sinais"),
        "tokens": list(zip(tokenizer.get("kinds") or [],
                           tokenizer.get("tokens") or [])),
        "ast_hash": parser.get("ast_hash"),
        "ast_completa": parser.get("completa"),
        "descartados": parser.get("descartados"),
        "latex": serializacao.get("latex"),
        "mathml_nos": serializacao.get("mathml_nos"),
        "fala": speech.get("text"),
        "issues": validator.get("issues") or [],
        "review_status": trilha.review_status,
        "etapa_da_perda": trilha.etapa_da_perda,
        "etapas": trilha.etapas_percorridas,
    }
