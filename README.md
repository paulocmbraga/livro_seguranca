# Engenharia de Segurança para Sistemas de IA

Materiais dos alunos. Autor: **Paulo Cesar Braga**.

Esta entrega acrescenta a **Parte V, capítulos 17 a 20**, preservando as anteriores. O projeto prevê 36 capítulos; os capítulos 1–20 estão redigidos. Os demais continuam em desenvolvimento.

Comece pelo [roteiro da Parte V](PARTE_V.md). Permanecem disponíveis [Parte IV](PARTE_IV.md), [Parte III](PARTE_III.md), [Parte II](PARTE_II.md), [Parte I](PARTE_I.md) e [L00/M1](COMECE_AQUI.md).

| Laboratório | Evidência nova |
|---|---|
| L17 | Aprovação vinculada ao objeto; 30 chamadas HTTP; 503 após commit; repetição e compensação |
| L18 | Delegação RS256 por HTTP; sete pedidos de delegação, dezoito introspecções e seis recibos |
| L19 | SDK MCP 2.3.0, segundo cliente HTTP, duas revisões e stdio; 46 verificações |
| L20 | SDK A2A 1.2.3, HTTP+JSON, SSE e callbacks; nove tarefas, dezoito callbacks e nove recibos |

O pacote cumulativo passou em **284 testes**, sendo 50 novos. A suíte nova executa os quatro laboratórios e aplica contraprovas sobre capturas. As oito capturas da Parte V (referência e repetição) foram reconciliadas no pacote. Verificar capturas históricas não significa repetir inferência, OCR ou execução de todos os runtimes das partes anteriores.

Os serviços HTTP, tokens assinados, processos stdio, SSE, callbacks e bancos são reais e locais. Planos, aprovações e resultados adversariais são preparados; não há nova geração de LLM. O digest do catálogo MCP detecta mudança de referência, mas não prova aprovação humana. Autenticação do callback A2A não substitui vínculo de tarefa, contexto, tenant e estado. O guia distingue protocolos padronizados de endpoints didáticos próprios e de regras de domínio.

O repositório contém código, testes, guias, materiais sintéticos, locks e capturas. Os **388 arquivos históricos além de README e manifesto geral** permanecem byte a byte. Os dois documentos atualizados conservam sua história no Git. Livro, PDF, EPUB, fontes, capas, KDP, pesos e executáveis ficam fora do pacote público.

Execute em diretórios novos. `run` cria evidência; `verify` reconcilia uma captura existente. Não recalcule hashes históricos para ocultar divergências. A validação ocorreu no mesmo computador; reprodução independente e revisão do autor permanecem pendentes.
