# Engenharia de Segurança para Sistemas de IA

Material dos alunos. Autor: **Paulo Cesar Braga**.

Esta entrega acrescenta a **Parte II, capítulos 5 a 8**, preservando a Parte I, o piloto L09 e a preparação L00/M1. O projeto editorial tem 36 capítulos; estes materiais não indicam que todo o livro esteja concluído.

Leia o [guia da Parte II](PARTE_II.md), o [guia da Parte I](PARTE_I.md) e o [guia L00/L09/M1](COMECE_AQUI.md).

| Laboratório novo | Integração e evidência |
|---|---|
| L05 | RS256/PyJWT no recurso HTTP: 16 chamadas, 5 leituras; audiência, validade, rotação e revogação |
| L06 | Matriz e cache HTTP: 66 chamadas, 42 leituras; perfis vulneráveis e completo |
| L07 | Ed25519 e processo emissor: 10 cenários, 2 carregamentos e 8 recusas anteriores ao uso |
| L08 | Docker Linux: 14 sondas diretas, ensaios de OOM e prazo, recibo no destino e limpeza |

Os resultados incluem falhas deliberadas nas variantes vulneráveis. Não são taxas gerais de segurança. As ações são preparadas e os dados são sintéticos; não há inferência de LLM na Parte II. L05–L07 usam Python 3.12 com dependências fixadas. L08 exige Docker Linux e uma imagem base fixada por digest.

A suíte nova tem **43 testes**; a regressão preserva 49 testes L09, 15 M1 e 46 da Parte I, totalizando **153 testes locais** no pacote exportado. O ensaio real do L08 é executado separadamente; seus oito testes de evidência não repetem o kernel. As capturas finais novas ficam em `output/parte2_v01`.

## Materiais históricos

L01–L04 conservam seus contratos e as capturas `output/parte1_v02`. O piloto L09 e M1 conservam versões, inferência e ensaios de protocolos documentados no guia anterior. Não atribua esses resultados à execução nova. Os arquivos existentes permanecem byte a byte, exceto este README e o manifesto geral, cujas versões ficam no histórico Git.

## Escopo público e limites

Aqui ficam código, testes, guias, materiais sintéticos, locks e capturas selecionadas. Manuscritos, PDFs editoriais, EPUBs, capas, fontes, arquivos KDP, executáveis e pesos de modelos não fazem parte do pacote.

L05 não é um provedor OAuth/OIDC; L06 não qualifica consistência distribuída; L07 não implementa TUF/SLSA nem isola o emissor contra o usuário do host; L08 não testa escape de kernel/hipervisor ou daemon rootless. A reprodução é local e autoral. Revisão técnica independente continua pendente para a consolidação editorial.

Use diretórios novos para suas execuções. `verify` confere captura; `run` produz nova execução. Não recalcule hashes de capturas antigas para esconder mudanças. O manifesto geral identifica a composição desta entrega, sem substituir uma raiz externa de autenticidade.
