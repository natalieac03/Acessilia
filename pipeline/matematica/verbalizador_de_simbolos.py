"""Verbaliza a matematica que NAO passou pela arvore.

Tres situacoes chegam aqui: simbolo solto no meio de uma frase,
formula que o modelo de visao devolveu como prosa em vez do formato
esperado, e o conteudo das celulas de tabela.

O que esta entre $...$ vai para a MESMA arvore das formulas de bloco —
nao existe um segundo tradutor. O resto usa tabela de substituicao.
A funcao traduzir_operadores_residuais trata os sinais soltos: produto
colado (4ac, 2a) vai para a arvore, "+" sempre vira "mais", e o "-"
passa por auditoria (hifen entre letras e palavra composta e fica).

Em texto corrido, as letras "a", "e" e "o" minusculas nunca sao
tocadas: podem ser preposicao, conjuncao ou artigo.
"""

from __future__ import annotations

import re

from pipeline.matematica.vocabulario_de_fala import numero_por_extenso

_EXPOENTES = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "ⁿ": "n",
}
_INDICES = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "ₙ": "n",
}

_NOME_DO_EXPOENTE = {
    "2": "ao quadrado",
    "3": "ao cubo",
}

_COMANDOS_LATEX = [
    (re.compile(r"\\sqrt\s*\[\s*3\s*\]"), " raiz cúbica de "),
    (re.compile(r"\\sqrt"), " raiz quadrada de "),
    (re.compile(r"\\d?frac"), " fração "),
    (re.compile(r"\\times|\\cdot"), " vezes "),
    (re.compile(r"\\div"), " dividido por "),
    (re.compile(r"\\pm"), " mais ou menos "),
    (re.compile(r"\\exists\s*!"), " existe um único "),
    (re.compile(r"\\exists"), " existe "),
    (re.compile(r"\\forall"), " para todo "),
    (re.compile(r"\\nexists"), " não existe "),
    (re.compile(r"\\emptyset|\\varnothing"), " conjunto vazio "),
    (re.compile(r"\\cup"), " união "),
    (re.compile(r"\\cap"), " interseção "),
    (re.compile(r"\\setminus"), " diferença de conjuntos "),
    (re.compile(r"\\subseteq"), " está contido ou é igual a "),
    (re.compile(r"\\subset"), " está contido em "),
    (re.compile(r"\\in\b"), " pertence a "),
    (re.compile(r"\\notin"), " não pertence a "),
    (re.compile(r"\\leq"), " é menor ou igual a "),
    (re.compile(r"\\geq"), " é maior ou igual a "),
    (re.compile(r"\\neq"), " é diferente de "),
    (re.compile(r"\\in\b"), " pertence a "),
    (re.compile(r"\\forall"), " para todo "),
    (re.compile(r"\\exists"), " existe "),
    (re.compile(r"\\cup"), " união "),
    (re.compile(r"\\cap"), " interseção "),
    (re.compile(r"\\mathbb\s*\{\s*N\s*\}"), " naturais "),
    (re.compile(r"\\mathbb\s*\{\s*R\s*\}"), " reais "),
    (re.compile(r"\\mathbb\s*\{\s*Z\s*\}"), " inteiros "),
    (re.compile(r"\\lim"), " limite "),
    (re.compile(r"\\log"), " logaritmo "),
    (re.compile(r"\\to"), " tende a "),
    (re.compile(r"\\Delta"), " delta "),
    (re.compile(r"\\[a-zA-Z]+"), " "),
]

_SIMBOLOS = {
    "√": " raiz quadrada de ",
    "∛": " raiz cúbica de ",
    "∜": " raiz quarta de ",
    "≠": " é diferente de ",
    "≥": " é maior ou igual a ",
    "≤": " é menor ou igual a ",
    "≈": " é aproximadamente igual a ",
    "≡": " é equivalente a ",
    "∝": " é proporcional a ",
    "=": " é igual a ",
    "<": " é menor que ",
    ">": " é maior que ",
    "±": " mais ou menos ",
    "∓": " menos ou mais ",
    "×": " vezes ",
    "·": " vezes ",
    "⋅": " vezes ",
    "÷": " dividido por ",
    "∙": " vezes ",
    "∉": " não pertence a ",
    "∈": " pertence a ",
    "∊": " pertence a ",
    "∍": " contém ",
    "∋": " contém ",
    "⊊": " está contido propriamente em ",
    "⊋": " contém propriamente ",
    "∖": " diferença de conjuntos ",
    "…": ", e assim por diante ",
    "...": ", e assim por diante ",

    "⊆": " está contido ou é igual a ",
    "⊇": " contém ou é igual a ",
    "⊂": " está contido em ",
    "⊃": " contém ",
    "∪": " união ",
    "∩": " interseção ",
    "∅": " conjunto vazio ",
    "∀": " para todo ",
    "∃!": " existe um único ",
    "∃": " existe ",
    "∄": " não existe ",
    "∧": " e ",
    "∨": " ou ",
    "¬": " não ",
    "ℕ": " naturais ",
    "ℝ": " reais ",
    "ℤ": " inteiros ",
    "ℚ": " racionais ",
    "ℂ": " complexos ",
    "⇒": " implica que ",
    "⇔": " se e somente se ",
    "→": " tende a ",
    "←": " recebe ",
    "↔": " equivale a ",
    "∞": " infinito ",
    "∑": " somatório de ",
    "∏": " produtório de ",
    "∫": " integral de ",
    "∂": " derivada parcial de ",
    "∇": " gradiente de ",
    "°": " graus ",
    "∠": " ângulo ",
    "∴": " portanto ",
    "∵": " porque ",
    "α": " alfa ", "β": " beta ", "γ": " gama ", "δ": " delta ",
    "ε": " épsilon ", "ζ": " zeta ", "η": " eta ", "θ": " teta ",
    "ι": " iota ", "κ": " capa ", "λ": " lambda ", "μ": " mi ",
    "ν": " ni ", "ξ": " csi ", "π": " pi ", "ρ": " rô ",
    "σ": " sigma ", "τ": " tau ", "υ": " úpsilon ", "φ": " fi ",
    "χ": " qui ", "ψ": " psi ", "ω": " ômega ",
    "Α": " alfa ", "Β": " beta ", "Γ": " gama ", "Δ": " delta ",
    "Θ": " teta ", "Λ": " lambda ", "Ξ": " csi ", "Π": " pi ",
    "Σ": " sigma ", "Φ": " fi ", "Ψ": " psi ", "Ω": " ômega ",
    "{": " abre chaves ",
    "}": " fecha chaves ",
    "[": " abre colchetes ",
    "]": " fecha colchetes ",
    "|": " barra ",
}

_LINHA_TECNICA = re.compile(
    r"^\s*(LATEX|LEITURA|MATHML|OMML|SPEECH)\s*:\s*", re.IGNORECASE
)

_ROTULO_DE_FORMULA = re.compile(
    r"^\s*(f[oó]rmula|express[aã]o)\s+matem[aá]tica\s*:\s*", re.IGNORECASE
)

_FRACAO_SIMPLES = re.compile(
    r"(?<![\w/])([A-Za-zÀ-ÿ0-9]{1,12})\s*/\s*([A-Za-zÀ-ÿ0-9]{1,12})(?![\w/])"
)

_NUMERO = re.compile(r"(?<![\w,.])(\d+)(?:[.,](\d+))?(?![\w])")


_IMPLICACAO_ENTRE_PROPOSICOES = re.compile(
    r"\b([A-Z])\s*→\s*([A-Z])\b"
)


_VARIAVEL_ISOLADA = re.compile(r"(?<![\wÀ-ÿ])([a-zA-Z])(?![\wÀ-ÿ])")

from pipeline.matematica.vocabulario_de_fala import (
    falar_letra as _falar_letra,
)


def _tem_sinal_matematico(texto: str) -> bool:
    if "\\" in texto:
        return True
    if any(s in texto for s in _SIMBOLOS):
        return True
    if any(e in texto for e in _EXPOENTES) or any(i in texto for i in _INDICES):
        return True
    if _ROTULO_DE_FORMULA.search(texto) or _LINHA_TECNICA.search(texto):
        return True
    if re.fullmatch(r"\s*-?\d+([.,]\d+)?\s*", texto):
        return True
    return bool(_FRACAO_SIMPLES.search(texto))


def _verbalizar_expoentes(texto: str) -> str:
    def _trocar(casado: re.Match) -> str:
        digitos = "".join(_EXPOENTES[c] for c in casado.group(0))
        nome = _NOME_DO_EXPOENTE.get(digitos)
        if nome:
            return f" {nome} "
        return f" elevado a {digitos} "

    padrao = re.compile(f"[{''.join(_EXPOENTES)}]+")
    return padrao.sub(_trocar, texto)


def _verbalizar_indices(texto: str) -> str:
    def _trocar(casado: re.Match) -> str:
        digitos = "".join(_INDICES[c] for c in casado.group(0))
        return f" índice {digitos} "

    padrao = re.compile(f"[{''.join(_INDICES)}]+")
    return padrao.sub(_trocar, texto)


def _verbalizar_numeros(texto: str) -> str:
    def _trocar(casado: re.Match) -> str:
        inteiro, decimal = casado.group(1), casado.group(2)
        fala = numero_por_extenso(int(inteiro))
        if decimal:
            fala = f"{fala} vírgula {numero_por_extenso(int(decimal))}"
        return fala

    return _NUMERO.sub(_trocar, texto)


def _verbalizar_variaveis(texto: str) -> str:
    _AMBIGUAS_EM_TEXTO = {"a", "e", "o"}

    def _trocar(casado: re.Match) -> str:
        letra = casado.group(1)
        if letra in _AMBIGUAS_EM_TEXTO:
            return letra
        if (letra in ("A", "E", "O") and casado.start() == 0
                and casado.end() + 1 < len(texto)
                and texto[casado.end()] == " "
                and texto[casado.end() + 1].islower()):
            return letra
        return _falar_letra(letra)

    return _VARIAVEL_ISOLADA.sub(_trocar, texto)


def _verbalizar_matematica_delimitada(linha: str) -> str:
    padrao = re.compile(r"(?<!\\)\$([^$\n]+?)\$|\\\(([^\n]+?)\\\)")

    def _fala_do_trecho(casado: re.Match) -> str:
        conteudo = (casado.group(1) or casado.group(2) or "").strip()
        if not conteudo:
            return " "
        from pipeline.matematica.vocabulario_de_fala import (
            UNIDADES_FALADAS,
            unidade_por_extenso,
        )

        canonico = conteudo.replace("^{2}", "²").replace("^2", "²")
        if canonico in UNIDADES_FALADAS and (
                "/" in canonico or "²" in canonico):
            return f" {unidade_por_extenso(canonico, None)} "
        from pipeline.matematica.vocabulario_de_fala import (
            LETRAS_SOLETRADAS as _LS,
        )

        nomes_de_fala = set(_LS.values()) | {
            "delta", "alfa", "beta", "gama", "sigma", "pi",
            "teta", "lambda", "ômega", "épsilon",
        }
        palavras = {w for w in conteudo.split() if len(w) > 1}
        if palavras and palavras & nomes_de_fala:
            return f" {conteudo} "
        try:
            from pipeline.matematica.arvore_matematica import construir_ast
            from pipeline.matematica.cobertura_matematica import (
                validar_fala_por_extenso,
                validar_idioma_da_fala,
            )
            from pipeline.matematica.fala_matematica import gerar_fala_matematica

            resultado = construir_ast(conteudo)
            plano = gerar_fala_matematica(resultado.ast)
            from pipeline.matematica.cobertura_matematica import (
                validar_texto_incorporado,
            )

            if (resultado.completa and not plano.tem_lacuna
                    and not plano.tem_simbolo_cru
                    and not validar_texto_incorporado(resultado.ast)
                    and not validar_fala_por_extenso(plano.texto)
                    and not validar_idioma_da_fala(plano.texto)):
                return f" {plano.texto} "
        except Exception:
            pass
        if "\\" in conteudo:
            return f" {conteudo} "
        basico = conteudo.replace("_", " ").replace(
            "^", " elevado a ")
        basico = re.sub(
            r"\b([A-Za-z])\b",
            lambda m: _falar_letra(m.group(1)),
            basico,
        )
        return f" {basico} "

    return padrao.sub(_fala_do_trecho, linha)


def verbalizar_linha(linha: str) -> str:
    if not linha or not linha.strip():
        return linha
    if "$" in linha or "\\(" in linha:
        linha = _verbalizar_matematica_delimitada(linha)
    if not _tem_sinal_matematico(linha):
        return linha

    if False:
        pass
    if linha.count("|") >= 2:
        linha = linha.replace("|", "; ")
    texto = _LINHA_TECNICA.sub("", linha)
    texto = _ROTULO_DE_FORMULA.sub("Fórmula: ", texto)

    tinha_latex = "\\" in texto
    for padrao, fala in _COMANDOS_LATEX:
        texto = padrao.sub(fala, texto)
    if tinha_latex:
        texto = texto.replace("{", " ").replace("}", " ")
    texto = re.sub(r"\^\s*\{?\s*2\s*\}?", " ao quadrado ", texto)
    texto = re.sub(r"\^\s*\{?\s*3\s*\}?", " ao cubo ", texto)
    texto = re.sub(r"\^\s*\{?\s*(-?\d+|[a-zA-Z])\s*\}?", r" elevado a \1 ", texto)
    texto = _IMPLICACAO_ENTRE_PROPOSICOES.sub(
        r"\1 implica \2", texto
    )
    from pipeline.matematica.vocabulario_de_fala import (
        texto_por_extenso_com_unidades,
    )

    texto = texto_por_extenso_com_unidades(texto)


    texto = _verbalizar_expoentes(texto)
    texto = _verbalizar_indices(texto)
    for simbolo, fala in _SIMBOLOS.items():
        texto = texto.replace(simbolo, fala)

    texto = re.sub(r"\)\s*/\s*\(", ") sobre (", texto)
    texto = _FRACAO_SIMPLES.sub(r"\1 sobre \2", texto)

    texto = re.sub(r"(?<=[\w\)])\s*[-−–]\s*(?=[\w\(])", " menos ", texto)
    texto = re.sub(r"(?<![\w\)])[-−–]\s*(?=[\w\(])", " menos ", texto)
    texto = re.sub(r"\s*\+\s*", " mais ", texto)

    texto = _verbalizar_numeros(texto)
    texto = _verbalizar_variaveis(texto)

    texto = texto.replace("(", " abre parênteses ").replace(")", " fecha parênteses ")

    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"\s+([,.;:!?])", r"\1", texto)
    texto = re.sub(r"([,.;:])\1+", r"\1", texto)
    return texto


def verbalizar_texto(texto: str) -> str:
    return "\n".join(verbalizar_linha(linha) for linha in texto.split("\n"))


def verbalizar_celula(celula: str) -> str:
    if not celula:
        return celula
    resultado = _verbalizar_matematica_delimitada(str(celula))
    if resultado.count("|") >= 2:
        resultado = resultado.replace("|", "; ")
    resultado = verbalizar_linha(resultado)
    from pipeline.matematica.vocabulario_de_fala import (
        texto_por_extenso_com_unidades,
    )

    resultado = traduzir_operadores_residuais(resultado)
    resultado = texto_por_extenso_com_unidades(resultado)
    resultado = re.sub(r"\s{2,}", " ", resultado)
    resultado = re.sub(r"(?:;\s*)+", "; ", resultado)
    return resultado.strip(" ;")


_HIFEN_DE_PALAVRA = re.compile(r"(?<=[A-Za-zÀ-ÿ])-(?=[A-Za-zÀ-ÿ])")
_PRODUTO_COLADO = re.compile(r"(?<![\wÀ-ÿ])(\d+)([a-zA-Z]{1,3})(?![\wÀ-ÿ])")
_MENOS_ESPACADO = re.compile(r"(?<=\s)-(?=\s)")
_MENOS_UNARIO = re.compile(r"(?<![\wÀ-ÿ])-(?=\d|[a-zA-Z]\b)")


def traduzir_operadores_residuais(texto: str,
                                  agressivo: bool = True) -> str:
    if not texto:
        return texto

    def _falar_produto(casado: "re.Match[str]") -> str:
        trecho = casado.group(0)
        try:
            from pipeline.matematica.arvore_matematica import construir_ast
            from pipeline.matematica.fala_matematica import (
                gerar_fala_matematica,
            )

            resultado = construir_ast(trecho)
            plano = gerar_fala_matematica(resultado.ast)
            if (resultado.completa and not plano.tem_lacuna
                    and not plano.tem_simbolo_cru):
                return plano.texto
        except Exception:
            pass
        return trecho

    texto = _PRODUTO_COLADO.sub(_falar_produto, texto)

    texto = re.sub(r"\s*\+\s*", " mais ", texto)

    protegido = _HIFEN_DE_PALAVRA.sub("\x00", texto)
    if agressivo:
        protegido = protegido.replace("-", " menos ")
    else:
        protegido = _MENOS_ESPACADO.sub(" menos ", protegido)
        protegido = _MENOS_UNARIO.sub(" menos ", protegido)
    texto = protegido.replace("\x00", "-")

    texto = re.sub(r"\s{2,}", " ", texto)
    texto = re.sub(r"\s+([.,;:!?])", r"\1", texto)
    return texto.strip()
