"""Decide por pixel que tipo de conteudo ha num recorte.

Existe porque "desconhecido" significa "o classificador nao soube
dizer", e nao "texto escaneado" — mas o roteamento antigo mandava todo
desconhecido para o prompt de OCR.

Um prompt de OCR aplicado a um recorte sem texto nenhum nao responde
"nao ha texto aqui": devolve texto inventado, porque foi isso que
pediram ao modelo. Era uma fabrica de alucinacao alimentada pela
propria incerteza do classificador. Aqui a pergunta e respondida por
pixel, antes de qualquer IA — e sem evidencia de conteudo, nenhuma IA
e chamada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DENSIDADE_MINIMA = 0.005

MIN_LINHAS_PARA_TEXTO = 2
MAX_COBERTURA_DE_LINHA = 0.75

TONS_PARA_FOTOGRAFIA = 40


@dataclass
class EvidenciaDoRecorte:

    kind: str
    densidade: float = 0.0
    linhas_detectadas: int = 0
    tons_distintos: int = 0
    motivo: str = ""
    sinais: list[str] = field(default_factory=list)

    @property
    def tem_conteudo(self) -> bool:
        return self.kind != "unresolved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "densidade": round(self.densidade, 4),
            "linhas_detectadas": self.linhas_detectadas,
            "tons_distintos": self.tons_distintos,
            "motivo": self.motivo,
            "sinais": list(self.sinais),
        }


def _perfil_horizontal(cinza, largura: int, altura: int) -> list[float]:
    perfil = []
    for y in range(altura):
        inicio = y * largura
        linha = cinza[inicio:inicio + largura]
        if not linha:
            perfil.append(0.0)
            continue
        perfil.append(sum(1 for v in linha if v < 200) / len(linha))
    return perfil


def _contar_faixas(perfil: list[float], limiar: float = 0.02) -> int:
    faixas = 0
    dentro = False
    for valor in perfil:
        if valor >= limiar and not dentro:
            faixas += 1
            dentro = True
        elif valor < limiar:
            dentro = False
    return faixas


def analisar_conteudo_do_recorte(
    imagem_bytes: bytes | None, texto_extraido: str = ""
) -> EvidenciaDoRecorte:
    if (texto_extraido or "").strip():
        from core.classificador_de_regioes import parece_formula

        if parece_formula(texto_extraido):
            return EvidenciaDoRecorte(
                kind="formula", motivo="texto extraido parece formula",
                sinais=["texto_do_pdf"],
            )
        return EvidenciaDoRecorte(
            kind="raster_text", motivo="texto ja disponivel no PDF",
            sinais=["texto_do_pdf"],
        )

    if not imagem_bytes:
        return EvidenciaDoRecorte(
            kind="unresolved", motivo="sem bytes de imagem"
        )

    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(imagem_bytes)) as img:
            cinza_img = img.convert("L")
            largura, altura = cinza_img.size
            if largura < 8 or altura < 8:
                return EvidenciaDoRecorte(
                    kind="unresolved", motivo="recorte pequeno demais"
                )
            obter = getattr(cinza_img, "get_flattened_data", None)
            cinza = list(obter() if obter else cinza_img.getdata())
            tons = len(set(cinza))
    except Exception:
        return EvidenciaDoRecorte(
            kind="unresolved", motivo="recorte ilegivel"
        )

    total = len(cinza) or 1
    densidade = sum(1 for v in cinza if v < 200) / total

    if densidade < DENSIDADE_MINIMA:
        return EvidenciaDoRecorte(
            kind="unresolved", densidade=densidade, tons_distintos=tons,
            motivo="recorte praticamente branco",
        )

    perfil = _perfil_horizontal(cinza, largura, altura)
    faixas = _contar_faixas(perfil)
    cobertura_vertical = sum(1 for v in perfil if v >= 0.02) / (len(perfil) or 1)

    if tons >= TONS_PARA_FOTOGRAFIA and cobertura_vertical > MAX_COBERTURA_DE_LINHA:
        return EvidenciaDoRecorte(
            kind="visual_object", densidade=densidade,
            linhas_detectadas=faixas, tons_distintos=tons,
            motivo="muitos tons e tinta continua: fotografia ou ilustracao",
            sinais=["tons_altos", "cobertura_continua"],
        )

    if faixas >= MIN_LINHAS_PARA_TEXTO and cobertura_vertical <= MAX_COBERTURA_DE_LINHA:
        return EvidenciaDoRecorte(
            kind="raster_text", densidade=densidade,
            linhas_detectadas=faixas, tons_distintos=tons,
            motivo="tinta organizada em faixas horizontais",
            sinais=["faixas_horizontais"],
        )

    return EvidenciaDoRecorte(
        kind="vector_complex", densidade=densidade,
        linhas_detectadas=faixas, tons_distintos=tons,
        motivo="tinta estruturada sem padrao de linhas de texto",
        sinais=["estrutura_sem_linhas"],
    )


_ESPECIALISTA_POR_EVIDENCIA = {
    "raster_text": "regiao_texto_escaneado",
    "formula": "regiao_formula",
    "visual_object": "regiao_imagem",
    "vector_complex": "regiao_imagem",
}


def especialista_para(evidencia: EvidenciaDoRecorte) -> str | None:
    return _ESPECIALISTA_POR_EVIDENCIA.get(evidencia.kind)
