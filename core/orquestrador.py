"""Coordena todo o processamento, do PDF aos arquivos finais.

Ponto de entrada do pipeline. Recebe o arquivo, confere o cache,
converte formatos de escritorio para PDF quando necessario, aciona o
agente que processa as paginas, monta o documento canonico e dispara
os renderizadores.

Segue o padrao fail-open: nenhum componente opcional pode impedir a
entrega do material. O que bloqueia a publicacao e erro de CONTEUDO
detectado pelos validadores, nunca falha de infraestrutura.
"""

import asyncio
import datetime
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from core.agents.agente_unico import AgenteUnico
from core.agents.gestor_de_estado import TaskCancelledError, gestor_de_estado
from core.services.cache import obter_do_cache, gravar_no_cache
from core.services.servico_de_historico import (
    finalizar_conversao,
    limpar_orfas,
    registrar_conversao,
)
from config.settings import settings
from core.utils.logger import logger
from core.utils.processador_de_texto import unir_paragrafos_quebrados
from pipeline.construtor_canonico import construir_documento_canonico
from pipeline.gestor_de_verbosidade import verbosity_for_mode

agente = AgenteUnico()


def _cache_version() -> str:
    return f"{settings.ai_client}-v1"


def _limpar_tarefas_orfas():
    limpar_orfas()


_limpar_tarefas_orfas()


def _salvar_json_canonico(
    canonical_document: dict, source_name: str
) -> Path | None:
    try:
        base = Path("output") / "canonical"
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out_dir = base / ts
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(source_name).stem
        path = out_dir / f"{stem}.json"
        canonical_document["canonicalPath"] = str(path.resolve())
        path.write_text(
            json.dumps(canonical_document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
    except Exception as e:
        logger.warning("Nao foi possivel salvar JSON canonico: {}", e)
        return None


def _gerar_formatos_acessiveis(
    canonical_document: dict,
    file_path: Path,
    task_id: str = "",
) -> dict[str, str]:
    from core.services.coordenador_de_exportacao import (
        diretorio_da_tarefa,
        gerar_artefatos_finais,
    )

    destino = diretorio_da_tarefa(
        settings.temp_dir, task_id or file_path.stem
    )

    gerados = gerar_artefatos_finais(
        canonical_document, destino, file_path.name,
        caminho_fonte=file_path,
    )
    logger.info("{} artefato(s) gerados", len(gerados))

    return gerados


async def process(
    file_path: Path,
    status_callback: Callable[[str], Coroutine] | None = None,
    mode: str = "normal",
    custom_prompt: str | None = None,
    thinking_mode: bool = False,
    permitir_reprocessamento: bool = False,
) -> dict[str, Any]:
    if not permitir_reprocessamento:
        from core.services.identidade_de_artefato import exigir_fonte_original

        exigir_fonte_original(file_path)

    cached = await obter_do_cache(file_path, _cache_version())
    if cached is not None:
        logger.info("Cache hit para {}", file_path.name)
        if isinstance(cached, dict):
            return cached
        return construir_documento_canonico(
            str(cached),
            title=file_path.stem,
            language="pt-BR",
            verbosity=verbosity_for_mode(mode),
            source_name=file_path.name,
            source_path=str(file_path),
            audience=["reader"],
        )

    task_id = gestor_de_estado.criar_tarefa(file_path)
    inicio = time.time()
    await registrar_conversao(
        task_id=task_id,
        arquivo=file_path.name,
        extensao=file_path.suffix,
        tamanho_bytes=file_path.stat().st_size,
        modo=mode,
    )

    try:
        gestor_de_estado.atualizar(
            task_id,
            etapa="Preparando arquivo",
            progresso=0.1,
        )
        gestor_de_estado.verificar_cancelamento(task_id)

        from core.services.conversao_de_entrada import (
            precisa_de_conversao, preparar_entrada,
        )

        if precisa_de_conversao(file_path):
            if status_callback:
                await status_callback(
                    f"📄 Convertendo {file_path.suffix} para PDF..."
                )
            file_path = preparar_entrada(file_path, file_path.parent)

        if status_callback:
            await status_callback("📄 Analisando arquivo...")

        gestor_de_estado.atualizar(
            task_id,
            etapa="Processando com IA",
            progresso=0.3,
        )
        gestor_de_estado.verificar_cancelamento(task_id)

        resultado = await agente.executar(
            file_path,
            file_path.parent,
            status_callback,
            mode=mode,
            structured_output=True,
            custom_prompt=custom_prompt,
            thinking_mode=thinking_mode,
        )

        if isinstance(resultado, dict):
            raw_text = resultado["text"]
        else:
            raw_text = resultado

        raw_text = unir_paragrafos_quebrados(raw_text)

        gestor_de_estado.verificar_cancelamento(task_id)
        if not raw_text.strip():
            raise RuntimeError("Resposta vazia do agente")

        relatorio_edicao = None
        if os.getenv("USAR_EDITOR", "false").lower() == "true":
            try:
                from core.agents.editor_textual import revisar_e_registrar

                if status_callback:
                    await status_callback("🔍 Revisando consistencia do texto...")
                relatorio_edicao = await asyncio.to_thread(
                    revisar_e_registrar, raw_text
                )
            except Exception as erro:
                logger.warning("Editor textual indisponivel: {}", erro)

        canonical_document = construir_documento_canonico(
            resultado,
            title=file_path.stem,
            language="pt-BR",
            verbosity=verbosity_for_mode(mode),
            source_name=file_path.name,
            source_path=str(file_path),
            audience=["reader"],
        )

        if relatorio_edicao is not None:
            canonical_document["revisao_textual"] = relatorio_edicao.model_dump()

        metadados = list(getattr(agente, "metadados_acessilia", []) or [])


        try:
            from pipeline.coerencia_global import verificar_coerencia_global

            coerencia = verificar_coerencia_global(canonical_document)
            canonical_document["globalCoherence"] = coerencia
            if not coerencia["coerente"]:
                logger.warning(
                    "Coerencia global: {} erro(s), {} aviso(s)",
                    coerencia["counts"]["ERROR"],
                    coerencia["counts"]["WARNING"],
                )
        except Exception as erro:
            logger.warning("Verificacao de coerencia falhou ({})", erro)


        gerados = _gerar_formatos_acessiveis(
            canonical_document, file_path, task_id
        )

        try:
            from pipeline.validadores_de_preservacao import (
                validar_preservacao_de_assets,
            )

            problemas = validar_preservacao_de_assets(
                canonical_document, gerados
            )
            if problemas:
                canonical_document["assetPreservation"] = problemas
                for problema in problemas:
                    logger.warning(
                        "Preservacao de asset: {} - {}",
                        problema.get("code"), problema.get("message"),
                    )
        except Exception as erro:
            logger.warning("Validacao de assets falhou ({})", erro)

        gestor_de_estado.finalizar(
            task_id,
            json.dumps(canonical_document, ensure_ascii=False),
        )
        await gravar_no_cache(file_path, canonical_document, _cache_version())
        _salvar_json_canonico(canonical_document, file_path.name)

        await finalizar_conversao(
            task_id=task_id,
            status="done",
            pipeline="ollama-unico",
            resultado_resumo=canonical_document["title"][:200],
            tempo_segundos=time.time() - inicio,
        )

        if status_callback:
            await status_callback("✅ Processamento finalizado com sucesso!")
        return canonical_document

    except TaskCancelledError:
        logger.info("Tarefa {} cancelada pelo usuario", task_id)
        await finalizar_conversao(
            task_id=task_id,
            status="cancelled",
            erro="Cancelado pelo usuario",
            tempo_segundos=time.time() - inicio,
        )
        raise

    except Exception as e:
        logger.error("Erro no pipeline: {}: {}", type(e).__name__, e)
        gestor_de_estado.errar(task_id, str(e))
        fallback = _fallback_texto_simples(file_path)
        gestor_de_estado.atualizar(task_id, resultado=fallback)

        await finalizar_conversao(
            task_id=task_id,
            status="error",
            erro=str(e),
            resultado_resumo=fallback[:200],
            tempo_segundos=time.time() - inicio,
        )

        if status_callback:
            await status_callback("❌ Nao foi possivel processar o arquivo.")
        return construir_documento_canonico(
            fallback,
            title=file_path.stem,
            language="pt-BR",
            verbosity=verbosity_for_mode(mode),
            source_name=file_path.name,
            source_path=str(file_path),
            audience=["reader"],
        )


def _fallback_texto_simples(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        try:
            import fitz

            doc = fitz.open(file_path)
            texts = []
            for i in range(min(len(doc), 10)):
                text = doc[i].get_text().strip()
                if text:
                    texts.append(f"--- Pagina {i + 1} ---\n{text}")
            doc.close()
            if texts:
                return "\n\n".join(texts)
        except Exception:
            pass
    return (
        "Nao foi possivel processar o arquivo automaticamente. "
        "Tente enviar em formato diferente."
    )
