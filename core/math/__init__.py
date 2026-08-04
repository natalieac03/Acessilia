"""Camada matematica do ACESSILIA - superficie unica de importacao."""

from __future__ import annotations

from pipeline.matematica.nos_matematicos import (
    Blocker,
    MathNode,
    MixedParagraph,
    MixedTableCell,
    TextNode,
    comparar_ocorrencias_equivalentes,
    construir_celula_mista,
    construir_no_matematico,
    construir_paragrafo_misto,
    indexar_formula,
    resumo_de_publicacao,
    validar_reconstrucao,
)

from pipeline.matematica.captura_matematica import (
    construir_evidencia,
    construir_geometria,
)
from pipeline.matematica.evidencia_matematica import (
    InlineSegment,
    MathCandidate,
    RegionContext,
    SourceEvidence,
    SpanGeometry,
    TextGeometry,
)

from pipeline.matematica.matematica_inline import (
    detectar_candidatos_matematicos,
    segmentar_bloco_misto,
    segmentar_matematica,
)

from pipeline.matematica.agrupador_matematico import (
    PageLayout,
    reunir_fragmentos_matematicos,
)

from pipeline.matematica.arvore_matematica import (
    Add,
    Connector,
    Desconhecido,
    Divide,
    Function,
    Group,
    Integer,
    MathAST,
    Multiply,
    NoAST,
    Numero,
    PlusMinus,
    Power,
    Relation,
    Sqrt,
    Subscript,
    Subtract,
    Symbol,
    TextMathSequence,
    Token,
    UnaryMinus,
    associar_scripts,
    classificar_menos,
    construir_ast,
    inserir_multiplicacao_implicita,
    tokenizar,
)


from pipeline.matematica.fala_matematica import (
    SpeechPlan,
    falar,
    falar_expressao,
    gerar_fala_matematica,
    gerar_ssml,
    planejar_fala,
)

from pipeline.matematica.serializacao_matematica import (
    gerar_latex,
    gerar_mathml,
    gerar_omml,
    para_texto_linear,
)

from pipeline.matematica.fronteira_matematica import (
    BoundaryReport,
    NeedsReview,
    completar_expressao,
    expandir_fronteira,
    validar_fronteira_expressao,
)
from pipeline.matematica.cobertura_matematica import (
    RelatorioCobertura,
    ValidationIssue,
    analisar_mathml,
    auditar_expressao,
    comparar_formulas_repetidas,
    comparar_latex_e_mathml,
    validar_cadeia_de_igualdade,
    validar_cobertura_da_fala,
    validar_cobertura_simbolica,
    validar_produto_de_grupos,
    validar_serializacoes,
)
from pipeline.matematica.problemas_matematicos import (
    AssinaturaSimbolica,
    assinatura_da_ast,
    assinatura_da_origem,
    comparar_assinaturas,
    extrair_semantica_da_fala,
)

from pipeline.matematica.tabela_matematica import (
    falar_tabela,
    processar_celula,
    processar_tabela,
    validar_celula_contra_contexto,
    validar_tabela,
)


from pipeline.matematica.normalizador_matematico import (
    DocumentContext,
    Glyph,
    ReparadorDeContextoMatematico,
    detectar_script_perdido,
    reparar_por_ocorrencia_confirmada,
    revisar_scripts_perdidos,
)

from core.math.pipeline import (
    ConfiguracaoDoPipeline,
    PipelineMatematico,
    ResultadoDoPipeline,
    pipeline_matematico,
    processar_expressao,
)

from core.services.trilha_matematica import (
    TrilhaDaExpressao,
    calcular_metricas,
    rastrear_expressao,
    resumo_para_depuracao,
)

from pipeline.matematica import arvore_matematica as ast_matematica
from pipeline.matematica import matematica_inline as detector
from pipeline.matematica import matematica_inline as segmenter
from pipeline.matematica import serializacao_matematica as serializers
from pipeline.matematica import fala_matematica as speech_ptbr

__all__ = [name for name in dir() if not name.startswith("_")]
