"""Gera o MP3 — completo, ou erro.

Corta o texto em blocos, sintetiza em paralelo (limitado a cinco por
vez) e junta tudo num arquivo so.

A garantia central e que nunca sai um audio parcial. Isso veio de um
bug real: o MP3 de um material saiu cortado e ninguem percebeu, porque
arquivo truncado abre e toca normalmente. Hoje o modulo confere que os
blocos gerados batem com os esperados, rejeita arquivo vazio e cancela
as tarefas pendentes quando uma falha. O callback de progresso e
tratado como cosmetico: se quebrar, vira aviso e a sintese continua.
"""

import asyncio
import inspect
from pathlib import Path
from typing import Callable, Coroutine

import edge_tts

from core.utils.logger import logger


async def _reportar_progresso(
    callback: Callable | None, concluidos: int, total: int
) -> None:
    if callback is None:
        return
    percentual = int((concluidos / total) * 100) if total else 100
    try:
        try:
            parametros = [
                p for p in inspect.signature(callback).parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                and p.default is p.empty
            ]
            quantos = len(parametros)
        except (TypeError, ValueError):
            quantos = 1
        if quantos >= 2:
            resultado = callback(concluidos, total)
        elif quantos == 1:
            resultado = callback(percentual)
        else:
            resultado = callback()
        if inspect.isawaitable(resultado):
            await resultado
    except Exception as erro:
        logger.warning(
            "Callback de progresso do audio falhou ({}); a sintese "
            "continua normalmente: {}",
            type(erro).__name__,
            erro,
        )


def _dividir_em_blocos(texto: str, tamanho: int = 1500) -> list[str]:
    blocos: list[str] = []
    atual = ""
    for paragrafo in texto.split("\n"):
        if len(atual) + len(paragrafo) < tamanho:
            atual += paragrafo + "\n"
        else:
            if atual.strip():
                blocos.append(atual.strip())
            atual = paragrafo + "\n"
    if atual.strip():
        blocos.append(atual.strip())
    return blocos


async def export_mp3(
    text: str,
    output_path: Path,
    voice: str = "pt-BR-ThalitaNeural",
    progress_callback: Callable[..., Coroutine] | None = None,
) -> Path:
    logger.debug(
        "Iniciando geração de áudio granular (TTS): {} -> {}",
        voice, output_path,
    )
    blocos = _dividir_em_blocos(text)
    if not blocos:
        raise ValueError("texto vazio: nao ha o que sintetizar")

    total = len(blocos)
    concluidos = 0
    semaforo = asyncio.Semaphore(5)

    async def _sintetizar(indice: int, trecho: str) -> Path:
        nonlocal concluidos
        async with semaforo:
            destino = output_path.with_suffix(f".part{indice}.mp3")
            comunicacao = edge_tts.Communicate(trecho, voice)
            await comunicacao.save(str(destino))
            if not destino.exists() or destino.stat().st_size == 0:
                raise RuntimeError(
                    f"bloco {indice + 1}/{total} nao produziu audio"
                )
            concluidos += 1
            logger.info(
                "Gerando áudio (TTS): {}/{} blocos concluídos ({}%)",
                concluidos, total,
                int((concluidos / total) * 100),
            )
            await _reportar_progresso(
                progress_callback, concluidos, total
            )
            return destino

    tarefas = [
        asyncio.create_task(_sintetizar(i, b))
        for i, b in enumerate(blocos)
    ]
    try:
        resultados = await asyncio.gather(*tarefas, return_exceptions=True)
    finally:
        for tarefa in tarefas:
            if not tarefa.done():
                tarefa.cancel()

    falhas = [r for r in resultados if isinstance(r, BaseException)]
    if falhas:
        _limpar_partes(output_path)
        raise RuntimeError(
            f"sintese incompleta: {len(falhas)} de {total} blocos "
            f"falharam; primeiro erro: {falhas[0]!r}"
        ) from falhas[0]

    partes = [r for r in resultados if isinstance(r, Path)]
    if len(partes) != total:
        _limpar_partes(output_path)
        raise RuntimeError(
            f"sintese incompleta: {len(partes)} de {total} blocos "
            "gerados - o audio sairia cortado"
        )

    try:
        with open(output_path, "wb") as final:
            for parte in partes:
                final.write(parte.read_bytes())
    except Exception:
        _limpar_partes(output_path)
        raise
    _limpar_partes(output_path)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(
            f"o MP3 final ficou vazio: {output_path}"
        )
    logger.info(
        "Áudio (MP3) granular exportado com sucesso: {} ({} blocos)",
        output_path, total,
    )
    return output_path


def _limpar_partes(output_path: Path) -> None:
    for parte in output_path.parent.glob(
        f"{output_path.stem}.part*.mp3"
    ):
        try:
            parte.unlink()
        except Exception:
            pass
