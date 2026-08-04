# ACESSÍLIA

Protótipo de pesquisa para adaptação semântica de materiais didáticos destinados a estudantes cegos ou com baixa visão.

O fluxo principal recebe um PDF ou uma imagem pelo Telegram, identifica regiões de texto, fórmulas, tabelas e elementos visuais, constrói um documento canônico e gera diferentes formatos de saída. O foco atual do protótipo é a **camada matemática em português do Brasil**: reconstruir a estrutura de uma expressão, gerar uma leitura verbal controlada e derivar representações como MathML e OMML a partir da mesma árvore sintática.

> **Estado do projeto:** demonstração técnica e experimental. O repositório ainda não representa um produto certificado, nem substitui revisão especializada ou testes com usuários cegos.

---

## Estado atual, sem vender mais do que o código entrega

Na rota principal pelo Telegram, o sistema pode entregar um pacote com:

- **TXT** com conteúdo linearizado e fala matemática;
- **HTML** com estrutura de títulos, tabelas e MathML preservado no documento;
- **DOCX** com equações OMML e propriedades de texto alternativo em imagens;
- **MP3** sintetizado a partir do TXT;
- **PDF visual**, identificado com o sufixo `_visual`, sem conformidade PDF/UA.

Esses formatos não têm o mesmo grau de acessibilidade. Atualmente:

| Formato | Situação real |
|---|---|
| TXT | Saída linear acessível para leitura e síntese de voz, mas sem navegação matemática hierárquica. |
| HTML | Preserva MathML, títulos e tabelas semânticas. A estratégia atual de fala usa `aria-label` para priorizar português; a navegação estrutural por leitor de tela ainda precisa ser validada e não deve ser tratada como garantida. |
| DOCX | Gera OMML, estrutura de tabelas e texto alternativo. Ainda precisa de uma matriz formal de testes com Word, NVDA e JAWS. |
| MP3 | É produzido pelo `edge-tts` a partir do TXT. O gerador de roteiro SSML existe, mas ainda não está conectado ao fluxo principal de produção. |
| PDF | É uma versão visual para impressão ou acompanhamento. **Não é PDF/UA** e não deve ser anunciado como PDF acessível. |


---

## O problema investigado

Em um teste do projeto, a fórmula quadrática foi extraída como:

```text
Vb2 X = 2a =b+ Aac
```

O problema não é apenas ortográfico. A estrutura matemática desapareceu: não é possível determinar com segurança o numerador, o denominador, o alcance da raiz, os expoentes e a função dos sinais.


---

## Ideia central: semântica antes da renderização

O núcleo matemático segue uma arquitetura semelhante à de compiladores:

```text
expressão reconhecida
        │
        ▼
normalização e recuperação de estrutura
        │
        ▼
tokenização
        │
        ▼
árvore sintática matemática, AST
        │
        ├──────────────┬──────────────┬──────────────┐
        ▼              ▼              ▼              ▼
 fala em PT-BR       MathML          LaTeX          OMML
        │              │                │              │
        ▼              ▼                ▼              ▼
 TXT e MP3           HTML         representação      DOCX
                                    técnica
```

A árvore é a fonte semântica da matemática. Isso permite:

- diferenciar menos unário de subtração;
- representar multiplicação implícita, como `4ac`;
- preservar o alcance de raízes e frações;
- distinguir expoente de número digitado na mesma linha;
- gerar fala, MathML, LaTeX e OMML de maneira consistente;
- comparar fórmulas pela estrutura, não apenas pela aparência;
- detectar perda de operadores ou termos antes da publicação.

---

## Arquitetura geral

```text
Telegram recebe o arquivo
        │
        ▼
validação de extensão, tamanho e assinatura
        │
        ▼
conversão para PDF, quando necessária e disponível
        │
        ▼
separação por páginas
        │
        ▼
extração de regiões com Docling ou PyMuPDF
        │
        ▼
classificação e planejamento da página
        │
        ├── texto digital confiável ───────────────► segue sem IA generativa
        │
        └── fórmula, tabela, imagem ou região ambígua
                            │
                            ▼
                   especialista multimodal
                            │
                            ▼
                     crítico visual opcional
                            │
                            ▼
                 normalização de acessibilidade
                            │
                            ▼
             fórmula entra no pipeline matemático
                            │
                            ▼
            AST + fala + MathML + LaTeX + OMML
                            │
                            ▼
                validadores de preservação
                            │
                            ▼
                  documento canônico único
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
         TXT/HTML        DOCX/PDF         MP3
                                             
                            ▼
                       pacote ZIP
```

O documento canônico contém seções e blocos tipados, como parágrafo, título, lista, tabela, imagem, código e matemática. Os renderizadores consomem esse documento; eles não deveriam reinterpretar a fórmula.

---

## O que é determinístico, o que usa modelos locais e o que usa IA generativa

A divisão correta não é simplesmente “IA” contra “sem IA”. O código possui três grupos.

### 1. Código determinístico

São regras Python que produzem a mesma transformação lógica para a mesma entrada:

- validação de upload e prevenção de reprocessamento de saídas do próprio sistema;
- divisão de PDF e gerenciamento de fila;
- classificação heurística de regiões;
- planejamento padrão da página;
- ordenação de leitura;
- ligação entre legendas e regiões próximas;
- reunião de fragmentos matemáticos;
- detecção de matemática em texto corrido e células;
- normalização de símbolos e scripts;
- tokenização e construção da AST;
- inserção de multiplicação implícita;
- geração de fala matemática;
- geração de LaTeX, MathML e OMML;
- comparação por assinatura estrutural;
- validação de cobertura e preservação;
- construção do documento canônico;
- renderização de TXT, HTML, DOCX e PDF;
- empacotamento dos arquivos e cache.


### 2. Extração local não generativa

- **PyMuPDF** lê a camada textual, as coordenadas e os blocos do PDF.
- **Docling** pode detectar estrutura e tipos de região usando modelos de layout executados localmente, com fallback para PyMuPDF.

Docling não deve ser confundido com a árvore matemática do ACESSÍLIA. Ele ajuda a localizar e classificar componentes da página; a reconstrução semântica da expressão é feita depois pelo pipeline matemático.

### 3. IA generativa

A IA generativa é usada principalmente nas etapas que exigem percepção visual ou julgamento textual:

- transcrição de fórmulas em regiões visuais;
- descrição de imagens;
- extração de tabelas ou texto rasterizado por modelo multimodal;
- crítica visual da descrição contra o recorte;
- revisão opcional da coerência entre LaTeX e leitura;
- reescrita opcional segundo regras de audiodescrição;
- revisão textual global opcional;
- resolução contextual opcional de ambiguidades matemáticas.

A camada matemática principal não precisa chamar uma LLM para cada formato. Depois que uma expressão de entrada é definida, a AST, a fala e as serializações são produzidas por código local.

---

## Agentes e responsabilidades

### Agente Único

Arquivo principal: `core/agents/agente_unico.py`.

É o orquestrador de páginas. Ele:

- separa o documento em páginas;
- consulta cache;
- extrai regiões;
- identifica texto que pode seguir diretamente;
- envia somente regiões necessárias para visão;
- limita o paralelismo por semáforo, configurado por `REGIOES_CONCORRENTES`;
- recompõe o conteúdo na ordem da página;
- mantém informações geométricas para a camada matemática.

As páginas são processadas em sequência. Dentro de uma página, regiões visuais podem ser processadas em paralelo.

### Planejador

Arquivo: `core/agents/planejador.py`.

O planejamento é **determinístico por padrão**. Ele cria um inventário da página, calcula vizinhança, identifica possíveis títulos e legendas, relaciona legendas a imagens, tabelas ou fórmulas e sinaliza fórmulas possivelmente fragmentadas.

Existe refinamento por IA, controlado por `USAR_PLANEJADOR_IA`, mas ele fica desligado no arquivo de configuração de demonstração.

### Especialistas multimodais

Arquivo: `core/agents/especialistas_agno.py`.

Há prompts e papéis diferentes para:

- imagens e gráficos;
- tabelas;
- fórmulas;
- texto escaneado;
- regiões desconhecidas.

Para fórmulas, a resposta solicitada ao modelo contém:

```text
LATEX: <expressão>
LEITURA: <leitura em português>
```

O LaTeX reconhecido ainda não é tratado como verdade automática. Ele passa pela camada matemática e por verificações posteriores.

### Crítico Visual

Arquivo: `core/agents/critico_visual.py`.

Compara o texto gerado com o mesmo recorte visual e devolve fidelidade, confiança e suspeitas. Quando reprova, pode solicitar uma segunda descrição. Se a nova tentativa continuar duvidosa, a saída recebe um marcador de incerteza.

Esse crítico é uma segunda avaliação probabilística, não uma prova de correção. Dois modelos podem repetir o mesmo erro.

### Normalizador Acessível

Arquivo: `core/agents/acessivel.py`.

A parte determinística sempre pode:

- remover prefixos redundantes;
- preservar marcadores de incerteza;
- detectar inferências explícitas;
- evitar que a resposta perca conteúdo relevante.

Uma reescrita por IA pode ser ativada com `USAR_ACESSIVEL=true`. O resultado é descartado se o guardião de preservação detectar perda excessiva de conteúdo.

### Conferidor de Fórmulas

Arquivo: `core/agents/conferidor_de_formulas.py`.

Possui duas funções diferentes:

1. conferir se os campos `LATEX:` e `LEITURA:` parecem coerentes;
2. executar uma crítica matemática opcional por IA.

A validação determinística continua sendo a camada principal. A crítica adicional por modelo é controlada por `USAR_CRITICO_MATEMATICO` e fica desligada por padrão na configuração de demonstração.

### Resolvedor de Contexto Matemático

Arquivo: `core/agents/resolvedor_de_contexto_matematico.py`.

A detecção de ambiguidades é determinística. Ela procura casos como:

- `2a` interpretável como produto ou ordinal;
- expoente possivelmente achatado;
- alcance incerto de radical;
- fração linear com vários termos;
- tokens não consumidos pelo parser.

A resolução por LLM é opcional e controlada por `USAR_RESOLVEDOR_CONTEXTO`. Se estiver desligada ou não houver evidência suficiente, a expressão deve permanecer com status de revisão.

### Editor Textual

Arquivo: `core/agents/editor_textual.py`.

Faz uma revisão opcional do documento completo para apontar inconsistências entre páginas. Ele não deveria reescrever o material. É controlado por `USAR_EDITOR`.

---

## A árvore matemática

O núcleo está em `pipeline/matematica/arvore_matematica.py` e na fachada `core/math/pipeline.py`.

O pipeline executa, em linhas gerais:

```text
1. receber evidência textual e geométrica
2. reparar possíveis scripts perdidos
3. localizar a fronteira da expressão
4. tokenizar
5. classificar sinais e inserir produtos implícitos
6. construir a AST
7. detectar ambiguidades contextuais
8. gerar fala e serializações
9. validar preservação
10. atribuir status de revisão
```

### Tipos de nós implementados

A árvore atual contém, entre outros:

- números inteiros e decimais;
- símbolos;
- grupos e parênteses;
- menos unário;
- mais ou menos;
- soma e subtração;
- multiplicação explícita e implícita;
- divisão e fração;
- potência;
- subscrito;
- raiz quadrada e raiz com índice;
- relações, como igualdade e desigualdade;
- funções matemáticas;
- operações de conjuntos;
- conjuntos literais e por propriedade;
- quantificadores;
- limite;
- negação e operações lógicas;
- valor absoluto;
- cardinalidade;
- nó desconhecido para trechos não interpretados.

O nó desconhecido impede que um trecho seja descartado silenciosamente. Entretanto, sua presença também sinaliza que a expressão não foi compreendida por completo.

### Exemplo: fórmula quadrática

Entrada:

```latex
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
```

Representação conceitual:

```text
Relation (=)
├── Symbol (x)
└── Divide
    ├── PlusMinus
    │   ├── UnaryMinus
    │   │   └── Symbol (b)
    │   └── Sqrt
    │       └── Subtract
    │           ├── Power
    │           │   ├── Symbol (b)
    │           │   └── Integer (2)
    │           └── Multiply, implícita
    │               ├── Integer (4)
    │               ├── Symbol (a)
    │               └── Symbol (c)
    └── Multiply, implícita
        ├── Integer (2)
        └── Symbol (a)
```

A mesma árvore pode gerar:

- fala estrutural em português;
- fala concisa;
- MathML;
- LaTeX normalizado;
- OMML para Word;
- assinatura estrutural para comparação e validação.

---

## Geração da fala matemática

Arquivo principal: `pipeline/matematica/fala_matematica.py`.

A fala percorre a AST. Ela não é produzida por uma nova chamada de IA.

### Modo estrutural

É o modo padrão. Anuncia fronteiras quando a estrutura é complexa:

```text
uma fração. No numerador: ... No denominador: ... Fim da fração
```

Para raízes complexas, também pode anunciar `fim da raiz`.

### Modo conciso

Remove parte dos marcadores e produz uma leitura mais corrida. Frações simples, cujos dois lados são folhas da árvore, já são faladas de maneira curta mesmo no modo estrutural.

### Modo pedagógico

Existe no código e pode trocar, por exemplo, `menos b` por `o oposto de b`. Ainda não está exposto como comportamento padrão do produto.

### Vocabulário

O vocabulário fica separado em `pipeline/matematica/vocabulario_de_fala.py`:

- números por extenso;
- unidades e concordância;
- letras gregas;
- funções trigonométricas, hiperbólicas e outras;
- relações matemáticas;
- operadores lógicos e de conjuntos.

O dicionário `LETRAS_SOLETRADAS` está vazio na versão atual. Portanto, as variáveis latinas são mantidas como a própria letra, embora a configuração interna ainda aceite o parâmetro de soletração.

---

## MathML, LaTeX e OMML

Arquivo: `pipeline/matematica/serializacao_matematica.py`.

### MathML

A serialização inclui estruturas como:

- `<mfrac>` para frações;
- `<msqrt>` e `<mroot>` para raízes;
- `<msup>` para potências;
- `<msub>` para índices;
- operadores e agrupamentos em `<mrow>`.

A multiplicação implícita pode receber o caractere Invisible Times, `U+2062`, tornando a relação explícita no MathML sem alterar a aparência visual.

O código também adiciona:

- anotação LaTeX dentro de `<semantics>`;
- idioma `pt-BR` quando possível;
- identificadores estáveis em nós estruturais.

Isso preserva a estrutura no arquivo. Ainda assim, o comportamento final depende do navegador, leitor de tela e motor matemático. A marcação correta não autoriza afirmar compatibilidade universal.

### LaTeX

O LaTeX é uma representação técnica e uma linguagem de autoria. **Não é uma saída braille**.

### OMML

O OMML é a representação matemática nativa do Microsoft Word. O DOCX usa essa serialização para inserir equações editáveis em vez de apenas imagens.

### Braille

A transcrição para braille matemático em português, com referência no CMU, ainda não foi implementada. A anotação LaTeX pode ser útil como dado intermediário, mas não substitui uma transcrição braille validada.

---

## Portão de validação matemática

A validação está distribuída principalmente entre:

- `pipeline/matematica/cobertura_matematica.py`;
- `pipeline/matematica/validadores_matematicos.py`;
- `pipeline/matematica/problemas_matematicos.py`.

As verificações incluem:

- menos unário e subtração;
- expoentes e subscritos;
- conteúdo de raízes;
- multiplicação implícita;
- parênteses e agrupamentos;
- cadeias de igualdade;
- preservação de termos e operadores;
- cobertura dos nós na fala;
- símbolos crus não verbalizados;
- validade XML do MathML;
- divergência entre LaTeX e MathML;
- diferenças entre ocorrências estruturalmente equivalentes;
- tokens ou trechos não consumidos pelo parser.

Cada expressão pode receber um dos seguintes estados:

| Estado | Significado no código |
|---|---|
| `reviewed` | Não foram encontrados problemas acionáveis pelas regras atuais. É aprovação automática do pipeline, não revisão humana. |
| `draft` | Há avisos ou problemas que não foram classificados como bloqueadores. |
| `needs_review` | Há ambiguidade, parse incompleto, bloqueador ou pedido explícito de revisão. |
| `approved` | Estado reservado para aprovação humana em partes da modelagem; o fluxo completo de aprovação não está integrado nesta demonstração. |

A existência do portão reduz erros silenciosos, mas não prova que a fórmula esteja correta. Ele verifica propriedades que o código sabe formalizar.

### Limitação de integração atual

Os estados existem no nível dos blocos matemáticos. O repositório também possui funções para pacote de revisão e decisão de publicação, mas o **portão documental completo ainda não está totalmente conectado ao caminho principal do orquestrador**. Portanto, a reunião deve apresentar essa parte como arquitetura em consolidação, não como fluxo institucional concluído.

---

## Documento canônico

Arquivo: `pipeline/construtor_canonico.py`.

Após o processamento, o material é convertido para um objeto estruturado com:

- metadados da fonte;
- idioma;
- seções hierárquicas;
- identificadores de blocos;
- parágrafos;
- listas;
- código;
- tabelas;
- imagens;
- matemática;
- avisos técnicos e dados de auditoria disponíveis.

A finalidade é aplicar uma política de **fonte única**: todos os renderizadores recebem o mesmo conteúdo estruturado.

---

## OCR: o que existe e o que ainda não existe

Esta versão **não usa um motor OCR local dedicado de forma efetivamente integrada ao caminho principal**.

O código contém dependências declaradas para `pytesseract` e `rapidocr`, mas não há chamada de produção a essas bibliotecas nos módulos do pipeline atual. O comando `/ocr` e as regiões classificadas como `text_scanned` usam, na prática, um **modelo multimodal com um prompt restritivo de transcrição**.

O fluxo atual é:

```text
PDF digital       → PyMuPDF/Docling tenta recuperar texto e estrutura
região rasterizada → recorte enviado ao modelo multimodal com prompt de OCR
fórmula visual     → modelo multimodal propõe LaTeX
```

Isso deve ser descrito como **transcrição visual por modelo multimodal**, e não como um subsistema OCR local finalizado.

A integração de um OCR local mais robusto está no roadmap. Os modelos locais de visão e reconhecimento que seriam úteis nessa etapa exigem mais memória e capacidade de GPU do que o equipamento atualmente disponível para o desenvolvimento. Por essa razão, a demonstração usa prioritariamente modelos remotos via OpenRouter, mantendo o suporte a Ollama como alternativa experimental para máquinas adequadas.

Docling também pode utilizar modelos locais para análise de layout, mas isso não resolve sozinho reconhecimento matemático confiável nem substitui a futura camada OCR dedicada.

---

## Extração e fallback

### Docling 

É selecionado por `STRUCTURER=docling`. Detecta regiões e tipos estruturais. Se uma falha de dependência ou de layout for diagnosticada, o estruturador pode ser desativado durante o processo e o sistema passa a usar PyMuPDF.

### PyMuPDF

É o fallback e também fornece:

- camada textual;
- blocos;
- coordenadas;
- recortes de página;
- extração básica de imagens.

### Fallback de infraestrutura

Vários componentes opcionais seguem uma estratégia `fail-open`: uma falha de agente pode permitir que o pipeline continue com texto local ou marcadores de erro. Isso evita perder o documento inteiro por uma indisponibilidade de API.

Entretanto, `fail-open` não significa que uma região perdida seja acessível. O fallback pode produzir texto não verificado ou o marcador:

```text
[falha ao processar esta regiao: ...]
```

Esses casos precisam alimentar revisão e decisão de publicação. A versão atual ainda precisa fortalecer essa ligação no nível documental.

---

## Formatos de saída

### TXT

- usa a fala matemática derivada da AST;
- lineariza tabelas;
- elimina marcadores técnicos;
- serve de base para o MP3.

### HTML

- usa títulos nativos e sumário;
- gera tabelas com `<th>`, `<thead>`, `<tbody>`, `caption` e resumo quando disponíveis;
- marca idiomas em células;
- inclui MathML e fala em português.

A estratégia atual envolve o MathML com uma leitura contínua por `aria-label` e marca o `<math>` interno com `aria-hidden`. Isso favorece a leitura corrida, mas pode impedir que a árvore interna seja exposta ao leitor de tela. Por isso, a navegação hierárquica ainda é uma questão aberta de implementação e teste.

### DOCX

- insere equações OMML;
- tenta embutir imagens reais;
- grava texto alternativo nas propriedades da figura;
- marca idioma em células;
- preserva cabeçalhos de tabela.

### PDF visual

- produz um documento legível e diagramado;
- cria sumário e marcadores visuais;
- não possui tags estruturais completas;
- não declara ordem lógica compatível com PDF/UA;
- recebe o sufixo `_visual`.

### MP3

No caminho do Telegram, o MP3 é criado depois dos outros artefatos. O handler lê o TXT e chama `renderers/sintetizador_de_voz.py`. O arquivo só é mantido se todas as partes forem sintetizadas e reunidas com sucesso.

---

## Estrutura do repositório

```text
config/
  settings.py                       configurações gerais

core/
  agents/
    agente_unico.py                 orquestra páginas e regiões
    planejador.py                   planejamento determinístico da página
    especialistas_agno.py           agentes multimodais por tipo
    critico_visual.py               verificação visual opcional
    conferidor_de_formulas.py       conferência de LaTeX e leitura
    acessivel.py                     normalização de audiodescrição
    editor_textual.py               auditoria global opcional
    resolvedor_de_contexto_matematico.py
                                    ambiguidades e contexto matemático
  ai/
    openrouter.py                   cliente remoto
    ollama.py                       alternativa local
  math/
    pipeline.py                     fachada da camada matemática
  services/
    cache.py                        cache
    coordenador_de_exportacao.py    geração e empacotamento
    servico_de_fila.py              fila de processamento
    servico_de_historico.py         histórico local
    trilha_matematica.py            rastreabilidade matemática
  estruturador.py                   Docling com fallback PyMuPDF
  extrator_de_regioes.py            regiões, recortes e perfis de página
  orquestrador.py                   entrada do pipeline

pipeline/
  matematica/
    arvore_matematica.py            tokenizador, parser e AST
    fala_matematica.py              fala em português
    serializacao_matematica.py      LaTeX, MathML e OMML
    cobertura_matematica.py         portão de validação
    normalizador_matematico.py      reparo e normalização
    agrupador_matematico.py         união de fragmentos
    matematica_inline.py            fórmulas em texto corrido
    tabela_matematica.py            matemática em células
    vocabulario_de_fala.py          números, unidades e símbolos
  analisador_de_estrutura.py        texto dos agentes para blocos tipados
  construtor_canonico.py            documento canônico
  ordem_de_leitura.py               ordenação espacial
  podador.py                        remoção de ruído e duplicação

renderers/
  renderizador_txt.py
  renderizador_html.py
  renderizador_docx.py
  renderizador_pdf.py
  renderizador_de_audio.py          roteiro e SSML ainda não integrado
  sintetizador_de_voz.py            geração do MP3

interfaces/
  telegram/                         interface da demonstração
  cli/                              entrypoint de execução

tests/                              testes unitários, integração e regressão
schemas/                            esquema do documento acessível
```

---

## Configuração dos componentes de IA

Os modelos são configuráveis no `.env`. A configuração de demonstração separa modelos de visão e texto:

| Função | Variável principal |
|---|---|
| visão geral | `OPENROUTER_MODEL` |
| reconhecimento de fórmula | `FORMULA_MODELO` |
| conferidor textual | `CONFERIDOR_MODELO` |
| editor textual | `EDITOR_MODELO` |
| normalizador acessível | `ACESSIVEL_MODELO` |

Principais flags:

| Variável | Papel |
|---|---|
| `USAR_AGNO` | ativa os especialistas implementados com Agno |
| `USAR_CRITICO` | ativa o crítico visual |
| `USAR_CONFERIDOR` | ativa a conferência textual de fórmula |
| `USAR_CRITICO_MATEMATICO` | ativa crítica matemática adicional por IA |
| `USAR_ACESSIVEL` | ativa reescrita opcional de acessibilidade |
| `USAR_EDITOR` | ativa revisão textual global |
| `USAR_RESOLVEDOR_CONTEXTO` | ativa resolução contextual por IA |
| `USAR_PLANEJADOR_IA` | ativa refinamento do plano da página por IA |
| `USAR_PIPELINE_MATEMATICO` | ativa a camada AST atual |

`MODEL_TEMPERATURE=0` reduz variação nas respostas do modelo, mas não elimina alucinações, erros de percepção ou mudanças do provedor.

---

## Instalação

### Requisitos

- Python 3.11 final;
- token de bot do Telegram;
- chave do OpenRouter para a configuração recomendada da demonstração;
- Tesseract instalado não ativa sozinho um OCR no fluxo atual;
- GPU é opcional para o caminho remoto, mas necessária para executar localmente modelos multimodais maiores com desempenho aceitável.

### Ambiente

```bash
cp .env.example .env
```

Preencha, no mínimo:

```env
ENABLED_INTERFACES=telegram
BOT_TOKEN=seu_token
AI_CLIENT=openrouter
OPENROUTER_API_KEY=sua_chave
STRUCTURER=docling
```

### Instalação com Poetry

```bash
poetry install
poetry run python run.py
```

### Instalação com pip

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```


---

## Limitações conhecidas e próximos passos

1. **Integrar OCR local dedicado.** `pytesseract` e `rapidocr` ainda não participam do fluxo principal. A escolha do motor precisa considerar texto, fórmulas, layout e capacidade de hardware.
2. **Separar OCR textual de reconhecimento matemático.** Um único motor não resolve ambos com a mesma qualidade.
3. **Revisar a estratégia HTML/MathML.** O `aria-label` atual oferece fala contínua, mas pode ocultar a árvore matemática da tecnologia assistiva.
4. **Criar uma matriz de testes reais.** Navegadores, NVDA, JAWS, VoiceOver, TalkBack e versões diferentes.
5. **Integrar SSML ao MP3.** O roteiro existe, mas o caminho principal ainda sintetiza o TXT diretamente.
6. **Conectar o portão documental.** Estados matemáticos, fallback visual, pacote de revisão e decisão final precisam formar um único fluxo obrigatório.
7. **Adicionar revisão humana operacional.** A versão de demonstração não possui painel integrado de aprovação.
8. **Gerar EPUB 3 acessível.** Com navegação, metadados e validação por EPUBCheck e Ace.
9. **Implementar braille matemático em CMU.** LaTeX não deve ser apresentado como braille.
10. **Produzir PDF/UA ou manter o PDF explicitamente visual.** O arquivo atual não é um formato assistivo confiável.
11. **Avaliar com usuários cegos.** Medir compreensão, tempo de tarefa, esforço de navegação e preferência entre fala estrutural, concisa, MathML e outras representações.
12. **Substituir métricas autodeclaradas de confiança.** A confiança fornecida por LLM não é uma probabilidade calibrada de correção.

---

## O que este protótipo demonstra


> acessibilidade matemática não deve ser tratada como uma legenda produzida para uma imagem, mas como reconstrução de uma estrutura formal que pode alimentar diferentes modalidades de acesso.

A principal contribuição atual não é afirmar que todo PDF se torna automaticamente acessível. É mostrar um caminho técnico no qual:

- percepção visual e geração documental são separadas;
- a matemática possui uma representação canônica;
- a fala é derivada da estrutura;
- os formatos compartilham a mesma fonte;
- perdas podem ser detectadas por regras explícitas;
- incerteza pode ser registrada em vez de ocultada.

---

## Licença

MIT, conforme `pyproject.toml`.
