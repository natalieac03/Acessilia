"""Le o documento inteiro e aponta inconsistencias.

Passada final com visao de conjunto, procurando o que nenhuma etapa
por regiao consegue ver: um termo escrito de duas formas em paginas
diferentes, uma repeticao estranha, um trecho que contradiz outro.

So aponta, nunca reescreve. E fail-open: se a resposta do modelo nao
puder ser interpretada, o material segue e a necessidade de revisao
fica registrada.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from pydantic import BaseModel, Field

from core.utils.logger import logger


class Inconsistencia(BaseModel):

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

    inconsistencias: list[Inconsistencia] = Field(default_factory=list)
    resumo: str = Field(
        default="",
        description="Uma frase sobre a saude geral do documento.",
    )
    falhou: bool = Field(
        default=False,
        description="A revisao nao pode ser concluida ou validada.",
    )
    motivo_da_falha: str = Field(default="")

    @property
    def bloqueia_publicacao(self) -> bool:
        return bool(self.falhou)

    def como_issues(self) -> list[dict]:
        if not self.falhou:
            return []
        return [{
            "code": "EDITOR-SCHEMA-001",
            "severity": "ERROR",
            "message": (
                f"Revisao editorial nao concluida: {self.motivo_da_falha}"
            ),
        }]


def _construir_modelo_texto():
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


_INSTRUCOES_EDITOR = """
RESPONDA APENAS COM JSON VALIDO. Sem texto antes. Sem texto depois. Sem cercas.
Formato obrigatorio:
{"inconsistencias": [...], "resumo": "frase"}
Se sem problemas: {"inconsistencias": [], "resumo": "..."}

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


def _extrair_json(texto: str) -> dict | None:
    if not texto:
        return None
    limpo = re.sub(r"```(?:json)?", "", texto).strip()
    inicio = limpo.find("{")
    if inicio < 0:
        return None
    try:
        objeto, _ = json.JSONDecoder().raw_decode(limpo[inicio:])
    except json.JSONDecodeError:
        return None
    return objeto if isinstance(objeto, dict) else None


@lru_cache(maxsize=1)
def _agente_editor():
    from agno.agent import Agent

    return Agent(
        name="editor-textual",
        model=_construir_modelo_texto(),
        description="Detector de inconsistencias em documento acessivel",
        instructions=_INSTRUCOES_EDITOR,
        markdown=False,
    )


MAX_CARACTERES = int(os.getenv("EDITOR_MAX_CARACTERES", "40000"))


def revisar_documento(texto: str) -> RelatorioEdicao | None:
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
        import time as _time
        _t0 = _time.monotonic()
        resultado = editor.run(
            "JSON APENAS. Revise e liste as inconsistencias.\n\n"
            f"=== DOCUMENTO ===\n{trecho}\n\n"
            "RESPOSTA: apenas o JSON, sem texto adicional."
        )
        conteudo = resultado.content
        try:
            from core.services import telemetria
            telemetria.registrar_chamada(
                "editor", resultado,
                duracao_ms=int((_time.monotonic() - _t0) * 1000),
                objeto_agente=editor,
            )
        except Exception:
            pass
        if isinstance(conteudo, RelatorioEdicao):
            return conteudo
        if isinstance(conteudo, str):
            dado = _extrair_json(conteudo)
            if dado is not None:
                try:
                    return RelatorioEdicao(**dado)
                except Exception as erro_validacao:
                    logger.warning(
                        "Editor: JSON fora do esquema ({}); marcando "
                        "necessidade de revisao humana", erro_validacao,
                    )
                    return RelatorioEdicao(
                        falhou=True,
                        motivo_da_falha=f"resposta fora do esquema: "
                                        f"{erro_validacao}",
                    )
        logger.warning(
            "Editor devolveu resposta sem JSON reconhecivel; marcando "
            "necessidade de revisao humana"
        )
        return RelatorioEdicao(
            falhou=True,
            motivo_da_falha="resposta sem JSON reconhecivel",
        )
    except Exception as erro:
        logger.warning(
            "Editor textual falhou ({}); pipeline segue, publicacao "
            "final bloqueada", erro,
        )
        return RelatorioEdicao(
            falhou=True, motivo_da_falha=f"{type(erro).__name__}: {erro}"
        )


def revisar_e_registrar(texto: str) -> RelatorioEdicao | None:
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
