"""Validacao de arquivos recebidos pelas interfaces (correcao F03)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from config.settings import settings

_TAMANHO_DO_BLOCO = 1024 * 1024

_ASSINATURAS: dict[str, tuple[bytes, ...] | None] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".bmp": (b"BM",),
    ".webp": (b"RIFF",),
    ".tiff": (b"II*\x00", b"MM\x00*"),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".docx": (b"PK\x03\x04",),
    ".html": None,
}


class ArquivoRecusado(Exception):

    def __init__(self, motivo: str, codigo: str):
        super().__init__(motivo)
        self.motivo = motivo
        self.codigo = codigo


def extensao_permitida(nome: str) -> str:
    sufixo = Path(nome or "").suffix.lower()
    if not sufixo:
        raise ArquivoRecusado(
            "O arquivo precisa ter extensao.", "UPLOAD-EXT-000"
        )
    if sufixo not in settings.allowed_extensions:
        aceitas = ", ".join(sorted(settings.allowed_extensions))
        raise ArquivoRecusado(
            f"Formato {sufixo} nao aceito. Formatos aceitos: {aceitas}.",
            "UPLOAD-EXT-001",
        )

    try:
        from core.services.conversao_de_entrada import (
            conversor_disponivel, precisa_de_conversao,
        )

        if precisa_de_conversao(Path(nome)) and not conversor_disponivel():
            raise ArquivoRecusado(
                f"Arquivos {sufixo} precisam ser convertidos para PDF, e o "
                f"LibreOffice nao esta instalado no servidor. "
                f"Envie o material em PDF, ou instale com: "
                f"sudo apt install libreoffice-writer",
                "UPLOAD-CONV-001",
            )
    except ImportError:
        pass

    return sufixo


def _conferir_assinatura(caminho: Path, sufixo: str) -> None:
    esperadas = _ASSINATURAS.get(sufixo)
    if esperadas is None:
        return
    with open(caminho, "rb") as arquivo:
        cabecalho = arquivo.read(16)
    if not any(cabecalho.startswith(a) for a in esperadas):
        raise ArquivoRecusado(
            f"O conteudo do arquivo nao corresponde a extensao {sufixo}.",
            "UPLOAD-MAGIC-001",
        )
    if sufixo == ".webp" and cabecalho[8:12] != b"WEBP":
        raise ArquivoRecusado(
            "O arquivo declara .webp mas nao e um WebP.", "UPLOAD-MAGIC-002"
        )


def gravar_upload_validado(
    fluxo: BinaryIO,
    nome_original: str,
    destino: Path,
    limite_bytes: int | None = None,
) -> Path:
    sufixo = extensao_permitida(nome_original)
    limite = limite_bytes or settings.max_file_size_bytes

    destino.parent.mkdir(parents=True, exist_ok=True)
    escritos = 0
    try:
        with open(destino, "wb") as saida:
            while True:
                bloco = fluxo.read(_TAMANHO_DO_BLOCO)
                if not bloco:
                    break
                escritos += len(bloco)
                if escritos > limite:
                    raise ArquivoRecusado(
                        f"Arquivo acima do limite de "
                        f"{settings.max_file_size_mb} MB.",
                        "UPLOAD-SIZE-001",
                    )
                saida.write(bloco)

        if escritos == 0:
            raise ArquivoRecusado("Arquivo vazio.", "UPLOAD-SIZE-000")

        _conferir_assinatura(destino, sufixo)
    except Exception:
        destino.unlink(missing_ok=True)
        raise

    return destino


def contar_paginas_pdf(caminho: Path) -> int | None:
    if caminho.suffix.lower() != ".pdf":
        return None
    try:
        import fitz

        with fitz.open(caminho) as documento:
            return documento.page_count
    except Exception:
        return None


def validar_paginas(caminho: Path, limite: int | None = None) -> None:
    limite = limite or settings.max_pages
    paginas = contar_paginas_pdf(caminho)
    if paginas is not None and paginas > limite:
        caminho.unlink(missing_ok=True)
        raise ArquivoRecusado(
            f"O PDF tem {paginas} paginas; o limite e {limite}.",
            "UPLOAD-PAGES-001",
        )
