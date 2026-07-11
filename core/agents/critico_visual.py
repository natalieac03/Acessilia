"""
Critico Visual (anti-alucinacao).

O especialista descreve a regiao; o CRITICO olha a MESMA imagem + a descricao
gerada e responde de forma estruturada se a descricao e fiel. Se nao for, o
especialista tenta de novo (uma vez), agora sabendo o que o critico apontou.
Se ainda assim nao convergir, a descricao e marcada como incerta - NUNCA
"corrigida no chute".

Principios de projeto (LÊ PQ EH IMPORTANTE!!!!):
  1. FAIL-OPEN: se o critico falhar (erro de rede, JSON invalido, etc), o
     pipeline segue com a descricao original. O critico melhora a qualidade,
     mas jamais pode derrubar o bot.
  2. NO MAXIMO 1 RETENTATIVA: cada regiao ja custa 1 chamada de visao. Sem
     limite, um PDF de 22 slides viraria uma conta impagavel.
  3. INCERTEZA HONESTA: em acessibilidade, "[verificacao incerta]" e melhor
     que uma descricao confiante e errada. O critico MARCA, nao inventa.
"""

from __future__ import annotations

import os
from functools import lru_cache

from agno.agent import Agent
from agno.media import Image
from pydantic import BaseModel, Field

from core.agents.agno_specialists import (
    TIPO_PARA_PROMPT,
    _construir_modelo_visao,
    _agente_para,
)
from core.utils.logger import logger



# O contrato de saida do critico (structured output).
# Sem isso, o critico responderia texto solto e nao daria para automatizar.

class Critica(BaseModel):
    """Veredito do critico sobre uma descricao gerada por um especialista."""

    fiel: bool = Field(
        description=(
            "true se a descricao contem APENAS o que e visivel na imagem. "
            "false se ha qualquer afirmacao inventada, invertida ou ausente."
        )
    )
    confianca: float = Field(
        ge=0.0,
        le=1.0,
        description="Quao seguro voce esta do seu veredito, de 0.0 a 1.0.",
    )
    suspeitas: list[str] = Field(
        default_factory=list,
        description=(
            "Lista curta de problemas concretos encontrados. Ex.: "
            "'a descricao diz que Linux Kernel esta no topo, mas esta na base'."
        ),
    )



# Instrucoes do critico, com regras ESPECIFICAS por tipo de regiao.
#    As regras vieram dos erros reais observados nos testes com aulas reais.



_REGRAS_BASE = """\
Voce e um verificador rigoroso de audiodescricao acessivel.

Voce recebe UMA IMAGEM e uma DESCRICAO que outro sistema gerou dela.
Sua tarefa NAO e reescrever a descricao. Sua tarefa e VERIFICAR se ela e fiel.

Marque fiel=false se encontrar QUALQUER um destes problemas:
- Afirma algo que nao esta visivel na imagem (invencao).
- Le um texto de forma diferente do que esta escrito na imagem.
- Inverte, embaralha ou omite a ordem/posicao dos elementos.
- Omite elementos importantes que aparecem claramente na imagem.

Se a descricao estiver correta e completa, marque fiel=true.
Seja rigoroso, mas nao invente problemas que nao existem.
Se voce mesmo nao conseguir ler algo na imagem, reduza a confianca.
"""

_REGRAS_POR_TIPO = {
    "embedded_image": """\
ATENCAO ESPECIAL A DIAGRAMAS (fonte comum de erro):
- Liste mentalmente os elementos DE CIMA PARA BAIXO antes de julgar.
- Confira se a descricao respeita essa ordem vertical real.
- Diagramas de camadas (ex.: kernel na base, aplicacoes no topo) sao
  frequentemente descritos INVERTIDOS. Verifique isso explicitamente.
- Conte os elementos da imagem e confira se a descricao menciona todos.
- Confira se "acima/abaixo" nao viraram "esquerda/direita" na descricao.
""",
    "table": """\
ATENCAO ESPECIAL A TABELAS:
- Conte as linhas e as colunas da imagem.
- Confira se a descricao tem o mesmo numero de linhas e colunas.
- Verifique celula a celula os valores numericos.
- Celulas ilegiveis devem estar marcadas, nao adivinhadas.
""",
    "formula": """\
ATENCAO ESPECIAL A FORMULAS (risco maximo):
- Confira simbolo por simbolo, indice por indice, expoente por expoente.
- Um unico caractere errado invalida a formula inteira.
- Na duvida, marque fiel=false e reduza a confianca. NAO adivinhe.
""",
    "text_scanned": """\
ATENCAO ESPECIAL A TEXTO ESCANEADO:
- Compare palavra por palavra com o que esta escrito na imagem.
- Siglas e nomes proprios sao frequentemente lidos errado. Confira letra
  a letra (ex.: uma sigla de 4 letras nao pode virar uma de 3).
- Texto ilegivel deve estar marcado como "[ilegivel]", nao adivinhado.
""",
}
_REGRAS_POR_TIPO["unknown"] = _REGRAS_POR_TIPO["text_scanned"]


@lru_cache(maxsize=None)
def _agente_critico(tipo: str) -> Agent:
    """Um critico por tipo de regiao, com as regras especificas daquele tipo."""
    instrucoes = _REGRAS_BASE + "\n" + _REGRAS_POR_TIPO.get(tipo, "")

    return Agent(
        name=f"critico-{tipo}",
        model=_construir_modelo_visao(),
        description="Verificador anti-alucinacao de audiodescricao",
        instructions=instrucoes,
        output_schema=Critica,
        # Modelos abertos (Qwen etc) nem sempre tem structured output nativo.
        # O json_mode instrui o modelo a responder em JSON valido.
        use_json_mode=True,
        markdown=False,
    )


# VERIFICAÇÃO!

def verificar_descricao(
    tipo: str,
    imagem_bytes: bytes,
    descricao: str,
) -> Critica | None:
    """Pede ao critico que julgue a descricao contra a imagem.

    Returns:
        Critica, ou None se a verificacao falhou (fail-open: o chamador
        deve seguir com a descricao original nesse caso).
    """
    if not descricao.strip():
        return None

    try:
        critico = _agente_critico(tipo)
        resultado = critico.run(
            "Verifique se a DESCRICAO abaixo e fiel a imagem.\n\n"
            f"DESCRICAO A VERIFICAR:\n{descricao}",
            images=[Image(content=imagem_bytes)],
        )
        critica = resultado.content
        if isinstance(critica, Critica):
            return critica
        logger.warning("Critico devolveu tipo inesperado: {}", type(critica))
        return None
    except Exception as erro:  # fail-open, nunca derruba o pipeline <3
        logger.warning("Critico falhou ({}), seguindo sem verificacao", erro)
        return None



# O ciclo completo: descrever -> verificar -> (tentar de novo?) -> marcar.

LIMIAR_CONFIANCA = float(os.getenv("CRITICO_LIMIAR_CONFIANCA", "0.6"))
MARCADOR_INCERTEZA = "[verificacao incerta]"


def _redescrever_com_critica(
    tipo: str,
    imagem_bytes: bytes,
    descricao_anterior: str,
    critica: Critica,
) -> str:
    """Segunda tentativa do especialista, agora sabendo o que estava errado."""
    problemas = "\n".join(f"- {s}" for s in critica.suspeitas) or "- (nao detalhado)"
    mensagem = (
        "Sua descricao anterior desta imagem foi revisada e apresenta "
        "problemas. Descreva a imagem novamente, do zero, corrigindo-os.\n\n"
        f"DESCRICAO ANTERIOR:\n{descricao_anterior}\n\n"
        f"PROBLEMAS APONTADOS:\n{problemas}\n\n"
        "Se voce nao conseguir determinar algo com certeza olhando a imagem, "
        "diga que nao e possivel determinar. NAO adivinhe."
    )
    agente = _agente_para(tipo)
    resultado = agente.run(mensagem, images=[Image(content=imagem_bytes)])
    return (resultado.content or "").strip()


def descrever_regiao_verificada(
    tipo: str,
    imagem_bytes: bytes,
    contexto: str | None = None,
) -> str:
    """Descreve uma regiao e VERIFICA a descricao antes de aceita-la.

    Substitui `descrever_regiao` quando USAR_CRITICO=true.

    Fluxo:
        especialista -> critico -> se reprovado: especialista (2a vez)
                                -> critico -> se ainda reprovado: marca incerteza
    """

    from core.agents.agno_specialists import descrever_regiao

    descricao = descrever_regiao(tipo, imagem_bytes, contexto)

    if os.getenv("USAR_CRITICO", "false").lower() != "true":
        return descricao
    if tipo not in TIPO_PARA_PROMPT or not descricao.strip():
        return descricao

    critica = verificar_descricao(tipo, imagem_bytes, descricao)
    if critica is None:
        return descricao  # fail-open

    aprovada = critica.fiel and critica.confianca >= LIMIAR_CONFIANCA
    if aprovada:
        logger.info(
            "Critico aprovou regiao {} (confianca={:.2f})", tipo, critica.confianca
        )
        return descricao

    logger.warning(
        "Critico REPROVOU regiao {} (fiel={}, confianca={:.2f}): {}",
        tipo,
        critica.fiel,
        critica.confianca,
        "; ".join(critica.suspeitas) or "sem detalhes",
    )

    # Segunda e ultima tentativa, agora com a critica no prompt.
    try:
        nova_descricao = _redescrever_com_critica(
            tipo, imagem_bytes, descricao, critica
        )
    except Exception as erro:
        logger.warning("Redescricao falhou ({}), mantendo a original", erro)
        return f"{MARCADOR_INCERTEZA} {descricao}"

    if not nova_descricao:
        return f"{MARCADOR_INCERTEZA} {descricao}"

    nova_critica = verificar_descricao(tipo, imagem_bytes, nova_descricao)
    if nova_critica is None:
        return nova_descricao  # fail-open

    if nova_critica.fiel and nova_critica.confianca >= LIMIAR_CONFIANCA:
        logger.info("Critico aprovou regiao {} na 2a tentativa", tipo)
        return nova_descricao

    # Nao convergiu. Entrega a melhor tentativa, mas SINALIZA a incerteza.
    # Melhor um aviso honesto do que uma descricao confiante e errada.
    logger.warning(
        "Regiao {} nao convergiu apos 2 tentativas - marcando incerteza", tipo
    )
    return f"{MARCADOR_INCERTEZA} {nova_descricao}"
