"""Etapa 7 - MATH CONTEXT RESOLVER: reasoning contextual CONTROLADO."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from pydantic import BaseModel, Field

from core.utils.logger import logger

class Ambiguidade(BaseModel):

    tipo: str
    descricao: str
    trecho: str = ""
    alternativas: list[str] = Field(default_factory=list)


_FAIXA_AMBIGUA = (0.4, 1.6)


def avaliar_ambiguidades(
    source_text: str,
    ast=None,
    geometria=None,
    contexto=None,
    boundary=None,
    nao_consumidos: list | None = None,
) -> list[Ambiguidade]:
    ambiguidades: list[Ambiguidade] = []
    texto = source_text or ""

    if geometria is not None:
        try:
            for span in geometria.spans:
                if not span.text.strip().isdigit():
                    continue
                deslocamento = abs(span.baseline_shift)
                if _FAIXA_AMBIGUA[0] <= deslocamento <= _FAIXA_AMBIGUA[1]:
                    ambiguidades.append(Ambiguidade(
                        tipo="indice_ambiguo",
                        descricao=(
                            f"o digito {span.text!r} esta deslocado "
                            f"{span.baseline_shift:.1f}pt - na faixa em que "
                            "nao se distingue sobrescrito de subscrito"
                        ),
                        trecho=span.text,
                        alternativas=["expoente", "indice", "multiplicacao"],
                    ))
        except Exception:
            pass
    elif re.search(r"[A-Za-z]\s?\d", re.sub(r"\\[A-Za-z]+", " ", texto)):
        sem_comandos = re.sub(r"\\[A-Za-z]+", " ", texto)
        if not any(c in texto for c in "⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉^_"):
            trecho = re.search(r"[A-Za-z]\s?\d", sem_comandos).group(0)
            ambiguidades.append(Ambiguidade(
                tipo="indice_ambiguo",
                descricao=("digito colado a variavel sem geometria que "
                           "distinga expoente, indice ou produto"),
                trecho=trecho,
                alternativas=["expoente", "indice", "multiplicacao"],
            ))

    for encontro in re.finditer(r"([⁰-⁹²³]|\d)\s{2,}(\d)", texto):
        ambiguidades.append(Ambiguidade(
            tipo="operador_possivelmente_ausente",
            descricao=("espaco largo entre termos: pode haver um sinal "
                       "apagado na origem"),
            trecho=encontro.group(0),
            alternativas=["subtracao", "adicao", "nenhum operador"],
        ))

    if boundary is not None and not getattr(boundary, "plausivel", True):
        ambiguidades.append(Ambiguidade(
            tipo="fronteira_incompleta",
            descricao=("a expressao nao fecha: " +
                       "; ".join(getattr(boundary, "detalhes", [])[:2])),
            trecho=texto[-24:],
            alternativas=["continua na proxima regiao", "expressao truncada"],
        ))

    if contexto is not None and getattr(contexto, "e_celula", False):
        if re.fullmatch(r"\s*\d+\s*[A-Za-z]\s*", texto):
            ambiguidades.append(Ambiguidade(
                tipo="produto_implicito_em_celula",
                descricao=("celula com coeficiente colado; o cabecalho e a "
                           "linha confirmam se e multiplicacao"),
                trecho=texto.strip(),
                alternativas=["multiplicacao", "rotulo ou ordinal"],
            ))

    for encontro in re.finditer(r"√\s*", texto):
        resto = texto[encontro.end():]
        if not resto or resto.lstrip().startswith("("):
            continue
        primeiro_atomo = re.match(r"[A-Za-z0-9⁰-⁹₀-₉²³Δ∆]+", resto.lstrip())
        if not primeiro_atomo:
            continue
        depois = resto.lstrip()[primeiro_atomo.end():].lstrip()
        if re.match(r"[+\-−·×]\s*\S", depois):
            ambiguidades.append(Ambiguidade(
                tipo="escopo_do_radical",
                descricao=("a barra do radical pode cobrir apenas o primeiro "
                           "termo ou os seguintes; sem parenteses o alcance "
                           "e visual"),
                trecho=(texto[encontro.start():encontro.end()
                              + len(resto.lstrip())][:32]),
                alternativas=["so o primeiro termo", "todos os termos"],
            ))

    if "/" in texto and not re.search(r"\\frac", texto):
        lados = texto.split("/", 1)
        if all(len(lado.strip().split()) > 1 for lado in lados):
            ambiguidades.append(Ambiguidade(
                tipo="fracao_em_linha_unica",
                descricao=("numerador e denominador com varios termos e sem "
                           "parenteses: o alcance da barra e visual"),
                trecho=texto[:40],
                alternativas=["fracao completa", "divisao de termos vizinhos"],
            ))

    if nao_consumidos:
        valores = [getattr(t, "value", str(t)) for t in nao_consumidos]
        ambiguidades.append(Ambiguidade(
            tipo="trecho_nao_interpretado",
            descricao=("o parser deterministico deixou "
                       f"{len(valores)} token(s) de fora da arvore"),
            trecho=" ".join(valores[:6]),
        ))

    if ast is not None:
        try:
            from pipeline.matematica.arvore_matematica import Desconhecido

            for no in ast.percorrer():
                if isinstance(no, Desconhecido) and (no.texto or "").strip():
                    ambiguidades.append(Ambiguidade(
                        tipo="trecho_nao_interpretado",
                        descricao="o parser deterministico nao explicou este trecho",
                        trecho=no.texto,
                    ))
        except Exception:
            pass

    return ambiguidades


def precisa_de_contexto(
    source_text: str, ast=None, geometria=None, contexto=None, boundary=None,
    nao_consumidos: list | None = None,
) -> bool:
    return bool(avaliar_ambiguidades(
        source_text, ast, geometria, contexto, boundary, nao_consumidos
    ))


class Interpretacao(BaseModel):
    node: str
    operands: list[Any] = Field(default_factory=list)


class ContextResolution(BaseModel):
    source_span: str
    interpretation: Interpretacao
    speech_pt_br: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    alternatives_rejected: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    source_tokens: list[str] = Field(default_factory=list)
    candidate_asts: list[dict] = Field(default_factory=list)
    aceita: bool = True
    violacoes: list[str] = Field(default_factory=list)

    @property
    def chosen_ast(self) -> dict:
        return self.interpretation.model_dump()


_MARCAS_PEDAGOGICAS = (
    "isso significa", "ou seja", "note que", "observe que", "lembre",
    "por exemplo", "portanto", "concluimos", "concluímos", "aprenda",
    "esta formula serve", "esta fórmula serve", "usamos essa",
)


def verificar_proibicoes(
    resolucao: ContextResolution, source_text: str,
) -> list[str]:
    violacoes: list[str] = []
    span = resolucao.source_span or ""
    fala = (resolucao.speech_pt_br or "").lower()

    igualdades_origem = source_text.count("=")
    igualdades_span = span.count("=")
    if igualdades_origem >= 2 and igualdades_span < igualdades_origem:
        violacoes.append(
            f"simplificou a cadeia de igualdade ({igualdades_origem} -> "
            f"{igualdades_span} igualdades)"
        )

    def _digitos(texto: str) -> list[str]:
        return sorted(re.findall(r"\d", texto))

    if span and _digitos(span) != _digitos(source_text):
        if not resolucao.alternatives_rejected and not resolucao.evidence:
            violacoes.append(
                "alterou os termos da expressao sem registrar evidencia "
                "nem alternativa rejeitada"
            )

    operadores_novos = {
        op for op in ("+", "-", "±", "/", "=", "·")
        if span.count(op) > source_text.count(op)
    }
    if operadores_novos and not resolucao.evidence:
        violacoes.append(
            "inseriu operador(es) " + ", ".join(sorted(operadores_novos))
            + " sem apresentar evidencia"
        )

    for marca in _MARCAS_PEDAGOGICAS:
        if marca in fala:
            violacoes.append(
                f"a fala contem explicacao pedagogica ({marca!r}); a "
                "transcricao deve ser so a leitura da expressao"
            )
            break

    if resolucao.confidence >= 0.99 and resolucao.requires_human_review is False:
        if not resolucao.evidence:
            violacoes.append(
                "declarou confianca maxima e dispensou revisao sem "
                "apresentar evidencia"
            )

    if resolucao.speech_pt_br and not (resolucao.interpretation.node or "").strip():
        violacoes.append(
            "devolveu fala sem a interpretacao estrutural (node) - a fala "
            "precisa derivar da AST"
        )

    return violacoes


_INSTRUCOES = """Voce e um resolvedor de estrutura matematica.

TAREFA
1. Observe SOMENTE o recorte e o texto fornecidos.
2. Use o texto anterior, o posterior e o contexto da tabela.
3. Identifique todos os simbolos visiveis.
4. Determine as relacoes: expoente, subscrito, raiz, fracao,
   agrupamento, multiplicacao e igualdade.
5. NAO simplifique e NAO corrija matematicamente a expressao.
6. NAO omita etapas de uma cadeia de igualdade.
7. Se a evidencia for insuficiente, marque requires_human_review=true.

Voce decide um ponto DUVIDOSO especifico - nao transcreve a expressao
inteira. Admitir duvida e a resposta correta quando ha duvida.

PESO DAS EVIDENCIAS, em ordem:
1. a geometria informada (deslocamento vertical, tamanho de fonte);
2. o texto imediatamente antes e depois;
3. o cabecalho da coluna e o restante da linha, se for tabela;
4. outras ocorrencias da mesma expressao no documento.

PROIBIDO
- simplificar uma cadeia de igualdade (todos os passos permanecem);
- trocar a expressao por uma equivalente;
- inserir operador sem evidencia visual ou contextual;
- misturar explicacao pedagogica com a transcricao;
- devolver fala sem a estrutura correspondente.

EXEMPLOS

Entrada: "2a"
Contexto da linha: "Denominador: duas vezes o coeficiente a."
{
  "source_span": "2a",
  "source_tokens": ["2", "a"],
  "candidate_asts": [
    {"node": "Multiply", "operands": [2, "a"]},
    {"node": "Ordinal", "operands": ["segunda"]}
  ],
  "interpretation": {"node": "Multiply", "operands": [2, "a"]},
  "speech_pt_br": "dois vezes a",
  "evidence": ["a descricao da mesma linha diz 'duas vezes o coeficiente a'"],
  "alternatives_rejected": ["numeral ordinal 'segunda': o contexto da linha o contradiz"],
  "confidence": 0.99,
  "requires_human_review": false
}

Entrada: "raiz de Delta"
{
  "source_span": "\u221a\u0394",
  "source_tokens": ["\u221a", "\u0394"],
  "candidate_asts": [{"node": "Sqrt", "operands": ["Delta"]}],
  "interpretation": {"node": "Sqrt", "operands": ["Delta"]},
  "speech_pt_br": "raiz quadrada de delta",
  "evidence": ["o radical cobre apenas o simbolo delta"],
  "alternatives_rejected": [],
  "confidence": 0.97,
  "requires_human_review": false
}

Entrada: "(x - 2)(x - 3) = 0"
{
  "source_span": "(x - 2)(x - 3) = 0",
  "source_tokens": ["(", "x", "-", "2", ")", "(", "x", "-", "3", ")", "=", "0"],
  "candidate_asts": [
    {"node": "Equality", "operands": ["Multiply(Group,Group)", 0]}
  ],
  "interpretation": {"node": "Equality",
                     "operands": ["Multiply(Group(Subtract(x,2)),Group(Subtract(x,3)))", 0]},
  "speech_pt_br": "abre parenteses, xis menos dois, fecha parenteses, vezes, abre parenteses, xis menos tres, fecha parenteses, e igual a zero",
  "evidence": ["dois pares de parenteses completos", "o lado direito da igualdade esta presente"],
  "alternatives_rejected": [],
  "confidence": 0.96,
  "requires_human_review": false
}

Responda APENAS com um objeto JSON valido, sem cercas de codigo, com as
chaves: source_span, source_tokens, candidate_asts, interpretation,
speech_pt_br, evidence, alternatives_rejected, confidence,
requires_human_review."""


def _extrair_json(texto: str) -> dict | None:
    if not texto:
        return None
    limpo = re.sub(r"```(?:json)?", "", texto).strip()
    inicio = limpo.find("{")
    if inicio < 0:
        return None
    fragmento = limpo[inicio:]
    try:
        objeto, _ = json.JSONDecoder().raw_decode(fragmento)
        if isinstance(objeto, dict):
            return objeto
    except json.JSONDecodeError:
        pass
    from core.agents.critico_visual import _reparar_json_truncado

    return _reparar_json_truncado(fragmento)


def _montar_mensagem(
    source_text: str,
    ambiguidades: list[Ambiguidade],
    antes: str,
    depois: str,
    cabecalho_coluna: str | None,
    contexto_linha: str | None,
    ocorrencias_equivalentes: list[str],
) -> str:
    partes = [f"TRECHO A INTERPRETAR:\n{source_text}", ""]
    partes.append("AMBIGUIDADES DETECTADAS:")
    for ambiguidade in ambiguidades:
        alternativas = (" | alternativas: " + ", ".join(ambiguidade.alternativas)
                        if ambiguidade.alternativas else "")
        partes.append(
            f"- [{ambiguidade.tipo}] {ambiguidade.descricao}{alternativas}"
        )
    partes.append("")
    if antes:
        partes.append(f"TEXTO ANTES: {antes[-240:]}")
    if depois:
        partes.append(f"TEXTO DEPOIS: {depois[:240]}")
    if cabecalho_coluna:
        partes.append(f"CABECALHO DA COLUNA: {cabecalho_coluna}")
    if contexto_linha:
        partes.append(f"CONTEXTO DA LINHA: {contexto_linha}")
    if ocorrencias_equivalentes:
        partes.append(
            "OUTRAS OCORRENCIAS DA MESMA EXPRESSAO NO DOCUMENTO: "
            + " | ".join(ocorrencias_equivalentes[:4])
        )
    return "\n".join(partes)


def resolver_com_contexto(
    source_text: str,
    ambiguidades: list[Ambiguidade] | None = None,
    imagem: bytes | None = None,
    antes: str = "",
    depois: str = "",
    cabecalho_coluna: str | None = None,
    contexto_linha: str | None = None,
    ocorrencias_equivalentes: list[str] | None = None,
) -> ContextResolution | None:
    ambiguidades = ambiguidades or avaliar_ambiguidades(source_text)
    if not ambiguidades:
        return None
    if os.getenv("USAR_RESOLVEDOR_CONTEXTO", "false").lower() != "true":
        logger.info(
            "resolvedor de contexto desligado; {} ambiguidade(s) vao para "
            "revisao humana", len(ambiguidades),
        )
        return None

    try:
        import time as _time

        from agno.agent import Agent

        from core.agents.conferidor_de_formulas import _construir_modelo_texto

        agente = Agent(
            model=_construir_modelo_texto(),
            description="Resolvedor de ambiguidade matematica",
            instructions=_INSTRUCOES,
            markdown=False,
        )
        mensagem = _montar_mensagem(
            source_text, ambiguidades, antes, depois, cabecalho_coluna,
            contexto_linha, ocorrencias_equivalentes or [],
        )
        _t0 = _time.monotonic()
        if imagem:
            from agno.media import Image

            resultado = agente.run(mensagem, images=[Image(content=imagem)])
        else:
            resultado = agente.run(mensagem)
        try:
            from core.services import telemetria

            telemetria.registrar_chamada(
                "resolvedor_contexto", resultado,
                duracao_ms=int((_time.monotonic() - _t0) * 1000),
                objeto_agente=agente,
            )
        except Exception:
            pass

        dados = _extrair_json(resultado.content or "")
        if not dados:
            logger.warning("resolvedor de contexto: resposta sem JSON valido")
            return None
        resolucao = ContextResolution(**dados)
    except (ModuleNotFoundError, ImportError) as erro:
        logger.warning("resolvedor de contexto indisponivel ({})", erro)
        return None
    except Exception as erro:
        logger.warning(
            "resolvedor de contexto falhou ({}: {})", type(erro).__name__, erro
        )
        return None

    violacoes = verificar_proibicoes(resolucao, source_text)
    if violacoes:
        resolucao.aceita = False
        resolucao.violacoes = violacoes
        resolucao.requires_human_review = True
        logger.warning(
            "resolucao contextual REPROVADA ({} violacao(oes)): {}",
            len(violacoes), "; ".join(violacoes)[:200],
        )
    return resolucao


def aplicar_resolucao(no_matematico, resolucao: ContextResolution | None):
    if resolucao is None:
        return no_matematico
    registro = [
        f"resolucao contextual: {resolucao.interpretation.node} "
        f"(confianca {resolucao.confidence:.2f})"
    ]
    registro += [f"evidencia: {e}" for e in resolucao.evidence[:3]]
    registro += [
        f"alternativa rejeitada: {a}" for a in resolucao.alternatives_rejected[:3]
    ]
    if not resolucao.aceita:
        registro.append(
            "RESOLUCAO REPROVADA pelas proibicoes: "
            + "; ".join(resolucao.violacoes)
        )

    no_matematico.uncertainties = list(no_matematico.uncertainties) + registro
    if not resolucao.aceita or resolucao.requires_human_review:
        no_matematico.review_status = "needs_review"
    return no_matematico
