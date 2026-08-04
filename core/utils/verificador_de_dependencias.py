"""Confere as dependencias ANTES de processar (nao no meio)."""

from __future__ import annotations

import importlib.util
import sys

_DEPENDENCIAS = (
    ("fitz", "PyMuPDF", "extracao de PDF", True),
    ("PIL", "Pillow", "recorte e preparo de imagens", True),
    ("agno", "agno", "TODOS os agentes de IA: descricao de imagem, "
     "formula, tabela, critico visual e editor", True),
    ("openai", "openai", "cliente que o Agno usa para falar com o "
     "OpenRouter", True),
    ("latex2mathml", "latex2mathml", "conversao LaTeX -> MathML "
     "(formulas navegaveis por leitor de tela)", True),
    ("docx", "python-docx", "geracao do DOCX", False),
    ("lxml", "lxml", "marcacao de idioma e alt-text no DOCX", False),
    ("reportlab", "reportlab", "geracao do PDF visual", False),
    ("edge_tts", "edge-tts", "geracao do MP3", False),
    ("docling", "docling", "extracao estruturada (cai para PyMuPDF)", False),
    ("timm", "timm", "modelo de layout do Docling", False),
)


def verificar_dependencias() -> tuple[list[str], list[str]]:
    criticas: list[str] = []
    opcionais: list[str] = []

    for modulo, pacote, perda, e_critica in _DEPENDENCIAS:
        try:
            existe = importlib.util.find_spec(modulo) is not None
        except (ImportError, ValueError):
            existe = False
        if existe:
            continue
        linha = f"{pacote}  (sem ele: {perda})"
        (criticas if e_critica else opcionais).append(linha)

    return criticas, opcionais


def relatar_dependencias(logger) -> bool:
    criticas, opcionais = verificar_dependencias()

    if opcionais:
        logger.warning(
            "Dependencias OPCIONAIS ausentes - o material sai, com menos "
            "recursos:\n  {}\nInstale com:\n  {} -m pip install {}",
            "\n  ".join(opcionais),
            sys.executable,
            " ".join(linha.split("  ")[0] for linha in opcionais),
        )

    if criticas:
        linha = "=" * 70
        lista = "\n".join(f"  - {c}" for c in criticas)
        pacotes = " ".join(c.split("  ")[0] for c in criticas)
        logger.error(
            "\n" + linha
            + "\nDEPENDENCIAS CRITICAS AUSENTES\n"
            + linha + "\n"
            + lista
            + "\n\nO processamento vai TERMINAR SEM ERRO e entregar um "
            "material sem descricao de imagem nem formula - o pipeline e "
            "fail-open, entao a ausencia nao interrompe nada, so esvazia "
            "o resultado.\n\n"
            f"Instale com:\n  {sys.executable} -m pip install {pacotes}\n"
            f"Python em uso: {sys.executable}\n"
            + linha
        )
        return False

    logger.info("Dependencias verificadas: tudo presente.")
    return True
