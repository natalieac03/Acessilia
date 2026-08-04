"""Confere a descricao gerada contra a imagem original.

Recebe o recorte e o texto que o especialista produziu e responde se
um corresponde ao outro, com um nivel de confianca. Se reprovar, o
especialista redescreve; depois de duas tentativas sem convergir, a
regiao e marcada como incerta em vez de insistir ou travar.

E a camada anti-alucinacao do pipeline: existe porque um modelo de
visao produz texto plausivel mesmo quando nao tem evidencia para isso.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from pydantic import BaseModel, Field

from core.agents.especialistas_agno import (
    TIPO_PARA_PROMPT,
    _construir_modelo_visao,
    _agente_para,
)
from core.utils.logger import logger


class Critica(BaseModel):

    fiel: bool = Field(
        description=(
            "true se a descricao contem APENAS o que e visivel na imagem. "
            "false se ha qualquer afirmacao inventada, invertida ou ausente."
        )
    )
    confianca: float = Field(
        ge=0.0,
        le=1.0,
        description="Quao seguro voce esta do seu veredito, de 0.0 a 1.0.",
    )
    suspeitas: list[str] = Field(
        default_factory=list,
        description=(
            "Lista curta de problemas concretos encontrados. Ex.: "
            "'a descricao diz que Linux Kernel esta no topo, mas esta na base'."
        ),
    )


_REGRAS_BASE = """\
Voce e um verificador rigoroso de audiodescricao acessivel.

Voce recebe UMA IMAGEM e uma DESCRICAO que outro sistema gerou dela.
Sua tarefa NAO e reescrever a descricao. Sua tarefa e VERIFICAR se ela e fiel.

Marque fiel=false se encontrar QUALQUER um destes problemas:
- Afirma algo que nao esta visivel na imagem (invencao).
- Le um texto de forma diferente do que esta escrito na imagem.
- Inverte, embaralha ou omite a ordem/posicao dos elementos.
- Omite elementos importantes que aparecem claramente na imagem.

Se a descricao estiver correta e completa, marque fiel=true.
Seja rigoroso, mas nao invente problemas que nao existem.
Se voce mesmo nao conseguir ler algo na imagem, reduza a confianca.

ANTES DE REPROVAR, CONFIRA VOCE MESMO:
- Se voce for apontar que um valor esta errado, escreva o valor da IMAGEM e o
  valor da DESCRICAO lado a lado e compare-os caractere por caractere. Se
  forem IGUAIS, isso NAO e um erro: nao aponte. Reprovar uma descricao correta
  e tao prejudicial quanto aprovar uma errada.
- Diferencas de ESTILO, ordem de mencao ou nivel de detalhe nao sao erros.
  So reprove por FATO ERRADO, ELEMENTO AUSENTE ou ELEMENTO INVENTADO.

CALIBRE A CONFIANCA DE VERDADE (nao responda sempre 1.0 ou 0.9):
- 0.9 a 1.0 : a imagem esta nitida e voce tem certeza do veredito.
- 0.5 a 0.8 : a imagem esta pequena/borrada, ou voce esta em duvida.
- 0.0 a 0.4 : voce mal consegue distinguir o conteudo da imagem.
"""

_REGRAS_POR_TIPO = {
    "embedded_image": """\
ATENCAO ESPECIAL A DIAGRAMAS (fonte comum de erro):
- Liste mentalmente os elementos DE CIMA PARA BAIXO antes de julgar.
- Confira se a descricao respeita essa ordem vertical real.
- Diagramas de camadas (ex.: kernel na base, aplicacoes no topo) sao
  frequentemente descritos INVERTIDOS. Verifique isso explicitamente.
- Conte os elementos da imagem e confira se a descricao menciona todos.
- Confira se "acima/abaixo" nao viraram "esquerda/direita" na descricao.

CONVENCAO DE ACESSIBILIDADE PARA GRAFICOS DE DADOS (obrigatoria):
- Quando a imagem e um GRAFICO DE DADOS (barras, linhas, pizza, area),
  a descricao correta e uma frase de identificacao ("Grafico de barras:
  titulo.") seguida de uma TABELA com pipes contendo os dados lidos.
- Esse formato tabular E O ESPERADO. NAO reprove a descricao por "usar
  formato de tabela" ou "nao corresponder visualmente ao grafico".
- O seu papel nesse caso e conferir OS DADOS: cada categoria e cada
  valor da tabela devem corresponder ao que o grafico mostra (rotulos
  dos eixos, valores das barras/pontos, ponto destacado se houver).
- Reprove SOMENTE se os dados divergirem da imagem, se faltarem series
  visiveis, ou se valores tiverem sido inventados.

ATENCAO A INFERENCIAS EM IMAGENS ESTATICAS:

- Reprove descricoes que transformam postura em acao nao comprovada.
- "Bracos estendidos e pernas flexionadas" e observavel.
- "Esta saltando", "esta correndo" ou "esta em movimento" somente podem
  ser aceitos quando a imagem apresenta evidencia inequivoca da acao.
- Expressoes como "como se", "parece estar", "aparenta estar", "prestes a"
  e "provavelmente" indicam possivel inferencia e devem ser examinadas.
- "Posicao dinamica" e uma avaliacao subjetiva. Exija a descricao concreta
  da posicao dos membros.
- "Ha sombra nas laterais" e observavel.
- "A sombra confere aspecto tridimensional" e interpretacao estetica.
- Identidades especificas devem estar visiveis, escritas no contexto ou ser
  inequivocas. Caso contrario, a descricao deve usar caracteristicas
  fisicas.
- Nao aceite categorias incompativeis com a postura descrita. Por exemplo,
  verifique o uso de "quadrupede" quando a figura aparece ereta com bracos
  e pernas diferenciados.

Quando houver inferencia, marque fiel=false e inclua uma suspeita
CONCRETA, citando o trecho. Exemplo de suspeita valida:
'A expressao "como se estivesse saltando" infere movimento nao comprovado
pela imagem estatica.'
""",
    "table": """\
ATENCAO ESPECIAL A TABELAS:
- Conte as linhas e as colunas da imagem.
- Confira se a descricao tem o mesmo numero de linhas e colunas.
- Verifique celula a celula os valores numericos.
- Celulas ilegiveis devem estar marcadas, nao adivinhadas.
""",
    "formula": """\
ATENCAO ESPECIAL A FORMULAS (risco maximo):
- Confira simbolo por simbolo, indice por indice, expoente por expoente.
- Um unico caractere errado invalida a formula inteira.
- Na duvida, marque fiel=false e reduza a confianca. NAO adivinhe.

CONVENCAO DE ACESSIBILIDADE PARA FORMULAS (obrigatoria):
- A descricao correta tem duas linhas: "LATEX: <formula>" e
  "LEITURA: <formula falada por extenso>". Esse formato E O ESPERADO;
  NAO reprove pela estrutura em si.
- Julgue se o LATEX e a LEITURA correspondem ao que a IMAGEM mostra.
- Se a PROPRIA IMAGEM tiver um defeito tipografico evidente (ex.: o
  simbolo de derivada ' renderizado como o numero 1 subscrito), aceite
  a interpretacao MATEMATICAMENTE PADRAO na leitura, desde que a
  descricao registre a grafia estranha ou o contexto deixe claro.
  Reprovar duas vezes por causa de um defeito do documento so produz
  incerteza inutil - o objetivo e o aluno entender a formula.
""",
    "text_scanned": """\
ATENCAO ESPECIAL A TEXTO ESCANEADO:
- Compare palavra por palavra com o que esta escrito na imagem.
- Siglas e nomes proprios sao frequentemente lidos errado. Confira letra
  a letra (ex.: uma sigla de 4 letras nao pode virar uma de 3).
- Texto ilegivel deve estar marcado como "[ilegivel]", nao adivinhado.
""",
}
_REGRAS_POR_TIPO["unknown"] = _REGRAS_POR_TIPO["text_scanned"]


def _Imagem():
    from agno.media import Image

    return Image


@lru_cache(maxsize=None)
def _agente_critico(tipo: str):
    from agno.agent import Agent
    instrucoes = (
        _INSTRUCAO_DE_FORMATO + "\n"
        + _REGRAS_BASE + "\n" + _REGRAS_POR_TIPO.get(tipo, "")
    )

    return Agent(
        name=f"critico-{tipo}",
        model=_construir_modelo_visao(),
        description="Verificador anti-alucinacao de audiodescricao",
        instructions=instrucoes,
        markdown=False,
    )


_INSTRUCAO_DE_FORMATO = """RESPONDA APENAS COM UM OBJETO JSON, sem cercas
de codigo, sem texto antes ou depois. O formato exato e:

{"fiel": true, "confianca": 0.95, "suspeitas": []}

- fiel: true se a descricao contem APENAS o que e visivel na imagem.
- confianca: numero entre 0.0 e 1.0.
- suspeitas: NO MAXIMO 5 itens, cada um com no maximo 200 caracteres.
  NUNCA repita a mesma suspeita com outras palavras - se o problema e o
  mesmo, escreva uma vez so. Lista vazia quando fiel=true.

O QUE NUNCA E DIVERGENCIA (nao reprove por isto):
- Equivalencia tipografica: "x" e "×" sao o MESMO simbolo de
  multiplicacao; ">=" e "≥", "<=" e "≤", "-" e "−" sao o mesmo simbolo.
  A adaptacao normaliza a tipografia de proposito - para o leitor de
  tela as duas formas sao vocalizadas identicamente.
- Contagem de linhas de tabela com ou sem o cabecalho: uma tabela com 6
  linhas de dados TEM 7 linhas quando o cabecalho conta. As duas
  contagens descrevem a mesma tabela.
- Dois valores IDENTICOS: antes de escrever "a descricao diz X, mas a
  imagem mostra Y", confira que X e Y sao DIFERENTES. Se forem iguais,
  nao ha divergencia e a suspeita nao deve ser escrita.
"""


_CONECTIVOS_CONTRASTE = (
    " mas ", " porem ", " porém ", " enquanto ", " na verdade ", " entretanto ",
    " contudo ", " ao passo que ",
    " em vez de ", " ao inves de ", " ao invés de ", " no lugar de ",
    " substituido por ", " substituído por ", " foi substituido ",
    " foi substituído ", " quando deveria ser ",
)

_PADRAO_CITADO = re.compile(r"[\"'\u201c\u201d\u2018\u2019]([^\"'\u201c\u201d\u2018\u2019]{1,60})[\"'\u201c\u201d\u2018\u2019]")
_PADRAO_VALOR_TECNICO = re.compile(r"\b[\w\-]*\d[\w\-]*\b")

_PADRAO_PAR_DESCRICAO_IMAGEM = re.compile(
    r"([\w,\.\-]{1,20})\s+na\s+descri[cç][aã]o\b[^;]{0,40}?"
    r"\b\1\s+na\s+imagem",
    re.IGNORECASE,
)

_EQUIVALENTES_TIPOGRAFICOS = {
    "×": "x", "⋅": "x", "∙": "x", "·": "x",
    "≥": ">=", "≤": "<=", "≠": "!=", "≈": "~",
    "−": "-", "–": "-", "—": "-",
    "’": "'", "‘": "'", "“": '"', "”": '"',
}


def _normalizar_tipografia(valor: str) -> str:
    for original, canonico in _EQUIVALENTES_TIPOGRAFICOS.items():
        valor = valor.replace(original, canonico)
    return re.sub(r"\s+", " ", valor).strip().lower()


def _valores_citados(texto: str) -> list[str]:
    valores = [v.strip() for v in _PADRAO_CITADO.findall(texto)]
    valores += _PADRAO_VALOR_TECNICO.findall(texto)
    return [_normalizar_tipografia(v) for v in valores if v]


def _suspeita_e_autocontraditoria(suspeita: str) -> bool:
    baixa = _normalizar_tipografia(suspeita)

    if _PADRAO_PAR_DESCRICAO_IMAGEM.search(baixa):
        return True

    conectivo_presente = next(
        (c for c in _CONECTIVOS_CONTRASTE if c in baixa), None
    )
    if conectivo_presente is None:
        return False

    valores = _valores_citados(suspeita)
    if len(valores) < 2:
        return False

    if len(set(valores)) == 1:
        return True

    esquerda, _, direita = baixa.partition(conectivo_presente)
    valores_direita = set(_valores_citados(direita))
    if valores_direita and valores_direita <= set(_valores_citados(esquerda)):
        return True

    return False


def _reparar_json_truncado(fragmento: str) -> dict | None:
    if not fragmento:
        return None

    dentro_de_string = False
    escapado = False
    pilha: list[str] = []
    for caractere in fragmento:
        if escapado:
            escapado = False
            continue
        if caractere == "\\":
            escapado = True
            continue
        if caractere == '"':
            dentro_de_string = not dentro_de_string
            continue
        if dentro_de_string:
            continue
        if caractere in "{[":
            pilha.append(caractere)
        elif caractere in "}]":
            if pilha:
                pilha.pop()

    reparado = fragmento
    if escapado:
        reparado = reparado[:-1]
    if dentro_de_string:
        reparado += '"'
    reparado = reparado.rstrip().rstrip(",:")
    for abertura in reversed(pilha):
        reparado += "}" if abertura == "{" else "]"

    try:
        objeto = json.loads(reparado)
    except json.JSONDecodeError:
        return None
    return objeto if isinstance(objeto, dict) else None


def extrair_critica_bruta(texto: str) -> dict | None:
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
    return _reparar_json_truncado(fragmento)


def _normalizar_suspeitas(bruto) -> list[str]:
    if not isinstance(bruto, list):
        return []
    vistas: set[str] = set()
    resultado: list[str] = []
    for item in bruto:
        texto = str(item or "").strip()
        if not texto:
            continue
        chave = re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()
        if chave in vistas:
            continue
        vistas.add(chave)
        resultado.append(texto[:300])
        if len(resultado) >= 5:
            break
    return resultado


def converter_para_critica(bruto: dict | None) -> "Critica | None":
    if not isinstance(bruto, dict) or "fiel" not in bruto:
        return None
    fiel = bruto.get("fiel")
    if isinstance(fiel, str):
        fiel = fiel.strip().lower() in ("true", "sim", "1")
    try:
        confianca = float(bruto.get("confianca", 0.0))
    except (TypeError, ValueError):
        confianca = 0.0
    return Critica(
        fiel=bool(fiel),
        confianca=min(max(confianca, 0.0), 1.0),
        suspeitas=_normalizar_suspeitas(bruto.get("suspeitas")),
    )


def _limpar_criticas_invalidas(critica: Critica) -> Critica:
    validas = [s for s in critica.suspeitas if not _suspeita_e_autocontraditoria(s)]
    descartadas = len(critica.suspeitas) - len(validas)
    if descartadas:
        logger.warning(
            "Critico apontou {} suspeita(s) autocontraditoria(s) - descartadas",
            descartadas,
        )
    if not critica.fiel and not validas:
        logger.warning("Todas as suspeitas eram invalidas - tratando como aprovada")
        return Critica(fiel=True, confianca=critica.confianca, suspeitas=[])
    return Critica(fiel=critica.fiel, confianca=critica.confianca, suspeitas=validas)


def verificar_descricao(
    tipo: str,
    imagem_bytes: bytes,
    descricao: str,
) -> Critica | None:
    if not descricao.strip():
        return None

    try:
        critico = _agente_critico(tipo)
        import time as _time
        _t0 = _time.monotonic()
        resultado = critico.run(
            "Verifique se a DESCRICAO abaixo e fiel a imagem.\n\n"
            f"DESCRICAO A VERIFICAR:\n{descricao}",
            images=[_Imagem()(content=imagem_bytes)],
        )
        critica = resultado.content
        if not isinstance(critica, Critica):
            critica = converter_para_critica(
                extrair_critica_bruta(
                    critica if isinstance(critica, str) else str(critica or "")
                )
            )
        try:
            from core.services import telemetria
            telemetria.registrar_chamada(
                "critico", resultado,
                duracao_ms=int((_time.monotonic() - _t0) * 1000),
                objeto_agente=critico,
                saida=descricao[:500],
                extra=(
                    {"fiel": critica.fiel, "confianca": critica.confianca,
                     "suspeitas": critica.suspeitas}
                    if isinstance(critica, Critica) else None
                ),
            )
        except Exception:
            pass
        if isinstance(critica, Critica):
            return _limpar_criticas_invalidas(critica)
        logger.warning(
            "Critico nao produziu veredito legivel; regiao segue SEM "
            "verificacao de fidelidade (resposta de {} caracteres)",
            len(str(resultado.content or "")),
        )
        return None
    except Exception as erro:
        logger.warning("Critico falhou ({}), seguindo sem verificacao", erro)
        return None


LIMIAR_CONFIANCA = float(os.getenv("CRITICO_LIMIAR_CONFIANCA", "0.6"))
MARCADOR_INCERTEZA = "[verificacao incerta]"


_ORIENTACAO_CORRECAO_INFERENCIA = (
    "Ao corrigir uma inferencia de movimento, emocao ou intencao, nao "
    "apenas apague a frase. Substitua-a pela evidencia fisica "
    "correspondente: postura, posicao dos membros, expressao facial ou "
    "relacao espacial."
)


def _redescrever_com_critica(
    tipo: str,
    imagem_bytes: bytes,
    descricao_anterior: str,
    critica: Critica,
) -> str:
    problemas = "\n".join(f"- {s}" for s in critica.suspeitas) or "- (nao detalhado)"
    mensagem = (
        "Sua descricao anterior desta imagem foi revisada e apresenta "
        "problemas. Descreva a imagem novamente, do zero, corrigindo-os.\n\n"
        f"DESCRICAO ANTERIOR:\n{descricao_anterior}\n\n"
        f"PROBLEMAS APONTADOS:\n{problemas}\n\n"
        f"{_ORIENTACAO_CORRECAO_INFERENCIA}\n\n"
        "Se voce nao conseguir determinar algo com certeza olhando a imagem, "
        "diga que nao e possivel determinar. NAO adivinhe."
    )
    agente = _agente_para(tipo)
    import time as _time
    _t0 = _time.monotonic()
    resultado = agente.run(mensagem, images=[_Imagem()(content=imagem_bytes)])
    try:
        from core.services import telemetria
        telemetria.registrar_chamada(
            "redescricao", resultado, tentativa=2,
            duracao_ms=int((_time.monotonic() - _t0) * 1000),
            objeto_agente=agente,
        )
    except Exception:
        pass
    return (resultado.content or "").strip()


def descrever_regiao_verificada(
    tipo: str,
    imagem_bytes: bytes,
    contexto: str | None = None,
) -> str:
    descricao, _ = descrever_regiao_verificada_com_meta(tipo, imagem_bytes, contexto)
    return descricao


def descrever_regiao_verificada_com_meta(
    tipo: str,
    imagem_bytes: bytes,
    contexto: str | None = None,
) -> tuple[str, dict]:
    from core.agents.especialistas_agno import descrever_regiao

    descricao = descrever_regiao(tipo, imagem_bytes, contexto)
    sem_verificacao = {"confianca": None, "suspeitas": [], "verificada": False}

    if os.getenv("USAR_CRITICO", "false").lower() != "true":
        return descricao, sem_verificacao
    if tipo not in TIPO_PARA_PROMPT or not descricao.strip():
        return descricao, sem_verificacao

    critica = verificar_descricao(tipo, imagem_bytes, descricao)
    if critica is None:
        return descricao, sem_verificacao

    aprovada = critica.fiel and critica.confianca >= LIMIAR_CONFIANCA
    if aprovada:
        logger.info(
            "Critico aprovou regiao {} (confianca={:.2f})", tipo, critica.confianca
        )
        return descricao, {
            "confianca": critica.confianca,
            "suspeitas": [],
            "verificada": True,
        }

    logger.warning(
        "Critico REPROVOU regiao {} (fiel={}, confianca={:.2f}): {}",
        tipo,
        critica.fiel,
        critica.confianca,
        "; ".join(critica.suspeitas) or "sem detalhes",
    )

    try:
        nova_descricao = _redescrever_com_critica(
            tipo, imagem_bytes, descricao, critica
        )
    except Exception as erro:
        logger.warning("Redescricao falhou ({}), mantendo a original", erro)
        return f"{MARCADOR_INCERTEZA} {descricao}", {
            "confianca": critica.confianca,
            "suspeitas": list(critica.suspeitas),
            "verificada": True,
        }

    if not nova_descricao:
        return f"{MARCADOR_INCERTEZA} {descricao}", {
            "confianca": critica.confianca,
            "suspeitas": list(critica.suspeitas),
            "verificada": True,
        }

    nova_critica = verificar_descricao(tipo, imagem_bytes, nova_descricao)
    if nova_critica is None:
        return nova_descricao, sem_verificacao

    if nova_critica.fiel and nova_critica.confianca >= LIMIAR_CONFIANCA:
        logger.info("Critico aprovou regiao {} na 2a tentativa", tipo)
        return nova_descricao, {
            "confianca": nova_critica.confianca,
            "suspeitas": list(critica.suspeitas),
            "verificada": True,
        }

    logger.warning(
        "Regiao {} nao convergiu apos 2 tentativas - marcando incerteza", tipo
    )
    return f"{MARCADOR_INCERTEZA} {nova_descricao}", {
        "confianca": nova_critica.confianca,
        "suspeitas": list(nova_critica.suspeitas),
        "verificada": True,
    }
