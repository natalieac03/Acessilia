"""Contratos de dados da camada matematica."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Caixa = tuple[float, float, float, float]


class SpanGeometry(BaseModel):

    text: str
    start: int
    end: int
    bbox: Caixa | None = None
    font_size: float = 0.0
    font_name: str = ""
    baseline_shift: float = 0.0

    @property
    def parece_sobrescrito(self) -> bool:
        return self.baseline_shift > 0.8 and self.font_size > 0

    @property
    def parece_subscrito(self) -> bool:
        return self.baseline_shift < -0.8 and self.font_size > 0


class TextGeometry(BaseModel):

    spans: list[SpanGeometry] = Field(default_factory=list)
    font_size_dominante: float = 0.0

    def span_em(self, posicao: int) -> SpanGeometry | None:
        for span in self.spans:
            if span.start <= posicao < span.end:
                return span
        return None

    def deslocamentos_em(self, inicio: int, fim: int) -> list[SpanGeometry]:
        return [
            s for s in self.spans
            if s.start < fim and s.end > inicio
            and (s.parece_sobrescrito or s.parece_subscrito)
        ]


class RegionContext(BaseModel):

    tipo_regiao: str = "text"
    e_celula: bool = False
    e_cabecalho: bool = False
    texto_vizinho: str = ""
    pagina: int | None = None


class SourceEvidence(BaseModel):

    document_id: str
    page_number: int
    region_id: str
    bbox: Caixa
    raw_text: str
    raw_lines: list[str] = Field(default_factory=list)
    line_bboxes: list[Caixa] = Field(default_factory=list)
    image_crop_path: str | None = None
    font_sizes: list[float] = Field(default_factory=list)
    superscript_candidates: list[dict] = Field(default_factory=list)
    subscript_candidates: list[dict] = Field(default_factory=list)
    extraction_engine: str = "desconhecido"
    geometry: TextGeometry | None = None


class MathCandidate(BaseModel):

    start: int
    end: int
    source_text: str
    signals: list[str] = Field(default_factory=list)
    score: float = 0.0
    bbox: Caixa | None = None

    @property
    def tem_sinal_forte(self) -> bool:
        return any(s.startswith("forte:") for s in self.signals)


class InlineSegment(BaseModel):

    type: Literal["text", "math_candidate"]
    start: int
    end: int
    source_text: str
    bbox: Caixa | None = None
    signals: list[str] = Field(default_factory=list)


class ResultadoSegmentacao(BaseModel):

    segments: list[InlineSegment] = Field(default_factory=list)
    aceita: bool = True
    motivo_rejeicao: str = ""

    @property
    def tem_matematica(self) -> bool:
        return any(s.type == "math_candidate" for s in self.segments)

    def reconstruir(self) -> str:
        return "".join(s.source_text for s in self.segments)
