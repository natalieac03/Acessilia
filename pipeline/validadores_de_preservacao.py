"""Confere se o que entrou chegou ao outro lado.

Tres perguntas em pontos diferentes do pipeline: LaTeX, MathML, OMML e
fala descrevem a mesma expressao? As imagens do documento canonico
existem nos artefatos gerados? A soma dos textos de origem reconstitui
o material original?

Sao deterministicos e baratos — contam simbolos e comparam conjuntos.
Um modelo avaliando a propria saida tenderia a aprova-la.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_ESTRUTURAS = {
    "fracao": (r"\\frac", r"<mfrac", r"<m:f[ >]", r"fra[çc][ãa]o"),
    "raiz": (r"\\sqrt", r"<msqrt|<mroot", r"<m:rad", r"raiz"),
    "potencia": (r"\^", r"<msup", r"<m:sSup", r"ao quadrado|ao cubo|elevado"),
    "indice": (r"_", r"<msub", r"<m:sSub", r"[íi]ndice|subscrito"),
}


def _tem(padrao: str, texto: str) -> bool:
    return bool(re.search(padrao, texto or "", re.IGNORECASE))


def validar_assinaturas_entre_formatos(no: Any) -> list[dict[str, Any]]:
    latex = getattr(no, "latex", "") or ""
    mathml = getattr(no, "mathml", "") or ""
    omml = getattr(no, "omml", "") or ""
    fala = getattr(no, "speech_pt_br", "") or ""

    issues: list[dict[str, Any]] = []
    if not latex.strip():
        return issues

    for nome, (p_latex, p_mathml, p_omml, p_fala) in _ESTRUTURAS.items():
        no_latex = _tem(p_latex, latex)
        if not no_latex:
            continue
        faltando = []
        if mathml and not _tem(p_mathml, mathml):
            faltando.append("MathML")
        if omml and not _tem(p_omml, omml):
            faltando.append("OMML")
        if fala and not _tem(p_fala, fala):
            faltando.append("fala")
        if faltando:
            issues.append({
                "severity": "ERROR",
                "message": (
                    f"A estrutura '{nome}' existe no LaTeX mas nao em "
                    f"{', '.join(faltando)}: as representacoes divergem."
                ),
                "evidence": {"estrutura": nome, "faltando": faltando},
            })

    numeros_latex = set(re.findall(r"\d+", latex))
    if mathml and numeros_latex:
        numeros_mathml = set(re.findall(r"\d+", mathml))
        perdidos = numeros_latex - numeros_mathml
        if perdidos:
            issues.append({
                "severity": "ERROR",
                "message": (
                    f"Numero(s) {sorted(perdidos)} presentes no LaTeX e "
                    "ausentes no MathML."
                ),
            })
    return issues


def _blocos(documento: dict[str, Any]):
    def _secao(secao):
        for bloco in secao.get("blocks", []) or []:
            yield bloco
        for filha in secao.get("children", []) or []:
            yield from _secao(filha)

    for secao in documento.get("sections", []) or []:
        yield from _secao(secao)
    for bloco in documento.get("blocks", []) or []:
        yield bloco


def contar_imagens_html(caminho: str | Path) -> int:
    try:
        html = Path(caminho).read_text(encoding="utf-8")
    except OSError:
        return 0
    return len(re.findall(r'<img[^>]+src="[^"]+"', html))


def contar_midias_docx(caminho: str | Path) -> int:
    import zipfile

    try:
        with zipfile.ZipFile(caminho) as z:
            return len([
                n for n in z.namelist() if n.startswith("word/media/")
            ])
    except Exception:
        return 0


def contar_imagens_pdf(caminho: str | Path) -> int:
    try:
        import fitz

        doc = fitz.open(caminho)
        try:
            return sum(len(doc[p].get_images(full=True)) for p in range(len(doc)))
        finally:
            doc.close()
    except Exception:
        return 0


def validar_preservacao_de_assets(
    documento: dict[str, Any], outputs: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    esperadas = 0

    for bloco in _blocos(documento):
        if bloco.get("type") != "image" or bloco.get("decorative"):
            continue
        esperadas += 1
        metadata = bloco.get("metadata") or {}
        caminho = bloco.get("asset_path") or metadata.get("asset_path")
        bloco_id = str(bloco.get("id") or "")

        if not caminho:
            issues.append({
                "code": "ASSET-001", "severity": "WARNING",
                "message": (
                    "Bloco de imagem sem asset: a figura chega apenas "
                    "como descricao."
                ),
                "block_id": bloco_id,
            })
            continue

        alvo = Path(caminho)
        if not alvo.is_absolute() and metadata.get("asset_base"):
            alvo = Path(metadata["asset_base"]) / caminho
        if not alvo.exists():
            issues.append({
                "code": "ASSET-002", "severity": "ERROR",
                "message": f"Asset referenciado nao existe em disco: {caminho}",
                "block_id": bloco_id,
            })

    if not outputs or not esperadas:
        return issues

    verificadores = (
        ("html", contar_imagens_html),
        ("docx", contar_midias_docx),
        ("pdf", contar_imagens_pdf),
    )
    for formato, contar in verificadores:
        caminho = outputs.get(formato)
        if not caminho or not Path(caminho).exists():
            continue
        encontradas = contar(caminho)
        if encontradas < esperadas:
            issues.append({
                "code": "ASSET-003", "severity": "ERROR",
                "message": (
                    f"O {formato.upper()} tem {encontradas} imagem(ns) para "
                    f"{esperadas} esperada(s): o renderer perdeu figura."
                ),
                "formato": formato,
            })
    return issues


def validar_reconstrucao_textual(
    documento: dict[str, Any], texto_original: str
) -> list[dict[str, Any]]:
    def _palavras(texto: str) -> set[str]:
        return set(re.findall(r"\w{3,}", (texto or "").lower()))

    da_origem = _palavras(texto_original)
    if not da_origem:
        return []

    do_documento: set[str] = set()
    for bloco in _blocos(documento):
        do_documento |= _palavras(bloco.get("source_text") or "")
        do_documento |= _palavras(bloco.get("text") or "")

    perdidas = da_origem - do_documento
    if not perdidas:
        return []

    fracao = len(perdidas) / len(da_origem)
    if fracao < 0.05:
        return []

    return [{
        "code": "RECON-001",
        "severity": "ERROR" if fracao > 0.20 else "WARNING",
        "message": (
            f"{len(perdidas)} de {len(da_origem)} palavras da origem "
            f"({fracao:.0%}) nao aparecem no documento final."
        ),
        "evidence": sorted(perdidas)[:10],
    }]


def validar_sobreposicao_de_regioes(
    regioes: list[Any], limite: float = 0.10
) -> list[dict[str, Any]]:
    confirmadas = [
        r for r in regioes
        if getattr(r, "type", "") in ("text", "formula", "image", "table")
    ]
    issues: list[dict[str, Any]] = []

    for regiao in regioes:
        if getattr(regiao, "type", "") != "unknown":
            continue
        bbox = getattr(regiao, "bbox", (0, 0, 0, 0))
        area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
        if area <= 0:
            continue
        for outra in confirmadas:
            ob = getattr(outra, "bbox", (0, 0, 0, 0))
            x0, y0 = max(bbox[0], ob[0]), max(bbox[1], ob[1])
            x1, y1 = min(bbox[2], ob[2]), min(bbox[3], ob[3])
            if x0 >= x1 or y0 >= y1:
                continue
            fracao = ((x1 - x0) * (y1 - y0)) / area
            if fracao > limite:
                issues.append({
                    "code": "GEOM-001", "severity": "ERROR",
                    "message": (
                        f"Regiao desconhecida cobre {fracao:.0%} de uma "
                        f"regiao '{getattr(outra, 'type', '?')}' confirmada."
                    ),
                })
                break
    return issues
