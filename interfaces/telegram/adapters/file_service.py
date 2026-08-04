from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from core.utils.logger import logger


async def download_file(bot: Bot, file_id: str, destination: Path) -> Path:
    import asyncio

    file = await bot.get_file(file_id)
    ultimo_erro: Exception | None = None
    for tentativa in range(1, 4):
        try:
            logger.debug(
                "Downloading file (tentativa {}): {} -> {}",
                tentativa, file.file_path, destination.name,
            )
            await bot.download_file(file.file_path, destination)
            logger.info(
                "File downloaded: {} ({} bytes)",
                destination.name, file.file_size or 0,
            )
            return destination
        except (TimeoutError, asyncio.TimeoutError, ConnectionError,
                OSError) as erro:
            ultimo_erro = erro
            try:
                if destination.exists():
                    destination.unlink()
            except OSError:
                pass
            if tentativa < 3:
                espera = 2 * tentativa
                logger.warning(
                    "Download falhou ({}: {}); nova tentativa em {}s",
                    type(erro).__name__, erro, espera,
                )
                await asyncio.sleep(espera)
    raise RuntimeError(
        f"Download do Telegram falhou apos 3 tentativas "
        f"({type(ultimo_erro).__name__}: {ultimo_erro}). "
        "Verifique a conexao e reenvie o arquivo."
    ) from ultimo_erro


async def send_output_file(
    bot: Bot, chat_id: int, file_path: Path, caption: str,
    message_thread_id: int | None = None,
) -> None:
    input_file = FSInputFile(file_path)
    await bot.send_document(
        chat_id=chat_id, document=input_file, caption=caption,
        message_thread_id=message_thread_id,
    )
