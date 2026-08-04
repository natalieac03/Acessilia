"""Especialista de visao: le a imagem e descreve a regiao.

Um especialista por tipo de conteudo (imagem, tabela, formula), cada
um com o seu prompt. Para formula, o formato de resposta e fixo: um
campo LATEX com a notacao e um campo LEITURA com a fala.

Na pratica, so o LATEX e aproveitado na maior parte dos casos — a
arvore reprocessa a partir dele e gera a fala de forma deterministica.
O campo LEITURA e usado como alternativa quando a arvore nao consegue
entender a expressao inteira.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _construir_modelo_visao(tipo: str = ""):
    cliente = os.getenv("AI_CLIENT", "ollama").lower()

    max_tokens = int(os.getenv("VISAO_MAX_TOKENS", "2048"))
    if tipo == "formula":
        max_tokens = int(os.getenv("FORMULA_MAX_TOKENS", str(max(max_tokens, 3072))))

    from core.ai.esforco_de_raciocinio import normalizar_esforco

    variavel = "FORMULA_REASONING" if tipo == "formula" else "VISAO_REASONING"
    bruto = os.getenv("VISAO_REASONING", "off")
    if tipo == "formula":
        bruto = os.getenv("FORMULA_REASONING", bruto)
    esforco = normalizar_esforco(bruto, variavel)

    if cliente == "openrouter":
        from agno.models.openrouter import OpenRouter

        modelo = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-vl-32b-instruct")
        if tipo == "formula":
            modelo = os.getenv("FORMULA_MODELO", modelo)

        from config.settings import settings as _cfg
        kwargs = {
            "id": modelo,
            "api_key": os.getenv("OPENROUTER_API_KEY"),
            "max_tokens": max_tokens,
            "extra_body": {"temperature": _cfg.model_temperature},
        }
        if esforco:
            kwargs["reasoning_effort"] = esforco

        return OpenRouter(**kwargs)

    from agno.models.ollama import Ollama

    return Ollama(
        id=os.getenv("OLLAMA_MODEL", "llama3.2-vision"),
        options={"num_predict": max_tokens},
    )


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


_ADENDO_GRAFICO = """
====================================================================
REGRA PRIORITARIA PARA GRAFICOS - SOBREPOE QUALQUER REGRA ACIMA
====================================================================
Se esta imagem for um GRAFICO DE DADOS (barras, linhas, pizza, area,
dispersao, histograma), NAO narre o desenho em prosa. NAO escreva
frases como "a linha sobe", "a barra maior", "tendencia de queda",
"atinge o pico". Isso obriga o aluno cego a memorizar prosa e e
PROIBIDO - os dados vao em tabela, que ele navega celula a celula.

Sua resposta DEVE ter EXATAMENTE esta estrutura:

Grafico de <tipo>: <titulo exato como aparece na imagem>.
Eixo X: <rotulo do eixo X> (<unidade, se houver>).
Eixo Y: <rotulo do eixo Y> (<unidade>), de <minimo> a <maximo>,
intervalo <passo entre as marcas>.
| <rotulo do eixo X> | <rotulo do eixo Y> |
| <categoria 1> | <valor 1> |
| <categoria 2> | <valor 2> |

REGRAS DO FORMATO:
- A PRIMEIRA linha e a frase de identificacao (tipo + titulo).
- As linhas "Eixo X:" e "Eixo Y:" sao OBRIGATORIAS quando os eixos
  estiverem rotulados. Elas dao ao aluno a anatomia do grafico: sem
  saber a faixa e a escala, ele nao consegue julgar se a representacao
  e adequada nem comparar com outro grafico.
- Se um eixo nao tiver rotulo visivel, escreva "Eixo X: sem rotulo".
- Depois, uma linha de pipes por par (categoria, valor) lido do grafico.
- Cabecalhos = os rotulos dos eixos, na primeira linha de pipes.
- SEM linha separadora de tracos ( |---| ).
- Inclua a unidade no cabecalho (ex.: "Custo (R$/km)").
- Valor ilegivel: [ilegivel]. NAO invente numeros.

SOBRE "PONTO DESTACADO" - LEIA COM ATENCAO:
- Use "Ponto destacado:" SOMENTE quando houver uma MARCA GRAFICA
  explicita na imagem: uma seta, um circulo, uma cor diferente das
  demais, um rotulo de chamada, um asterisco.
- O maior e o menor valor NAO sao pontos destacados. Eles sao
  propriedades CALCULADAS dos dados, e o sistema ja as calcula sozinho
  a partir da tabela que voce extraiu.
- Escrever "Ponto destacado: Platinum" so porque a platina tem o maior
  valor inventa uma marca grafica que nao existe na imagem.
- Na duvida sobre haver marca visual, NAO escreva a linha.

Se a imagem NAO for um grafico de dados (foto, diagrama, logotipo,
ilustracao), ignore este bloco e descreva normalmente.
""".strip()

_ADENDO_TABELA = """
FORMATO DA SAIDA: cabecalhos na PRIMEIRA linha de pipes; SEM linha
separadora de tracos ( |---| ).
""".strip()

_ADENDO_FORMULA = """
FORMATO OBRIGATORIO DA RESPOSTA (substitui a regra de abertura por
tipologia para este tipo):
LATEX: <a formula em LaTeX, sem cifroes>
LEITURA: <a formula falada por extenso em portugues do Brasil>
Exemplo:
LATEX: x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}
LEITURA: x e igual a menos b, mais ou menos a raiz quadrada de b ao
quadrado menos quatro a c, tudo sobre dois a
Se houver texto explicativo ao lado da formula, adicione-o em linhas
seguintes, depois das duas linhas acima.

LETRA COLADA A NUMERO E VARIAVEL, NUNCA UNIDADE DE MEDIDA.
Numa formula, "2L" significa "dois L" - dois vezes a variavel L. NAO e
"dois litros". O mesmo vale para 5A, 3M, 10N, 2P: sao coeficiente e
variavel, nao medida.

  ERRADO: LEITURA: dois litros dividido por cinco
  CERTO:  LEITURA: dois L dividido por cinco

Interprete como unidade APENAS quando a propria imagem trouxer a unidade
por extenso ao lado, ou quando o simbolo nao aparecer em nenhum outro
ponto da expressao como variavel. Na duvida, e variavel: material
didatico define as variaveis numa legenda proxima ("L = nivel"), e
trocar a variavel por uma unidade destroi a formula para quem estuda.

Nao invente unidades tambem na LEITURA de resultados: "137 pontos" so se
"pontos" estiver escrito na imagem.
""".strip()

ADENDOS_POR_TIPO = {
    "embedded_image": _ADENDO_GRAFICO,
    "table": _ADENDO_TABELA,
    "formula": _ADENDO_FORMULA,
}


def _montar_instrucoes(tipo: str) -> str:
    base = _carregar_prompt(TIPO_PARA_PROMPT[tipo])
    try:
        from core.agents.acessivel import REGRAS_DE_OURO

        base = f"{base}\n\n{REGRAS_DE_OURO}"
    except ImportError:
        pass
    adendo = ADENDOS_POR_TIPO.get(tipo)
    if adendo:
        base = f"{base}\n\n{adendo}"
    return base


@lru_cache(maxsize=None)
def _agente_para(tipo: str):
    from agno.agent import Agent

    if tipo not in TIPO_PARA_PROMPT:
        raise ValueError(f"tipo de regiao sem especialista: {tipo!r}")

    return Agent(
        name=f"especialista-{tipo}",
        model=_construir_modelo_visao(tipo),
        description=TIPO_PARA_PAPEL.get(tipo, "Especialista de acessibilidade"),
        instructions=_montar_instrucoes(tipo),
        markdown=False,
    )


def descrever_regiao(
    tipo: str,
    imagem_bytes: bytes,
    contexto: str | None = None,
) -> str:
    agente = _agente_para(tipo)

    mensagem = "Processe a regiao da imagem seguindo estritamente as regras."
    if contexto:
        mensagem += (
            "\n\n--- CONTEXTO (NAO E CONTEUDO DA IMAGEM) ---\n"
            + contexto
            + "\n--- FIM DO CONTEXTO ---\n"
            "REGRA ABSOLUTA sobre o contexto acima:\n"
            "- ele indica o que e RELEVANTE destacar;\n"
            "- ele NUNCA confirma o que existe na imagem.\n"
            "- E PROIBIDO usar o contexto para afirmar especie, "
            "identidade, nome proprio, quantidade, cor ou qualquer "
            "atributo que voce nao consiga ver nos pixels.\n"
            "- Se o contexto menciona algo que voce nao ve, ignore.\n"
            "- Descreva SOMENTE o que esta visivel."
        )

    from agno.media import Image

    import time as _time
    _t0 = _time.monotonic()
    resultado = agente.run(mensagem, images=[Image(content=imagem_bytes)])
    try:
        from core.services import telemetria
        telemetria.registrar_chamada(
            f"especialista_{tipo}", resultado,
            duracao_ms=int((_time.monotonic() - _t0) * 1000),
            objeto_agente=agente,
        )
    except Exception:
        pass
    return (resultado.content or "").strip()
