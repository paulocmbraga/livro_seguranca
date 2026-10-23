# Parte VIII: verificação adversarial e operação

Paulo Cesar Braga · versão 1.0 · 23/10/2026 · capítulos 29–32.

## Instalação e execução

Execute na raiz do pacote. Qualificado em Windows, Python 3.12.0 e SQLite 3.42.0.
O ambiente limpo abaixo foi instalado e passou em pip check e 51 testes novos.
Não substitua o ambiente da Parte VII, que usa versões próprias de ML.

```powershell
python -m venv .venv/parte8
$py = '.venv/parte8/Scripts/python'
& $py -m pip install -r materiais/parte8/requirements.lock.txt
& $py -m pip check
& $py -m unittest discover -s testes_parte8 -v
& $py producao/qualificar_parte8.py --out output/minha_execucao/parte8
```

Em Linux, o caminho é `.venv/parte8/bin/python`; essa plataforma não recebeu reprodução
independente nesta entrega. Não use `-O`: os verificadores usam asserts.
Os diretórios de run devem ser novos. Os arquivos da captura são dados sintéticos públicos.
Sem API paga, download de modelo, Docker ou serviço externo nesta parte.

```powershell
& $py -m laboratorios.parte8 run L29 --out output/minha_execucao/l29
& $py -m laboratorios.parte8 run L30 --out output/minha_execucao/l30
& $py -m laboratorios.parte8 run L31 --out output/minha_execucao/l31
& $py -m laboratorios.parte8 run L32 --out output/minha_execucao/l32
& $py -m laboratorios.parte8 verify L29 --out output/parte8_v01/l29
& $py -m laboratorios.parte8 verify L30 --out output/parte8_v01/l30
& $py -m laboratorios.parte8 verify L31 --out output/parte8_v01/l31
& $py -m laboratorios.parte8 verify L32 --out output/parte8_v01/l32
```

`run` exerce o mecanismo. `verify` confere inventário, hashes, assinaturas e relações
persistidas; não repete HTTP ou o escalonamento do worker. As capturas de referência
e repetição no mesmo host estão em `output/parte8_v01` e `output/parte8_qualificacao_v01`.

## L29: campanha e achado

24 chamadas HTTP em loopback: três perfis, cinco propostas de ataque e três controles
por perfil. O adversário altera proposta documental preparada, sem geração de LLM.
Após recusa 403, a segunda tentativa troca a justificativa; não é busca aberta.
O servidor lê o registro sintético e copia seu conteúdo para uma caixa lógica SQLite.
`external` é um rótulo de destinatário, sem envio à internet.

| Perfil | Efeitos indevidos / 5 | Utilidade / 3 |
|---|---|---|
| weak | 5 | 3 |
| filter | 4 | 1 |
| bound | 0 | 3 |

Plano, tentativas, bancos, recibos e F29-01 estão preservados. O principal vem da
credencial sintética; o corpo não o substitui. Idempotência exige mesmos argumentos.
Reprodução por outro operador: seguir `materiais/parte8/CONTRATO.md`; aceite pendente.

## L30: avaliação pareada

72 tarefas: 48 adversariais, 24 legítimas; 12 grupos de contexto, quatro de desenvolvimento
e oito reservados conhecidos. Quatro IDs por grupo adversarial são correlacionados,
não quatro mecanismos independentes. Corpus autoral e conhecido, sem teste cego.
Três tentativas por tarefa/perfil, 216 chamadas por perfil, 864 totais.

| Perfil | Efeitos conhecidos / 32 reservadas | Incertas | Utilidade / 24 |
|---|---|---|---|
| filter | 30 | 2 | 0 |
| bound | 0 | 0 | 24 |
| no_owner | 11 | 1 | 24 |
| no_destination | 8 | 0 | 24 |

Sete chamadas perdem a resposta após commit por falha injetada. A visão online conserva
incompletude e a auditoria posterior registra o efeito separadamente. Juiz lexical:
108 TP, 144 FP, 528 TN, 77 FN e sete sem resposta. Não é juiz LLM nem revisão humana
independente. Labels autorais têm regra e recibo verificáveis.

Bootstrap descritivo pareado por oito grupos, 2.000 reamostragens, semente 2930.
Banda com imputações extremas de -1 a -0,84375 para bound menos filter; não é garantia
populacional nem redução prometida em produção. Todos os casos e falhas são conservados.

## L31: evidência e detecção

Oito chamadas; oito eventos de decisão e cinco de efeito. Ed25519 real com chaves
efêmeras em memória; somente chaves públicas exportadas. Entrega em lotes é invertida,
perde dois eventos, duplica um e recebe duas adulterações. Detectadas assinaturas inválidas,
duplicata e lacunas controller/2 e destination/5. O canário bruto não entra nos eventos.

Uma alegação falsa assinada pelo produtor válido passa na assinatura e falha no cotejo
com o destino. Restaurar a trilha não apaga os quatro efeitos indevidos. Âncoras e banco
ficam no mesmo host confiável; não há WORM, PKI, SIEM ou Collector qualificado.
UTC e monotonic_ns locais não fornecem uma ordem global multi-host.

## L32: contenção e recuperação

SQLite/FTS5 e dois subprocessos reais: reinício de executor permissivo e worker em voo.
Somente rotação de chave mantém sessão/delegação; reinício mantém estado contaminado.
Dois efeitos externos lógicos permanecem como evidência. Após contenção, o worker
revalida época/sessão/delegação e registra revoked sem efeito para pending.

Backup consistente preservado; sua restauração responde ao healthcheck, mas falha no gate.
Reconstrução de memória/índice/política, piso de revogação e drenagem precedem nova sessão.
A tarefa legítima nova confirma efeito interno. O artefato model é uma política preparada,
não modelo neural; não houve desaprendizado, IdP externo ou rollback de imagem neste lab.

## Recursos e limitações

Referência: L29 1,00 s/36,9 MiB; L30 9,32 s/40,6 MiB; L31 1,12 s/41,3 MiB;
L32 1,78 s/52,1 MiB. Valores arredondados de `resources.json`, RSS da árvore amostrado
a cada 100 ms; pode perder picos e duplicar páginas compartilhadas. Inclui imports e
encerramento, exclui instalação e uso total do host. Sem benchmark, SLA ou RTO.

Os oito exemplos Python do manuscrito foram executados. O pacote completo conserva
as partes anteriores; seus ambientes, pré-requisitos e limites continuam nos guias
históricos. Revisão técnica independente permanece pendente. Fontes oficiais, versões
e limites de uso estão em `materiais/parte8/fontes.json`.
