"""
Professor (contextualizacao didatica das descricoes).

O QUE ELE FAZ:
  Recebe uma descricao de imagem JA APROVADA pelo critico + o texto da pagina
  (contexto confiavel, extraido localmente) e produz a versao final que o
  aluno vai ouvir: conectada ao assunto da aula, sem muletas repetitivas,
  em texto corrido limpo para leitor de tela.

O QUE ELE NAO FAZ:
  Ele NUNCA viu a imagem. Portanto ele NAO pode adicionar, corrigir ou
  remover FATOS VISUAIS... isso destruiria o trabalho do critico visual.
  Ele explica e conecta; quem enxerga eh o especialista + critico.

Divisao de tarefas desta camada:
  - Repeticao de logos      -> resolvida ANTES, deterministicamente, pelo
                               cache de posicao (sem IA, sem custo).
  - Emojis e simbolos       -> removidos deterministicamente aqui
                               (funcao limpar_para_leitor_de_tela).
  - Didatica e contexto     -> a chamada de IA deste modulo (texto puro).

Custo: +1 chamada de TEXTO por regiao de visao unica. Com o critico ligado,
cada regiao passa a custar ate 3 chamadas (especialista + critico + professor).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

from agno.agent import Agent

from core.utils.logger import logger



# Limpeza deterministica para leitor de tela (sem IA).
# Leitores de tela leem emojis e simbolos em voz alta ("circulo preto",
# "rosto sorridente"), o que polui a audicao do material.

_PADRAO_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # simbolos, pictogramas, emoticons
    "\U00002600-\U000027bf"  # simbolos diversos e dingbats
    "\U0001f1e6-\U0001f1ff"  # bandeiras
    "\ufe0f"                 # seletor de variacao
    "]+",
    flags=re.UNICODE,
)

_PADRAO_QUEBRAS = re.compile(r"\n{3,}")


def limpar_para_leitor_de_tela(texto: str) -> str:
    """Remove emojis e normaliza quebras de linha. Deterministico e barato."""
    texto = _PADRAO_EMOJI.sub("", texto)
    texto = _PADRAO_QUEBRAS.sub("\n\n", texto)
    # espacos duplicados deixados pela remocao de emojis ou afins
    texto = re.sub(r"[ \t]{2,}", " ", texto)
    return texto.strip()


# O AGENTE PROFESSOT (apenas texto)
_INSTRUCOES_PROFESSOR = """\
Voce e um professor que prepara material didatico para estudantes cegos.
Voce recebe:
1. A DESCRICAO de uma imagem, gerada e verificada por outro sistema.
2. O CONTEXTO: o texto da pagina/slide onde a imagem aparece.

Sua tarefa e reescrever a descricao na versao final que o aluno vai OUVIR
pelo leitor de tela, tornando-a didatica e conectada ao assunto da aula.

REGRAS ABSOLUTAS:
- Voce NAO viu a imagem. NUNCA adicione, corrija ou remova fatos visuais.
  Todos os elementos visuais citados na descricao devem permanecer; nenhum
  elemento visual novo pode ser inventado.
- Use o CONTEXTO apenas para explicar o PAPEL da imagem na aula
  (ex.: "este diagrama ilustra as areas de memoria discutidas acima").
- Remova muletas que nada acrescentam para quem ouve, como
  "Nao ha pessoas, objetos ou acoes visiveis", "A imagem apresenta",
  "Nao ha texto embutido na imagem", "O cenario e simples".
- Texto corrido, em portugues do Brasil, sem Markdown, sem emojis,
  sem listas. No maximo DOIS paragrafos.
- Se a descricao ja estiver boa e enxuta, mude o minimo possivel.
- Se a descricao contiver o marcador [verificacao incerta], PRESERVE o
  marcador no inicio da sua resposta - o aluno tem o direito de saber.

Responda APENAS com a descricao final, sem preambulo nem comentarios.
"""


def _construir_modelo_texto():
    """Modelo somente-texto (mesma logica do editor textual)."""
    cliente = os.getenv("AI_CLIENT", "ollama").lower()

    # O professor REESCREVE a descricao inteira. Se o limite for baixo, ele
    # corta no meio da frase - foi o que aconteceu com o diagrama da estrutura
    # do SO, truncado em "A coluna da direita cont".
    max_tokens = int(os.getenv("PROFESSOR_MAX_TOKENS", "2048"))

    if cliente == "openrouter":
        from agno.models.openrouter import OpenRouter

        return OpenRouter(
            id=os.getenv("PROFESSOR_MODELO", os.getenv("EDITOR_MODELO", "qwen/qwen3-8b")),
            api_key=os.getenv("OPENROUTER_API_KEY"),
            max_tokens=max_tokens,
        )

    from agno.models.ollama import Ollama

    return Ollama(
        id=os.getenv("PROFESSOR_MODELO", "llama3.1"),
        options={"num_predict": max_tokens},
    )


@lru_cache(maxsize=1)
def _agente_professor() -> Agent:
    return Agent(
        name="professor",
        model=_construir_modelo_texto(),
        description="Professor que torna descricoes de imagem didaticas",
        instructions=_INSTRUCOES_PROFESSOR,
        markdown=False,
    )


# Contexto muito longo encarece sem melhorar o resultado btw
_MAX_CONTEXTO = 2000


def lecionar_descricao(descricao: str, contexto_pagina: str | None) -> str:
    """Produz a versao didatica final de uma descricao de imagem.

    Fail-open: se a IA falhar, devolve a descricao original apenas com a
    limpeza deterministica. O professor melhora, nunca
    bloqueia.
    """
    descricao = limpar_para_leitor_de_tela(descricao)
    if not descricao:
        return descricao

    if os.getenv("USAR_PROFESSOR", "false").lower() != "true":
        return descricao

    contexto = (contexto_pagina or "").strip()[:_MAX_CONTEXTO]

    mensagem = (
        f"CONTEXTO DA PAGINA:\n{contexto or '(sem texto na pagina)'}\n\n"
        f"DESCRICAO DA IMAGEM:\n{descricao}"
    )

    try:
        resultado = _agente_professor().run(mensagem)
        final = (resultado.content or "").strip()
        if not final:
            return descricao

        if "[verificacao incerta]" in descricao and "[verificacao incerta]" not in final:
            final = f"[verificacao incerta] {final}"

        return limpar_para_leitor_de_tela(final)
    except Exception as erro: 
        logger.warning("Professor falhou ({}), mantendo descricao original", erro)
        return descricao
