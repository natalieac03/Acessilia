## O que ainda precisa melhorar no Acessília (com base em uma saída gerada de um material sobre a fórmula de báskara)

### 1. UNIFICAR o tratamento de todas as fórmulas

Hoje, as fórmulas isoladas passam pela árvore matemática e são lidas corretamente, mas expressões dentro de parágrafos e tabelas ainda podem seguir outro caminho.

**Como está:**

> “quatroac”
> “ax ao quadrado”
> “coeficiente do termo linear bx”

**Como deveria ficar:**

> “quatro vezes a vezes c”
> “a vezes x ao quadrado”
> “coeficiente do termo linear b vezes x”

Hoje ele está pegando apenas fórmulas maiores e esquecendo dos termos matemáticos simples.

A regra deve ser: encontrou matemática em qualquer lugar do documento, envia para a mesma árvore semântica.

---

### 2. Manter a fórmula integrada ao parágrafo

Quando uma fórmula aparece no meio de uma frase, o sistema ainda pode dividir o parágrafo em vários blocos.

**Como está:**

> A fórmula de Bhaskara resolve equações escritas na forma geral
>
> a vezes x ao quadrado mais b vezes x mais c é igual a zero
>
> . Os coeficientes a, b e c...

O ponto fica separado e a leitura soa cortada.

**Como deveria ficar:**

> A fórmula de Bhaskara resolve equações escritas na forma geral: a vezes x ao quadrado, mais b vezes x, mais c é igual a zero. Os coeficientes a, b e c...

Internamente, o parágrafo deve continuar sendo uma única estrutura:

```text
Texto inicial
+ fórmula inline
+ texto final
```

---

### 3. Melhorar as regras de português 

A estrutura matemática pode estar correta, mas a frase gerada ainda precisa respeitar a gramática.

**Como está:**

> “dois vezes a”

**Como deveria ficar:**

> “duas vezes a”

Outro exemplo:

**Como está:**

> “x índice um e x índice dois”

**Pode ficar mais natural como:**

> “x um e x dois”

ou, em uma leitura mais estrutural:

> “x com índice um e x com índice dois”

Essas escolhas precisam ser padronizadas e testadas com usuários.

---

### 4. Melhorar a leitura de fórmulas complexas

A leitura estrutural já está melhor, mas precisa anunciar claramente onde cada parte começa e termina.

**Como está em uma leitura corrida:**

> “x igual a menos b mais ou menos raiz de delta sobre dois a”

Essa leitura pode gerar dúvida: o que está dentro da raiz? O denominador é apenas o “a” ou é “dois a”?

**Como deveria ficar:**

> “x é igual a uma fração. No numerador: menos b, mais ou menos, raiz quadrada de delta. Fim da raiz. No denominador: duas vezes a. Fim da fração.”

Para expressões simples, não é necessário anunciar tantas fronteiras.

**Exemplo simples:**

> “a sobre b”

em vez de:

> “uma fração. No numerador a. No denominador b. Fim da fração.”

---

### 5. Preservar títulos e a hierarquia do documento

Alguns títulos podem desaparecer ou virar texto comum. Isso prejudica a navegação por leitores de tela.

**Como está:**

```text
Fórmula de Bhaskara
Quando a fórmula é usada?
FORMA GERAL
DISCRIMINANTE
```

Mas nem todos esses textos estão marcados como títulos reais no HTML ou no Word.

**Como deveria ficar:**

```text
Título principal
└── Fórmula de Bhaskara

Seção
└── Quando a fórmula é usada?

Subseções
├── Forma geral
├── Discriminante
└── Fórmula de Bhaskara
```

No HTML, isso deve corresponder a `h1`, `h2` e `h3`. No DOCX, deve usar estilos como `Título 1`, `Título 2` e `Título 3`.

---

### 6. Melhorar a acessibilidade das tabelas

A tabela já possui cabeçalhos, mas as fórmulas dentro das células ainda precisam passar pela árvore matemática.

**Como está:**

| Componente | Significado                                    |
| ---------- | ---------------------------------------------- |
| 4ac        | quatroac                                       |
| ax²        | coeficiente do termo quadrático ax ao quadrado |

**Como deveria ficar:**

| Componente | Significado            |
| ---------- | ---------------------- |
| 4ac        | quatro vezes a vezes c |
| ax²        | a vezes x ao quadrado  |

Também deve existir uma legenda clara, por exemplo:

> “Tabela: significado dos componentes da fórmula de Bhaskara.”

No áudio, é melhor dizer:

> “Tabela com duas colunas e nove linhas de dados.”

em vez de:

> “Tabela com nove registros.”

---

### 7. Permitir exploração matemática no HTML

Hoje, o HTML pode apresentar uma leitura em português, mas o MathML pode estar escondido da tecnologia assistiva.

Isso significa que a pessoa escuta a fórmula inteira, mas não consegue navegar por suas partes.

**Como está:**

> O leitor de tela anuncia uma frase pronta com a fórmula completa.

**Como deveria funcionar:**

A pessoa deveria poder escolher:

```text
Ouvir fórmula completa
Explorar fórmula
```

No modo de exploração, seria possível:

```text
Entrar na fração
Entrar no numerador
Entrar na raiz
Ouvir o conteúdo da raiz
Voltar ao numerador
Ir para o denominador
```

Assim, a fórmula deixa de ser apenas uma frase e passa a ser uma estrutura navegável.

---

### 8. Melhorar o DOCX

As fórmulas principais já podem aparecer como equações reais do Word, mas as fórmulas menores, principalmente dentro de tabelas, ainda podem ficar como texto Unicode.

**Como está:**

```text
Δ = b² − 4ac
```

armazenado como texto comum.

**Como deveria ficar:**

A expressão deve ser armazenada como equação OMML do Word ou ser derivada da mesma árvore matemática usada nas outras saídas.

O objetivo é evitar que o DOCX tenha duas lógicas:

```text
Fórmula principal → equação estruturada
Fórmula na tabela → texto comum
```

---

### 9. Não chamar o PDF atual de acessível

O PDF gerado ainda não possui estrutura suficiente para ser considerado acessível.

**Como está:**

* texto visualmente organizado;
* sem tags semânticas;
* sem ordem de leitura declarada;
* tabela sem estrutura acessível;
* fórmulas sem matemática navegável;
* não é PDF/UA.

**Como deveria ser apresentado atualmente:**

> “PDF visual de apoio.”

Ou o arquivo pode ser nomeado como:

```text
material_visual_nao_acessivel.pdf
```

Para ser acessível de verdade, precisaria ter títulos, parágrafos, listas, tabelas, fórmulas e ordem de leitura corretamente marcados.

---

### 10. Melhorar o TXT e o áudio

O TXT e o MP3 precisam de uma revisão final de fluidez.

**Como está:**

> “Deve ser diferente de zero..”

> “Coeficiente do termo linear b x..”

**Como deveria ficar:**

> “O coeficiente a deve ser diferente de zero.”

> “b é o coeficiente do termo linear, representado por b vezes x.”

Também é necessário remover:

* pontos duplicados;
* pausas artificiais;
* frases quebradas;
* leitura de símbolos colados;
* nomes técnicos de arquivos.

---

### 11. Gerar um relatório de validação

O pacote atualmente contém apenas os arquivos finais. Falta mostrar o que foi reconhecido, o que foi validado e o que ainda apresenta risco.

**Como está:**

```text
TXT
HTML
DOCX
PDF
MP3
```

**Como deveria ficar:**

```text
TXT
HTML
DOCX
PDF visual
MP3
relatorio_validacao.json
```

O relatório poderia informar:

```json
{
  "status": "precisa_de_revisao",
  "formulas_detectadas": 4,
  "problemas": [
    "formula_inline_fragmentada",
    "matematica_na_tabela_nao_normalizada",
    "titulo_ausente",
    "erro_gramatical_em_duas_vezes_a"
  ]
}
```

---

### 12. Testar com tecnologias assistivas e usuários

Os testes automáticos verificam se o código funciona, mas não comprovam que o material é fácil de estudar.

Ainda é necessário testar:

* HTML com NVDA e diferentes navegadores;
* MathML com MathCAT;
* DOCX no Word com NVDA e JAWS;
* áudio com diferentes velocidades;
* compreensão das fórmulas por pessoas cegas;
* facilidade para voltar, repetir e explorar partes da expressão.

O objetivo final não deve ser apenas:

> “O leitor de tela conseguiu falar.”

Deve ser:

> “O estudante conseguiu compreender, navegar e utilizar a fórmula para resolver o exercício.”
