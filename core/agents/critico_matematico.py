"""

Ordem de execucao, de proposito:
  1. CAMADA DETERMINISTICA (sempre roda, sem IA, sem rede): cobertura de
     termos, arvore MathML, coerencia LaTeX/leitura. Pega os erros
     estruturais - que sao a maioria - de graca e sem alucinacao.
  2. CAMADA DE IA (opcional, USAR_CRITICO_MATEMATICO=true): so e acionada
     quando a deterministica APROVA, para procurar o que codigo nao ve
     (sinal trocado, termo reordenado, indice no elemento errado).


"""

from __future__ import annotations

import os

from core.utils.logger import logger
from pipeline.matematica.validadores_matematicos import auditar_formula

MARCADOR_INCERTEZA = "[verificacao incerta]"

_INSTRUCOES_CRITICO_MATEMATICO = """Voce confere a FIDELIDADE de uma formula
matematica adaptada para um estudante cego. Voce recebe quatro
representacoes da MESMA formula e deve dizer se elas concordam.

Verifique, nesta ordem:
1. Todos os termos da ORIGEM aparecem no LATEX (nenhum passo removido).
2. Sinais (+, -, +-) estao corretos e na mesma ordem.
3. Expoentes e indices estao no elemento CERTO: em (-5)^2 o expoente
   pertence ao grupo (-5), nao ao parentese.
4. Numerador e denominador correspondem a fracao original.
5. A raiz cobre exatamente os termos que cobria na origem.
6. A LEITURA falada descreve a mesma expressao, dizendo onde comecam e
   terminam numerador, denominador e raiz.

NAO reclame de formatacao, espacos ou da escolha entre \\cdot e x.
NAO exija que a leitura seja literal - ela deve ser natural em portugues.
Uma cadeia de igualdade ("= 6/2 = 3") deve manter TODOS os passos.

Responda APENAS com uma das formas:
FIEL
ou
INFIEL: <problema concreto, citando o termo>
"""


def _construir_agente():
    from agno.agent import Agent

    from core.agents.conferidor_de_formulas import _construir_modelo_texto

    return Agent(
        model=_construir_modelo_texto(),
        description="Critico de fidelidade matematica",
        instructions=_INSTRUCOES_CRITICO_MATEMATICO,
        markdown=False,
    )


def verificar_formula(
    origem: str,
    latex: str,
    mathml: str,
    leitura: str,
) -> dict:
    """Audita uma formula nas quatro representacoes.

    Returns:
        {
          "fiel": bool,
          "problemas": [str, ...],
          "camada": "deterministica" | "ia" | "aprovado",
        }
    """
    veredito = auditar_formula(origem, latex, mathml, leitura)
    if not veredito["aprovada"]:
        logger.warning(
            "critico_matematico: {} problema(s) estrutural(is): {}",
            len(veredito["problemas"]),
            "; ".join(veredito["problemas"])[:200],
        )
        return {
            "fiel": False,
            "problemas": veredito["problemas"],
            "camada": "deterministica",
        }

    if os.getenv("USAR_CRITICO_MATEMATICO", "false").lower() != "true":
        return {"fiel": True, "problemas": [], "camada": "aprovado"}

    # Camada de IA: procura o que o codigo nao consegue ver.
    try:
        import time as _time

        agente = _construir_agente()
        mensagem = (
            f"ORIGEM (como aparece no material):\n{origem}\n\n"
            f"LATEX gerado:\n{latex}\n\n"
            f"LEITURA falada gerada:\n{leitura}"
        )
        _t0 = _time.monotonic()
        resultado = agente.run(mensagem)
        try:  # telemetria do painel (fail-open)
            from core.services import telemetria

            telemetria.registrar_chamada(
                "critico_matematico",
                resultado,
                duracao_ms=int((_time.monotonic() - _t0) * 1000),
                objeto_agente=agente,
            )
        except Exception:
            pass

        resposta = (resultado.content or "").strip()
        if resposta.upper().startswith("INFIEL"):
            problema = resposta.split(":", 1)[-1].strip() or "nao detalhado"
            logger.warning("critico_matematico (IA): {}", problema[:200])
            return {"fiel": False, "problemas": [problema], "camada": "ia"}
        return {"fiel": True, "problemas": [], "camada": "ia"}
    except Exception as erro:  # fail-open
        logger.warning(
            "critico_matematico indisponivel ({}); mantendo o veredito "
            "deterministico",
            erro,
        )
        return {"fiel": True, "problemas": [], "camada": "aprovado"}


def marcar_se_infiel(texto: str, veredito: dict) -> str:
    """Anexa o marcador de incerteza quando a formula nao passou.

    O marcador leva a regiao para reviewStatus="draft" no sidecar
    os avisos da fórmula, sem descartar
    o conteudo (o aluno recebe a formula, sinalizada).
    """
    if veredito.get("fiel", True):
        return texto
    if MARCADOR_INCERTEZA in texto:
        return texto
    return f"{MARCADOR_INCERTEZA} {texto}"


def _extrair_campos(descricao: str) -> tuple[str, str]:
    """Separa (latex, leitura) da saida do especialista de formula.

    Formato esperado:
        LATEX: x = \\frac{-b}{2a}
        LEITURA: x e igual a menos b sobre dois a
    Tolera o marcador de incerteza antes do LATEX e linhas extras.
    """
    latex = leitura = ""
    for linha in (descricao or "").splitlines():
        limpo = linha.strip()
        if limpo.startswith(MARCADOR_INCERTEZA):
            limpo = limpo[len(MARCADOR_INCERTEZA):].strip()
        maiuscula = limpo.upper()
        if maiuscula.startswith("LATEX:"):
            latex = limpo[len("LATEX:"):].strip()
        elif maiuscula.startswith("LEITURA:"):
            leitura = limpo[len("LEITURA:"):].strip()
    return latex, leitura


def auditar_descricao_de_formula(
    descricao: str, origem: str | None = None,
) -> tuple[str, dict]:
    """Audita a saida do especialista de formula, ainda em texto cru.

    Este e o ponto do pipeline em que a formula existe como
    "LATEX:/LEITURA:", antes do analisador_de_estrutura montar o bloco math.
    Auditar aqui permite MARCAR a incerteza a tempo de ela chegar ao
    os avisos que acompanham a fórmula.

    Args:
        descricao: texto do especialista (LATEX:/LEITURA:).
        origem: texto bruto extraido do PDF para aquela regiao. E o que
            permite a verificacao de COBERTURA (nenhum passo do calculo
            pode desaparecer). Sem ele, a checagem roda so com as
            verificacoes estruturais.

    Returns:
        (descricao_possivelmente_marcada, veredito)
    """
    latex, leitura = _extrair_campos(descricao)
    if not latex:
        # Nao e uma formula no formato esperado: nada a auditar.
        return descricao, {"fiel": True, "problemas": [], "camada": "ignorado"}

    try:
        from pipeline.matematica.normalizador_matematico import normalizar_latex
        from pipeline.analisador_de_estrutura import _latex_para_mathml

        latex_normalizado = normalizar_latex(latex)
        mathml = _latex_para_mathml(latex_normalizado) or ""
    except Exception as erro:  # fail-open
        logger.warning("critico_matematico: normalizacao falhou ({})", erro)
        latex_normalizado, mathml = latex, ""

    veredito = verificar_formula(
        origem or latex, latex_normalizado, mathml, leitura
    )
    return marcar_se_infiel(descricao, veredito), veredito
