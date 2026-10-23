# Parte IV: roteiro de reprodução

Paulo Cesar Braga | versão 1.0 | 23/10/2026. Execute na raiz do repositório. Dados e marcadores são sintéticos; os servidores usam somente loopback. Preserve as capturas publicadas e escolha diretórios novos para cada campanha.

## Ambiente

O perfil executado é Windows/Python 3.12.0, scikit-learn 1.9.1, NumPy 2.5.4 e Playwright 1.64.1. O lock inclui as dependências transitivas desta parte. Navegador local necessário para L14: a referência usa Edge 155.0.4283.62. A versão e o hash do executável estão na captura; o binário não é distribuído.

```powershell
python -m venv .venv
$py = '.venv/Scripts/python'
& $py -m pip install -r materiais/parte4/requirements.lock.txt
& $py -m unittest discover -s testes_parte4 -v
```

Não é necessário modelo, GPU, API paga ou Docker para L13–L16. O laboratório não instala navegador nem reutiliza perfil pessoal. Se Edge não estiver no caminho padrão, use `--browser` com o caminho de um executável Chromium/Edge local. Para a suíte cumulativa, instale também os locks de M1, Partes II e III, conforme seus guias. O ramo POSIX do subprocesso existe, mas não foi qualificado nesta entrega. O comando de testes da Parte IV executa os quatro laboratórios, incluindo navegador headless e encerramento de workers próprios.

## Executar e conferir

```powershell
& $py -m laboratorios.parte4 run L13 --out output/minha_execucao/l13
& $py -m laboratorios.parte4 run L14 --out output/minha_execucao/l14
& $py -m laboratorios.parte4 run L15 --out output/minha_execucao/l15
& $py -m laboratorios.parte4 run L16 --out output/minha_execucao/l16
& $py -m laboratorios.parte4 verify L13 --out output/minha_execucao/l13
& $py -m laboratorios.parte4 verify L14 --out output/minha_execucao/l14
& $py -m laboratorios.parte4 verify L15 --out output/minha_execucao/l15
& $py -m laboratorios.parte4 verify L16 --out output/minha_execucao/l16
```

Para conferir a referência, substitua o destino por `output/parte4_v01/l13` até `l16`. A repetição está em `output/parte4_qualificacao_v01`. O verificador exige a mesma fonte selada e inventário exato de artefatos; não altere uma captura publicada para fazê-la corresponder a código novo.

## L13: escore, política e consequência

São 32 textos de treino, 12 de calibração de decisão e 16 de avaliação. IDs e textos são disjuntos; todas as famílias são autorais e conhecidas. O treino real usa TF-IDF de n-gramas de caracteres e regressão logística. O limiar 0,45 foi escolhido exclusivamente na calibração pela função `2*FN+FP`, entre seis candidatos. A escolha é gravada antes de pontuar avaliação. Isso não é seleção cega nem calibração probabilística.

Na avaliação: TP=7, FN=1, FP=5, TN=3. As quatro citações legítimas foram marcadas. R15 recebe falha preparada na interface de decisão; não é timeout de rede medido. As 64 trajetórias correspondem a 16 casos em quatro políticas, com propostas fixadas para isolar o controle. Uma chamada direta adicional contorna o detector e continua sujeita à autorização do domínio.

| Política | Indevidos / 8 hostis | Legítimas concluídas / 8 |
|---|---|---|
| Negativa A, sem detector | 8 | 8 |
| Sinalização + C | 0 | 8 |
| Bloqueio + C | 0 | 3 |
| Revisão limitada + C | 0 | 3 |

São 30 recibos HTTP/SQLite: 16+8+3+3. A revisão tem capacidade quatro e decisões preparadas, incluindo aprovação errada recusada por C. Não estima desempenho humano. Os artefatos JSON do modelo são inspecionáveis, sem pickle; sua integridade local não equivale a assinatura de fornecedor.

## L14: consumidores reais

São 22 casos: SQL, comando, HTML, caminho e URL com pares legítimo/hostil e fraco/estrito, mais dois redirecionamentos. SQL é executado em SQLite; o subprocesso fraco cria um marcador em arquivo; o navegador executa o script preparado e preserva quatro PNGs/HTMLs. O estrito separa parâmetros, argumentos, texto e caminhos autorizados. O ensaio de URL mantém seis requisições no seu próprio receptor; duas alcançam a rota interna apenas pelos perfis fracos.

O bloqueio de rede do navegador contém o ensaio; a ausência do marcador JavaScript no DOM e a presença do texto literal sustentam o resultado de codificação. O filesystem é controlado pela bancada, sem atacante concorrente; `resolve` seguido de leitura não constitui solução geral para TOCTOU. O ensaio não cobre DNS rebinding, IPv6, proxy externo, todas as linguagens de Markdown ou todos os contextos de HTML. Os argumentos são sintéticos e os processos pertencem à execução.

## L15: observar as cópias

Quatro perfis (tardio, redaction, tokenização, minimização) recebem dois registros. O receptor HTTP calcula 50+5 e ecoa o payload; não é LLM. São oito POSTs. Uma rota não aprovada é recusada antes de I/O. Todos os resultados ao usuário são 55 e não contêm os marcadores, embora os perfis fracos exponham dados em componentes anteriores.

A matriz separa origem local, gateway, receptor, cache, ferramenta, auditoria e usuário. A redaction de e-mail deixa a nota privada; tokenização conserva identificador estável e nota; minimização envia apenas tópico/valor e restringe cópias. A limpeza deixa cache=0, cofre=0 e auditoria=8 no SQLite local. Exportações sintéticas anteriores e recibos continuam preservados; não é apagamento forense ou exclusão em todas as réplicas. Não há criptografia nem API multiusuário de cofre. A necessidade de cada campo e a utilidade foram avaliadas somente para essa tarefa estreita.

## L16: reservar, admitir, cancelar, reconciliar

Vinte threads competem por reservas de quatro unidades contra limite de vinte: cinco são admitidas, somando vinte. `BEGIN IMMEDIATE` torna a admissão atômica nesse banco. Repetir o mesmo ID e os mesmos dados não duplica reserva; conflitos são recusados.

A carga tem 24 pedidos (vinte A, quatro B) em cada política. FIFO admite oito A e zero B. Quota por tenant e round-robin admitem quatro de cada. São 48 decisões, dezesseis chamadas HTTP concluídas e dois workers de execução por perfil. Não são ensaios de SLA, tráfego ilimitado ou distribuição multinó.

O teste de cancelamento inicia um cliente em subprocesso, espera o receptor registrar a chegada e realmente encerra esse worker. O receptor continua. Liberar quatro unidades cedo demais permite uma segunda chamada: seis consumidas para limite quatro. Conservar reserva desconhecida impede a segunda: três consumidas, saldo um após reconciliação. Há dois workers encerrados e três recibos de cancelamento; com a carga, dezenove recibos de provedor nesta bancada. Custos são unidades artificiais, sem tokens ou moeda.

## Recursos e limites de reprodução

Uma repetição sequencial no mesmo computador, incluindo imports, execução e encerramento, mediu:

| Laboratório | Segundos | Pico amostrado de RSS da árvore (MiB) |
|---|---:|---:|
| L13 | 7,31 | 194,5 |
| L14 | 4,22 | 616,7 |
| L15 | 1,19 | 35,9 |
| L16 | 4,78 | 74,2 |

A amostragem foi de 100 ms; soma processos próprios vivos, pode contar páginas compartilhadas duas vezes e perder picos. Não mede RAM total, downloads, instalação ou máquina dedicada. O navegador domina o maior valor. A memória e o tempo variam por host; não são mínimos de produção.

Para repetir a instrumentação, instale também `psutil==7.2.2` (já fixado no lock da Parte III) e execute:

```powershell
& $py -m pip install psutil==7.2.2
& $py producao/qualificar_parte4.py --out output/minha_execucao/qualificacao
```

O relatório `resources.json` guarda valores e limitações. Os logs e as quatro capturas dessa segunda execução também estão publicados. Referências oficiais consultadas em 23/10/2026 estão em `materiais/parte4/referencias.lock.json`. Resultados locais não demonstram segurança de uma aplicação real nem demanda comercial.

## Exercitar com critério

Troque uma família legítima antes de escolher limiar; mude a ordem da fila sem retreinar; crie um título SQL legítimo com apóstrofo; registre a diferença entre URL recusada e requisição iniciada; inclua um campo dispensável em auditoria; simule recibo atrasado ou duplicado. Escreva propriedade, contraprova, utilidade e observação independente. Mudanças em código, corpus ou contratos exigem uma nova captura, preservando a anterior.
