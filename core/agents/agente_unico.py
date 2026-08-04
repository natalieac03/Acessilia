"""Processa cada pagina: divide em regioes, roteia e remonta.

E o agente que faz o trabalho pesado. Para cada pagina, executa tres
fases: decide o destino de cada regiao na ordem do documento, processa
em paralelo as que precisam de visao computacional (limitado por
semaforo), e remonta o resultado na ordem original.

Texto limpo vai direto para a saida, sem IA. Formula, tabela e imagem
vao para o especialista de visao com o critico em seguida. As paginas
continuam sequenciais entre si — so as regioes de uma mesma pagina
rodam em paralelo.
"""

import asyncio
import re
import io
import os
from pathlib import Path
from typing import Any, Callable, Coroutine

import fitz
from PIL import Image

from config.settings import settings

if settings.ai_client == "openrouter":
    from core.ai.openrouter import client as ai_client
else:
    from core.ai.ollama import client as ai_client

from core.classificador_de_regioes import (
    classificar_regiao,
    regiao_tem_marcadores,
    regiao_precisa_de_visao,
    chave_de_prompt_da_regiao,
    reclassificar_para_formula,
)
from core.extrator_de_regioes import (
    Region,
    compute_adaptive_dpi,
    regiao_legivel,
)
from core.services.cache import obter_do_cache, gravar_no_cache
from core.estruturador import BaseStructurer, get_structurer
from core.utils.conversor_de_imagem import convert_pdf_to_png
from core.utils.melhorador_de_imagem import (
    enhance_image_for_ocr,
    preparar_imagem_regiao,
    resize_image,
)
from core.utils.logger import logger
from core.utils.divisor_de_pdf import split_pdf
from pipeline.geometria_de_pagina import catalogar_pagina
from pipeline.analisador_de_estrutura import MARCADOR_DECORATIVA, converter_texto_em_blocos

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "interfaces" / "telegram" / "prompts"

MODE_MAP = {
    "detalhado": "detalhado.txt",
    "medio": "medio.txt",
    "normal": "medio.txt",
    "baixo": "baixo.txt",
    "ocr": "ocr.txt",
}

REGION_PROMPT_MAP = {
    "regiao_imagem": "regiao_imagem.txt",
    "regiao_texto_escaneado": "regiao_texto_escaneado.txt",
    "regiao_tabela": "regiao_tabela.txt",
    "regiao_formula": "regiao_formula.txt",
}

REGION_MARKERS: dict[str, tuple[str, str]] = {
    "code_block": ("Início de código-fonte:", "Fim de código-fonte"),
    "list_block": ("Início de lista:", "Fim de lista"),
    "callout_box": ("Início de box:", "Fim de box"),
    "embedded_image": ("Início de imagem:", "Fim de imagem"),
    "formula": ("Início de fórmula:", "Fim de fórmula"),
}

CALLOUT_LABEL_MAP: dict[str, str] = {
    "note": "nota",
    "quote": "citação",
    "sidebar": "barra lateral",
    "warning": "aviso",
    "tip": "dica",
    "important": "importante",
}

def _apply_marker(text: str, classification: str, region: Region) -> str:
    markers = REGION_MARKERS.get(classification)
    if not markers:
        return text
    start, end = markers
    lab = region.metadata.get("docling_label", "")
    custom = CALLOUT_LABEL_MAP.get(lab)
    if custom:
        start = f"Início de {custom}:"
        end = f"Fim de {custom}"
    return f"{start}\n{text}\n{end}"


def _overlaps_clean(
    bbox: tuple[float, float, float, float],
    clean_bboxes: list[tuple[float, float, float, float]],
    threshold: float = 0.3,
) -> bool:
    x0, y0, x1, y1 = bbox
    area = max((x1 - x0) * (y1 - y0), 1)
    for cb in clean_bboxes:
        ox0 = max(x0, cb[0])
        oy0 = max(y0, cb[1])
        ox1 = min(x1, cb[2])
        oy1 = min(y1, cb[3])
        if ox0 < ox1 and oy0 < oy1:
            overlap = (ox1 - ox0) * (oy1 - oy0)
            if overlap / area >= threshold:
                return True
    return False


def _content_fingerprint(text: str) -> int:
    clean = " ".join(text.lower().split())
    return hash(clean)


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


_agno_ja_avisado = False


def _bbox_proximo(
    bbox_a: tuple[float, float, float, float],
    bbox_b: tuple[float, float, float, float],
    tolerance: float,
) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(bbox_a, bbox_b))


def _buscar_no_cache_posicional(
    cache: dict[tuple[float, float, float, float], str],
    bbox: tuple[float, float, float, float],
    tolerance: float,
) -> str | None:
    for bbox_visto, descricao in cache.items():
        if _bbox_proximo(bbox, bbox_visto, tolerance):
            return descricao
    return None


def _expandir_numeracao_slide(texto: str, total_pages: int) -> str:
    if total_pages <= 0:
        return texto

    def _substituir(m: "re.Match[str]") -> str:
        numero = int(m.group(1))
        if not 1 <= numero <= total_pages:
            return m.group(0)
        return f"Slide {numero} de {total_pages}"

    padrao = re.compile(rf"(?<!\d)(\d+)\s*/\s*{total_pages}(?!\d)")
    linhas = texto.split("\n")
    linhas = [
        l if l.lstrip().upper().startswith("LATEX:") else padrao.sub(_substituir, l)
        for l in linhas
    ]
    return "\n".join(linhas)


def _referencia_curta(descricao_completa: str) -> str:
    texto = descricao_completa.strip()

    if texto.startswith("[verificacao incerta]"):
        texto = texto[len("[verificacao incerta]"):].lstrip()

    for abertura in ("A imagem apresenta ", "A imagem mostra ", "A imagem contem "):
        if texto.startswith(abertura):
            texto = texto[len(abertura):]
            break

    cortes = [i for i in (texto.find(":"), texto.find(".")) if i != -1]
    tipologia = texto[: min(cortes)].strip() if cortes else texto.strip()

    estruturada = (
        "|" in tipologia
        or "\\" in tipologia
        or tipologia.upper() in ("LATEX", "LEITURA")
    )
    if tipologia and len(tipologia) <= 80 and not estruturada:
        tipologia = tipologia[0].upper() + tipologia[1:]
        return f"Aparece novamente: {tipologia}."
    return "O mesmo elemento visual aparece novamente."


_PADRAO_NUMERO_SLIDE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def _normalizar_numero_de_slide(texto: str, total_pages: int) -> str:
    match = _PADRAO_NUMERO_SLIDE.match(texto)
    if not match:
        return texto
    atual, total = int(match.group(1)), int(match.group(2))
    if total != total_pages:
        return texto
    return f"Slide {atual} de {total}."


def _avisar_agno_indisponivel(erro: Exception) -> None:
    global _agno_ja_avisado
    if not _agno_ja_avisado:
        _agno_ja_avisado = True
        logger.error(
            "USAR_AGNO=true mas o pacote nao esta instalado ({}). "
            "Usando o cliente de IA original. Para ativar: pip install agno openai",
            erro,
        )


_structurer: BaseStructurer | None = None


def _get_structurer() -> BaseStructurer:
    global _structurer
    if _structurer is None:
        _structurer = get_structurer()
    return _structurer


def _load_system_prompt(mode: str = "medio") -> str:
    filename = MODE_MAP.get(mode, "medio.txt")
    prompt_path = PROMPTS_DIR / filename
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")

    logger.warning(
        "Prompt file not found at {}, falling back to medio",
        prompt_path,
    )
    fallback = PROMPTS_DIR / "medio.txt"
    if fallback.exists():
        return fallback.read_text(encoding="utf-8")

    return (
        "Voce e um sistema de acessibilidade digital. Converta as imagens "
        "recebidas em texto acessivel para leitores de tela em portugues "
        "brasileiro. Descreva elementos visuais e extraia todo o texto "
        "presente."
    )


def _load_region_prompt(region_type: str) -> str:
    filename = REGION_PROMPT_MAP.get(region_type)
    if not filename:
        return ""
    prompt_path = PROMPTS_DIR / filename
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return ""


def _compress_to_jpg(
    image_bytes: bytes,
    max_width: int | None = None,
    quality: int | None = None,
) -> bytes:
    max_width = max_width or settings.max_page_width
    quality = quality or settings.jpg_quality

    img = Image.open(io.BytesIO(image_bytes))

    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        alpha = img.split()[-1] if "A" in img.mode else None
        background.paste(img, mask=alpha)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    width, height = img.size
    if width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        img = img.resize((max_width, new_height), Image.LANCZOS)

    output = io.BytesIO()
    img.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()


def _page_prompt(
    system_prompt: str,
    total_pages: int,
    page_num: int,
    is_pdf: bool,
) -> str:
    advanced_instructions = (
        "\n\nREGRAS DE FORMATAÇÃO E SEMÂNTICA:\n"
        "1. Se houver imagens, gráficos ou diagramas, forneça a "
        "audiodescrição entre colchetes.\n"
        "2. Preserve a ênfase do texto original usando Markdown apenas "
        "quando necessário.\n"
        "3. Para MATEMÁTICA: linearize fórmulas simples e use LaTeX para "
        "expressões complexas.\n"
        "4. Se um parágrafo termina com hífen ou parece continuar na "
        "próxima página, apenas transcreva-o."
    )

    prompt = system_prompt + advanced_instructions
    if is_pdf:
        prompt += (
            f"\n\nEste e o documento de {total_pages} paginas. "
            f"Voce esta processando a pagina {page_num} de {total_pages}."
        )
    return prompt


class AgenteUnico:
    POSITION_CACHE_MAX_AREA = 15000.0
    POSITION_CACHE_TOLERANCE = 3.0

    def __init__(self, mode: str = "medio"):
        self.metadados_acessilia: list[dict] = []
        self.mode = mode
        self.system_prompt = _load_system_prompt(mode)
        self.estruturador = _get_structurer()

    async def executar(
        self,
        file_path: Path,
        tmpdir: Path,
        status_callback: Callable[[str], Coroutine] | None = None,
        mode: str | None = None,
        structured_output: bool = False,
        custom_prompt: str | None = None,
        thinking_mode: bool = False,
    ) -> str | dict[str, Any]:
        effective_mode = mode or self.mode
        self.metadados_acessilia = []
        if custom_prompt:
            system_prompt = custom_prompt
        else:
            system_prompt = _load_system_prompt(effective_mode)
        if thinking_mode:
            system_prompt = "<|think|>\n" + system_prompt
        is_pdf = file_path.suffix.lower() == ".pdf"

        if is_pdf:
            if status_callback:
                await status_callback("📄 Separando PDF em paginas...")
            page_pdfs = split_pdf(file_path, tmpdir, settings.max_pages)
        else:
            if status_callback:
                await status_callback("🖼️ Preparando imagem...")
            page_pdfs = [file_path]

        total_pages = len(page_pdfs)
        if total_pages == 0:
            raise RuntimeError("Nenhuma pagina gerada a partir do arquivo")

        logger.info(
            "Processando {} pagina(s) para {} com estruturador={}",
            total_pages,
            file_path.name,
            self.estruturador.name,
        )

        results: list[str] = []
        page_payloads: list[dict[str, Any]] = []
        position_cache: dict[tuple[float, float, float, float], str] = {}
        catalogos_por_pagina: dict[int, Any] = {}

        try:
            from config.settings import settings as _cfg
            from core.services.assets_visuais import RepositorioDeAssets

            self._repositorio_de_assets = RepositorioDeAssets(
                Path(_cfg.temp_dir) / "output" / Path(file_path).stem
            )
        except Exception as erro_repo:
            logger.warning(
                "Repositorio de assets indisponivel ({}); imagens seguirao "
                "apenas como descricao", erro_repo,
            )
            self._repositorio_de_assets = None

        for index, page_path in enumerate(page_pdfs):
            page_num = index + 1
            if status_callback:
                label = f"📷 Processando pagina {page_num} de {total_pages}..."
                await status_callback(label)

            page_cache_key = f"page_{page_num}_{effective_mode}"
            cached_page = await obter_do_cache(
                page_path,
                page_cache_key,
                ttl=86400,
            )
            if cached_page:
                logger.info("[pag {}] Cache hit (pulando IA)", page_num)
                if is_pdf:
                    self._catalogar_do_arquivo(
                        page_path, page_num, catalogos_por_pagina
                    )
                results.append(cached_page)
                page_payloads.append(
                    {
                        "page_number": page_num,
                        "file_path": str(page_path),
                        "text": cached_page,
                        "blocks": converter_texto_em_blocos(
                            cached_page,
                            catalogos_por_pagina.get(page_num),
                        ),
                        "cached": True,
                    }
                )
                continue

            response = await self._process_page(
                page_path, page_num, total_pages, is_pdf,
                system_prompt, effective_mode, status_callback,
                position_cache, catalogos_por_pagina,
            )

            if is_pdf:
                response = _expandir_numeracao_slide(response, total_pages)

            if not response.strip():
                logger.warning("Resposta vazia para pagina {}", page_num)
                response = f"[Pagina {page_num}: resposta vazia do modelo]"

            await gravar_no_cache(page_path, response, page_cache_key)

            output_file = tmpdir / f"imagen{page_num:03d}.txt"
            output_file.write_text(response, encoding="utf-8")
            logger.info(
                "Resposta da pagina {} salva em {}",
                page_num,
                output_file.name,
            )

            results.append(response)
            page_payloads.append(
                {
                    "page_number": page_num,
                    "file_path": str(page_path),
                    "text": response,
                    "blocks": converter_texto_em_blocos(
                        response, catalogos_por_pagina.get(page_num)
                    ),
                    "cached": False,
                }
            )

        texto_final = "\n\n".join(
            f"=== Pagina {i + 1} ===\n{response}"
            for i, response in enumerate(results)
        )

        logger.info(
            "AgenteUnico: {} paginas processadas, {} chars no total",
            total_pages,
            len(texto_final),
        )
        try:
            from core.services import telemetria
            telemetria.atualizar_documento_atual(paginas=total_pages)
        except Exception:
            pass

        if structured_output:
            return {
                "text": texto_final,
                "pages": page_payloads,
                "page_count": total_pages,
                "mode": effective_mode,
                "source_path": str(file_path),
            }

        return texto_final

    def _catalogar_do_arquivo(
        self,
        page_path: Path,
        page_num: int,
        catalogos_por_pagina: dict[int, Any] | None,
    ) -> None:
        if catalogos_por_pagina is None:
            return
        doc = None
        try:
            doc = fitz.open(page_path)
            page = doc[0]
            regions = self.estruturador.extract_page_regions(page)
            try:
                from pipeline.matematica.agrupador_matematico import (
                    fundir_fragmentos_em_regioes,
                )

                regions = fundir_fragmentos_em_regioes(regions, page_num)
            except Exception:
                pass
            self._catalogar(
                page, regions, page_path, page_num, catalogos_por_pagina
            )
        except Exception as erro:
            logger.warning(
                "[pag {}] Nao foi possivel catalogar geometria do cache ({})",
                page_num,
                f"{type(erro).__name__}: {erro}",
            )
        finally:
            if doc is not None:
                doc.close()

    def _catalogar(
        self,
        page,
        regions: list,
        page_path: Path,
        page_num: int,
        catalogos_por_pagina: dict[int, Any] | None,
    ) -> None:
        if catalogos_por_pagina is None:
            return
        try:
            catalogo = catalogar_pagina(
                page=page,
                regioes=regions,
                document_id=page_path.stem,
                page_number=page_num,
            )
            catalogos_por_pagina[page_num] = catalogo
            logger.info(
                "[pag {}] Geometria catalogada: {} regiao(oes), {} com spans",
                page_num,
                len(catalogo),
                catalogo.com_geometria,
            )
        except Exception as erro:
            logger.warning(
                "[pag {}] Catalogacao de geometria falhou ({}); "
                "a camada matematica seguira sem geometria",
                page_num,
                f"{type(erro).__name__}: {erro}",
            )

    async def _process_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        is_pdf: bool,
        system_prompt: str,
        effective_mode: str,
        status_callback: Callable[[str], Coroutine] | None,
        position_cache: dict[tuple[float, float, float, float], str] | None = None,
        catalogos_por_pagina: dict[int, Any] | None = None,
    ) -> str:
        if is_pdf:
            return await self._process_pdf_page(
                page_path, page_num, total_pages, system_prompt,
                effective_mode, status_callback, position_cache,
                catalogos_por_pagina,
            )

        return await self._process_image_page(
            page_path, page_num, total_pages, system_prompt, status_callback,
        )

    async def _process_pdf_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        effective_mode: str,
        status_callback: Callable[[str], Coroutine] | None,
        position_cache: dict[tuple[float, float, float, float], str] | None = None,
        catalogos_por_pagina: dict[int, Any] | None = None,
    ) -> str:
        doc = fitz.open(page_path)
        try:
            page = doc[0]
            regions = self.estruturador.extract_page_regions(page)
            try:
                from pipeline.matematica.agrupador_matematico import (
                    fundir_fragmentos_em_regioes,
                )

                regions = fundir_fragmentos_em_regioes(regions, page_num)
            except Exception as erro_fusao:
                logger.warning(
                    "Fusao de fragmentos indisponivel ({})", erro_fusao
                )
            self._catalogar(
                page, regions, page_path, page_num, catalogos_por_pagina
            )
        finally:
            doc.close()

        if not regions:
            return ""

        logger.info(
            "[pag {}] Extraidas {} regioes na pagina (estruturador={})",
            page_num,
            len(regions),
            self.estruturador.name,
        )

        all_text_clean = True
        for r in regions:
            classification = classificar_regiao(r)
            if classification != "text_clean" and classification != "ignore":
                all_text_clean = False
                break

        if all_text_clean:
            text_parts: list[str] = []
            clean_fps: set[int] = set()
            for region in regions:
                classification = classificar_regiao(region)
                if classification == "text_clean" and region.text.strip():
                    fp = _content_fingerprint(region.text)
                    if fp not in clean_fps:
                        clean_fps.add(fp)
                        text_parts.append(region.text)
                elif regiao_tem_marcadores(classification) and region.text.strip():
                    fp = _content_fingerprint(region.text)
                    if fp not in clean_fps:
                        clean_fps.add(fp)
                        text_parts.append(_apply_marker(region.text, classification, region))
            full_text = "\n\n".join(text_parts)

            if len(full_text) >= 20:
                logger.info(
                    "[pag {}] {} regioes de texto limpo (sem IA de visao)",
                    page_num,
                    len(text_parts),
                )
                return full_text

        return await self._process_with_vision_by_regions(
            page_path, page_num, total_pages, system_prompt, status_callback,
            position_cache, catalogos_por_pagina,
        )

    async def _process_with_vision_by_regions(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        status_callback: Callable[[str], Coroutine] | None,
        position_cache: dict[tuple[float, float, float, float], str] | None = None,
        catalogos_por_pagina: dict[int, Any] | None = None,
    ) -> str:
        doc = fitz.open(page_path)
        try:
            page = doc[0]
            regions = self.estruturador.extract_page_regions(page)
            try:
                from pipeline.matematica.agrupador_matematico import (
                    fundir_fragmentos_em_regioes,
                )

                regions = fundir_fragmentos_em_regioes(regions, page_num)
            except Exception:
                pass
            self._catalogar(
                page, regions, page_path, page_num, catalogos_por_pagina
            )
        finally:
            doc.close()

        text_parts: list[str] = []
        vision_count = 0
        clean_bboxes: list[tuple[float, float, float, float]] = []
        content_fingerprints: set[int] = set()

        plano = None
        try:
            from core.agents.planejador import planejar

            plano = planejar(regions, pagina=page_num)
        except Exception as erro_plano:
            logger.warning(
                "[pag {}] Planejador indisponivel ({}); seguindo sem plano",
                page_num, erro_plano,
            )

        contexto_pagina = "\n".join(
            r.text.strip()
            for r in regions
            if classificar_regiao(r) == "text_clean" and r.text.strip()
        )

        catalogo_da_pagina = (catalogos_por_pagina or {}).get(page_num)
        try:
            from pipeline.matematica.agrupador_matematico import (
                agrupar_blocos_matematicos,
            )

            for grupo in agrupar_blocos_matematicos(regions):
                if not grupo.fragmentado or catalogo_da_pagina is None:
                    continue
                for indice in grupo.indices:
                    outros = [
                        regions[i].text for i in grupo.indices
                        if i != indice and regions[i].text
                    ]
                    if outros:
                        catalogo_da_pagina.registrar_vizinhos(
                            regions[indice].text or "", outros
                        )
                logger.info(
                    "[pag {}] expressao fragmentada reunida: {!r} "
                    "({} regioes)",
                    page_num, grupo.texto[:60], len(grupo.indices),
                )
        except Exception as erro_grupo:
            logger.warning(
                "Agrupador matematico indisponivel ({}); seguindo sem "
                "reuniao de fragmentos", erro_grupo,
            )

        partes: list[tuple[str, object]] = []
        visao_pendentes: list[tuple[str, object]] = []

        for region in regions:
            classification = classificar_regiao(region)

            classification = reclassificar_para_formula(
                classification, region.text or ""
            )
            try:
                from core.services import telemetria
                telemetria.contar_regiao(classification)
            except Exception:
                pass

            if classification == "ignore":
                continue

            if classification == "text_clean" and region.text.strip():
                fp = _content_fingerprint(region.text)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    texto = _normalizar_numero_de_slide(
                        region.text.strip(), total_pages
                    )
                    partes.append(("texto", texto))
                    clean_bboxes.append(region.bbox)
                continue

            if (
                regiao_tem_marcadores(classification)
                and not regiao_precisa_de_visao(classification)
                and region.text.strip()
            ):
                fp = _content_fingerprint(region.text)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    partes.append(
                        ("texto", _apply_marker(region.text, classification, region))
                    )
                    clean_bboxes.append(region.bbox)
                continue

            if regiao_precisa_de_visao(classification):
                if classification in ("unknown", "text_scanned") and _overlaps_clean(
                    region.bbox, clean_bboxes
                ):
                    if region.text.strip():
                        fp = _content_fingerprint(region.text)
                        if fp not in content_fingerprints:
                            content_fingerprints.add(fp)
                            partes.append(("texto", region.text))
                    continue
                vision_count += 1
                logger.info(
                    "[pag {}] Regiao {} - tipo={}, bbox={}",
                    page_num,
                    len(partes) + 1,
                    classification,
                    region.bbox,
                )
                partes.append(("visao", len(visao_pendentes)))
                visao_pendentes.append((classification, region))

        resultados_visao: list[str] = []
        if visao_pendentes:
            limite = max(1, int(os.getenv("REGIOES_CONCORRENTES", "3") or "3"))
            semaforo = asyncio.Semaphore(limite)

            async def _com_limite(cls: str, reg) -> str:
                async with semaforo:
                    return await self._process_region_with_vision(
                        page_path, reg, cls, page_num,
                        total_pages, system_prompt, status_callback,
                        position_cache, contexto_pagina,
                        plano=plano, regioes_da_pagina=regions,
                        catalogo=(catalogos_por_pagina or {}).get(page_num),
                    )

            resultados_visao = list(
                await asyncio.gather(
                    *[_com_limite(c, r) for c, r in visao_pendentes]
                )
            )

        for tipo_parte, valor in partes:
            if tipo_parte == "texto":
                text_parts.append(valor)
                continue
            classification, region = visao_pendentes[valor]
            region_desc = resultados_visao[valor]
            if region_desc.strip():
                fp = _content_fingerprint(region_desc)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    if regiao_tem_marcadores(classification):
                        region_desc = _apply_marker(
                            region_desc, classification, region
                        )
                    text_parts.append(region_desc)

        if not text_parts:
            logger.warning(
                "[pag {}] Nenhum texto extraido por regioes, "
                "fallback para pagina inteira",
                page_num,
            )
            return await self._fallback_whole_page(
                page_path, page_num, total_pages, system_prompt,
                status_callback,
            )

        logger.info(
            "[pag {}] {} regioes ({}, {} visao sequencial)",
            page_num,
            len(text_parts),
            len(text_parts) - vision_count,
            vision_count,
        )

        return "\n\n".join(text_parts)

    async def _process_region_with_vision(
        self,
        page_path: Path,
        region: Region,
        classification: str,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        status_callback: Callable[[str], Coroutine] | None,
        position_cache: dict[tuple[float, float, float, float], str] | None = None,
        contexto_pagina: str | None = None,
        plano=None,
        regioes_da_pagina: list | None = None,
        catalogo=None,
    ) -> str:
        is_small_region = _bbox_area(region.bbox) <= self.POSITION_CACHE_MAX_AREA
        cache_key = None
        if position_cache is not None and is_small_region:
            cache_key = region.bbox
            cached_desc = _buscar_no_cache_posicional(
                position_cache, region.bbox, self.POSITION_CACHE_TOLERANCE
            )
            if cached_desc is not None:
                logger.info(
                    "[pag {}] Regiao recorrente na mesma posicao de pagina "
                    "anterior - usando referencia curta (sem chamar IA)",
                    page_num,
                )
                referencia = _referencia_curta(cached_desc)
                self._registrar_acessilia(
                    referencia, page_num, classification, region.bbox,
                    origem="cache_posicional",
                    limitacoes=[
                        "Elemento recorrente: referencia curta derivada de "
                        "descricao ja verificada em pagina anterior"
                    ],
                    review_status="reviewed",
                )
                return referencia

        meta_critico = {"confianca": None, "suspeitas": [], "verificada": False}

        prompt_key = chave_de_prompt_da_regiao(classification)
        base_prompt = _load_region_prompt(prompt_key)

        if not base_prompt:
            base_prompt = system_prompt

        region_prompt = base_prompt

        try:
            doc = fitz.open(page_path)
            try:
                page = doc[0]
                dpi = compute_adaptive_dpi(region.bbox)
                region_png = self.estruturador.crop_region(page, region.bbox, dpi=dpi)
            finally:
                doc.close()

            with Image.open(io.BytesIO(region_png)) as _img:
                larg_px, alt_px = _img.size
            if not regiao_legivel(larg_px, alt_px):
                logger.info(
                    "[pag {}] Regiao {} ilegivel ({}x{} px) - nao sera enviada a IA",
                    page_num,
                    classification,
                    larg_px,
                    alt_px,
                )
                return region.text.strip() or MARCADOR_DECORATIVA

            jpg_bytes = preparar_imagem_regiao(region_png, classification)

            if classification == "embedded_image" and catalogo is not None:
                try:
                    from core.services.assets_visuais import (
                        RepositorioDeAssets,
                    )

                    repositorio = getattr(self, "_repositorio_de_assets", None)
                    if repositorio is not None:
                        asset = (
                            repositorio.gravar_regiao(region)
                            or repositorio.gravar(
                                region_png, page_num, "png",
                                source_bbox=region.bbox,
                            )
                        )
                        if asset is not None:
                            catalogo.registrar_asset(region.bbox, asset)
                            logger.debug(
                                "[pag {}] asset gravado: {}",
                                page_num, asset.asset_path,
                            )
                except Exception as erro_asset:
                    logger.warning(
                        "Asset nao gravado ({}); a descricao segue sem "
                        "arquivo de imagem", erro_asset,
                    )

            if classification == "unknown":
                try:
                    from pipeline.evidencia_do_recorte import (
                        analisar_conteudo_do_recorte, especialista_para,
                    )

                    evidencia_recorte = analisar_conteudo_do_recorte(
                        region_png, region.text or ""
                    )
                    destino = especialista_para(evidencia_recorte)
                    if destino is None:
                        logger.info(
                            "[pag {}] regiao unknown sem conteudo "
                            "verificavel ({}) - ignorada sem chamar IA",
                            page_num, evidencia_recorte.motivo,
                        )
                        self._registrar_acessilia(
                            "", page_num, classification, region.bbox,
                            origem="ignorada",
                            limitacoes=[
                                f"Regiao sem conteudo verificavel: "
                                f"{evidencia_recorte.motivo}"
                            ],
                            review_status="reviewed",
                        )
                        return region.text.strip() or MARCADOR_DECORATIVA
                    if destino != prompt_key:
                        logger.info(
                            "[pag {}] regiao unknown roteada para {} "
                            "por evidencia: {}",
                            page_num, destino, evidencia_recorte.motivo,
                        )
                        prompt_key = destino
                        novo_prompt = _load_region_prompt(destino)
                        if novo_prompt:
                            region_prompt = novo_prompt
                except Exception as erro_evid:
                    logger.warning(
                        "Detector de conteudo indisponivel ({}); "
                        "seguindo com o roteamento padrao", erro_evid,
                    )

            logger.debug(
                "[pag {}] Enviando regiao para visao ({}x{} px @ {} dpi, "
                "{} bytes, tipo={})",
                page_num,
                larg_px,
                alt_px,
                dpi,
                len(jpg_bytes),
                classification,
            )

            try:
                from core.services import telemetria
                telemetria.marcar_regiao(
                    page_num, getattr(region, "index", None), classification
                )
            except Exception:
                pass

            _descrever = None
            if os.getenv("USAR_AGNO", "false").lower() == "true":
                try:
                    if os.getenv("USAR_CRITICO", "false").lower() == "true":
                        from core.agents.critico_visual import (
                            descrever_regiao_verificada_com_meta as _descrever,
                        )
                        _rotulo = "especialista Agno + critico"
                    else:
                        from core.agents.especialistas_agno import (
                            descrever_regiao as _descrever,
                        )
                        _rotulo = "especialista Agno"
                except ImportError as erro_import:
                    _avisar_agno_indisponivel(erro_import)
                    _descrever = None

            if _descrever is not None:
                logger.info("[pag {}] {}: {}", page_num, _rotulo, classification)

                try:
                    from pipeline.contexto_e_evidencia import contexto_para

                    contexto_desta_regiao = contexto_para(
                        classification, region, regioes_da_pagina or [],
                        contexto_pagina or "",
                    )
                except Exception:
                    contexto_desta_regiao = None

                result = await asyncio.to_thread(
                    _descrever, classification, jpg_bytes,
                    contexto_desta_regiao,
                )
                if isinstance(result, tuple):
                    result, meta_critico = result
                else:
                    meta_critico = {
                        "confianca": None, "suspeitas": [], "verificada": False,
                    }

            else:
                logger.info(
                    "[pag {}] cliente de IA original: {}", page_num, classification
                )
                result = await ai_client.send_message(
                    text=region_prompt,
                    images=[jpg_bytes],
                )

            result = result.strip()

            try:
                from core.agents.acessivel import normalizar_descricao

                result = (
                    await asyncio.to_thread(
                        normalizar_descricao, result, classification
                    )
                ).strip()
            except Exception as erro_acessivel:
                logger.warning(
                    "[pag {}] acessivel indisponivel ({}); seguindo",
                    page_num,
                    erro_acessivel,
                )

            if plano is not None and classification == "formula":
                try:
                    indice = (
                        regioes_da_pagina.index(region)
                        if regioes_da_pagina else -1
                    )
                    if indice >= 0:
                        vizinhos = plano.textos_vizinhos(
                            indice, regioes_da_pagina
                        )
                        if vizinhos and catalogo is not None:
                            catalogo.registrar_vizinhos(
                                region.text or "", vizinhos
                            )
                            logger.info(
                                "[pag {}] regiao {}: {} vizinho(s) "
                                "registrados para fechar a fronteira",
                                page_num, indice, len(vizinhos),
                            )
                except Exception:
                    pass

            if classification == "formula":
                try:
                    from core.agents.conferidor_de_formulas import (
                        conferir_e_marcar_formula,
                    )

                    result = (
                        await asyncio.to_thread(conferir_e_marcar_formula, result)
                    ).strip()
                except ImportError as erro_import:
                    _avisar_agno_indisponivel(erro_import)

                try:
                    from core.agents.conferidor_de_formulas import (
                        auditar_descricao_de_formula,
                    )

                    result, veredito_math = await asyncio.to_thread(
                        auditar_descricao_de_formula,
                        result,
                        region.text or None,
                    )
                    if not veredito_math.get("fiel", True):
                        logger.warning(
                            "[pag {}] critico matematico reprovou ({}): {}",
                            page_num,
                            veredito_math.get("camada"),
                            "; ".join(veredito_math.get("problemas", []))[:180],
                        )
                    result = result.strip()
                except Exception as erro_math:
                    logger.warning(
                        "[pag {}] critico matematico indisponivel ({}); "
                        "seguindo",
                        page_num,
                        erro_math,
                    )

            if position_cache is not None and cache_key is not None:
                position_cache[cache_key] = result


            limitacoes_finais = []
            if result.strip() == "[imagem decorativa]":
                limitacoes_finais.append(
                    "Classificada como decorativa: silenciada nos formatos "
                    "finais (equivalente ao alt vazio)"
                )
            self._registrar_acessilia(
                result, page_num, classification, region.bbox,
                origem="visao",
                confianca=meta_critico.get("confianca"),
                suspeitas=meta_critico.get("suspeitas"),
                limitacoes=limitacoes_finais,
            )
            return result

        except Exception as error:
            import traceback
            tb = traceback.format_exc()
            logger.critical(
                "[pag {}] Erro na regiao {}: {} | Traceback:\n{}",
                page_num,
                classification,
                error,
                tb,
            )
            if region.text.strip():
                self._registrar_acessilia(
                    region.text, page_num, classification, region.bbox,
                    origem="fallback",
                    limitacoes=[
                        "Visao falhou; texto extraido localmente sem verificacao"
                    ],
                )
                return region.text
            aviso_falha = f"[falha ao processar esta regiao: {classification}]"
            self._registrar_acessilia(
                aviso_falha, page_num, classification, region.bbox,
                origem="fallback",
                limitacoes=["Falha no processamento; conteudo perdido"],
            )
            return aviso_falha

    def _registrar_acessilia(
        self,
        descricao: str,
        pagina: int,
        tipo: str,
        bbox,
        *,
        origem: str,
        confianca: float | None = None,
        suspeitas: list[str] | None = None,
        limitacoes: list[str] | None = None,
        review_status: str | None = None,
    ) -> None:
        try:
            from core.services.acessilia_meta import montar_metadado

            self.metadados_acessilia.append(
                montar_metadado(
                    descricao,
                    pagina=pagina,
                    tipo=tipo,
                    bbox=tuple(bbox) if bbox else None,
                    confianca=confianca,
                    suspeitas=suspeitas,
                    limitacoes=limitacoes,
                    origem=origem,
                    review_status=review_status,
                )
            )
        except Exception as erro:
            logger.warning("Metadado ACESSILIA nao registrado ({})", erro)

    async def _fallback_whole_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        status_callback: Callable[[str], Coroutine] | None,
    ) -> str:
        logger.info(
            "[pag {}] Fallback: enviando pagina inteira para IA de visao",
            page_num,
        )

        png_bytes = convert_pdf_to_png(page_path, settings.pdf_split_dpi)
        jpg_bytes = _compress_to_jpg(png_bytes)
        jpg_bytes = enhance_image_for_ocr(jpg_bytes)
        jpg_bytes = resize_image(jpg_bytes)

        prompt = _page_prompt(system_prompt, total_pages, page_num, is_pdf=True)

        result = await ai_client.send_message(
            text=prompt,
            images=[jpg_bytes],
        )

        return result.strip()

    async def _process_image_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        status_callback: Callable[[str], Coroutine] | None,
    ) -> str:
        logger.debug("[pag {}] lendo imagem: {}", page_num, page_path)
        with open(page_path, "rb") as file_handle:
            raw_bytes = file_handle.read()

        jpg_bytes = _compress_to_jpg(raw_bytes)
        jpg_bytes = enhance_image_for_ocr(jpg_bytes)
        jpg_bytes = resize_image(jpg_bytes)

        logger.info(
            "Enviando pagina {} para IA de visao ({} bytes)",
            page_num,
            len(jpg_bytes),
        )

        prompt = _page_prompt(system_prompt, total_pages, page_num, is_pdf=False)

        result = await ai_client.send_message(
            text=prompt,
            images=[jpg_bytes],
        )

        return result.strip()
