"""
Cada TIPO de regiao (tabela, formula, imagem, texto escaneado) vira um
Agente especializado, reaproveitando 100% os prompts que ja existem em
interfaces/telegram/prompts/. Este modulo NAO reescreve o projeto: ele
oferece a funcao `descrever_regiao(...)` que pode substituir, no futuro,
a chamada direta ao cliente de IA feita hoje em agente_unico.py.


Se sua versao divergir, confira https://docs.agno.com (ou docs.agno.com/llms-full.txt).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from agno.agent import Agent
from agno.media import Image


# MODELO DE VISÃO DA OPEN ROUTER

def _construir_modelo_visao():
    """Escolhe o modelo pela variavel AI_CLIENT, espelhando o config do projeto."""
    cliente = os.getenv("AI_CLIENT", "ollama").lower()

    # Descricoes de diagramas complexos sao longas. O default do provedor
    # costuma ser baixo demais e a descricao sai CORTADA no meio da frase.
    max_tokens = int(os.getenv("VISAO_MAX_TOKENS", "2048"))

    if cliente == "openrouter":
        from agno.models.openrouter import OpenRouter

        return OpenRouter(
            id=os.getenv("OPENROUTER_MODEL", "qwen/qwen3-vl-32b-instruct"),
            api_key=os.getenv("OPENROUTER_API_KEY"),
            max_tokens=max_tokens,
        )

    from agno.models.ollama import Ollama

    return Ollama(
        id=os.getenv("OLLAMA_MODEL", "llama3.2-vision"),
        options={"num_predict": max_tokens},
    )


# REAPROVEITA OS PROMPTS QUE JÁ EXISTEM NO PROJETO

_DIR_PROMPTS = (
    Path(__file__).resolve().parents[2] / "interfaces" / "telegram" / "prompts"
)

TIPO_PARA_PROMPT = {
    "embedded_image": "regiao_imagem",
    "text_scanned": "regiao_texto_escaneado",
    "unknown": "regiao_texto_escaneado",
    "table": "regiao_tabela",
    "formula": "regiao_formula",
}

# Papel curto de cada especialista q aparece nos logs/observabilidade do Agno
TIPO_PARA_PAPEL = {
    "table": "Especialista em transcrever tabelas para texto acessivel",
    "formula": "Especialista em transcrever formulas matematicas",
    "embedded_image": "Especialista em audiodescricao de imagens",
    "text_scanned": "Especialista em OCR de texto escaneado",
    "unknown": "Especialista em OCR de regioes ambiguas",
}


@lru_cache(maxsize=None)
def _carregar_prompt(nome: str) -> str:
    return (_DIR_PROMPTS / f"{nome}.txt").read_text(encoding="utf-8")



# Um Agente por tipo de regiao 

@lru_cache(maxsize=None)
def _agente_para(tipo: str) -> Agent:
    if tipo not in TIPO_PARA_PROMPT:
        raise ValueError(f"tipo de regiao sem especialista: {tipo!r}")

    return Agent(
        name=f"especialista-{tipo}",
        model=_construir_modelo_visao(),
        description=TIPO_PARA_PAPEL.get(tipo, "Especialista de acessibilidade"),
        # O prompt existente entra como "instructions" (contexto de sistema).
        instructions=_carregar_prompt(TIPO_PARA_PROMPT[tipo]),
        markdown=False,  # o projeto exige texto puro, sem Markdown
    )


# A funçao que o resto do projeto chama.

def descrever_regiao(
    tipo: str,
    imagem_bytes: bytes,
    contexto: str | None = None,
) -> str:
    """Descreve/transcreve UMA regiao recortada, com o especialista certo.

    Args:
        tipo: tipo da regiao (um de TIPO_PARA_PROMPT). Vem do region_classifier.
        imagem_bytes: bytes do recorte (JPEG/PNG) - o projeto ja produz isso.
        contexto: (opcional) legenda/titulo vizinho. Gancho para a Ideia #8
                  (dar contexto ao especialista). Deixe None por enquanto.

    Returns:
        Texto acessivel pronto para entrar no documento canonico.
    """
    agente = _agente_para(tipo)

    mensagem = "Processe a regiao da imagem seguindo estritamente as regras."
    if contexto:
        mensagem += (
            "\n\nContexto da pagina (use apenas para entender, nao copie): "
            + contexto
        )

    # Se sua versao do Agno nao aceitar Image(content=...), use um arquivo:
    #   Image(filepath="/caminho/recorte.jpg")
    resultado = agente.run(mensagem, images=[Image(content=imagem_bytes)])
    return (resultado.content or "").strip()



# Proximos passos (nao implementados aqui de proposito):
#   - um Agente "critico" com output_schema (Pydantic) conferindo
#     esta saida antes de aceita-la.
#   - envolver especialista + critico num Workflow com Loop de reparo.
#   - preencher `contexto` com a legenda/titulo vizinho da regiao.
