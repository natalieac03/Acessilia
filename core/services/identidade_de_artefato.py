"""Identifica arquivos gerados pelo proprio sistema."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

PRODUTOR = "ACESSILIA"
CHAVE_MARCA = "acessilia_generated"

_MARCA_TEXTO = "ACESSILIA-GENERATED-ARTIFACT"


class ReprocessamentoNaoPermitido(Exception):
    pass


def sha256_do_arquivo(caminho: Path, blocos: int = 1 << 20) -> str:
    h = hashlib.sha256()
    try:
        with open(caminho, "rb") as arquivo:
            for pedaco in iter(lambda: arquivo.read(blocos), b""):
                h.update(pedaco)
    except OSError:
        return ""
    return h.hexdigest()


def normalizar_nome(nome: str) -> str:
    limpo = unicodedata.normalize("NFKD", str(nome or ""))
    limpo = "".join(c for c in limpo if not unicodedata.combining(c))
    limpo = re.sub(r"[^A-Za-z0-9._-]+", "_", limpo).strip("._-")
    return limpo or "documento"


def construir_metadados(
    caminho_fonte: Path,
    decisao_status: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dados = {
        CHAVE_MARCA: True,
        "producer": PRODUTOR,
        "source_name": Path(caminho_fonte).name,
        "source_sha256": sha256_do_arquivo(Path(caminho_fonte)),
        "publication_status": decisao_status,
    }
    if extra:
        dados.update(extra)
    return dados


def _marca_em_pdf(caminho: Path) -> bool:
    try:
        import fitz

        doc = fitz.open(caminho)
        try:
            meta = doc.metadata or {}
        finally:
            doc.close()
    except Exception:
        return False
    alvo = " ".join(
        str(meta.get(campo) or "")
        for campo in ("producer", "creator", "keywords", "subject")
    ).upper()
    return PRODUTOR in alvo or _MARCA_TEXTO in alvo


def _marca_em_docx(caminho: Path) -> bool:
    try:
        import docx

        doc = docx.Document(str(caminho))
        props = doc.core_properties
    except Exception:
        return False
    alvo = " ".join(
        str(getattr(props, campo, "") or "")
        for campo in ("comments", "category", "keywords", "subject")
    ).upper()
    return PRODUTOR in alvo or _MARCA_TEXTO in alvo


def _marca_em_texto(caminho: Path, limite: int = 8192) -> bool:
    try:
        with open(caminho, "r", encoding="utf-8", errors="ignore") as arquivo:
            inicio = arquivo.read(limite)
    except OSError:
        return False
    if _MARCA_TEXTO in inicio:
        return True
    try:
        tamanho = caminho.stat().st_size
        if tamanho > limite:
            with open(caminho, "r", encoding="utf-8",
                      errors="ignore") as arquivo:
                arquivo.seek(max(0, tamanho - limite))
                return _MARCA_TEXTO in arquivo.read()
    except OSError:
        return False
    return False


def _marca_em_sidecar(caminho: Path) -> bool:
    vizinho = caminho.with_suffix(caminho.suffix + ".acessilia.json")
    irmao = caminho.parent / f"{caminho.stem}.acessilia.json"
    for candidato in (vizinho, irmao):
        if candidato.exists():
            try:
                dados = json.loads(candidato.read_text(encoding="utf-8"))
            except Exception:
                return True
            if isinstance(dados, dict) and dados.get("standard", "").upper()\
                    .startswith("ACESSILIA"):
                return True
    return False


def arquivo_gerado_pelo_acessilia(caminho: str | Path) -> bool:
    caminho = Path(caminho)
    if not caminho.exists():
        return False

    nome = caminho.stem.lower()
    if nome.endswith("_acessivel") or "rascunho_nao_aprovado" in nome:
        return True
    if _marca_em_sidecar(caminho):
        return True

    sufixo = caminho.suffix.lower()
    try:
        if sufixo == ".pdf":
            return _marca_em_pdf(caminho)
        if sufixo == ".docx":
            return _marca_em_docx(caminho)
        if sufixo in (".txt", ".html", ".htm", ".md"):
            return _marca_em_texto(caminho)
    except Exception:
        return False
    return False


def exigir_fonte_original(caminho: str | Path) -> None:
    if arquivo_gerado_pelo_acessilia(caminho):
        raise ReprocessamentoNaoPermitido(
            "Este arquivo ja foi gerado pelo ACESSILIA. Reprocessa-lo "
            "descreveria a descricao, nao o material. Envie o PDF-fonte "
            "original."
        )


def marcar_texto(conteudo: str, metadados: dict[str, Any]) -> str:
    ficha = json.dumps(metadados, ensure_ascii=False, sort_keys=True)
    return f"{conteudo.rstrip()}\n\n<!-- {_MARCA_TEXTO} {ficha} -->\n"


def marcar_html(conteudo: str, metadados: dict[str, Any]) -> str:
    ficha = json.dumps(metadados, ensure_ascii=False, sort_keys=True)
    marca = f"<!-- {_MARCA_TEXTO} {ficha} -->"
    if "</body>" in conteudo:
        return conteudo.replace("</body>", f"{marca}\n</body>", 1)
    return f"{conteudo}\n{marca}\n"


def marcar_docx(documento: Any, metadados: dict[str, Any]) -> None:
    try:
        props = documento.core_properties
        props.category = PRODUTOR
        props.comments = json.dumps(metadados, ensure_ascii=False)
    except Exception:
        pass


def marcar_pdf(documento: Any, metadados: dict[str, Any]) -> None:
    try:
        documento.set_metadata({
            "producer": PRODUTOR,
            "creator": PRODUTOR,
            "keywords": json.dumps(metadados, ensure_ascii=False),
        })
    except Exception:
        pass


def nome_de_saida(
    nome_fonte: str, sufixo: str, extensao: str
) -> str:
    base = normalizar_nome(Path(nome_fonte).stem)
    extensao = extensao.lstrip(".")
    return f"{base}{sufixo}.{extensao}"
