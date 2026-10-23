# Contrato da bancada VIII

Versão 1.0. Somente dados sintéticos e recursos do processo/host próprio.
L29: 24 chamadas HTTP, três perfis, cinco ataques e três controles cada.
Destino external é uma caixa lógica SQLite local, sem egress remoto.
Documentos fornecem propostas estruturadas preparadas: não há LLM ou índice RAG em L29/L30.
L30: 72 tarefas, 12 famílias autorais, quatro de desenvolvimento e oito reservadas conhecidas.
Quatro perfis, três tentativas por tarefa, 864 chamadas. Comparação principal filter/bound;
no_owner e no_destination são ablações. Família é unidade de reamostragem, não tentativa.
Timeout após commit é injetado: conservar resultado desconhecido na visão online e recibo
na auditoria posterior. Sem revisão humana independente ou conjunto cego.
L31: oito chamadas HTTP; assinaturas Ed25519 reais; entrega em lotes perturbada pelo harness.
Chaves privadas só em memória. Âncoras, produtores e banco no mesmo host confiável.
L32: SQLite/FTS5 e subprocesso reais; artefato model representa política preparada, sem treino.
Backup não é removido durante recuperação. Revogação exige piso fora do backup restaurado.
Não é ensaio de IdP, SIEM, broker, LLM, ambiente multi-host ou serviço público.

## Reprodução por outro operador

Criar ambiente conforme PARTE_VIII.md, executar run em pasta nova, guardar manifestos e
recibos, verificar diferenças de decisão, não apenas hashes. Repetir o achado F29-01,
controle legítimo, perfil bound, ablações e o worker em voo. Registrar operador, plataforma,
revisão de código, resultados e divergências em relatório próprio. Esse aceite permanece
pendente nesta entrega; repetição pelo mesmo autor/agente não o satisfaz.
