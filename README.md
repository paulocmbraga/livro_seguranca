# Engenharia de Segurança para Sistemas de IA

Materiais dos alunos. Autor: **Paulo Cesar Braga**.

Esta entrega acrescenta a **Parte IV, capítulos 13 a 16**, preservando as anteriores. O projeto prevê 36 capítulos; os capítulos 1–16 estão redigidos. Os demais continuam em desenvolvimento.

Comece pelo [roteiro da Parte IV](PARTE_IV.md). Permanecem disponíveis os guias [Parte III](PARTE_III.md), [Parte II](PARTE_II.md), [Parte I](PARTE_I.md) e [L00/M1](COMECE_AQUI.md).

| Laboratório | Evidência nova |
|---|---|
| L13 | Classificador treinado; seleção de limiar; 64 trajetórias HTTP em quatro políticas; 30 recibos |
| L14 | 22 casos em SQLite, subprocessos, navegador, filesystem e HTTP; quatro capturas de tela |
| L15 | Oito envios HTTP; matriz de cópias, minimização, projeção e limpeza local |
| L16 | Corrida de 20 reservas, 48 decisões de admissão, 16 chamadas de carga e dois workers realmente encerrados |

O pacote cumulativo passou em **234 testes**, sendo 47 novos. A suíte nova executa novamente os quatro laboratórios e aplica mutações sobre as capturas. As oito capturas da Parte IV (referência e repetição) foram reconciliadas. Verificar capturas não significa repetir inferência histórica ou OCR das partes anteriores.

L13 treina regressão logística sobre TF-IDF; é um corpus pequeno e conhecido pelo autor, sem avaliação independente. Não há nova geração de LLM nesta parte. L14 testa consumidores reais com saídas preparadas. L15 e L16 usam receptores HTTP locais com comportamento preparado, sem fornecedor externo ou faturamento real. Quantidades de custo no L16 são sintéticas.

O repositório contém código, testes, guias, materiais sintéticos, locks e capturas. Os 275 arquivos históricos além de README e manifesto geral permanecem byte a byte. Os dois arquivos atualizados conservam sua história no Git. Livro, PDF, EPUB, fontes, capas, KDP, pesos e executáveis ficam fora do pacote público.

Execute em diretórios novos. `run` cria evidência; `verify` reconcilia uma captura existente. Não recalcule hashes históricos para ocultar divergências. A validação ocorreu no mesmo computador; reprodução independente permanece pendente.
