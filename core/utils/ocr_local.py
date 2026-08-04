"""OCR local com Tesseract — tentativa barata antes de chamar a IA.

Fica desligado por padrão (USAR_OCR_LOCAL=false). Quando ligado, region
classificada como text_scanned ou unknown passa primeiro por aqui; só
vai pro Especialista de visao (que custa uma chamada de API) se o OCR
local nao conseguir extrair um texto minimamente confiavel.

A confianca nao e so a media que o Tesseract devolve: uma pagina em
branco com um traco de sujeira pode "reconhecer" duas letras com 95%
de confianca e ainda assim nao ser leitura confiavel de verdade. Por
isso o veredito cruza tres coisas: confianca media, quantidade minima
de caracteres, e proporcao de caracteres alfanumericos (garbled OCR
tende a devolver muito simbolo solto).

Fail-open sempre: sem o binario do tesseract instalado, ou qualquer
excecao na leitura, devolve resultado nao confiavel — o roteamento
segue pro caminho de IA como se este modulo nao existisse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CONFIANCA_MINIMA = 60.0
CARACTERES_MINIMOS = 8
PROPORCAO_ALFANUMERICA_MINIMA = 0.6

_ALFANUMERICO = re.compile(r"[^\W\d_]|\d", re.UNICODE)


@dataclass
class ResultadoOcrLocal:
    texto: str
    confianca_media: float
    confiavel: bool
    motivo: str


def _proporcao_alfanumerica(texto: str) -> float:
    sem_espaco = texto.replace(" ", "").replace("\n", "")
    if not sem_espaco:
        return 0.0
    alfanumericos = len(_ALFANUMERICO.findall(sem_espaco))
    return alfanumericos / len(sem_espaco)


def extrair_texto_local(imagem_png: bytes, idioma: str = "por") -> ResultadoOcrLocal:
    try:
        import pytesseract
        from PIL import Image
        import io

        from config.settings import settings

        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

        img = Image.open(io.BytesIO(imagem_png))
        dados = pytesseract.image_to_data(
            img, lang=idioma, output_type=pytesseract.Output.DICT
        )
    except Exception as erro:
        return ResultadoOcrLocal(
            texto="", confianca_media=0.0, confiavel=False,
            motivo=f"ocr indisponivel: {erro}",
        )

    palavras, confiancas = [], []
    for texto, conf in zip(dados.get("text", []), dados.get("conf", [])):
        texto = texto.strip()
        if not texto:
            continue
        try:
            conf_num = float(conf)
        except (TypeError, ValueError):
            continue
        if conf_num < 0:
            continue
        palavras.append(texto)
        confiancas.append(conf_num)

    texto_final = " ".join(palavras).strip()
    confianca_media = sum(confiancas) / len(confiancas) if confiancas else 0.0

    if not texto_final:
        return ResultadoOcrLocal(
            texto="", confianca_media=0.0, confiavel=False,
            motivo="nenhum caractere reconhecido",
        )
    if len(texto_final) < CARACTERES_MINIMOS:
        return ResultadoOcrLocal(
            texto=texto_final, confianca_media=confianca_media, confiavel=False,
            motivo=f"texto curto demais ({len(texto_final)} caracteres)",
        )
    if confianca_media < CONFIANCA_MINIMA:
        return ResultadoOcrLocal(
            texto=texto_final, confianca_media=confianca_media, confiavel=False,
            motivo=f"confianca media baixa ({confianca_media:.0f}%)",
        )
    proporcao = _proporcao_alfanumerica(texto_final)
    if proporcao < PROPORCAO_ALFANUMERICA_MINIMA:
        return ResultadoOcrLocal(
            texto=texto_final, confianca_media=confianca_media, confiavel=False,
            motivo=f"proporcao alfanumerica baixa ({proporcao:.0%}) — provavel garbled",
        )

    return ResultadoOcrLocal(
        texto=texto_final, confianca_media=confianca_media, confiavel=True,
        motivo="ok",
    )
