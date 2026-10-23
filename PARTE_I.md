# Parte I: roteiro executável

Autor: Paulo Cesar Braga. Entrega 1.0, 22/10/2026. Execute os comandos na raiz do repositório, com Python 3.12. Os quatro laboratórios não têm dependências externas. O perfil efetivamente executado nesta entrega é Windows/Python 3.12.0.

## Execução

```powershell
python -m unittest discover -s testes_parte1 -v
python -m laboratorios.parte1 run L01 --out output/minha_execucao/l01
python -m laboratorios.parte1 run L02 --out output/minha_execucao/l02
python -m laboratorios.parte1 run L03 --out output/minha_execucao/l03
python -m laboratorios.parte1 run L04 --out output/minha_execucao/l04
```

Cada saída deve ser nova. O L04 inicia dois processos com portas efêmeras em `127.0.0.1` e os encerra no final. Usa credenciais temporárias em memória e contratos fictícios. Não exponha esses serviços como aplicação pública: são uma bancada didática com variantes vulneráveis deliberadas.

## Conferir as capturas

```powershell
python -m laboratorios.parte1 verify L01 --out output/minha_execucao/l01
python -m laboratorios.parte1 verify L02 --out output/minha_execucao/l02
python -m laboratorios.parte1 verify L03 --out output/minha_execucao/l03
python -m laboratorios.parte1 verify L04 --out output/minha_execucao/l04
python -m laboratorios.parte1.evidence run --capture output/minha_execucao/l04 --out output/minha_execucao/vinculo
python -m laboratorios.parte1.evidence verify --out output/minha_execucao/vinculo
```

As referências publicadas estão em `output/parte1_v02/l01`, `l02`, `l03`, `l04` e `vinculo`. Para verificá-las, substitua os caminhos nos comandos `verify`. O vínculo usa a estrutura relativa do projeto; conserve-a.

| Saída | Resultado de referência |
| --- | --- |
| L01 | 6 observações satisfeitas, 6 violadas, 6 desconhecidas |
| L02 | 2/2/3 caminhos nos grafos; 1/0/1 desvios |
| L03 inicial | 8 associações, 4 controles planejados, nenhum comprovado |
| L04 | 3 efeitos autorizados, 3 proibidos, 3 bloqueios, 1 erro |
| Vínculo L03–L04 | C01–C03 evidenciados localmente; C04 planejado |

## Examinar os artefatos

- `materiais/parte1/inventario.json`: ativos, responsáveis, precondições e contraexemplos.
- `materiais/parte1/arquiteturas.json`: grafos com caminho alternativo e nova rota de diagnóstico.
- `materiais/parte1/controles.json`: mecanismos, referências, testes e riscos residuais.
- `materiais/parte1/referencias.lock.json`: edições, commit ATLAS e hashes das fontes selecionadas.
- `materiais/parte1/casos_l04.json`: agenda dos dez casos antes da execução.
- `output/parte1_v02/l04/services`: bancos sintéticos de domínio e destino.
- `output/parte1_v02/l04/responses.json`: resposta HTTP e narrativa do cliente.
- `output/parte1_v02/l04/results.json`: classificação reconciliada.

O caso `false_log_A` deve permanecer `forbidden_effect`, embora o cliente declare `blocked`. O caso `missing_C` deve ser `error`, não bloqueio. O verificador rejeita campanha incompleta. Um recibo conhecido pode provar um efeito mesmo se outro log estiver ausente; isso não aprova a captura inteira.

## Ficha para sua reprodução

Registre em uma pasta própria: data, commit do repositório, sistema operacional, versão do Python, comandos completos, diretórios criados, resultados, erros e interpretação. Compare contagens e contratos; horários, portas, PIDs e alguns hashes variam entre execuções. Preserve a primeira tentativa se houver falha.

Uma repetição na mesma máquina não é reprodução independente. Não use os dez casos públicos como amostra inédita de ataques. O conjunto testa regras de aplicação e observação com ações preparadas; não estima resistência de um LLM nem isolamento do host.

## Atividades de extensão

Faça cópias dos materiais fora da referência: remova uma precondição do inventário, acrescente uma rota ao grafo, duplique uma associação documental e simule indisponibilidade de auditoria em um teste. Preveja a resposta antes de executar. Mantenha separados o contrato que você alterou, o resultado observado e a conclusão que essa observação permite. Os testes fornecem exemplos de mutações e de seus critérios de rejeição.
