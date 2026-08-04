"""Indice de evidencia por regiao, consultado depois.

Resolve um problema de encanamento com efeito semantico: a geometria
existe onde a pagina esta aberta, mas a camada matematica precisa dela
mais adiante, quando so resta uma string de texto.

O catalogo e montado com a pagina aberta e consultado depois, ligando
cada trecho de texto a evidencia visual que o originou.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from pipeline.matematica.evidencia_matematica import SourceEvidence, SpanGeometry, TextGeometry

_LIMIAR_SIMILARIDADE = 0.86

_PROPORCAO_MINIMA_ANCORADA = 0.7


def _chave_exata(texto: str) -> str:
    return " ".join(str(texto or "").split())


def _chave_frouxa(texto: str) -> str:
    return "".join(str(texto or "").split())


def _mapa_frouxo(texto: str) -> tuple[str, list[int]]:
    reduzido: list[str] = []
    indices: list[int] = []
    for posicao, caractere in enumerate(texto):
        if caractere.isspace():
            continue
        reduzido.append(caractere)
        indices.append(posicao)
    return "".join(reduzido), indices


def localizar_trecho(agulha: str, palheiro: str) -> tuple[int, int] | None:
    if not agulha or not palheiro:
        return None

    direto = palheiro.find(agulha)
    if direto >= 0:
        return direto, direto + len(agulha)

    alvo = _chave_frouxa(agulha)
    if not alvo:
        return None
    reduzido, indices = _mapa_frouxo(palheiro)
    posicao = reduzido.find(alvo)
    if posicao < 0:
        return None
    inicio = indices[posicao]
    fim = indices[posicao + len(alvo) - 1] + 1
    return inicio, fim


def realinhar_geometria(
    geometria: TextGeometry | None, texto: str
) -> TextGeometry | None:
    if geometria is None or not geometria.spans or not texto:
        return None

    ancorados: list[SpanGeometry] = []
    cursor = 0
    perdidos = 0
    for span in geometria.spans:
        conteudo = span.text
        if not conteudo.strip():
            continue
        posicao = texto.find(conteudo, cursor)
        if posicao < 0:
            achado = localizar_trecho(conteudo, texto[cursor:])
            posicao = cursor + achado[0] if achado else -1
        if posicao < 0:
            perdidos += 1
            continue
        fim = posicao + len(conteudo)
        ancorados.append(
            span.model_copy(update={"start": posicao, "end": fim})
        )
        cursor = fim

    if not ancorados:
        return None
    total = len(ancorados) + perdidos
    if total and len(ancorados) / total < _PROPORCAO_MINIMA_ANCORADA:
        return None
    return TextGeometry(
        spans=ancorados,
        font_size_dominante=geometria.font_size_dominante,
    )


def recortar_geometria(
    geometria: TextGeometry | None, inicio: int, fim: int
) -> TextGeometry | None:
    if geometria is None or not geometria.spans:
        return None
    recortados: list[SpanGeometry] = []
    for span in geometria.spans:
        if span.end <= inicio or span.start >= fim:
            continue
        recortados.append(
            span.model_copy(
                update={
                    "start": max(0, span.start - inicio),
                    "end": min(fim, span.end) - inicio,
                }
            )
        )
    if not recortados:
        return None
    return TextGeometry(
        spans=recortados,
        font_size_dominante=geometria.font_size_dominante,
    )


def recortar_evidencia(
    evidencia: SourceEvidence, inicio: int, fim: int
) -> SourceEvidence:
    trecho = evidencia.raw_text[inicio:fim]
    geometria = recortar_geometria(evidencia.geometry, inicio, fim)
    sobrescritos = [
        {
            "text": s.text,
            "start": s.start,
            "end": s.end,
            "baseline_shift": s.baseline_shift,
            "font_size": s.font_size,
        }
        for s in (geometria.spans if geometria else [])
        if s.parece_sobrescrito and s.text.strip()
    ]
    subscritos = [
        {
            "text": s.text,
            "start": s.start,
            "end": s.end,
            "baseline_shift": s.baseline_shift,
            "font_size": s.font_size,
        }
        for s in (geometria.spans if geometria else [])
        if s.parece_subscrito and s.text.strip()
    ]
    return evidencia.model_copy(
        update={
            "raw_text": trecho,
            "raw_lines": list(evidencia.raw_lines) or [evidencia.raw_text],
            "geometry": geometria,
            "superscript_candidates": sobrescritos,
            "subscript_candidates": subscritos,
        }
    )


class CatalogoDeEvidencias:

    def __init__(self, document_id: str = "", page_number: int = 0):
        self.document_id = document_id
        self.page_number = page_number
        self._evidencias: list[SourceEvidence] = []
        self._por_chave_exata: dict[str, SourceEvidence] = {}
        self._por_chave_frouxa: dict[str, SourceEvidence] = {}
        self._vizinhos_por_chave: dict[str, list[str]] = {}
        self._vizinhos_consumidos: dict[str, list[str]] = {}
        self._assets_por_bbox: dict[tuple, Any] = {}
        self._assets_registrados: list[Any] = []

    def registrar_asset(self, bbox, asset) -> None:
        if asset is None:
            return
        chave = tuple(round(float(v), 1) for v in (bbox or (0, 0, 0, 0)))
        self._assets_por_bbox.setdefault(chave, asset)
        self._assets_registrados.append(asset)

    def asset_em(self, bbox, tolerancia: float = 2.0):
        if not bbox:
            return None
        alvo = tuple(float(v) for v in bbox)
        chave = tuple(round(v, 1) for v in alvo)
        if chave in self._assets_por_bbox:
            return self._assets_por_bbox[chave]
        for candidata, asset in self._assets_por_bbox.items():
            if all(
                abs(a - b) <= tolerancia for a, b in zip(alvo, candidata)
            ):
                return asset
        return None

    def proximo_asset_sem_uso(self):
        return self._assets_registrados.pop(0) if self._assets_registrados \
            else None

    @property
    def assets(self) -> list:
        return list(self._assets_por_bbox.values())

    def registrar_vizinhos(self, texto: str, vizinhos: list[str]) -> None:
        limpos = [str(v).strip() for v in (vizinhos or []) if str(v).strip()]
        if not (texto or "").strip() or not limpos:
            return
        self._vizinhos_por_chave.setdefault(_chave_exata(texto), limpos)
        self._vizinhos_por_chave.setdefault(_chave_frouxa(texto), limpos)

    def vizinhos_de(self, texto: str) -> list[str]:
        if not (texto or "").strip():
            return []
        for chave in (_chave_exata(texto), _chave_frouxa(texto)):
            if chave in self._vizinhos_por_chave:
                return list(self._vizinhos_por_chave[chave])
        alvo = _chave_frouxa(texto)
        for chave, vizinhos in self._vizinhos_por_chave.items():
            if alvo and alvo in chave:
                return list(vizinhos)
        return []

    def registrar_consumo(self, texto: str, usados: list[str]) -> None:
        if not usados:
            return
        self._vizinhos_consumidos.setdefault(
            _chave_frouxa(texto), [str(u) for u in usados]
        )

    def consumo_de(self, texto: str) -> list[str]:
        return list(self._vizinhos_consumidos.get(_chave_frouxa(texto), []))

    @property
    def com_vizinhos(self) -> int:
        return len(self._vizinhos_por_chave)

    def registrar(self, evidencia: SourceEvidence | None) -> None:
        if evidencia is None or not (evidencia.raw_text or "").strip():
            return
        self._evidencias.append(evidencia)
        exata = _chave_exata(evidencia.raw_text)
        frouxa = _chave_frouxa(evidencia.raw_text)
        self._por_chave_exata.setdefault(exata, evidencia)
        self._por_chave_frouxa.setdefault(frouxa, evidencia)

    def buscar(self, texto: str) -> SourceEvidence | None:
        alvo = (texto or "").strip()
        if not alvo or not self._evidencias:
            return None

        exata = self._por_chave_exata.get(_chave_exata(alvo))
        if exata is not None:
            return exata
        frouxa = self._por_chave_frouxa.get(_chave_frouxa(alvo))
        if frouxa is not None:
            return frouxa

        for evidencia in self._evidencias:
            achado = localizar_trecho(alvo, evidencia.raw_text)
            if achado is not None:
                inicio, fim = achado
                if inicio == 0 and fim == len(evidencia.raw_text):
                    return evidencia
                return recortar_evidencia(evidencia, inicio, fim)

        return self._buscar_por_similaridade(alvo)

    def _buscar_por_similaridade(self, alvo: str) -> SourceEvidence | None:
        chave = _chave_frouxa(alvo)
        melhor: SourceEvidence | None = None
        melhor_razao = 0.0
        for evidencia in self._evidencias:
            razao = SequenceMatcher(
                None, chave, _chave_frouxa(evidencia.raw_text)
            ).ratio()
            if razao > melhor_razao:
                melhor_razao, melhor = razao, evidencia
        if melhor is not None and melhor_razao >= _LIMIAR_SIMILARIDADE:
            return melhor
        return None

    @property
    def evidencias(self) -> list[SourceEvidence]:
        return list(self._evidencias)

    @property
    def com_geometria(self) -> int:
        return sum(
            1 for e in self._evidencias
            if e.geometry is not None and e.geometry.spans
        )

    def __len__(self) -> int:
        return len(self._evidencias)

    def __bool__(self) -> bool:
        return bool(self._evidencias)
