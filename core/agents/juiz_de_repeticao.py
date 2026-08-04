"""

Por que ele existe, e por que so ele resolve: medindo os pares reais de
uma saida de producao, as duas classes SE SOBREPOEM na similaridade de
texto.


O juiz olha a IMAGEM DA PAGINA. E a diferenca decisiva: ele nao compara
duas strings, ele confere as duas contra a fonte. "Estas duas leituras
descrevem a mesma regiao da pagina?" e uma pergunta com resposta
verificavel, ao contrario de "estes dois textos sao parecidos?".

TRES REGRAS DE PROJETO:

1. ELE E ESCALACAO, NAO PRIMEIRA INSTANCIA. So e chamado para os pares
   que o podador marcou como duvidosos. Sem duvida, nao gasta chamada -
   o mesmo criterio do resolvedor de contexto matematico.

2. A DUVIDA FAVORECE MANTER OS DOIS. Sem resposta, sem imagem, sem
   chave, com erro ou com confianca baixa, o veredito e "ambos". Repetir
   um paragrafo incomoda; perder um passo do calculo inviabiliza o
   estudo. O erro barato e o unico que o juiz tem permissao de cometer.

3. ELE NAO REESCREVE NADA. Escolhe entre versoes que ja existem. Um juiz
   que redigisse a versao final estaria descrevendo sem ter sido
   auditado pelo critico visual.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from core.utils.logger import logger


@dataclass
class Veredito:
    """O que o juiz decidiu, e com base em que."""

    sao_o_mesmo: bool = False
    manter: str = "ambos"          # "a" | "b" | "ambos"
    confianca: float = 0.0
    motivo: str = ""
    origem: str = "abstencao"      # deterministico | visao | abstencao
    evidencias: list[str] = field(default_factory=list)

    @property
    def decidiu(self) -> bool:
        return self.manter in ("a", "b")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sao_o_mesmo": self.sao_o_mesmo, "manter": self.manter,
            "confianca": round(self.confianca, 2), "motivo": self.motivo,
            "origem": self.origem, "evidencias": list(self.evidencias),
        }


def _juiz_ligado() -> bool:
    return os.getenv("USAR_JUIZ_REPETICAO", "false").strip().lower() == "true"


def _limiar_confianca() -> float:
    try:
        return float(os.getenv("JUIZ_LIMIAR_CONFIANCA", "0.75"))
    except ValueError:
        return 0.75



_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")


def julgar_deterministicamente(texto_a: str, texto_b: str) -> Veredito:
    """O que da para decidir sem olhar a imagem e sem gastar chamada.

    Cobre os casos em que a evidencia esta no proprio texto: uma das
    versoes ficou truncada, ou uma delas carrega marca de ilegibilidade
    que a outra nao tem. Nesses casos a escolha e obvia e nao ha por que
    consultar um modelo.
    """
    from pipeline.matematica.podador import _grau_de_quebra

    bloco_a = {"type": "paragraph", "text": texto_a}
    bloco_b = {"type": "paragraph", "text": texto_b}
    quebra_a = _grau_de_quebra(bloco_a)
    quebra_b = _grau_de_quebra(bloco_b)

    if quebra_a != quebra_b:
        vencedor = "b" if quebra_a > quebra_b else "a"
        return Veredito(
            sao_o_mesmo=True, manter=vencedor, confianca=0.9,
            origem="deterministico",
            motivo="uma das versoes esta truncada ou marcada como ilegivel",
            evidencias=[f"quebra_a={quebra_a}", f"quebra_b={quebra_b}"],
        )

    # Numeros divergentes: conteudo divergente, sem discussao.
    if _NUMERO.findall(texto_a) != _NUMERO.findall(texto_b):
        return Veredito(
            sao_o_mesmo=False, manter="ambos", confianca=0.9,
            origem="deterministico",
            motivo="os numeros diferem; sao trechos diferentes",
        )
    return Veredito()



_INSTRUCOES_JUIZ = """\
Voce recebe a IMAGEM de uma pagina de material didatico e DUAS leituras
que o sistema produziu a partir dela.

Decida uma coisa so: as duas leituras descrevem O MESMO trecho da pagina?

Confira cada leitura contra a imagem. Preste atencao especial a:
- numeros, sinais, indices e expoentes - se divergem, sao trechos
  DIFERENTES, ainda que a redacao seja quase igual;
- passos consecutivos de um calculo, que se parecem muito e NAO sao a
  mesma coisa (por exemplo x1 com sinal de mais e x2 com sinal de menos);
- leituras cortadas no meio, que descrevem o mesmo trecho de forma
  incompleta.

Se forem o mesmo trecho, diga qual leitura e mais FIEL a imagem.

Responda EXATAMENTE neste formato, sem mais nada:
MESMO: sim|nao
MANTER: A|B|AMBOS
CONFIANCA: <numero entre 0 e 1>
MOTIVO: <uma frase curta>

Na duvida, responda MESMO: nao e MANTER: AMBOS. Perder um passo do
calculo e muito pior que repetir um trecho.
"""


def _construir_modelo_juiz():
    """Modelo de VISAO com raciocinio, configuravel e independente.

    O juiz e o unico agente que compara duas leituras contra a pagina, e
    e onde o raciocinio rende mais - por isso ele tem modelo e nivel de
    esforco proprios, sem encarecer as demais etapas.
    """
    from agno.models.openrouter import OpenRouter

    modelo = (
        os.getenv("JUIZ_MODELO")
        or os.getenv("OPENROUTER_MODEL")
        or "qwen/qwen3-vl-32b-instruct"
    )
    parametros: dict = {"id": modelo}
    chave = os.getenv("OPENROUTER_API_KEY")
    if chave:
        parametros["api_key"] = chave
    from core.ai.esforco_de_raciocinio import normalizar_esforco

    esforco = normalizar_esforco(
        os.getenv("JUIZ_REASONING", "high"), "JUIZ_REASONING"
    )
    if esforco:
        parametros["reasoning_effort"] = esforco
    teto = os.getenv("JUIZ_MAX_TOKENS")
    if teto:
        try:
            parametros["max_tokens"] = int(teto)
        except ValueError:
            pass
    return OpenRouter(**parametros)


def _interpretar_resposta(conteudo: str) -> Veredito:
    """Le o formato tabulado. Resposta fora do formato = abstencao."""
    campos: dict[str, str] = {}
    for linha in (conteudo or "").splitlines():
        if ":" not in linha:
            continue
        chave, _, valor = linha.partition(":")
        campos[chave.strip().upper()] = valor.strip()

    manter = campos.get("MANTER", "AMBOS").strip().upper()
    if manter not in ("A", "B", "AMBOS"):
        manter = "AMBOS"
    mesmo = campos.get("MESMO", "").strip().lower().startswith("s")
    try:
        confianca = float(campos.get("CONFIANCA", "0").replace(",", "."))
    except ValueError:
        confianca = 0.0

    # Coerencia: nao pode escolher um vencedor sem afirmar que sao o
    # mesmo trecho. Incoerencia vira abstencao - resposta confusa nao
    # autoriza descartar conteudo.
    if manter in ("A", "B") and not mesmo:
        manter = "AMBOS"

    return Veredito(
        sao_o_mesmo=mesmo,
        manter="ambos" if manter == "AMBOS" else manter.lower(),
        confianca=max(0.0, min(1.0, confianca)),
        motivo=campos.get("MOTIVO", "")[:200],
        origem="visao",
    )


def julgar_com_visao(
    texto_a: str, texto_b: str, imagem: bytes | None = None
) -> Veredito:
    """O veredito olhando a pagina. Fail-open para "ambos"."""
    if not _juiz_ligado():
        return Veredito(motivo="juiz desligado")
    if not imagem:
        # Sem a imagem, o juiz nao tem nada que o podador ja nao tenha.
        return Veredito(motivo="sem imagem da pagina; abstencao")

    try:
        from agno.agent import Agent
        from agno.media import Image

        agente = Agent(
            name="juiz-repeticao",
            model=_construir_modelo_juiz(),
            description="Decide se duas leituras descrevem o mesmo trecho",
            instructions=_INSTRUCOES_JUIZ,
            markdown=False,
        )
        resposta = agente.run(
            f"LEITURA A:\n{texto_a}\n\nLEITURA B:\n{texto_b}",
            images=[Image(content=imagem)],
        )
        veredito = _interpretar_resposta(resposta.content or "")

        if veredito.decidiu and veredito.confianca < _limiar_confianca():
            logger.info(
                "Juiz: confianca {:.2f} abaixo do limiar; mantendo os dois",
                veredito.confianca,
            )
            veredito.manter = "ambos"
            veredito.motivo = (
                f"confianca insuficiente ({veredito.confianca:.2f})"
            )
        return veredito
    except Exception as erro:
        logger.warning("Juiz de repeticao indisponivel ({}); mantendo", erro)
        return Veredito(motivo=f"falha: {type(erro).__name__}")


def julgar(
    texto_a: str, texto_b: str, imagem: bytes | None = None
) -> Veredito:
    """Ponto de entrada: deterministico primeiro, visao so se preciso."""
    veredito = julgar_deterministicamente(texto_a, texto_b)
    if veredito.origem == "deterministico":
        return veredito
    return julgar_com_visao(texto_a, texto_b, imagem)
