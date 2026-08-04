"""Entrada do sistema: sobe o bot do Telegram.

Confere as dependencias ANTES de aceitar qualquer arquivo. O pipeline e
fail-open durante o processamento — um agente opcional que falha nao
pode derrubar a entrega —, mas na partida a ausencia precisa ser
gritada: sem isso o sistema processa o documento inteiro e entrega
material sem descricao nenhuma, "com sucesso".

Usa um lock em arquivo para impedir duas instancias simultaneas, que
disputariam as mesmas atualizacoes do Telegram.
"""

import asyncio
import os
import subprocess
import sys

from core.utils.logger import setup_logger, logger
from config.settings import settings

LOCK_FILE = os.path.join(os.path.dirname(__file__), "bot.lock")


def _is_process_running(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def acquire_lock() -> None:
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                pid = int(f.read().strip())
            if _is_process_running(pid):
                logger.critical(
                    "Outra instancia do bot ja esta rodando (PID={})",
                    pid,
                )
                sys.exit(1)
            else:
                logger.warning(
                    "Lock file stale (PID {} nao existe), removendo...",
                    pid,
                )
                os.remove(LOCK_FILE)
        except ValueError:
            os.remove(LOCK_FILE)
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    logger.info("Lock acquired (PID={})", os.getpid())


def release_lock() -> None:
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Lock released")
    except OSError:
        pass


async def startup():
    setup_logger()

    from core.utils.verificador_de_dependencias import relatar_dependencias

    relatar_dependencias(logger)

    enabled = [i.strip() for i in settings.enabled_interfaces.split(",")]
    tasks = []

    if "telegram" in enabled and settings.bot_token_valid:
        from interfaces.telegram.bot import start_polling
        tasks.append(start_polling())
        logger.info("Interface Telegram habilitada")
    elif "telegram" in enabled and not settings.bot_token_valid:
        logger.warning("Interface Telegram habilitada mas BOT_TOKEN nao configurado")

    if "web" in enabled:
        logger.warning(
            "ENABLED_INTERFACES pede 'web', mas esta versão só tem o "
            "Telegram. Ignorando."
        )

    if not tasks:
        logger.critical("Nenhuma interface habilitada. Configure ENABLED_INTERFACES no .env")
        sys.exit(1)

    logger.info("Iniciando com interfaces: {}", settings.enabled_interfaces)
    await asyncio.gather(*tasks)


async def _cleanup_http_clients():
    from core.ai.ollama import client as ollama_cli
    from core.ai.openrouter import client as or_cli
    try:
        await ollama_cli.close()
    except Exception:
        pass
    try:
        await or_cli.close()
    except Exception:
        pass


if __name__ == "__main__":
    acquire_lock()
    try:
        asyncio.run(startup())
    except KeyboardInterrupt:
        logger.info("Bot interrompido pelo usuario")
    except Exception:
        logger.exception("Erro fatal no bot")
        sys.exit(1)
    finally:
        release_lock()
        try:
            asyncio.run(_cleanup_http_clients())
        except Exception:
            pass
