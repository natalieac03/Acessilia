"""Converte formatos de escritorio para PDF antes do pipeline."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from core.utils.logger import logger

FORMATOS_CONVERSIVEIS = frozenset({
    ".docx", ".doc", ".odt", ".rtf",
    ".html", ".htm",
    ".pptx", ".ppt", ".odp",
})

FORMATOS_NATIVOS = frozenset({
    ".pdf",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp",
})

_TEMPO_LIMITE_CONVERSAO = 180


class ConversaoIndisponivel(RuntimeError):
    pass


def _binario_libreoffice() -> str | None:
    for nome in ("soffice", "libreoffice"):
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    return None


def conversor_disponivel() -> bool:
    return _binario_libreoffice() is not None


def precisa_de_conversao(caminho: Path) -> bool:
    return caminho.suffix.lower() in FORMATOS_CONVERSIVEIS


def converter_para_pdf(origem: Path, destino_dir: Path | None = None) -> Path:
    origem = Path(origem)
    destino_dir = Path(destino_dir or origem.parent)
    destino_dir.mkdir(parents=True, exist_ok=True)

    binario = _binario_libreoffice()
    if not binario:
        raise ConversaoIndisponivel(
            f"O arquivo {origem.suffix} precisa ser convertido para PDF, "
            f"mas o LibreOffice nao esta instalado no servidor. "
            f"Instale com: sudo apt install libreoffice-writer"
        )

    logger.info("Convertendo {} para PDF...", origem.name)
    try:
        resultado = subprocess.run(
            [
                binario, "--headless", "--norestore",
                "--convert-to", "pdf",
                "--outdir", str(destino_dir),
                str(origem),
            ],
            capture_output=True,
            timeout=_TEMPO_LIMITE_CONVERSAO,
            check=False,
        )
    except subprocess.TimeoutExpired as erro:
        raise ConversaoIndisponivel(
            f"A conversao de {origem.name} passou de "
            f"{_TEMPO_LIMITE_CONVERSAO}s e foi interrompida. "
            f"O documento pode ser grande demais."
        ) from erro

    pdf = destino_dir / f"{origem.stem}.pdf"
    if not pdf.is_file():
        detalhe = (resultado.stderr or b"").decode("utf-8", "replace")[:300]
        raise ConversaoIndisponivel(
            f"Nao foi possivel converter {origem.name} para PDF. "
            f"O arquivo pode estar corrompido ou protegido por senha. "
            f"{detalhe}".strip()
        )

    logger.info(
        "Convertido: {} -> {} ({} KB)",
        origem.name, pdf.name, pdf.stat().st_size // 1024,
    )
    return pdf


def preparar_entrada(caminho: Path, destino_dir: Path | None = None) -> Path:
    caminho = Path(caminho)
    if precisa_de_conversao(caminho):
        return converter_para_pdf(caminho, destino_dir)
    return caminho
