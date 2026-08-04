"""Normaliza a descricao segundo as regras de audiodescricao.

Aplica as convencoes de audiodescricao didatica: presente do
indicativo, voz ativa, sem prefixos redundantes ("Imagem de...") e sem
mencao a cor quando ela nao tem valor didatico.

Muda a FORMA, nunca o conteudo. A parte deterministica sempre roda; a
reescrita por IA e opcional e protegida por guardas que descartam o
resultado se ele perder informacao em relacao ao original.
"""

from __future__ import annotations

import os
import re
import unicodedata

from core.utils.logger import logger

MARCADOR_INCERTEZA = "[verificacao incerta]"

REGRAS_DE_OURO = """
REGRAS DE OURO DA DESCRICAO ACESSIVEL (obrigatorias):
1. Descreva APENAS o que e observavel. Nada de inferir intencao, emocao,
   profissao ou identidade sem evidencia visivel. Na duvida, diga que nao
   e possivel determinar.
2. Verbos SEMPRE no presente do indicativo. Nunca gerundio para cena
   estatica: escreva "um homem sorri", nao "um homem sorrindo".
3. NUNCA comece com "Imagem de...", "Foto de...", "A imagem mostra/
   apresenta/contem...". O leitor de tela ja anuncia que e uma imagem.
   COMECE pela tipologia, em 1-4 palavras, seguida de ponto ou dois-pontos:
   "Diagrama de blocos.", "Fotografia:", "Grafico de barras.",
   "Logotipo institucional:", "Tabela.", "Tirinha comica."
4. Varredura do geral para o especifico; da esquerda para a direita e de
   cima para baixo (salvo quando a logica da imagem exigir outra ordem,
   como piramides - ai siga a estrutura, sem vaivem).
5. Frases curtas, voz ativa, ordem direta (sujeito + verbo + complemento).
   Uma ideia principal por frase.
6. Cite cores SOMENTE quando tiverem valor didatico (codificarem algo,
   como camadas de um diagrama ou series de um grafico). Nao enumere
   cores decorativas.
7. Texto legivel dentro da imagem deve ser transcrito fielmente, letra a
   letra. Se um trecho estiver ilegivel, declare "conteudo ilegivel" -
   NUNCA invente.
8. Para logotipos ou formas ambiguas, use verbos de verossimilhanca:
   "assemelha-se a", "lembra". Nao afirme o que nao da para confirmar.
""".strip()


_PREFIXOS_PROIBIDOS = re.compile(
    r"^\s*(?:"
    r"a\s+imagem\s+(?:apresenta|mostra|contem|contém|exibe|ilustra|e|é)\s*|"
    r"a\s+figura\s+(?:apresenta|mostra|contem|contém|exibe|ilustra)\s*|"
    r"imagem\s+de\s+|foto(?:grafia)?\s+de\s+|figura\s+de\s+|"
    r"trata-se\s+de\s+(?:uma?\s+)?|"
    r"o\s+diagrama\s+apresentado\s+(?:e|é)\s+"
    r")",
    re.IGNORECASE,
)


def _remover_prefixos_proibidos(texto: str) -> str:
    novo = _PREFIXOS_PROIBIDOS.sub("", texto, count=1)
    try:
        from pipeline.matematica.podador import remover_rotulo_de_processo

        novo = remover_rotulo_de_processo(novo)
    except Exception:
        pass
    novo = novo.lstrip()
    if novo and novo[0].islower():
        novo = novo[0].upper() + novo[1:]
    return novo if novo else texto


_MARCADORES_PROTEGIDOS = ("[imagem decorativa]", "[ilegivel]", "[ilegível]")
_PREFIXO_FALHA = "[falha ao processar"


def _remover_colchetes_externos(texto: str) -> str:
    limpo = texto.strip()

    if limpo.lower() in _MARCADORES_PROTEGIDOS:
        return limpo
    if limpo.lower().startswith(_PREFIXO_FALHA):
        return limpo

    if (
        len(limpo) >= 2
        and limpo.startswith("[")
        and limpo.endswith("]")
        and not limpo.startswith(MARCADOR_INCERTEZA)
    ):
        return limpo[1:-1].strip()

    return limpo


def _separar_marcador(texto: str) -> tuple[bool, str]:
    limpo = texto.strip()
    if limpo.startswith(MARCADOR_INCERTEZA):
        return True, limpo[len(MARCADOR_INCERTEZA):].lstrip()
    return False, limpo


def _palavras_de_conteudo(texto: str) -> set[str]:
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    tokens = re.findall(r"[A-Za-z0-9]{3,}", sem_acento.lower())
    return {t for t in tokens if len(t) >= 4 or t.isdigit() or t.isupper()}


_PADRAO_LINHA_TABELA = re.compile(r"(?m)^\s*\|.+\|\s*$")
_PADRAO_FORMULA = re.compile(r"(?mi)^\s*(?:LATEX|LEITURA)\s*:")


def _parece_estruturado(texto: str) -> bool:
    return bool(
        _PADRAO_LINHA_TABELA.search(texto)
        or _PADRAO_FORMULA.search(texto)
        or "<math" in texto
    )


_PERDA_MAXIMA = 0.25


_PADROES_INFERENCIA_EXPLICITA = (
    re.compile(r"\bcomo se\b", re.IGNORECASE),
    re.compile(r"\bparece estar\b", re.IGNORECASE),
    re.compile(r"\baparenta estar\b", re.IGNORECASE),
    re.compile(r"\bprestes a\b", re.IGNORECASE),
    re.compile(r"\bprovavelmente\b", re.IGNORECASE),
    re.compile(r"\bposição dinâmica\b", re.IGNORECASE),
    re.compile(r"\bposicao dinamica\b", re.IGNORECASE),
)


def detectar_inferencias_explicitas(texto: str) -> list[str]:
    encontradas: list[str] = []
    for padrao in _PADROES_INFERENCIA_EXPLICITA:
        match = padrao.search(texto)
        if match:
            encontradas.append(match.group(0))
    return encontradas


def _marcar_inferencia_remanescente(
    texto: str, tipo: str | None, tinha_marcador: bool
) -> str:
    if tipo != "embedded_image":
        return texto
    inferencias = detectar_inferencias_explicitas(texto)
    if not inferencias:
        return texto
    logger.warning(
        "acessivel: possivel inferencia permaneceu na descricao: {}",
        ", ".join(inferencias),
    )
    if tinha_marcador:
        return texto
    return f"{MARCADOR_INCERTEZA} {texto}"


def _preservou_conteudo(original: str, reescrito: str) -> bool:
    antes = _palavras_de_conteudo(original)
    if not antes:
        return True
    depois = _palavras_de_conteudo(reescrito)
    perdidas = antes - depois
    return (len(perdidas) / len(antes)) <= _PERDA_MAXIMA


def _construir_modelo_texto():
    cliente = os.getenv("AI_CLIENT", "ollama").lower()
    max_tokens = int(os.getenv("ACESSIVEL_MAX_TOKENS", "2048"))
    from core.ai.esforco_de_raciocinio import normalizar_esforco

    esforco = normalizar_esforco(
        os.getenv("ACESSIVEL_REASONING", "off"), "ACESSIVEL_REASONING"
    )

    if cliente == "openrouter":
        from agno.models.openrouter import OpenRouter

        kwargs = {
            "id": os.getenv(
                "ACESSIVEL_MODELO",
                os.getenv("PROFESSOR_MODELO", "qwen/qwen3-8b"),
            ),
            "api_key": os.getenv("OPENROUTER_API_KEY"),
            "max_tokens": max_tokens,
        }
        if esforco:
            kwargs["reasoning_effort"] = esforco
        return OpenRouter(**kwargs)

    from agno.models.ollama import Ollama

    return Ollama(
        id=os.getenv("ACESSIVEL_MODELO", os.getenv("PROFESSOR_MODELO", "llama3.1")),
        options={"num_predict": max_tokens},
    )


_INSTRUCOES_ACESSIVEL = f"""
Voce e um NORMALIZADOR de descricoes de imagem para leitores de tela.
Voce recebe uma descricao JA VERIFICADA contra a imagem. Sua unica tarefa
e ajustar a FORMA do texto as regras abaixo. Voce NAO viu a imagem.

{REGRAS_DE_OURO}

PROIBICOES ABSOLUTAS (violar qualquer uma invalida a resposta):
- NAO adicione, remova ou altere NENHUM fato visual: objetos, textos
  transcritos, numeros, siglas, quantidades, posicoes, cores citadas.
- NAO resuma. O texto de saida cobre exatamente o mesmo conteudo.
- NAO adicione contexto didatico, opiniao ou interpretacao.
- NAO use Markdown, emojis ou listas.
- Se a descricao ja cumprir as regras, devolva-a igual.

TRATAMENTO DE INFERENCIAS:

- Se o texto atribuir movimento a uma imagem estatica, substitua a
  interpretacao pela postura observavel.

Exemplo:
"como se estivesse saltando"
deve virar uma descricao dos bracos, pernas e posicao do corpo.

- Substitua avaliacoes como "posicao dinamica", "aspecto tridimensional"
  e "cena alegre" por caracteristicas visuais concretas, quando elas
  estiverem presentes no texto original.

- "Ha sombreamento nas laterais" e observacao.
  "O sombreamento confere aspecto tridimensional" e interpretacao.

- Nao apague objetos, posicoes, cores, quantidades, textos ou
  caracteristicas fisicas para realizar essa correcao.

Responda SOMENTE com o texto normalizado, sem preambulo.
""".strip()


def _agente_acessivel():
    from agno.agent import Agent

    return Agent(
        name="acessivel",
        model=_construir_modelo_texto(),
        description="Normaliza descricoes ao padrao de audiodescricao",
        instructions=_INSTRUCOES_ACESSIVEL,
        markdown=False,
    )


def normalizar_descricao(descricao: str, tipo: str | None = None) -> str:
    if not descricao or not descricao.strip():
        return descricao

    tinha_marcador, corpo = _separar_marcador(descricao)
    corpo = _remover_colchetes_externos(corpo)
    corpo = _remover_prefixos_proibidos(corpo)

    if os.getenv("USAR_ACESSIVEL", "false").lower() != "true":
        deterministico = _marcar_inferencia_remanescente(
            corpo, tipo, tinha_marcador
        )
        if tinha_marcador:
            return f"{MARCADOR_INCERTEZA} {deterministico}"
        return deterministico

    deterministico = (
        f"{MARCADOR_INCERTEZA} {corpo}" if tinha_marcador else corpo
    )

    if tipo in ("table", "formula") or _parece_estruturado(corpo):
        return deterministico

    try:
        if tipo is None:
            mensagem = corpo
        else:
            mensagem = (
                f"Contexto (nao faz parte do texto): a descricao abaixo "
                f"veio de uma regiao do tipo '{tipo}'.\n"
                f"Reescreva SOMENTE o texto entre as marcas, sem repetir "
                f"este contexto nem as marcas.\n"
                f"<<<TEXTO\n{corpo}\nTEXTO>>>"
            )
        import time as _time
        _t0 = _time.monotonic()
        _agente = _agente_acessivel()
        resultado = _agente.run(mensagem)
        try:
            from core.services import telemetria
            telemetria.registrar_chamada(
                "acessivel", resultado,
                duracao_ms=int((_time.monotonic() - _t0) * 1000),
                objeto_agente=_agente,
            )
        except Exception:
            pass
        final = (resultado.content or "").strip()

        if not final:
            return deterministico

        _, final_sem_marcador = _separar_marcador(final)
        final_sem_marcador = _remover_colchetes_externos(final_sem_marcador)
        final_sem_marcador = _remover_prefixos_proibidos(final_sem_marcador)

        try:
            from pipeline.barreira_de_dados_tecnicos import (
                texto_seguro_para_estudante,
            )

            final_sem_marcador, vazados = texto_seguro_para_estudante(
                final_sem_marcador, corpo
            )
            if vazados:
                logger.warning(
                    "acessivel: termo interno na saida ({}); "
                    "mantendo versao deterministica",
                    ", ".join(vazados[:3]),
                )
                return _marcar_inferencia_remanescente(
                    deterministico, tipo, tinha_marcador
                )
        except Exception:
            pass

        if not _preservou_conteudo(corpo, final_sem_marcador):
            logger.warning(
                "acessivel: saida perdeu conteudo demais; mantendo "
                "normalizacao deterministica"
            )
            return _marcar_inferencia_remanescente(
                deterministico, tipo, tinha_marcador
            )

        final_sem_marcador = _marcar_inferencia_remanescente(
            final_sem_marcador, tipo, tinha_marcador
        )

        if tinha_marcador:
            return f"{MARCADOR_INCERTEZA} {final_sem_marcador}"
        return final_sem_marcador

    except Exception as error:
        logger.warning("acessivel indisponivel ({}); seguindo sem ele", error)
        return _marcar_inferencia_remanescente(
            deterministico, tipo, tinha_marcador
        )
