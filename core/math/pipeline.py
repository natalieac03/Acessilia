from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.matematica.evidencia_matematica import MathCandidate, RegionContext, SourceEvidence
from pipeline.matematica.nos_matematicos import MathNode


@dataclass
class ConfiguracaoDoPipeline:

    modo_fala: str = "estrutural"
    soletrar_variaveis: bool = True
    indice_tecnico: bool = False
    preservar_forma: bool = True
    usar_resolvedor_de_contexto: bool = True
    gerar_omml: bool = True
    rastrear: bool = False
    reparar_scripts: bool = True


@dataclass
class ResultadoDoPipeline:

    node: MathNode
    ast: Any = None
    tokens: list = field(default_factory=list)
    candidato: MathCandidate | None = None
    resolucao_contextual: Any = None
    trilha: Any = None


_PALAVRAS_MATEMATICAS = frozenset("""
delta alpha beta gamma theta lambda sigma omega pi phi epsilon
sqrt frac sen sin cos tan log ln exp lim int sum max min
""".split())

_MAX_PALAVRAS_DE_PROSA = 3


def _entrada_e_so_expressao(texto: str) -> bool:
    import re as _re

    palavras = [
        p.lower() for p in _re.findall(r"[A-Za-zÀ-ú]{3,}", texto)
    ]
    prosa = [p for p in palavras if p not in _PALAVRAS_MATEMATICAS]
    return len(prosa) <= _MAX_PALAVRAS_DE_PROSA


class PipelineMatematico:

    def __init__(self, configuracao: ConfiguracaoDoPipeline | None = None):
        self.configuracao = configuracao or ConfiguracaoDoPipeline()

    def processar(
        self,
        evidencia: SourceEvidence | str,
        contexto: RegionContext | None = None,
        vizinhos: list | None = None,
    ) -> MathNode:
        return self.processar_detalhado(evidencia, contexto, vizinhos).node

    def processar_detalhado(
        self,
        evidencia: SourceEvidence | str,
        contexto: RegionContext | None = None,
        vizinhos: list | None = None,
    ) -> ResultadoDoPipeline:
        evidencia = self._normalizar_evidencia(evidencia)
        contexto = contexto or RegionContext()

        trilha = None
        if self.configuracao.rastrear:
            try:
                from core.services.trilha_matematica import abrir_trilha

                trilha = abrir_trilha(evidencia.region_id, evidencia.raw_text)
                trilha.registrar(
                    "evidencia",
                    raw_lines=evidencia.raw_lines or None,
                    image_crop_path=evidencia.image_crop_path,
                    sobrescritos=len(evidencia.superscript_candidates) or None,
                )
            except Exception:
                trilha = None

        evidencia, issues_do_reparo = self.reparar(
            evidencia, contexto, vizinhos, trilha
        )
        geometria = getattr(evidencia, "geometry", None)
        candidato = self.montar(evidencia, contexto, vizinhos, trilha)
        tokens = self.tokenizar(candidato, geometria, trilha)
        parse = self.analisar(candidato, geometria, tokens, trilha)
        ast, resolucao, issues_de_contexto = self.resolver_se_necessario(
            parse, evidencia, contexto, trilha
        )
        coletor_de_fala: list = []
        node = self.serializar_e_falar(
            ast, evidencia, candidato, trilha, coletor_de_fala
        )
        issues = self.validar(
            node, evidencia, ast, parse, trilha, candidato,
            coletor_de_fala[0] if coletor_de_fala else None,
        )
        issues = issues_do_reparo + issues_de_contexto + issues
        node = self.aplicar_status(node, issues, parse, resolucao, trilha)

        if trilha is not None:
            trilha.review_status = node.review_status
            trilha.registrar(
                "publicacao", review_status=node.review_status,
                publicavel=not node.bloqueia_publicacao,
            )
        return ResultadoDoPipeline(
            node=node, ast=ast, tokens=tokens, candidato=candidato,
            resolucao_contextual=resolucao, trilha=trilha,
        )

    def reparar(
        self,
        evidencia: SourceEvidence,
        contexto: RegionContext,
        vizinhos: list | None = None,
        trilha=None,
    ) -> tuple[SourceEvidence, list[dict]]:
        if not self.configuracao.reparar_scripts:
            return evidencia, []

        texto = evidencia.raw_text or ""
        if not texto.strip():
            return evidencia, []

        if self._geometria_explica_scripts(evidencia):
            if trilha is not None:
                trilha.registrar(
                    "reparo", aplicado=False,
                    motivo="geometria conclusiva; decidido no tokenizador",
                )
            return evidencia, []

        try:
            from pipeline.matematica.normalizador_matematico import (
                DocumentContext,
                revisar_scripts_perdidos,
            )

            documento = DocumentContext(
                section_title=getattr(contexto, "texto_vizinho", "") or "",
                section_topic=getattr(contexto, "texto_vizinho", "") or "",
                nearby_formulas=[
                    str(getattr(v, "source_text", v) or "")
                    for v in (vizinhos or [])
                ],
            )
            reparado, issues = revisar_scripts_perdidos(
                texto,
                glifos=None,
                geometria=getattr(evidencia, "geometry", None),
                documento=documento,
                contexto=contexto,
                formulas_documento=vizinhos or None,
            )
        except Exception as erro:
            if trilha is not None:
                trilha.registrar(
                    "reparo", aplicado=False,
                    falha=f"{type(erro).__name__}: {erro}",
                )
            return evidencia, []

        como_dict = [
            i.to_dict() if hasattr(i, "to_dict") else dict(i) for i in issues
        ]
        if trilha is not None:
            trilha.registrar(
                "reparo",
                aplicado=reparado != texto or None,
                texto_reparado=reparado if reparado != texto else None,
                codigos=sorted({
                    i.get("code") for i in como_dict if i.get("code")
                }) or None,
            )

        if reparado == texto:
            return evidencia, como_dict

        from pipeline.catalogo_de_evidencias import realinhar_geometria

        return (
            evidencia.model_copy(
                update={
                    "raw_text": reparado,
                    "geometry": realinhar_geometria(
                        evidencia.geometry, reparado
                    ),
                }
            ),
            como_dict,
        )

    @staticmethod
    def _geometria_explica_scripts(evidencia: SourceEvidence) -> bool:
        if (
            getattr(evidencia, "superscript_candidates", None)
            or getattr(evidencia, "subscript_candidates", None)
        ):
            return True
        geometria = getattr(evidencia, "geometry", None)
        if geometria is None or not getattr(geometria, "spans", None):
            return False
        try:
            deslocados = geometria.deslocamentos_em(
                0, len(evidencia.raw_text or "")
            )
        except Exception:
            return False
        return any(s.text.strip() for s in deslocados)

    def montar(
        self,
        evidencia: SourceEvidence,
        contexto: RegionContext,
        vizinhos: list | None = None,
        trilha=None,
    ) -> MathCandidate:
        from pipeline.matematica.fronteira_matematica import (
            expandir_fronteira,
            validar_fronteira_expressao,
        )
        from pipeline.matematica.matematica_inline import detectar_candidatos_matematicos

        texto = evidencia.raw_text

        if getattr(contexto, "tipo_regiao", "") == "formula":
            candidato = MathCandidate(
                start=0, end=len(texto), source_text=texto,
                signals=["contexto:expressao_ja_isolada"],
            )
            candidatos = [candidato]
        else:
            candidatos = detectar_candidatos_matematicos(
                texto, getattr(evidencia, "geometry", None), contexto
            )
            if candidatos:
                candidato = max(
                    candidatos, key=lambda c: (c.score, len(c.source_text))
                )
            else:
                candidato = MathCandidate(
                    start=0, end=len(texto), source_text=texto,
                    signals=["contexto:sem_sinal_detectado"],
                )

            inteiro = texto.strip()
            recorte_valido = validar_fronteira_expressao(
                candidato.source_text
            ).plausivel
            if (
                inteiro
                and (
                    not recorte_valido
                    or len(candidato.source_text) < len(inteiro) * 0.6
                )
                and _entrada_e_so_expressao(inteiro)
                and validar_fronteira_expressao(inteiro).plausivel
            ):
                candidato = MathCandidate(
                    start=0, end=len(texto), source_text=inteiro,
                    signals=["contexto:entrada_inteira_e_expressao"],
                )

        fronteira = validar_fronteira_expressao(candidato.source_text)
        if not fronteira.plausivel and vizinhos:
            candidato = expandir_fronteira(candidato, vizinhos)
            fronteira = validar_fronteira_expressao(candidato.source_text)

        if trilha is not None:
            trilha.registrar(
                "detector",
                result="math_candidate" if candidatos else "text",
                candidatos=len(candidatos) or None,
                sinais=candidato.signals[:6] or None,
            )
            trilha.registrar(
                "fronteira", plausivel=fronteira.plausivel,
                detalhes=fronteira.detalhes or None,
                perdeu=not fronteira.plausivel or None,
            )
        return candidato

    def tokenizar(self, candidato: MathCandidate, geometria=None,
                  trilha=None) -> list:
        from pipeline.matematica.arvore_matematica import tokenizar as _tokenizar

        tokens = _tokenizar(candidato.source_text, geometria)
        if trilha is not None:
            trilha.registrar(
                "tokenizer",
                tokens=[t.value for t in tokens],
                kinds=[t.kind for t in tokens],
                por_geometria=sum(
                    1 for t in tokens if t.origem == "geometria"
                ) or None,
            )
        return tokens

    def analisar(self, candidato: MathCandidate, geometria=None,
                 tokens: list | None = None, trilha=None):
        from pipeline.matematica.arvore_matematica import construir_ast

        resultado = construir_ast(candidato.source_text, geometria)
        if trilha is not None:
            from pipeline.matematica.nos_matematicos import indexar_formula

            trilha.registrar(
                "parser",
                ast_hash=indexar_formula(resultado.ast),
                ast_tipo=resultado.ast.tipo,
                completa=resultado.completa,
                descartados=[t.value for t in resultado.nao_consumidos] or None,
                perdeu=bool(resultado.nao_consumidos) or None,
            )
        return resultado

    def resolver_se_necessario(
        self, parse, evidencia: SourceEvidence,
        contexto: RegionContext, trilha=None,
    ):
        issues: list[dict] = []
        try:
            from core.agents.resolvedor_de_contexto_matematico import (
                avaliar_ambiguidades,
                resolver_com_contexto,
            )

            ambiguidades = avaliar_ambiguidades(
                evidencia.raw_text, parse.ast,
                getattr(evidencia, "geometry", None), contexto,
                nao_consumidos=parse.nao_consumidos,
            )
            if not ambiguidades:
                return parse.ast, None, issues

            if trilha is not None:
                trilha.registrar(
                    "contexto", acionado=True,
                    ambiguidades=[a.tipo for a in ambiguidades],
                )

            resolucao = None
            if self.configuracao.usar_resolvedor_de_contexto:
                resolucao = resolver_com_contexto(
                    evidencia.raw_text, ambiguidades,
                    antes=getattr(contexto, "texto_vizinho", ""),
                    cabecalho_coluna=(
                        contexto.texto_vizinho if contexto.e_celula else None
                    ),
                )

            if resolucao is None:
                issues.append({
                    "check": "contexto_matematico",
                    "severity": "ERROR",
                    "message": "Ambiguidade matematica nao resolvida.",
                    "evidence": [a.tipo for a in ambiguidades],
                })

            return parse.ast, resolucao, issues
        except Exception:
            return parse.ast, None, issues

    def serializar_e_falar(
        self, ast, evidencia: SourceEvidence,
        candidato: MathCandidate | None = None, trilha=None,
        plano_de_fala: list | None = None,
    ) -> MathNode:
        from pipeline.matematica.serializacao_matematica import gerar_latex, gerar_mathml, gerar_omml
        from pipeline.matematica.fala_matematica import gerar_fala_matematica

        latex = gerar_latex(ast)
        mathml = gerar_mathml(ast, latex)
        omml = gerar_omml(ast) if self.configuracao.gerar_omml else ""
        fala = gerar_fala_matematica(
            ast, modo=self.configuracao.modo_fala,
            soletrar_variaveis=self.configuracao.soletrar_variaveis,
            indice_tecnico=self.configuracao.indice_tecnico,
        )
        fala_concisa = gerar_fala_matematica(
            ast, modo="conciso",
            soletrar_variaveis=self.configuracao.soletrar_variaveis,
            indice_tecnico=self.configuracao.indice_tecnico,
        )

        if trilha is not None:
            trilha.registrar(
                "speech", text=fala.texto, modo=fala.modo,
                avisos=fala.avisos or None, perdeu=fala.tem_lacuna or None,
            )
            trilha.registrar(
                "serializacao", latex=latex, omml_ok=bool(omml) or None,
                mathml_nos=sorted({
                    marca for marca in ("mfrac", "msup", "msub", "msqrt")
                    if f"<{marca}>" in mathml
                }) or None,
            )

        if plano_de_fala is not None:
            plano_de_fala.append(fala)

        origem = candidato.source_text if candidato else evidencia.raw_text
        return MathNode(
            source_text=origem,
            source_bbox=getattr(evidencia, "bbox", None),
            ast=ast.to_dict() if ast is not None else {},
            latex=latex, mathml=mathml, omml=omml,
            speech_pt_br=fala.texto,
            speech_pt_br_concisa=fala_concisa.texto,
            uncertainties=list(fala.avisos),
        )

    def validar(self, node: MathNode, evidencia: SourceEvidence,
                ast=None, parse=None, trilha=None,
                candidato: MathCandidate | None = None,
                fala=None) -> list[dict]:
        from pipeline.matematica.cobertura_matematica import (
            comparar_latex_e_mathml,
            validar_cobertura_da_fala,
            validar_cobertura_simbolica,
            validar_serializacoes,
        )

        origem = (candidato.source_text if candidato
                  else evidencia.raw_text)
        issues: list[dict] = []
        try:
            from pipeline.matematica.fala_matematica import SpeechPlan

            plano = fala if fala is not None else SpeechPlan(
                texto=node.speech_pt_br
            )
            relatorio = validar_cobertura_simbolica(
                evidence=origem, ast=ast, speech=plano,
                latex=node.latex, mathml=node.mathml,
                nao_consumidos=(parse.nao_consumidos if parse else None),
                tokens=(parse.tokens if parse else None),
            )
            issues += [i.to_dict() for i in relatorio.issues]
            issues += [
                i.to_dict() for i in validar_serializacoes(
                    ast, node.latex, node.mathml, node.omml
                )
            ]
            issues += [
                i.to_dict()
                for i in comparar_latex_e_mathml(node.latex, node.mathml)
            ]
            issues += [
                i.to_dict() for i in validar_cobertura_da_fala(
                    origem, ast, node.speech_pt_br, plano
                )
            ]
        except Exception as erro:
            issues.append({
                "check": "pipeline", "severity": "INFO", "code": "",
                "message": f"validacao parcial: {type(erro).__name__}: {erro}",
            })

        vistos, unicos = set(), []
        for issue in issues:
            chave = (issue.get("code"), issue.get("message"))
            if chave in vistos:
                continue
            vistos.add(chave)
            unicos.append(issue)

        if trilha is not None:
            trilha.registrar(
                "validator", issues=unicos or None,
                codigos=sorted({
                    i["code"] for i in unicos if i.get("code")
                }) or None,
            )
        return unicos

    def aplicar_status(
        self, node: MathNode, issues: list[dict], parse=None,
        resolucao=None, trilha=None,
    ) -> MathNode:
        node.validation_issues = issues
        bloqueia = any(i.get("severity") == "BLOCKER" for i in issues)
        acionaveis = [
            i for i in issues
            if str(i.get("severity", "")).upper() not in ("INFO", "")
        ]
        ambiguidade_aberta = any(
            str(i.get("check", "")) == "contexto_matematico" for i in issues
        )
        incompleto = parse is not None and not parse.completa
        pede_revisao = bool(
            resolucao is not None and (
                not getattr(resolucao, "aceita", True)
                or getattr(resolucao, "requires_human_review", False)
            )
        )

        if bloqueia or incompleto or pede_revisao or ambiguidade_aberta:
            node.review_status = "needs_review"
            node.confidence = 0.3 if bloqueia else 0.6
        elif acionaveis:
            node.review_status = "draft"
            node.confidence = 0.7
        else:
            node.review_status = "reviewed"
            node.confidence = 0.95

        if resolucao is not None:
            from core.agents.resolvedor_de_contexto_matematico import aplicar_resolucao

            node = aplicar_resolucao(node, resolucao)
        if incompleto:
            node.uncertainties = list(node.uncertainties) + [
                "o parser nao explicou a expressao inteira"
            ]
        return node

    @staticmethod
    def _normalizar_evidencia(evidencia) -> SourceEvidence:
        if isinstance(evidencia, SourceEvidence):
            return evidencia
        texto = str(evidencia or "")
        return SourceEvidence(
            document_id="avulso", page_number=0,
            region_id=f"avulso-{abs(hash(texto)) % 10**8}",
            bbox=(0.0, 0.0, 0.0, 0.0), raw_text=texto,
            raw_lines=[texto] if texto else [],
            extraction_engine="entrada-direta",
        )


pipeline_matematico = PipelineMatematico()


def processar_expressao(
    texto: str, contexto: RegionContext | None = None, **configuracao
) -> MathNode:
    if configuracao:
        return PipelineMatematico(
            ConfiguracaoDoPipeline(**configuracao)
        ).processar(texto, contexto)
    return pipeline_matematico.processar(texto, contexto)
