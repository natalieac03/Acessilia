"""Confere a coerencia da formula: LATEX x LEITURA e fidelidade.

Duas camadas de verificacao complementares ao critico visual. A
primeira compara os dois campos que o especialista devolveu, sem ver a
imagem: se a leitura menciona uma raiz que o LaTeX nao tem, um dos
dois esta errado.

A segunda audita a descricao da formula contra a expressao de origem.
Nenhuma das duas corrige em silencio — divergencia detectada vira
marcacao de incerteza, porque escolher qual das versoes esta certa
seria transformar uma hipotese em fato matematico.
"""

from __future__ import annotations

import os
import re

from core.utils.logger import logger


import os

from core.utils.logger import logger
from pipeline.matematica.validadores_matematicos import auditar_formula

_PADRAO_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "\ufe0f"
    "]+",
    flags=re.UNICODE,
)

_PADRAO_QUEBRAS = re.compile(r"\n{3,}")


def limpar_para_leitor_de_tela(texto: str) -> str:
    texto = _PADRAO_EMOJI.sub("", texto)
    texto = _PADRAO_QUEBRAS.sub("\n\n", texto)
    texto = re.sub(r"[ \t]{2,}", " ", texto)
    return texto.strip()


def _construir_modelo_texto():
    from agno.models.openrouter import OpenRouter

    modelo = (
        os.getenv("CONFERIDOR_MODELO")
        or os.getenv("PROFESSOR_MODELO")
        or os.getenv("OPENROUTER_TEXT_MODEL")
        or os.getenv("OPENROUTER_MODEL")
        or "deepseek/deepseek-v4-flash"
    )
    parametros: dict = {"id": modelo}
    chave = os.getenv("OPENROUTER_API_KEY")
    if chave:
        parametros["api_key"] = chave
    teto = os.getenv("CONFERIDOR_MAX_TOKENS") or os.getenv("PROFESSOR_MAX_TOKENS")
    if teto:
        try:
            parametros["max_tokens"] = int(teto)
        except ValueError:
            pass
    return OpenRouter(**parametros)


_MARCADOR_INCERTEZA = "[verificacao incerta]"

_INSTRUCOES_CONFERIDOR = """\
Voce confere formulas de material didatico. Voce recebe:
LATEX: a formula em LaTeX.
LEITURA: a mesma formula falada por extenso em portugues.

A LEITURA descreve fielmente a formula do LATEX? Ignore diferencas de
estilo; olhe estrutura: operacoes, fracoes, raizes, expoentes, sinais.

Responda com UMA unica palavra:
SIM - se a leitura corresponde a formula.
NAO - se a leitura contradiz ou omite parte estrutural da formula.
"""


def _extrair_latex_leitura(texto: str) -> tuple[str, str]:
    latex = ""
    leitura = ""
    for linha in texto.splitlines():
        limpa = linha.strip()
        if limpa.startswith(_MARCADOR_INCERTEZA):
            limpa = limpa[len(_MARCADOR_INCERTEZA):].strip()
        maiuscula = limpa.upper()
        if maiuscula.startswith("LATEX:"):
            latex = limpa[len("LATEX:"):].strip()
        elif maiuscula.startswith("LEITURA:"):
            leitura = limpa[len("LEITURA:"):].strip()
    return latex, leitura


def _conferidor_ligado() -> bool:
    for chave in ("USAR_CONFERIDOR", "USAR_PROFESSOR"):
        valor = os.getenv(chave)
        if valor is not None:
            return valor.strip().lower() == "true"
    return False


def conferir_e_marcar_formula(descricao: str) -> str:
    if not _conferidor_ligado():
        return descricao
    if _MARCADOR_INCERTEZA in descricao:
        return descricao

    latex, leitura = _extrair_latex_leitura(descricao)
    if not latex or not leitura:
        return descricao

    try:
        from agno.agent import Agent

        agente = Agent(
            name="conferidor-formula",
            model=_construir_modelo_texto(),
            description="Confere consistencia entre LaTeX e leitura falada",
            instructions=_INSTRUCOES_CONFERIDOR,
            markdown=False,
        )
        import time as _time
        _t0 = _time.monotonic()
        resposta = agente.run(f"LATEX: {latex}\nLEITURA: {leitura}")
        try:
            from core.services import telemetria
            telemetria.registrar_chamada(
                "conferidor", resposta,
                duracao_ms=int((_time.monotonic() - _t0) * 1000),
                objeto_agente=agente,
            )
        except Exception:
            pass
        veredicto = (resposta.content or "").strip().upper()

        if veredicto.startswith("NAO") or veredicto.startswith("NÃO"):
            logger.warning(
                "Conferidor: LEITURA nao corresponde ao LATEX; marcando incerteza"
            )
            return f"{_MARCADOR_INCERTEZA} {descricao}"
        return descricao
    except Exception as erro:
        logger.warning("Conferidor de formula indisponivel ({}); seguindo", erro)
        return descricao


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
        try:
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
    except Exception as erro:
        logger.warning(
            "critico_matematico indisponivel ({}); mantendo o veredito "
            "deterministico",
            erro,
        )
        return {"fiel": True, "problemas": [], "camada": "aprovado"}


def marcar_se_infiel(texto: str, veredito: dict) -> str:
    if veredito.get("fiel", True):
        return texto
    if MARCADOR_INCERTEZA in texto:
        return texto
    return f"{MARCADOR_INCERTEZA} {texto}"


def _extrair_campos(descricao: str) -> tuple[str, str]:
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
    latex, leitura = _extrair_campos(descricao)
    if not latex:
        return descricao, {"fiel": True, "problemas": [], "camada": "ignorado"}

    try:
        from pipeline.matematica.normalizador_matematico import normalizar_latex
        from pipeline.analisador_de_estrutura import _latex_para_mathml

        latex_normalizado = normalizar_latex(latex)
        mathml = _latex_para_mathml(latex_normalizado) or ""
    except Exception as erro:
        logger.warning("critico_matematico: normalizacao falhou ({})", erro)
        latex_normalizado, mathml = latex, ""

    veredito = verificar_formula(
        origem or latex, latex_normalizado, mathml, leitura
    )
    return marcar_se_infiel(descricao, veredito), veredito
