# Apêndices A–G — reprodução, evidência e manutenção

Este complemento conserva os laboratórios L01–L36 e acrescenta utilitários
didáticos com biblioteca padrão. Não contém o livro nem suas soluções editoriais.
Os exemplos são sintéticos e não efetuam chamadas a LLMs, serviços externos ou Docker.

## Preparação e execução

Na raiz do repositório, use Python 3.12 e um ambiente novo:

```powershell
py -3.12 -m venv .venv/apendices
$py = '.\.venv\apendices\Scripts\python.exe'
& $py -m unittest discover -s testes_apendices -v
& $py -m apoio_apendices verify --out output/apendices_v02
& $py -m apoio_apendices run --out output/minha_execucao/apendices
```

`run` exige pasta inexistente e grava resultados, ambiente e manifesto.
`verify` confere hashes/inventário/fontes e recompõe pequenas operações locais
para comparar resultados. Não reexecuta os laboratórios históricos nem atesta
que houve inferência nova. Preserve cada captura com nome próprio.

## O que os 40 testes verificam

- Inventário fechado, caminhos relativos, aliases, tamanho e alteração de bytes.
- JSON com chaves duplicadas e valores não finitos recusados.
- Denominadores, resultados desconhecidos e limites identificados.
- Intervalo de Wilson, sob as hipóteses estatísticas explicadas no livro.
- Recibos duplicados, conflitantes, efeitos múltiplos e auditoria indisponível.
- Identidade de referências versionadas e impacto num grafo declarado.

`materiais/apendices/casos.json` contém a bancada pequena. As métricas adversariais
são quatro casos, um efeito confirmado e um desconhecido: limites de 25% a 50%.
Isso não é estimativa de taxa de falha de um LLM. O controle legítimo tem um caso
concluído em dois, com um desconhecido. Zero em vinte na função Wilson produz
limite superior próximo de 0,1611, sem demonstrar impossibilidade de falha.

`dossie_modelo.json` e `runbook_modelo.json` são modelos incompletos: decisão,
responsável e critérios precisam ser preenchidos no contexto autorizado.
`matriz_referencias.json` contém relações temáticas autorais, sem certificação.
`fontes.json` registra páginas oficiais consultadas e seus limites.

## Limites de segurança e de reprodução

O verificador de arquivos supõe raiz confiável e ausência de mutação concorrente;
não é extrator de arquivos hostis nem mecanismo de autenticidade. O reconciliador
recebe evidências preparadas: a indicação de ausência completa é uma premissa do
fixture, não uma consulta independente a um recurso remoto. O analisador de impacto
depende de um grafo declarado e nunca aprova produção automaticamente.

Referência: `output/apendices_v02`. Repetição no mesmo host:
`output/apendices_repeticao_v02`. Reprodução por outro operador permanece pendente.
Os perfis das partes anteriores continuam nos guias PARTE_I a PARTE_IX; não
instale todos os locks em um único ambiente.

O pacote público inclui apenas código, testes, guias, dados sintéticos e capturas.
Manuscritos, PDF, EPUB, capas, fontes, pesos e executáveis permanecem fora dele.

## Ocorrência conhecida no Windows

Na validação cumulativa de 23/10/2026, uma execução dos 47 testes da Parte IV
falhou em `tearDownClass`, ao remover `l15/local.sqlite` ainda aberto
(`WinError 32`, seguido de `WinError 267`). Uma repetição sem alteração do
código passou. Isso registra uma intermitência de encerramento/limpeza,
não comprova que ela foi corrigida. O perfil histórico usa conexões SQLite
cujo contexto transacional não equivale ao fechamento explícito da conexão.
Preserve o primeiro log se isso ocorrer; não descarte a falha nem reclassifique
limpeza malsucedida como sucesso. Os novos utilitários dos apêndices não usam
SQLite. Uma correção do ciclo de vida histórico requer uma entrega própria,
com contraprova de fechamento e novas capturas, sem reescrever as anteriores.
