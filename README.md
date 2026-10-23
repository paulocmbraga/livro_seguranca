# Engenharia de Segurança para Sistemas de IA

Materiais dos alunos. Autor: **Paulo Cesar Braga**.

Esta entrega integra o piloto à **Parte III, capítulos 9 a 12**, preservando todos os materiais anteriores. O projeto tem 36 capítulos; os capítulos 1–12 estão redigidos, e o restante permanece em desenvolvimento.

Comece pelo [guia da Parte III](PARTE_III.md). Os guias [Parte II](PARTE_II.md), [Parte I](PARTE_I.md) e [L00/M1](COMECE_AQUI.md) continuam disponíveis.

| Laboratório | Evidência da entrega |
|---|---|
| L09 ampliado | 8 casos novos; 32 gerações em Q4/Q8 e interfaces livre/enumerada; 128 trajetórias reais e 32 preparadas |
| L10 | SQLite FTS5 e FAISS reais; 20 observações, 10 exposições reconciliadas; cache, revogação e limpeza |
| L11 | Texto/HTML/PNG, Tesseract e LLM textual; 7 gerações, uma adaptação, 13 recibos em 14 decisões |
| L12 | SQLite persistente entre sessões; 16 etapas, 3 recibos HTTP; promoção, escopo, expiração e derivados |

A suíte nova tem 34 testes. O pacote cumulativo é validado com as 153 regressões anteriores, totalizando 187 testes. Os testes não repetem automaticamente inferência ou OCR: as campanhas reais são executadas separadamente, com respostas e versões preservadas em `output/parte3_v02`.

Os resultados incluem falhas deliberadas e erros de integração. O modelo pequeno propõe recursos inexistentes na interface livre; esses erros não são bloqueios defensivos. A comparação enumerada foi escolhida após observar tais falhas e é exploratória sobre casos conhecidos. Q4/Q8 são quantizações da mesma família. O L11 usa OCR seguido de modelo textual, sem visão multimodal nativa. L10 usa vetores lexicais normalizados, sem embeddings neurais. L12 usa propostas preparadas.

Aqui ficam apenas código, testes, guias, materiais sintéticos, locks e capturas selecionadas. Livro, PDF, EPUB, capas, fontes, arquivos KDP, executáveis e pesos permanecem fora deste repositório. Os 148 arquivos históricos além do README e manifesto geral permanecem byte a byte; esses dois arquivos versionados conservam sua história no Git.

Use diretórios novos ao executar. `run` produz uma captura; `verify` confere evidência existente. Não recalcule hashes de arquivos históricos para ocultar alterações. A validação é local e autoral; a reprodução independente continua pendente.
