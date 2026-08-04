"""Porta unica de geracao de arquivos."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from core.services.identidade_de_artefato import (
    construir_metadados,
    nome_de_saida,
)
from core.utils.logger import logger

_FORMATOS = (
    ("txt", "renderers.renderizador_txt", "gerar_txt"),
    ("html", "renderers.renderizador_html", "gerar_html"),
    ("docx", "renderers.renderizador_docx", "gerar_docx"),
    ("pdf", "renderers.renderizador_pdf", "gerar_pdf"),
)

FORMATOS_NAO_ACESSIVEIS = ("pdf",)
SUFIXO_VISUAL = "_visual"


def diretorio_da_tarefa(base: Path, task_id: str) -> Path:
    destino = Path(base) / "output" / str(task_id)
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def gerar_artefatos(
    documento: dict[str, Any],
    destino: Path,
    nome_fonte: str,
    sufixo: str = "_acessivel",
    caminho_fonte: Path | None = None,
    status_publicacao: str = "",
    formatos: tuple[str, ...] | None = None,
) -> dict[str, str]:
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    gerados: dict[str, str] = {}

    metadados = construir_metadados(
        Path(caminho_fonte) if caminho_fonte else Path(nome_fonte),
        decisao_status=status_publicacao,
    )
    documento.setdefault("metadata", {})
    documento["metadata"]["artifact"] = metadados

    escolhidos = [f for f in _FORMATOS if not formatos or f[0] in formatos]

    for extensao, modulo, funcao in escolhidos:
        sufixo_do_formato = (
            SUFIXO_VISUAL
            if extensao in FORMATOS_NAO_ACESSIVEIS and sufixo == "_acessivel"
            else sufixo
        )
        alvo = destino / nome_de_saida(nome_fonte, sufixo_do_formato, extensao)
        try:
            renderer = getattr(importlib.import_module(modulo), funcao)
            caminho = renderer(documento, alvo)
            gerados[extensao] = str(caminho)
        except Exception as erro:
            logger.warning(
                "Formato {} nao gerado ({}: {})",
                extensao, type(erro).__name__, erro,
            )

    if gerados:
        documento["outputs"] = dict(documento.get("outputs") or {}, **gerados)
        if "pdf" in gerados:
            documento.setdefault("metadata", {})["pdf_disclaimer"] = (
                "PDF visual, nao validado como PDF/UA. Os formatos "
                "acessiveis deste pacote sao o HTML e o TXT."
            )
        logger.info(
            "Artefatos gerados em {}: {}", destino, ", ".join(sorted(gerados))
        )
    return gerados


def gerar_artefatos_finais(
    documento: dict[str, Any],
    destino: Path,
    nome_fonte: str,
    caminho_fonte: Path | None = None,
) -> dict[str, str]:
    return gerar_artefatos(
        documento, destino, nome_fonte, sufixo="_acessivel",
        caminho_fonte=caminho_fonte, status_publicacao="final",
    )


def gerar_pacote_de_revisao(
    documento: dict[str, Any],
    destino: Path,
    nome_fonte: str,
    decisao: Any = None,
    caminho_fonte: Path | None = None,
) -> dict[str, str]:
    if decisao is not None:
        documento["publicationDecision"] = (
            decisao.to_dict() if hasattr(decisao, "to_dict") else decisao
        )

    gerados = gerar_artefatos(
        documento, destino, nome_fonte,
        sufixo="_rascunho_nao_aprovado",
        caminho_fonte=caminho_fonte, status_publicacao="draft",
    )

    try:
        relatorio = _escrever_relatorio_de_pendencias(
            documento, Path(destino), nome_fonte, decisao
        )
        if relatorio:
            gerados["pendencias"] = str(relatorio)
            documento["outputs"] = dict(
                documento.get("outputs") or {}, pendencias=str(relatorio)
            )
    except Exception as erro:
        logger.warning("Relatorio de pendencias nao gerado ({})", erro)

    return gerados


def _escrever_relatorio_de_pendencias(
    documento: dict[str, Any],
    destino: Path,
    nome_fonte: str,
    decisao: Any,
) -> Path | None:
    if decisao is None:
        return None
    dados = decisao.to_dict() if hasattr(decisao, "to_dict") else dict(decisao)

    linhas = [
        "PENDENCIAS DE PUBLICACAO",
        "=" * 60,
        "",
        f"Documento: {nome_fonte}",
        f"Status: {dados.get('status', '?')}",
        f"Rotulo: {dados.get('rotulo', '')}",
        "",
        "Este material NAO foi aprovado como versao acessivel final.",
        "Ele foi gerado apenas para revisao humana.",
        "",
    ]

    bloqueadores = dados.get("bloqueadores") or []
    if bloqueadores:
        linhas += ["BLOQUEADORES", "-" * 60]
        linhas += [f"  - {b}" for b in bloqueadores] + [""]

    pendencias = dados.get("pendencias") or []
    if pendencias:
        linhas += [f"EXPRESSOES AGUARDANDO REVISAO ({len(pendencias)})",
                   "-" * 60]
        for i, pendencia in enumerate(pendencias, 1):
            linhas.append(f"  {i}. {pendencia.get('source_text', '')[:120]}")
            linhas.append(
                f"     status={pendencia.get('review_status', '?')} "
                f"codigos={', '.join(pendencia.get('codigos') or []) or '-'}"
            )
            for motivo in (pendencia.get("motivos") or [])[:3]:
                linhas.append(f"     motivo: {motivo}")
            linhas.append("")

    contagem = dados.get("contagem") or {}
    if contagem:
        linhas += ["CONTAGEM", "-" * 60]
        linhas += [f"  {k}: {v}" for k, v in sorted(contagem.items())]

    caminho = destino / nome_de_saida(
        nome_fonte, "_pendencias", "txt"
    )
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho


def empacotar_outputs(
    outputs: dict[str, str], destino: Path, nome_zip: str
) -> Path | None:
    import zipfile

    caminhos = [Path(p) for p in (outputs or {}).values() if p]
    existentes = [p for p in caminhos if p.exists()]
    if not existentes:
        return None

    zip_path = Path(destino) / nome_zip
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for caminho in existentes:
            z.write(caminho, arcname=caminho.name)
    return zip_path
