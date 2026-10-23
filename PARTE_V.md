# Parte V: roteiro de reprodução

Paulo Cesar Braga | versão 1.0 | 23/10/2026. Execute na raiz do repositório. Os dados são sintéticos e os serviços ficam em loopback. Escolha diretórios novos e preserve as capturas publicadas.

## Ambiente

Perfil executado: Windows, Python 3.12.0, MCP SDK 2.3.0 e A2A SDK 1.2.3. O lock também fixa PyJWT 2.15.1, cryptography 50.0.2, httpx 0.28.1, httpx2 2.16.0 e demais dependências. Não são necessários modelo, GPU, navegador, Docker ou API paga para L17–L20. Os requisitos das partes anteriores continuam nos respectivos guias; o lock desta parte não é um instalador único de todo o acervo.

```powershell
python -m venv .venv
$py = '.venv/Scripts/python'
& $py -m pip install -r materiais/parte5/requirements.lock.txt
& $py -m unittest discover -s testes_parte5 -v
```

A suíte tem 50 testes e executa novamente os quatro laboratórios, incluindo HTTP, emissão e validação criptográfica, subprocesso stdio e SSE. O perfil foi qualificado no mesmo computador do autor; não se promete compatibilidade automática com outras versões ou sistemas. O emissor utiliza chaves efêmeras; a captura não publica chaves privadas nem bearers reutilizáveis.

## Executar e conferir

```powershell
& $py -m laboratorios.parte5 run L17 --out output/minha_execucao/l17
& $py -m laboratorios.parte5 run L18 --out output/minha_execucao/l18
& $py -m laboratorios.parte5 run L19 --out output/minha_execucao/l19
& $py -m laboratorios.parte5 run L20 --out output/minha_execucao/l20
& $py -m laboratorios.parte5 verify L17 --out output/minha_execucao/l17
& $py -m laboratorios.parte5 verify L18 --out output/minha_execucao/l18
& $py -m laboratorios.parte5 verify L19 --out output/minha_execucao/l19
& $py -m laboratorios.parte5 verify L20 --out output/minha_execucao/l20
```

Referência publicada: `output/parte5_v01/l17` até `l20`. Repetição: `output/parte5_qualificacao_v01`. O verificador exige inventário e hashes da fonte selada, além de relações semânticas entre pedidos, decisões e efeitos. Uma captura com hashes atualizados ainda pode ser rejeitada por faltar recibo ou contradizer a campanha. Não altere o histórico para adaptar evidência antiga a código novo.

## L17: decisão, objeto, estado e efeito

Os perfis compartilham autenticação e validade básica da aprovação. O fraco não vincula integralmente objeto e estado; o estrito compara ator, digest, versão do recurso, versão da política e ID da operação. O objeto tem oito campos: operação, plano, revisão, recurso, versão do recurso, destino, versão da política e corpo. A aprovação é preparada pelo controlador confiável da bancada, sem estudo com revisores humanos.

Dez casos são executados em cada perfil: legítimo, recurso, destino, corpo, replanejamento, recurso alterado, política alterada, aprovação expirada, ator errado e aprovação ausente. Depois há uma operação cujo commit precede uma resposta 503, repetição pelo mesmo ID, conflito com objeto novo aprovado e duas compensações do mesmo recibo. São **30 chamadas HTTP**, 26 eventos de execução e duas compensações persistidas, uma por perfil.

O fraco produz dez recibos; o estrito, dois. No estrito, a repetição devolve a referência original e o conflito não cria outro efeito. A compensação marca retração e preserva a história. O erro 503 é preparado depois do commit; não é crash nem desconexão real. A transação é SQLite local, sem atomicidade entre serviços externos. A retração não garante que ninguém tenha lido uma publicação anterior.

## L18: capacidade delegada e consumidor final

Um emissor com chave RSA efêmera emite JWTs RS256. O root identifica usuário e workload; dois saltos atenuam escopos, recursos, audiência, prazo, atores permitidos e profundidade. O endpoint `/delegate` é próprio: **não é implementação completa do RFC 8693**. A introspecção também é um perfil didático próprio, não certificação do RFC 7662.

Há sete pedidos HTTP de delegação: dois permitidos e cinco recusados. Dezoito chamadas ao consumidor provocam dezoito introspecções reais. As nove situações por perfil incluem leitura legítima, escrita, recurso estrangeiro, neto, audiência errada, expiração, assinatura alterada e dois descendentes após revogação da raiz. O fraco usa autoridade implícita excessiva depois de autenticar; o estrito respeita a capacidade.

São quatro recibos no fraco e dois no estrito. As duas leituras autorizadas permanecem úteis; os descendentes são recusados depois da revogação da raiz. O emissor conserva 25 eventos, somando delegação e introspecção. A captura inclui claims e chave pública, sem bearer ou chave privada. A consulta de estado não torna atômica uma revogação que aconteça entre introspecção e efeito; essa corrida distribuída está fora da garantia.

## L19: MCP real em HTTP e stdio

O SDK usa o perfil moderno `2026-07-28`, com informações de protocolo por requisição. Um cliente `httpx` separado executa inicialização e confirmação no perfil legado `2025-11-25`. O worker stdio também executa o perfil legado. Não se apresenta um único ciclo de inicialização como regra para todas as revisões.

O HTTP inclui desafio de autenticação, descoberta do recurso e emissor, emissão local por `client_credentials`, JWKS e verificação RS256. Tokens com audiência, assinatura, expiração ou escopo inadequados são recusados. Um token válido de alpha continua impedido de ler beta. O emissor reduzido não demonstra consentimento de usuário, PKCE, federação, TLS ou conformidade integral de OAuth/MCP.

O descritor de ferramenta muda durante o ensaio. O argumento `approved_catalog` carrega um digest esperado: o estrito recusa a referência antiga; o fraco permite. Atualizar a referência permite novamente a leitura própria, mas não a estrangeira. **Esse digest não prova aprovação humana nem integridade do código remoto**; o cliente consegue calcular o novo valor. Uma aprovação confiável exigiria outro vínculo, como o registro de decisão do L17.

São 46 verificações, quatorze chamadas HTTP que alcançam a ferramenta, sete recibos HTTP (quatro fraco, três estrito) e duas chamadas stdio. O cabeçalho de sessão inventado sem bearer recebe 401, em perfil stateless; isso não qualifica sequestro de sessão stateful. A identidade do worker vem de ambiente controlado pelo lançador, não de atestação contra o mesmo usuário do sistema operacional. O segundo cliente é independente em implementação, não em autoria ou revisão.

## L20: A2A, eventos e retorno assíncrono

O SDK 1.2.3 usa A2A 1.0 com HTTP+JSON explicitamente selecionado. A Agent Card anuncia streaming e callbacks. Dois sujeitos autenticados criam tarefas. Três tentativas de beta contra tarefa/contexto de alpha são recusadas, incluindo cancelamento. Um campo de tenant no corpo não altera o proprietário validado.

São nove tarefas: sete da campanha de callbacks, uma de beta e uma de streaming. A última produz três eventos SSE interpretáveis. As sete primeiras recebem quatorze configurações de callback, duas por tarefa. O especialista envia nove situações a cada receptor: legítimo, tarefa trocada, contexto trocado, tenant trocado, artefato incompatível, tardio, origem inválida, duplicado e conflito. São dezoito POSTs e 23 verificações adicionais de protocolo/integração.

O receptor valida bearer e token de notificação da tarefa. O fraco aceita resultados autenticados sem todos os vínculos; o estrito compara tarefa, contexto, tenant, tarefa de origem, recurso, conclusão e estado local. O fraco consome oito vezes; o estrito, uma. Uma duplicação idêntica recebe sucesso sem segundo recibo; conteúdo diferente com o mesmo ID produz conflito. O resultado tardio não reabre a expectativa cancelada.

O callback é um `StreamResponse` contendo uma Task concluída; a configuração usa `TaskPushNotificationConfig` na API do SDK fixado. Metadados de tenant/origem/recurso são contrato do domínio didático. A allowlist exata aceita apenas os receptores locais; outro destino é recusado antes do envio. Não é uma defesa geral contra SSRF ou DNS rebinding. A persistência de auditoria não implementa restauração após crash. Não há análise por LLM, callback externo, TLS, federação ou certificação completa de conformidade.

## Recursos medidos e repetição

Uma repetição sequencial, no mesmo host e incluindo imports e encerramento, registrou:

| Laboratório | Segundos | Pico amostrado de RSS da árvore (MiB) |
|---|---:|---:|
| L17 | 4,01 | 87,2 |
| L18 | 9,05 | 94,0 |
| L19 | 5,29 | 166,3 |
| L20 | 6,90 | 94,7 |

Amostragem a cada 100 ms: soma processos próprios vivos, pode contar memória compartilhada mais de uma vez e perder picos. Não mede RAM total, instalação/download, máquina dedicada ou latência externa. Não houve cobrança de API ou inferência. O lock inclui psutil 7.2.2.

```powershell
& $py producao/qualificar_parte5.py --out output/minha_execucao/qualificacao
```

O diretório terá quatro capturas, logs e `resources.json`. Para alterações de código ou materiais, crie outra captura. As fontes oficiais versionadas estão em `materiais/parte5/referencias.lock.json`, consultadas em 23/10/2026. A revisão independente continua aberta.

## Extensões com critério

Acrescente uma aprovação com capacidade limitada e corrida controlada; pause entre introspecção e efeito para medir a janela de revogação; fixe uma referência de catálogo em serviço de aprovação externo ao cliente; interrompa SSE em uma posição definida; envie callbacks concorrentes e reconcilie um efeito remoto pelo mesmo ID. Para cada extensão, escreva propriedade, adversário, controle negativo, utilidade e observação no destino. Não transforme uma extensão proposta em resultado já demonstrado.
