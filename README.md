# Engenharia de Segurança para Sistemas de IA

Materiais dos alunos. Autor: **Paulo Cesar Braga**.

Esta entrega acrescenta a **Parte VI, capítulos 21 a 24**, preservando as anteriores. O projeto prevê 36 capítulos; os capítulos 1–24 estão redigidos. Os demais continuam em desenvolvimento.

Comece pelo [roteiro da Parte VI](PARTE_VI.md). Permanecem disponíveis [Parte V](PARTE_V.md), [Parte IV](PARTE_IV.md), [Parte III](PARTE_III.md), [Parte II](PARTE_II.md), [Parte I](PARTE_I.md) e [L00/M1](COMECE_AQUI.md).

| Laboratório | Evidência nova |
|---|---|
| L21 | Store HTTP, partições, seleção de árvores e promoção vinculada; 11 chamadas |
| L22 | 48 modelos ajustados; orçamento, pares com gatilho, filtro e adaptação |
| L23 | 48 condições, 5.760 variantes válidas; mascaramento de gradiente e utilidade |
| L24 | API de modelo próprio; 12 substitutos, 1.048 chamadas, 736 inferências |

O pacote cumulativo passou em **327 testes**, sendo 43 novos, e 53 trabalhos de teste/reconciliação. A suíte nova executa novamente os quatro laboratórios. Referência final: `output/parte6_v02`; repetição: `output/parte6_qualificacao_v01`. Verificar capturas históricas não significa repetir inferência, OCR ou todos os runtimes anteriores.

Os modelos tabulares são treinados de verdade; dados e cenários são sintéticos. L21 preserva um resultado em que a contaminação piora a acurácia, sem torná-la válida. L22 mede gatilho, utilidade e falsos positivos. L23 inclui ataques alternativos e o custo limpo da defesa. L24 mede fidelidade fora das consultas e prejuízo legítimo causado pela cota. Não há certificado de robustez, recuperação de pesos da vítima, API paga ou avaliação de modelos de terceiros.

O repositório contém código, testes, guias, materiais, locks, capturas e pequenos modelos numéricos em JSON para auditoria. Os **472 arquivos históricos além de README e manifesto geral** permanecem byte a byte. Os dois documentos atualizados conservam sua história no Git. Livro, PDF, EPUB, fontes, capas, dados de KDP, pesos de LLM e executáveis ficam fora do pacote público.

Execute em diretórios novos. `run` cria evidência; `verify` reconcilia uma captura existente. Não use `python -O` nem recalcule hashes históricos para ocultar divergências. A validação ocorreu no mesmo computador; reprodução independente e revisão do autor permanecem pendentes. Os guias detalham dependências e limites de cada parte.
