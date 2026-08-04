"""Assets visuais persistidos."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PASTA_ASSETS = "assets"

_EXTENSOES_SEGURAS = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}


@dataclass
class AssetVisual:

    asset_id: str
    asset_path: str
    absolute_path: Path
    page_number: int
    width_px: int = 0
    height_px: int = 0
    extension: str = "png"
    digest: str = ""
    source_bbox: tuple[float, float, float, float] | None = None
    xref: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_path": self.asset_path,
            "page_number": self.page_number,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "extension": self.extension,
            "digest": self.digest,
            "source_bbox": list(self.source_bbox) if self.source_bbox else None,
            "xref": self.xref,
            **self.metadata,
        }


def _identificador(dados: bytes, digest: str = "") -> str:
    base = digest or hashlib.sha256(dados).hexdigest()
    return f"asset-{base[:16]}"


def _normalizar_extensao(extensao: str) -> str:
    ext = (extensao or "png").lower().lstrip(".")
    return ext if ext in _EXTENSOES_SEGURAS else "png"


def _converter_para_png(dados: bytes) -> bytes:
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(dados)) as img:
            saida = io.BytesIO()
            img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")\
                .save(saida, format="PNG")
            return saida.getvalue()
    except Exception:
        return dados


class RepositorioDeAssets:

    def __init__(self, diretorio_da_tarefa: str | Path):
        self.base = Path(diretorio_da_tarefa)
        self.pasta = self.base / PASTA_ASSETS
        self._por_digest: dict[str, AssetVisual] = {}
        self._assets: dict[str, AssetVisual] = {}

    def gravar(
        self,
        dados: bytes,
        page_number: int,
        extensao: str = "png",
        digest: str = "",
        source_bbox: tuple[float, float, float, float] | None = None,
        xref: int = 0,
        width_px: int = 0,
        height_px: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> AssetVisual | None:
        if not dados:
            return None

        chave = digest or hashlib.sha256(dados).hexdigest()
        if chave in self._por_digest:
            return self._por_digest[chave]

        ext = _normalizar_extensao(extensao)
        if ext == "png" and (extensao or "").lower().lstrip(".") not in (
            "png", ""
        ):
            dados = _converter_para_png(dados)

        indice = len(self._assets) + 1
        nome = f"pagina_{page_number:03d}_imagem_{indice:03d}.{ext}"

        try:
            self.pasta.mkdir(parents=True, exist_ok=True)
            caminho = self.pasta / nome
            caminho.write_bytes(dados)
        except OSError:
            return None

        asset = AssetVisual(
            asset_id=_identificador(dados, chave),
            asset_path=f"{PASTA_ASSETS}/{nome}",
            absolute_path=caminho,
            page_number=page_number,
            width_px=int(width_px or 0),
            height_px=int(height_px or 0),
            extension=ext,
            digest=chave,
            source_bbox=tuple(source_bbox) if source_bbox else None,
            xref=int(xref or 0),
            metadata=dict(metadata or {}),
        )
        self._por_digest[chave] = asset
        self._assets[asset.asset_id] = asset
        return asset

    def gravar_regiao(self, region: Any) -> AssetVisual | None:
        dados = getattr(region, "image_bytes", None)
        if not dados:
            return None
        meta = getattr(region, "metadata", {}) or {}
        return self.gravar(
            dados,
            page_number=getattr(region, "page_num", 0) or 0,
            extensao=meta.get("extension", "png"),
            digest=meta.get("digest", ""),
            source_bbox=getattr(region, "bbox", None),
            xref=meta.get("xref", 0),
            width_px=meta.get("width_px", 0) or 0,
            height_px=meta.get("height_px", 0) or 0,
        )

    def obter(self, asset_id: str) -> AssetVisual | None:
        return self._assets.get(asset_id)

    def todos(self) -> list[AssetVisual]:
        return list(self._assets.values())

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {a.asset_id: a.to_dict() for a in self._assets.values()}


def resolver_caminho_do_asset(
    bloco: dict[str, Any], base: str | Path | None = None
) -> Path | None:
    caminho = bloco.get("asset_path") or (
        bloco.get("metadata", {}) or {}
    ).get("asset_path")
    if not caminho:
        return None

    alvo = Path(caminho)
    if alvo.is_absolute() and alvo.exists():
        return alvo
    if base:
        candidato = Path(base) / caminho
        if candidato.exists():
            return candidato
    return alvo if alvo.exists() else None
