"""
DIFERENCA CRUCIAL PARA O CRITICO VISUAL (critico_visual.py):
  - O critico VE a imagem. Ele pega erro factual ("o diagrama esta invertido").
    Mas ele so olha UMA regiao por vez, sem enxergar o documento todo.
  - O editor NAO ve imagem nenhuma. Ele le o DOCUMENTO INTEIRO como texto.
    Ele pega erro de CONSISTENCIA, cruzando informacao entre trechos.

Exemplo real (aula de Sistemas Operacionais):
  - O texto extraido localmente (confiavel) diz "DInf UFPR, Curitiba PR".
  - A IA de visao descreveu o brasao como a sigla "JFP", 22 vezes.
  - O editor le os dois no mesmo documento e desconfia: "JFP" nao aparece
    em lugar nenhum, enquanto "UFPR" aparece no texto confiavel.
  Nenhum critico de regiao isolada pegaria isso: falta a visao de conjunto.

O editor e um DETECTOR, nao um CORRETOR.
Ele NUNCA reescreve o documento. Ele sinaliza trechos suspeitos, porque
corrigir um erro visual exige olhar a imagem - e isso e trabalho do critico.

Barato: 1 chamada de TEXTO PURO (sem visao) para o documento inteiro,
em vez de 1 chamada por regiao.
"""

from __future__ import annotations

import os
from functools import lru_cache

from agno.agent import Agent
from pydantic import BaseModel, Field

from core.utils.logger import logger



# Contratos de saida (structured output).

class Inconsistencia(BaseModel):
    """Um problema detectado no documento montado."""

    trecho: str = Field(
        description="O trecho exato e curto do documento onde esta o problema."
    )
    tipo: str = Field(
        description=(
            "Categoria: 'termo_suspeito', 'repeticao', 'formatacao_vazada', "
            "'instrucao_vazada' ou 'incoerencia'."
        )
    )
    motivo: str = Field(
        description="Por que isso e suspeito, em uma frase objetiva."
    )
    sugestao: str | None = Field(
        default=None,
        description=(
            "O que provavelmente deveria estar ali, SE houver evidencia no "
            "proprio documento. Caso contrario, deixe nulo. Nao adivinhe."
        ),
    )


class RelatorioEdicao(BaseModel):
    """Resultado da revisao textual do documento inteiro."""

    inconsistencias: list[Inconsistencia] = Field(default_factory=list)
    resumo: str = Field(
        default="",
        description="Uma frase sobre a saude geral do documento.",
    )



# Modelo de TEXTO PURO (sem visao) >> eh bem mais barato que os especialistas.

def _construir_modelo_texto():
    """Modelo somente-texto. Nao precisa enxergar imagem, entao pode ser barato."""
    cliente = os.getenv("AI_CLIENT", "ollama").lower()

    max_tokens = int(os.getenv("EDITOR_MAX_TOKENS", "2048"))

    if cliente == "openrouter":
        from agno.models.openrouter import OpenRouter

        return OpenRouter(
            id=os.getenv("EDITOR_MODELO", "qwen/qwen3-8b"),
            api_key=os.getenv("OPENROUTER_API_KEY"),
            max_tokens=max_tokens,
        )

    from agno.models.ollama import Ollama

    return Ollama(
        id=os.getenv("EDITOR_MODELO", "llama3.1"),
        options={"num_predict": max_tokens},
    )


# Instrucoes. Cada regra veio de um erro REAL observado nos testes.

_INSTRUCOES_EDITOR = """\
Voce revisa um documento acessivel gerado automaticamente a partir de um
material didatico. Partes do texto foram extraidas diretamente do arquivo
(confiaveis). Outras partes sao descricoes de imagens geradas por uma IA de
visao (podem conter erros).

Sua tarefa e DETECTAR inconsistencias. Voce NAO reescreve o documento.

Procure especificamente por:

1. TERMO SUSPEITO (o mais importante):
   Uma sigla, nome proprio ou termo que aparece numa descricao de imagem mas
   CONTRADIZ ou nao encontra respaldo no restante do documento.
   Exemplo: se o texto do documento cita a universidade "UFPR" e uma descricao
   de imagem afirma que o brasao diz "JFP", isso e um termo suspeito - a sigla
   provavelmente foi lida errado pela IA de visao.
   Use o texto do documento como referencia: ele e mais confiavel.

2. REPETICAO:
   Varias descricoes quase identicas do mesmo elemento decorativo (logo,
   brasao, rodape) repetidas ao longo do documento. Isso cansa quem usa
   leitor de tela.

3. FORMATACAO VAZADA:
   Marcacao Markdown que sobrou no texto (#, **, *, `, ```), quando o
   documento deveria ser texto puro.

4. INSTRUCAO VAZADA:
   Pedacos do prompt que vazaram para a saida (ex.: "Esta e a regiao...",
   "Sua tarefa e descrever...", "REGRAS:").

5. INCOERENCIA:
   Duas afirmacoes do documento que se contradizem diretamente.

REGRAS DE OURO:
- So preencha "sugestao" se houver evidencia NO PROPRIO DOCUMENTO. Nunca chute.
- Nao invente problemas. Se o documento estiver bom, devolva a lista vazia.
- Voce NAO viu as imagens. Nao julgue se uma descricao de imagem e visualmente
  correta - isso nao e seu trabalho. Julgue apenas a consistencia do texto.
- Seja conciso. No maximo 15 inconsistencias, as mais relevantes.
"""


@lru_cache(maxsize=1)
def _agente_editor() -> Agent:
    return Agent(
        name="editor-textual",
        model=_construir_modelo_texto(),
        description="Detector de inconsistencias em documento acessivel",
        instructions=_INSTRUCOES_EDITOR,
        output_schema=RelatorioEdicao,
        use_json_mode=True,  # modelos abertos nem sempre tem schema nativo
        markdown=False,
    )



# REVISÃO!!!
# Documentos muito longos estouram contexto e custo. Truncamos com folga:
# o objetivo e detectar padroes, e os primeiros milhares de caracteres ja
# contem o texto confiavel (titulo, autor, instituicao) necessario para
# flagrar termos suspeitos.

MAX_CARACTERES = int(os.getenv("EDITOR_MAX_CARACTERES", "40000"))


def revisar_documento(texto: str) -> RelatorioEdicao | None:
    """Revisa o documento inteiro procurando inconsistencias internas.

    Args:
        texto: o documento montado (todas as paginas concatenadas).

    Returns:
        RelatorioEdicao, ou None se a revisao falhou (fail-open: o chamador
        deve seguir normalmente, o editor nunca pode derrubar o pipeline).
    """
    if not texto.strip():
        return None

    trecho = texto[:MAX_CARACTERES]
    if len(texto) > MAX_CARACTERES:
        logger.info(
            "Editor textual: documento truncado de {} para {} caracteres",
            len(texto),
            MAX_CARACTERES,
        )

    try:
        editor = _agente_editor()
        resultado = editor.run(
            "Revise o documento abaixo e liste as inconsistencias.\n\n"
            f"=== DOCUMENTO ===\n{trecho}"
        )
        relatorio = resultado.content
        if isinstance(relatorio, RelatorioEdicao):
            return relatorio
        logger.warning("Editor devolveu tipo inesperado: {}", type(relatorio))
        return None
    except Exception as erro:  
        logger.warning("Editor textual falhou ({}), seguindo sem revisao", erro)
        return None


def revisar_e_registrar(texto: str) -> RelatorioEdicao | None:
    """Roda a revisao (se a flag estiver ligada) e registra o resultado no log.

    Nao altera o texto. Retorna o relatorio para quem quiser anexa-lo ao
    documento canonico ou exibi-lo ao usuario.
    """
    if os.getenv("USAR_EDITOR", "false").lower() != "true":
        return None

    relatorio = revisar_documento(texto)
    if relatorio is None:
        return None

    if not relatorio.inconsistencias:
        logger.info("Editor textual: nenhuma inconsistencia detectada")
        return relatorio

    logger.warning(
        "Editor textual: {} inconsistencia(s) detectada(s)",
        len(relatorio.inconsistencias),
    )
    for item in relatorio.inconsistencias:
        sugestao = f" | sugestao: {item.sugestao}" if item.sugestao else ""
        logger.warning(
            "  [{}] {!r}: {}{}",
            item.tipo,
            item.trecho[:80],
            item.motivo,
            sugestao,
        )

    return relatorio
