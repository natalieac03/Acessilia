"""Interface com o Docling, com PyMuPDF como alternativa."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import fitz

from config.settings import settings
from core.extrator_de_regioes import Region, crop_region_to_image, extract_regions
from core.utils.logger import logger

DOCLING_AVAILABLE = False
DOCLING_IMPORT_ERROR: Exception | None = None

try:
    from docling.document_converter import DocumentConverter

    DOCLING_AVAILABLE = True
except Exception as exc:
    DocumentConverter = None
    DOCLING_IMPORT_ERROR = exc
    logger.warning(
        "Docling indisponível; usando PyMuPDF como fallback: {}",
        exc,
    )


class BaseStructurer:
    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        raise NotImplementedError

    def crop_region(
        self, page: fitz.Page, bbox: tuple[float, float, float, float], dpi: int = 200
    ) -> bytes:
        return crop_region_to_image(page, bbox, dpi)

    @property
    def name(self) -> str:
        return self.__class__.__name__


class PyMuPDFStructurer(BaseStructurer):
    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        return extract_regions(page)

    @property
    def name(self) -> str:
        return "PyMuPDF"


class DoclingStructurer(BaseStructurer):
    def __init__(self) -> None:
        self._converter: Any = None
        self._doc_cache: dict[str, Any] = {}
        self._quebrado: str | None = None

    @staticmethod
    def _diagnosticar(erro: Exception) -> str | None:
        texto = str(erro)
        if "AutoModelForObjectDetection" in texto or \
                "Duplicate dispatch rule" in texto:
            return DoclingStructurer._diagnosticar_falha_de_layout(erro, texto)
        if isinstance(erro, (ImportError, ModuleNotFoundError)):
            return (
                f"Dependencia do Docling ausente: {texto}. "
                "Tente: pip install 'docling[complete]'"
            )
        return None

    @staticmethod
    def _diagnosticar_falha_de_layout(erro: Exception, texto: str) -> str:
        import sys

        python_em_uso = f"{sys.executable} (Python {sys.version.split()[0]})"

        try:
            import timm

            timm_ok = True
            timm_versao = getattr(timm, "__version__", "desconhecida")
        except Exception as erro_timm:
            timm_ok = False
            timm_versao = ""
            erro_timm_texto = f"{type(erro_timm).__name__}: {erro_timm}"

        if not timm_ok:
            return (
                "O timm NAO esta importavel neste processo "
                f"({erro_timm_texto}).\n"
                f"Python em uso: {python_em_uso}\n"
                "Se voce ja rodou 'pip install timm', o mais provavel e "
                "que a instalacao foi feita em outro Python/venv. "
                "Confirme rodando, no MESMO terminal/servico que executa "
                "o ACESSILIA:\n"
                f"    {sys.executable} -m pip install timm accelerate\n"
                "e reinicie o servico depois (nao basta reprocessar - o "
                "processo em memoria continua marcado como quebrado)."
            )

        return (
            f"O timm esta instalado (versao {timm_versao}) e a falha "
            "PERSISTE - a causa nao e mais dependencia ausente.\n"
            f"Python em uso: {python_em_uso}\n"
            f"Erro original do Docling: {texto}\n"
            "Causas mais comuns nesta situacao:\n"
            "  1. Versao incompativel entre torch/torchvision/transformers "
            "e o timm instalado - tente:\n"
            f"       {sys.executable} -m pip install -U "
            "'docling[complete]' timm accelerate torch torchvision\n"
            "  2. Cache de modelo corrompido em ~/.cache/huggingface ou "
            "~/.cache/docling - tente apagar essas pastas e reprocessar.\n"
            "  3. Memoria insuficiente para carregar o modelo de layout "
            "(table-transformer) - verifique dmesg/journalctl por OOM."
        )

    def _get_converter(self) -> Any:
        if self._converter is None:
            self._converter = DocumentConverter()
        return self._converter

    def _process_document(self, file_path: Path) -> Any:
        path_str = str(file_path.resolve())

        if path_str in self._doc_cache:
            cache_entry = self._doc_cache[path_str]
            if time.time() - cache_entry["time"] < 300:
                return cache_entry["doc"]
            del self._doc_cache[path_str]

        start = time.time()
        converter = self._get_converter()
        result = converter.convert(path_str)
        docling_doc = result.document
        elapsed = time.time() - start

        logger.info("Docling processou {} em {:.1f}s", file_path.name, elapsed)

        self._doc_cache[path_str] = {"doc": docling_doc, "time": time.time()}
        return docling_doc

    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        page_num = page.number + 1

        if self._quebrado is not None:
            return extract_regions(page)

        try:
            docling_doc = self._process_document(Path(page.parent.name))
            return self._docling_page_to_regions(docling_doc, page_num, page)
        except Exception as e:
            diagnostico = self._diagnosticar(e)
            if diagnostico is not None:
                self._quebrado = diagnostico
                logger.error(
                    "Docling DESATIVADO para este processo.\n{}", diagnostico
                )
            else:
                logger.warning(
                    "Docling falhou na pagina {} ({}), fallback PyMuPDF",
                    page_num,
                    e,
                )
            return extract_regions(page)

    def _docling_page_to_regions(
        self,
        docling_doc: Any,
        page_num: int,
        fitz_page: fitz.Page,
    ) -> list[Region]:
        regions: list[Region] = []
        page_w = fitz_page.rect.width
        page_h = fitz_page.rect.height

        try:
            page_items = [
                item for item, level in docling_doc.iterate_items(page_no=page_num)
            ]
        except Exception:
            page_items = []

        for item in page_items:
            region = self._docling_item_to_region(item, page_num)
            if region:
                left, top, right, bottom = region.bbox
                if top > bottom:
                    top, bottom = page_h - top, page_h - bottom
                    region.bbox = (left, top, right, bottom)
                regions.append(region)

        if not regions:
            regions.append(
                Region(
                    bbox=(0, 0, page_w, page_h),
                    type="unknown",
                    text="",
                    image_bytes=None,
                    confidence=0.0,
                    page_num=page_num,
                    metadata={"docling_empty": True},
                )
            )

        from pipeline.ordem_de_leitura import ordenar_por_leitura

        regions = ordenar_por_leitura(regions)
        return regions

    def _docling_item_to_region(self, item: Any, page_num: int) -> Region | None:
        bbox = self._docling_bbox(item)
        if bbox is None:
            return None

        item_type = self._docling_label(item)
        text = self._docling_text(item)

        return Region(
            bbox=bbox,
            type=item_type,
            text=text,
            image_bytes=None,
            confidence=0.8,
            page_num=page_num,
            metadata={
                "source": "docling",
                "docling_type": item_type,
                "docling_label": str(getattr(item, "label", "")),
            },
        )

    def _docling_bbox(self, item: Any) -> tuple[float, float, float, float] | None:
        prov = getattr(item, "prov", []) or []
        for p in prov:
            bbox = getattr(p, "bbox", None)
            if bbox:
                try:
                    return (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))
                except Exception:
                    try:
                        return (
                            float(bbox[0]),
                            float(bbox[1]),
                            float(bbox[2]),
                            float(bbox[3]),
                        )
                    except Exception:
                        pass

        obj = getattr(item, "bbox", None)
        if obj:
            try:
                return (float(obj.l), float(obj.t), float(obj.r), float(obj.b))
            except Exception:
                try:
                    return (float(obj[0]), float(obj[1]), float(obj[2]), float(obj[3]))
                except Exception:
                    pass
        return None

    def _docling_label(self, item: Any) -> str:
        label = str(getattr(item, "label", "")).lower()
        if (
            "figure" in label
            or "picture" in label
            or "image" in label
            or "photo" in label
        ):
            return "image"
        if "table" in label:
            return "table"
        if "formula" in label or "equation" in label or "math" in label:
            return "formula"
        if "heading" in label or "title" in label or "section" in label:
            return "heading"
        if "list" in label or "enumeration" in label:
            return "list"
        if "code" in label or "source" in label or "terminal" in label:
            return "code"
        if (
            "note" in label
            or "callout" in label
            or "sidebar" in label
            or "quote" in label
        ):
            return "callout"
        if "caption" in label or "legend" in label:
            return "caption"
        if "paragraph" in label or "text" in label or "body" in label:
            return "text"
        return "text"

    def _docling_text(self, item: Any) -> str:
        text = getattr(item, "text", "") or getattr(item, "caption", "") or ""
        if not text:
            for attr in ("markdown", "raw_text", "content"):
                val = getattr(item, attr, None)
                if val:
                    text = str(val)
                    break
        return str(text).strip()


def get_structurer() -> BaseStructurer:
    mode = settings.estruturador.lower()

    if mode == "docling":
        if not DOCLING_AVAILABLE:
            detalhe = (
                f" Erro de importação: {DOCLING_IMPORT_ERROR}"
                if DOCLING_IMPORT_ERROR
                else ""
            )
            logger.warning(
                "STRUCTURER=docling, mas o Docling está indisponível. "
                "Usando PyMuPDF.{}",
                detalhe,
            )
            return PyMuPDFStructurer()
        logger.info("Usando estruturador: Docling (com fallback PyMuPDF)")
        return DoclingStructurer()

    logger.info("Usando estruturador: PyMuPDF")
    return PyMuPDFStructurer()
