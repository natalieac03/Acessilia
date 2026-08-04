import asyncio
import tempfile

import uuid
import shutil
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, Document, PhotoSize, FSInputFile
from aiogram.exceptions import TelegramRetryAfter

from interfaces.telegram.adapters.file_service import download_file
from core.orquestrador import process
from core.services.conversao_de_entrada import ConversaoIndisponivel
from core.services.identidade_de_artefato import ReprocessamentoNaoPermitido


from core.utils.logger import logger
from core.utils.validadores import validate_file
from interfaces.telegram.adapters.status_tracker import StatusTracker
from config.settings import settings

from renderers.sintetizador_de_voz import export_mp3

router = Router()

OUTPUT_DIR = settings.temp_dir / "output"

user_modes: dict[tuple[int, int | None], str] = {}
user_emails: dict[tuple[int, int | None], str] = {}


async def _send_with_retry(
    bot,
    chat_id: int,
    msg: str,
    message_thread_id: int | None = None,
    max_retries: int = 3,
) -> None:
    for attempt in range(max_retries):
        try:
            await bot.send_message(chat_id, msg, message_thread_id=message_thread_id)
            return
        except TelegramRetryAfter as e:
            wait = e.retry_after + attempt * 5
            logger.warning(
                "Telegram rate limit, aguardando {}s: {}",
                wait,
                msg[:50],
            )
            await asyncio.sleep(wait)
    logger.error("Falha apos {} tentativas para enviar mensagem", max_retries)


@router.message(F.document)
async def handle_document(message: Message) -> None:
    document: Document | None = message.document
    if document is None:
        return

    filename = document.file_name or "documento"
    file_size = document.file_size or 0

    valid, error_msg = validate_file(filename, file_size)
    if not valid:
        await message.answer(error_msg)
        return

    mode = user_modes.pop((message.chat.id, message.message_thread_id), "normal")
    await message.answer("📄 Arquivo recebido!")
    await process_file(message, document.file_id, filename, mode=mode)


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    photo: PhotoSize | None = message.photo[-1] if message.photo else None
    if photo is None:
        return

    mode = user_modes.pop((message.chat.id, message.message_thread_id), "normal")
    await message.answer("📷 Foto recebida!")
    await process_file(message, photo.file_id, "imagem.png", mode=mode)


from core.services.servico_de_fila import unified_queue, QueueItem


async def process_file(
    message: Message,
    file_id: str,
    filename: str,
    mode: str = "normal",
) -> None:
    message_thread_id = message.message_thread_id
    tracker = StatusTracker(message.bot, message.chat.id, filename, message_thread_id=message_thread_id)

    with tempfile.TemporaryDirectory(dir=settings.temp_dir) as tmpdir:
        input_path = Path(tmpdir) / filename
        await tracker("Baixando arquivo...")
        await download_file(message.bot, file_id, input_path)

        persistent_tmp = settings.temp_dir / f"task_{uuid.uuid4().hex}"
        persistent_tmp.mkdir(parents=True, exist_ok=True)
        task_path = persistent_tmp / filename
        shutil.copy2(input_path, task_path)

        async def task_callback(
            path: Path,
            t_filename: str,
            t_mode: str,
            t_tracker: StatusTracker,
            cleanup_dir: Path,
        ):
            try:
                canonical_document = await process(
                    path,
                    status_callback=t_tracker,
                    mode=t_mode,
                )

                await t_tracker(
                    "Conteudo extraido com sucesso! Preparando exportacao..."
                )

                from core.services.coordenador_de_exportacao import (
                    empacotar_outputs,
                )

                outputs = dict(canonical_document.get("outputs") or {})
                decisao = canonical_document.get("publicationDecision") or {}
                e_final = bool(decisao.get("publicar_como_final"))

                txt_path = Path(outputs["txt"]) if outputs.get("txt") else None
                task_dir = (
                    txt_path.parent if txt_path else OUTPUT_DIR
                )
                task_dir.mkdir(parents=True, exist_ok=True)
                base_name = (
                    txt_path.stem if txt_path
                    else f"{path.stem}_rascunho_nao_aprovado"
                )

                mp3_path = task_dir / f"{base_name}.mp3"
                try:
                    if txt_path and txt_path.exists():
                        clean_text = txt_path.read_text(encoding="utf-8")

                        async def audio_progress(atual: int, total: int):
                            try:
                                await t_tracker(
                                    f"Gerando áudio... ({atual}/{total})"
                                )
                            except Exception:
                                pass

                        await export_mp3(
                            clean_text,
                            mp3_path,
                            progress_callback=audio_progress,
                        )
                        if mp3_path.exists():
                            outputs["mp3"] = str(mp3_path)
                except Exception as e:
                    logger.error("Falha ao gerar MP3: {}", e)
                    if mp3_path.exists():
                        try:
                            mp3_path.unlink()
                        except Exception:
                            pass
                    try:
                        await t_tracker(
                            "O áudio não pôde ser gerado; os demais "
                            "formatos seguem no pacote."
                        )
                    except Exception:
                        pass

                zip_path = empacotar_outputs(
                    outputs, task_dir, f"{base_name}.zip"
                )
                if zip_path is None:
                    raise RuntimeError(
                        "Nenhum artefato para empacotar. "
                        f"decisao={decisao.get('status', '?')}, "
                        f"outputs={sorted(outputs) or 'vazio'}, "
                        f"dir={task_dir}"
                    )

                target_email = user_emails.pop((message.chat.id, message.message_thread_id), None)

                web_url = (settings.web_url or "").strip().rstrip("/")
                url_valida = web_url and "sua_url_publica_aqui" not in web_url

                if target_email and url_valida:
                    from core.services.servico_de_token_de_download import criar_token
                    from core.services.servico_de_email import send_result_email

                    token = await criar_token(task_dir, base_name)
                    download_url = f"{web_url}/download/{token}"

                    await t_tracker(f"Enviando link para e-mail: {target_email}...")
                    await send_result_email(
                        target_email, t_filename, download_url=download_url
                    )
                    await message.answer(
                        f"✅ Link de download enviado para {target_email}!"
                    )
                else:
                    if e_final:
                        aviso = "✅ Pronto! Enviando o arquivo abaixo."
                    else:
                        aviso = (
                            "✅ Pronto! Enviando o arquivo abaixo. "
                            "Vale conferir com calma depois — o relatório "
                            "de pendências vai junto no pacote."
                        )
                    legenda = "📦 Material acessível (TXT, DOCX, PDF, HTML e MP3)."

                    await t_tracker("Enviando pacote...")
                    await _send_with_retry(
                        message.bot,
                        message.chat.id,
                        aviso,
                        message_thread_id=message_thread_id,
                    )
                    await message.bot.send_document(
                        chat_id=message.chat.id,
                        document=FSInputFile(zip_path, filename=zip_path.name),
                        message_thread_id=message_thread_id,
                        caption=legenda,
                    )

                    if target_email and not url_valida:
                        await message.answer(
                            "ℹ️ O arquivo foi enviado aqui no chat. Para receber "
                            "por e-mail, configure WEB_URL no arquivo .env."
                        )

                await t_tracker.finish(success=True)
            except ReprocessamentoNaoPermitido as erro:
                logger.info("Reprocessamento recusado: {}", erro)
                await message.answer(
                    "⚠️ Este arquivo já é uma saída do ACESSÍLIA.\n\n"
                    "Processá-lo de novo descreveria a descrição, não o "
                    "material original — e cada passagem acumula os erros "
                    "da anterior.\n\n"
                    "Envie o PDF-fonte original."
                )
                await t_tracker.finish(success=False)
            except ConversaoIndisponivel as erro:
                logger.warning("Conversao indisponivel: {}", erro)
                await message.answer(f"⚠️ {erro}")
                await t_tracker.finish(success=False)
            except Exception:
                logger.exception("Erro no processamento da fila (Bot)")
                try:
                    await message.answer(
                        "❌ Não consegui processar este arquivo.\n\n"
                        "Pode ser um formato que o sistema ainda não trata, "
                        "um arquivo protegido por senha, ou um problema "
                        "temporário. Vale tentar enviar em PDF.\n\n"
                        "Se continuar acontecendo, o log do servidor tem o "
                        "detalhe técnico."
                    )
                except Exception:
                    logger.exception("Falha ao avisar o usuario sobre o erro")
                await t_tracker.finish(success=False)
            finally:
                if cleanup_dir.exists():
                    shutil.rmtree(cleanup_dir)

        queue_item = QueueItem(
            file_path=task_path,
            filename=filename,
            source="telegram",
            callback=task_callback,
            callback_args={
                "path": task_path,
                "t_filename": filename,
                "t_mode": mode,
                "t_tracker": tracker,
                "cleanup_dir": persistent_tmp,
            },
        )
        confirmation_email = user_emails.get((message.chat.id, message.message_thread_id))
        if confirmation_email:
            from core.services.servico_de_email import send_confirmation_email
            asyncio.create_task(send_confirmation_email(confirmation_email, filename))

        pos = await unified_queue.enqueue(queue_item)
        if pos > 1:
            await message.answer(f"⏳ Você está na fila única (Posição: {pos}).")
